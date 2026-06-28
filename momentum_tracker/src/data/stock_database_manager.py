"""
stock_database_manager.py – Persistent + in-memory cache for price and
                       fundamental data.

Design principles
-----------------
* Price data  → Parquet files (preserves dtypes, fast I/O).
* Fundamental → JSON files (human-readable, safe for dict serialisation).
* Two-layer reads:  in-memory dict → disk cache → network download.
* Incremental updates: if cache is stale but exists, only the missing
  date range is fetched and merged, then saved back.
* Full-download fallback: if cache is missing or too shallow, the system
  tries decreasing period strings (e.g. 20y → 19y → … → 1y) until it
  succeeds or gives up.
* Config-driven:  MAX_CACHE_DAYS and DOWNLOAD_HISTORY_YEARS come from
  the Config object passed at construction time.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config import Config
from .data_downloader import DataDownloaderBase


# ─────────────────────────────────────────────────────────────────────────────
# StockDatabaseManager
# ─────────────────────────────────────────────────────────────────────────────

class StockDatabaseManager:
    """
    Manages all on-disk and in-memory data for the momentum system.

    Parameters
    ----------
    config      : Config instance – used for MAX_CACHE_DAYS, DOWNLOAD_HISTORY_YEARS, etc.
    downloader  : DataDownloaderBase – responsible for network fetches.
    cache_dir   : Path to the disk-cache folder (created if absent).
    """

    # Price-data sub-folder name inside cache_dir
    _PRICE_SUBDIR = "price"
    # Fundamental-data sub-folder name inside cache_dir
    _FUND_SUBDIR = "fundamental"

    def __init__(
        self,
        config: Config,
        downloader: DataDownloaderBase,
        cache_dir: str | Path = "./mps_cache",
    ) -> None:
        self._cfg = config
        self._dl = downloader

        self._cache_root = Path(cache_dir)
        self._price_dir = self._cache_root / self._PRICE_SUBDIR
        self._fund_dir = self._cache_root / self._FUND_SUBDIR
        self._price_dir.mkdir(parents=True, exist_ok=True)
        self._fund_dir.mkdir(parents=True, exist_ok=True)

        # In-memory caches
        self._price_mem:      Dict[str, pd.DataFrame] = {}
        self._benchmark_mem:  Dict[str, pd.DataFrame] = {}
        self._fund_derived_mem: Dict[str, Dict[str, Optional[float]]] = {}

    # ─────────────────────────────────────────────────────────────────────────
    # Public: price data
    # ─────────────────────────────────────────────────────────────────────────

    def get_price(self, ticker: str) -> Optional[pd.DataFrame]:
        """Return in-memory price DataFrame for *ticker* (or None)."""
        df = self._price_mem.get(ticker)
        if df is not None:
            return df
        return self._benchmark_mem.get(ticker)

    def ensure_price(self, ticker: str, is_benchmark: bool = False) -> bool:
        """
        Guarantee that *ticker*'s price data is loaded in memory.

        Flow:
          1. Already in memory?  ← return True
          2. Disk cache valid?   ← load into memory, return True
          3. Cache stale?        ← incremental update, merge, save, return True/False
          4. Cache missing?      ← full download with year-fallback, save, return True/False
        """
        if ticker in self._price_mem or ticker in self._benchmark_mem:
            return True

        return (
            self._load_benchmark(ticker)
            if is_benchmark
            else self._load_stock(ticker)
        )

    def ensure_prices(
        self, tickers: List[str], benchmark_ticker: Optional[str] = None
    ) -> None:
        """Ensure all *tickers* are loaded (download missing / stale ones)."""
        for ticker in tickers:
            self.ensure_price(ticker, is_benchmark=False)
        if benchmark_ticker:
            self.ensure_price(benchmark_ticker, is_benchmark=True)

    def bulk_precache(
        self, stock_tickers: List[str], benchmark_tickers: List[str]
    ) -> Tuple[int, int]:
        """
        Download and cache all tickers.

        Returns (successful_price_count, total_count).
        """
        all_tickers = list(dict.fromkeys(benchmark_tickers + stock_tickers))
        total = len(all_tickers)
        success = 0

        bench_set = set(benchmark_tickers)

        for idx, ticker in enumerate(all_tickers, 1):
            sys.stdout.write(
                f"  [{idx}/{total}] Caching {ticker} …         \r"
            )
            sys.stdout.flush()

            ok = self.ensure_price(ticker, is_benchmark=(ticker in bench_set))
            if ok:
                success += 1

        sys.stdout.write(" " * 80 + "\r")
        sys.stdout.flush()
        print(f"\n[DB] Price cache complete: {success}/{total} tickers loaded.")
        return success, total

    def clear_cache(self) -> None:
        """Delete all on-disk cache files and wipe in-memory stores."""
        import shutil
        if self._cache_root.exists():
            shutil.rmtree(self._cache_root)
        self._cache_root.mkdir(parents=True, exist_ok=True)
        self._price_dir.mkdir(parents=True, exist_ok=True)
        self._fund_dir.mkdir(parents=True, exist_ok=True)
        self._price_mem.clear()
        self._benchmark_mem.clear()
        self._fund_derived_mem.clear()
        print("[DB] Cache cleared.")

    # ─────────────────────────────────────────────────────────────────────────
    # Public: fundamental data
    # ─────────────────────────────────────────────────────────────────────────

    def get_fundamental(self, ticker: str) -> Dict[str, Optional[float]]:
        """
        Return derived fundamental metrics for *ticker*:
            BookToPrice, EarningsYield, SalesToPrice

        Layer order: in-memory → disk JSON → yfinance fetch.
        """
        empty = {"BookToPrice": None, "EarningsYield": None, "SalesToPrice": None}

        # 1. In-memory cache
        if ticker in self._fund_derived_mem:
            return self._fund_derived_mem[ticker]

        # 2. Disk cache (raw info JSON)
        raw_info: Optional[dict] = None
        if self._is_fund_cache_valid(ticker):
            raw_info = self._load_fund_raw(ticker)

        # 3. Check failure cache
        if raw_info is None and self._is_fund_failure_cached(ticker):
            self._cfg.debug_print(f"{ticker}: fundamental download failure is cached, skipping.")
            derived = empty
            self._fund_derived_mem[ticker] = derived
            return derived

        # 4. Network fetch
        if raw_info is None:
            raw_info = self._dl.download_fundamental_info(ticker)
            if raw_info and len(raw_info) > 10:
                self._save_fund_raw(ticker, raw_info)
            else:
                raw_info = {}
                self._save_fund_failure(ticker)

        # 5. Derive metrics
        derived = self._derive_fundamental_metrics(raw_info) if raw_info else empty

        self._fund_derived_mem[ticker] = derived
        return derived

    def get_sector(self, ticker: str) -> Optional[str]:
        """
        Return the sector name for *ticker*.
        Layer order: disk raw JSON cache -> yfinance fetch.
        """
        raw_info: Optional[dict] = None
        if self._is_fund_cache_valid(ticker):
            raw_info = self._load_fund_raw(ticker)
        if raw_info is None and self._is_fund_failure_cached(ticker):
            return None
        if raw_info is None:
            raw_info = self._dl.download_fundamental_info(ticker)
            if raw_info and len(raw_info) > 10:
                self._save_fund_raw(ticker, raw_info)
            else:
                raw_info = {}
                self._save_fund_failure(ticker)
        return raw_info.get("sector")

    def bulk_precache_fundamentals(self, tickers: List[str]) -> int:
        """Pre-populate fundamental cache for all tickers. Returns success count."""
        success = 0
        total = len(tickers)
        for idx, ticker in enumerate(tickers, 1):
            sys.stdout.write(
                f"  [{idx}/{total}] Fundamentals {ticker} …         \r"
            )
            sys.stdout.flush()
            derived = self.get_fundamental(ticker)
            if any(v is not None and not np.isnan(v) for v in derived.values()):
                success += 1
        sys.stdout.write(" " * 80 + "\r")
        sys.stdout.flush()
        print(f"[DB] Fundamental cache complete: {success}/{total} tickers.")
        return success

    # ─────────────────────────────────────────────────────────────────────────
    # Private: stock price load/download
    # ─────────────────────────────────────────────────────────────────────────

    def _load_stock(self, ticker: str) -> bool:
        """Full cache→incremental→full-download logic for a single stock ticker."""
        if self._is_price_failure_cached(ticker):
            self._cfg.debug_print(f"{ticker}: price download failure is cached, skipping yfinance.")
            return False

        today = date.today()
        config_years: int = self._cfg["DATA_CONFIG"].get("DOWNLOAD_HISTORY_YEARS", 5)

        # Ideal history start date – used only when deciding how many years
        # to request on a FIRST download, never to invalidate a fresh cache.
        # Stocks with short listing history (e.g. recent IPOs) will never
        # reach this date and must NOT be re-downloaded on every run.
        try:
            required_start = today.replace(year=today.year - config_years)
        except ValueError:
            required_start = today - timedelta(days=config_years * 365 + 5)

        cache_path = self._price_path(ticker)
        cache_exists = cache_path.exists()
        df_cached: Optional[pd.DataFrame] = None
        trigger_full = False

        if cache_exists:
            try:
                df_cached = self._load_price_disk(ticker)

                if df_cached is None or df_cached.empty:
                    trigger_full = True
                elif self._is_price_cache_valid(ticker):
                    # Cache is fresh → use it unconditionally.
                    # Do NOT check history depth here: recently-listed stocks
                    # (IPOs, new indices) will never have N years of data, so
                    # checking depth on a fresh cache causes a full re-download
                    # on every single run for those tickers.
                    self._price_mem[ticker] = df_cached
                    self._cfg.debug_print(
                        f"{ticker}: cache valid, loaded up to "
                        f"{df_cached.index.max().date()}."
                    )
                    return True
                else:
                    # Stale cache → incremental update
                    cache_end = df_cached.index.max().date()
                    inc_start = cache_end + timedelta(days=1)

                    if inc_start < today:
                        sys.stdout.write(
                            f"  {ticker}: stale, incremental {inc_start}→{today} …\r"
                        )
                        sys.stdout.flush()
                        df_new = self._dl.download_single(
                            ticker, start=inc_start, end=today
                        )
                        if df_new is not None and not df_new.empty:
                            combined = pd.concat([df_cached, df_new])
                            combined = combined[
                                ~combined.index.duplicated(keep="last")
                            ]
                            combined = combined[
                                combined.index.date >= required_start
                            ]
                            self._save_price_disk(ticker, combined)
                            self._price_mem[ticker] = combined
                            return True
                        else:
                            print(f"[DB] {ticker}: incremental failed → full download.")
                            trigger_full = True
                    else:
                        # Cache technically stale but data is current
                        self._price_mem[ticker] = df_cached
                        return True

            except Exception as exc:
                print(f"[DB] {ticker}: cache load error ({exc}) → full download.")
                trigger_full = True

        # Full download with year-fallback
        if not cache_exists or trigger_full:
            for years in range(config_years, 0, -1):
                period = f"{years}y"
                sys.stdout.write(f"  {ticker}: downloading {period} …         \r")
                sys.stdout.flush()
                df_full = self._dl.download_single(ticker, period=period)

                if df_full is not None and not df_full.empty:
                    if years == 1 and len(df_full) < 252:
                        # Minimum 1 year of trading days
                        break
                    self._save_price_disk(ticker, df_full)
                    self._price_mem[ticker] = df_full
                    return True

            print(f"[DB] {ticker}: all download attempts failed.")
            self._save_price_failure(ticker)
            return False

        return False

    def _load_benchmark(self, ticker: str) -> bool:
        """Simplified load for benchmark/index tickers (same logic, different store)."""
        # Benchmarks may lack volume – use same parquet path but different memory dict
        ok = self._load_stock(ticker)
        if ok and ticker in self._price_mem:
            self._benchmark_mem[ticker] = self._price_mem.pop(ticker)
        return ok

    # ─────────────────────────────────────────────────────────────────────────
    # Private: disk helpers – price
    # ─────────────────────────────────────────────────────────────────────────

    def _price_path(self, ticker: str) -> Path:
        safe = ticker.replace("^", "INDEX_").replace("/", "-")
        return self._price_dir / f"{safe}.parquet"

    def _price_failed_path(self, ticker: str) -> Path:
        safe = ticker.replace("^", "INDEX_").replace("/", "-")
        return self._price_dir / f"{safe}.failed"

    def _is_price_cache_valid(self, ticker: str) -> bool:
        p = self._price_path(ticker)
        if not p.exists():
            return False
        max_days: int = self._cfg["DATA_CONFIG"].get("MAX_CACHE_DAYS", 3)
        age = datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)
        return age <= timedelta(days=max_days)

    def _is_price_failure_cached(self, ticker: str) -> bool:
        p = self._price_failed_path(ticker)
        if not p.exists():
            return False
        max_days: int = self._cfg["DATA_CONFIG"].get("MAX_CACHE_DAYS", 3)
        age = datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)
        return age <= timedelta(days=max_days)

    def _load_price_disk(self, ticker: str) -> Optional[pd.DataFrame]:
        p = self._price_path(ticker)
        try:
            df = pd.read_parquet(p)
            if not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index)
            return df
        except Exception as exc:
            print(f"[DB] Parquet read failed for {ticker}: {exc}")
            return None

    def _save_price_disk(self, ticker: str, df: pd.DataFrame) -> None:
        p = self._price_path(ticker)
        try:
            df.index.name = "Date"
            df.to_parquet(p, index=True)
            self._clear_price_failure(ticker)
        except Exception as exc:
            print(f"[DB] Parquet write failed for {ticker}: {exc}")

    def _save_price_failure(self, ticker: str) -> None:
        p = self._price_failed_path(ticker)
        try:
            p.touch()
        except Exception as exc:
            print(f"[DB] Failed to touch price failure file for {ticker}: {exc}")

    def _clear_price_failure(self, ticker: str) -> None:
        p = self._price_failed_path(ticker)
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    # Private: disk helpers – fundamentals
    # ─────────────────────────────────────────────────────────────────────────

    def _fund_path(self, ticker: str) -> Path:
        safe = ticker.replace("^", "INDEX_").replace("/", "-")
        return self._fund_dir / f"{safe}_info.json"

    def _fund_failed_path(self, ticker: str) -> Path:
        safe = ticker.replace("^", "INDEX_").replace("/", "-")
        return self._fund_dir / f"{safe}_info.failed"

    def _is_fund_cache_valid(self, ticker: str) -> bool:
        p = self._fund_path(ticker)
        if not p.exists():
            return False
        max_days: int = self._cfg["DATA_CONFIG"].get("MAX_CACHE_DAYS", 3)
        age = datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)
        return age <= timedelta(days=max_days)

    def _is_fund_failure_cached(self, ticker: str) -> bool:
        p = self._fund_failed_path(ticker)
        if not p.exists():
            return False
        max_days: int = self._cfg["DATA_CONFIG"].get("MAX_CACHE_DAYS", 3)
        age = datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)
        return age <= timedelta(days=max_days)

    def _load_fund_raw(self, ticker: str) -> Optional[dict]:
        p = self._fund_path(ticker)
        try:
            with open(p, "r") as fh:
                return json.load(fh)
        except Exception as exc:
            self._cfg.debug_print(f"Fund cache read failed for {ticker}: {exc}")
            return None

    def _save_fund_raw(self, ticker: str, data: dict) -> None:
        p = self._fund_path(ticker)
        try:
            safe = _make_json_safe(data)
            with open(p, "w") as fh:
                json.dump(safe, fh, indent=4, skipkeys=True)
            self._clear_fund_failure(ticker)
        except Exception as exc:
            self._cfg.debug_print(f"Fund cache write failed for {ticker}: {exc}")

    def _save_fund_failure(self, ticker: str) -> None:
        p = self._fund_failed_path(ticker)
        try:
            p.touch()
        except Exception as exc:
            self._cfg.debug_print(f"Failed to touch fund failure file for {ticker}: {exc}")

    def _clear_fund_failure(self, ticker: str) -> None:
        p = self._fund_failed_path(ticker)
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    # Private: derive fundamental metrics from raw yfinance info
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _derive_fundamental_metrics(
        raw_info: dict,
    ) -> Dict[str, Optional[float]]:
        def safe_inverse(ratio: Any) -> Optional[float]:
            if ratio is None:
                return None
            try:
                v = float(ratio)
            except (ValueError, TypeError):
                return None
            if v == 0.0 or np.isinf(v) or np.isnan(v):
                return None
            return 1.0 / v

        return {
            "BookToPrice":   safe_inverse(raw_info.get("priceToBook")),
            "EarningsYield": safe_inverse(raw_info.get("trailingPE")),
            "SalesToPrice":  safe_inverse(raw_info.get("priceToSales")),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Module-level utility
# ─────────────────────────────────────────────────────────────────────────────

def _make_json_safe(obj: Any) -> Any:
    """Recursively convert numpy types / NaN / Inf to JSON-safe Python types."""
    if isinstance(obj, dict):
        return {k: _make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_make_json_safe(v) for v in obj]
    if isinstance(obj, (np.floating, np.float64)):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj)
    if isinstance(obj, (np.integer, np.int64)):
        return int(obj)
    try:
        if pd.isna(obj):
            return None
    except Exception:
        pass
    return obj
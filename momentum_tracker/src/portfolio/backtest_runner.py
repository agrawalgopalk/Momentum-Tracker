"""
backtest_runner.py – Orchestrates all backtest scenarios.

Wraps Backtester and exposes named scenario runners matching the
interactive menu options from the original script:

  run_single            – one category, custom date range
  run_multi_category    – all configured categories, one date range
  run_multi_year        – multiple lookback windows ending at each FY
  run_multi_category_multi_year – full cross of all categories × all FY windows
  run_quick_default     – preconfigured quick comparisons

All run_* methods return None but call ReportExporter internally.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config import Config
from data.stock_database_manager import StockDatabaseManager
from strategy.momentum_strategy import MomentumStrategy
from .backtester import Backtester, _calendar_dates
from reporting.report_exporter import ReportExporter


class BacktestRunner:
    """
    High-level orchestrator for backtest scenarios.

    Parameters
    ----------
    config   : Config
    db       : StockDatabaseManager
    strategy : MomentumStrategy
    exporter : ReportExporter
    """

    def __init__(
        self,
        config: Config,
        db: StockDatabaseManager,
        strategy: MomentumStrategy,
        exporter: ReportExporter,
    ) -> None:
        self._cfg      = config
        self._db       = db
        self._strategy = strategy
        self._exporter = exporter
        self._engine   = Backtester(config, db, strategy)

    # ─────────────────────────────────────────────────────────────────────
    # Shared helpers
    # ─────────────────────────────────────────────────────────────────────

    def _b_cfg(self) -> Dict[str, Any]:
        return self._cfg.get("BACKTEST_CONFIG", {})

    def _load_symbols(self, category: str) -> List[str]:
        from data.symbol_loader import SymbolLoader
        return SymbolLoader(self._cfg).load(category)

    # ─────────────────────────────────────────────────────────────────────
    # Single category, one date range
    # ─────────────────────────────────────────────────────────────────────

    def run_single(
        self,
        category: str,
        start_date: datetime,
        end_date: datetime,
        top_n: Optional[int] = None,
        rebalance_freq: Optional[str] = None,
        transaction_cost: Optional[float] = None,
        export: bool = True,
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Run one complete backtest and (optionally) export results."""
        bcfg = self._b_cfg()
        top_n            = top_n            or bcfg.get("TOP_N", 20)
        rebalance_freq   = rebalance_freq   or bcfg.get("REBALANCE_FREQUENCY", "M")
        transaction_cost = transaction_cost or bcfg.get("TRANSACTION_COST", 0.001)

        symbols = self._load_symbols(category)
        if not symbols:
            print(f"[Runner] No symbols for '{category}'.")
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

        df_r, df_e, df_t, df_b = self._engine.run(
            category, symbols, start_date, end_date,
            top_n, rebalance_freq, transaction_cost,
        )

        if export and not df_e.empty:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._exporter.export_backtest(
                category, df_r, df_e, df_t, df_b,
                filename=f"{category}_{ts}",
            )

        return df_r, df_e, df_t, df_b

    # ─────────────────────────────────────────────────────────────────────
    # All categories, one date range
    # ─────────────────────────────────────────────────────────────────────

    def run_multi_category(
        self,
        start_date: datetime,
        end_date: datetime,
        categories: Optional[List[str]] = None,
        top_n: Optional[int] = None,
        rebalance_freq: Optional[str] = None,
        transaction_cost: Optional[float] = None,
    ) -> None:
        """Run backtest for each category and export individually."""
        categories = categories or list(self._cfg["DATA_CONFIG"]["SYMBOL_FILE_MAP"].keys())
        for cat in categories:
            print(f"\n{'='*65}")
            print(f"  Category: {cat}")
            print(f"{'='*65}")
            self.run_single(cat, start_date, end_date, top_n, rebalance_freq, transaction_cost)

    # ─────────────────────────────────────────────────────────────────────
    # One category, multiple lookback windows (ending at current date)
    # ─────────────────────────────────────────────────────────────────────

    def run_multi_year(
        self,
        category: str,
        year_lengths: List[int],
        top_n: Optional[int] = None,
        rebalance_freq: Optional[str] = None,
        transaction_cost: Optional[float] = None,
    ) -> None:
        """
        Run backtest for each lookback in *year_lengths* and export a
        comparison Excel with all equity curves side by side.
        """
        today = datetime.now()
        equity_curves: Dict[str, pd.Series] = {}
        bench_curves: Dict[str, pd.Series] = {}
        summary_rows: List[Dict] = []

        for years in year_lengths:
            start = today - timedelta(days=int(years * 365.25))
            print(f"\n  [{category}] {years}y window ({start.date()} → {today.date()})")
            df_r, df_e, df_t, df_b = self.run_single(
                category, start, today, top_n, rebalance_freq, transaction_cost, export=False
            )
            if df_e.empty:
                continue

            df_e["date"]  = pd.to_datetime(df_e["date"])
            eq_ser = df_e.set_index("date")["Equity"]

            bench_ser: Optional[pd.Series] = None
            if df_b is not None and not df_b.empty and "close" in df_b.columns:
                df_b["date"] = pd.to_datetime(df_b["date"])
                bench_ser = df_b.set_index("date")["close"]
                eq_ser, bench_ser = eq_ser.align(bench_ser, join="inner")

            label = f"{years}y"
            equity_curves[label] = eq_ser

            # Performance summary
            eq_start = float(eq_ser.iloc[0])
            eq_end   = float(eq_ser.iloc[-1])
            total_r  = eq_end / eq_start - 1.0
            cagr     = (1 + total_r) ** (1 / max(years, 0.01)) - 1

            row: Dict[str, Any] = {
                "Category":        category,
                "Window_Years":    years,
                "Strategy_Total_Return_%": round(total_r * 100, 2),
                "Strategy_CAGR_%": round(cagr * 100, 2),
            }
            if bench_ser is not None and len(bench_ser) >= 2:
                b_start = float(bench_ser.iloc[0])
                b_end   = float(bench_ser.iloc[-1])
                b_total = b_end / b_start - 1.0
                b_cagr  = (1 + b_total) ** (1 / max(years, 0.01)) - 1
                bench_curves[label] = bench_ser
                row["Benchmark_Total_Return_%"] = round(b_total * 100, 2)
                row["Benchmark_CAGR_%"]         = round(b_cagr  * 100, 2)
            summary_rows.append(row)

        if summary_rows:
            df_summary = pd.DataFrame(summary_rows)
            self._exporter.export_multi_year_comparison(
                category, df_summary, equity_curves, bench_curves
            )

    # ─────────────────────────────────────────────────────────────────────
    # All categories × multiple FY end-years
    # ─────────────────────────────────────────────────────────────────────

    def run_multi_category_multi_year(
        self,
        categories: List[str],
        year_lengths: List[int],
        start_fy_year: int = 2020,
        top_n: Optional[int] = None,
        rebalance_freq: Optional[str] = None,
        transaction_cost: Optional[float] = None,
    ) -> None:
        """
        For each FY end year from *start_fy_year* to today, for each
        category and each lookback window, run a backtest.
        Aggregates results into one master Excel.
        """
        current_year = datetime.now().year
        summary_rows : List[Dict] = []
        curves_by_fy : Dict[int, Dict] = {}

        for fy_year in range(start_fy_year, current_year + 1):
            fy_end = datetime(fy_year, 3, 31)

            for years in year_lengths:
                fy_start = fy_end - timedelta(days=int(years * 365.25))

                for cat in categories:
                    print(f"\n  FY{fy_year} | {cat} | {years}y  ({fy_start.date()} → {fy_end.date()})")
                    df_r, df_e, df_t, df_b = self.run_single(
                        cat, fy_start, fy_end,
                        top_n, rebalance_freq, transaction_cost, export=False
                    )
                    if df_e is None or df_e.empty:
                        continue

                    df_e["date"] = pd.to_datetime(df_e["date"])
                    eq_ser = df_e.set_index("date")["Equity"]

                    bench_ser: Optional[pd.Series] = None
                    if df_b is not None and not df_b.empty and "close" in df_b.columns:
                        df_b["date"] = pd.to_datetime(df_b["date"])
                        bench_ser = df_b.set_index("date")["close"]
                        eq_ser, bench_ser = eq_ser.align(bench_ser, join="inner")
                        if len(eq_ser) < 2:
                            bench_ser = None

                    eq_start = float(eq_ser.iloc[0])
                    eq_end   = float(eq_ser.iloc[-1])
                    total_r  = eq_end / eq_start - 1.0
                    ann_r    = (1 + total_r) ** (1 / max(years, 0.01)) - 1

                    row: Dict[str, Any] = {
                        "FY_End":          fy_year,
                        "Category":        cat,
                        "Lookback_Years":  years,
                        "Strategy_Total_Return_%": round(total_r * 100, 2),
                        "Strategy_CAGR_%":         round(ann_r   * 100, 2),
                    }

                    if bench_ser is not None and len(bench_ser) >= 2:
                        b_start = float(bench_ser.iloc[0])
                        b_end   = float(bench_ser.iloc[-1])
                        b_total = b_end / b_start - 1.0
                        b_ann   = (1 + b_total) ** (1 / max(years, 0.01)) - 1
                        row["Benchmark_Total_Return_%"] = round(b_total * 100, 2)
                        row["Benchmark_CAGR_%"]         = round(b_ann   * 100, 2)

                    summary_rows.append(row)

                    # Store curves grouped by FY
                    fy_dict = curves_by_fy.setdefault(fy_year, {"strategy": {}, "benchmark": {}})
                    label   = f"{cat}_{years}y"
                    fy_dict["strategy"][label] = eq_ser
                    if bench_ser is not None:
                        fy_dict["benchmark"][label] = bench_ser

        if summary_rows:
            df_summary = pd.DataFrame(summary_rows)
            self._exporter.export_multi_category_multi_year(df_summary, curves_by_fy)

    # ─────────────────────────────────────────────────────────────────────
    # Interactive wrapper (called from Application menu)
    # ─────────────────────────────────────────────────────────────────────

    def run_quick_interactively(self) -> None:
        """Presents the quick-backtest sub-menu and dispatches the chosen scenario."""
        categories = list(self._cfg["DATA_CONFIG"]["SYMBOL_FILE_MAP"].keys())
        bcfg       = self._b_cfg()

        print("\n--- Quick Backtest Menu ---")
        print("  [1] Single category, last N years")
        print("  [2] All categories, last N years")
        print("  [3] Single category, multiple lookback windows")
        print("  [4] All categories, one fixed lookback window")
        print("  [5] Single category across multiple FY end-years")
        print("  [6] All categories across multiple FY end-years")
        print("  [7] All categories × multiple FY × multiple lookbacks")
        print("  [0] Cancel")

        choice = input("Choose: ").strip()

        today     = datetime.now()
        def _ask_years(default=3) -> int:
            s = input(f"  Lookback years (default {default}): ").strip()
            return int(s) if s.isdigit() else default

        def _ask_start_fy(default=2020) -> int:
            s = input(f"  Start FY year (default {default}): ").strip()
            return int(s) if s.isdigit() else default

        def _ask_category() -> Optional[str]:
            from data.symbol_loader import SymbolLoader
            return SymbolLoader(self._cfg).select_interactively()

        if choice == "1":
            years = _ask_years()
            cat   = _ask_category()
            if cat:
                self.run_single(cat, today - timedelta(days=years*365), today)

        elif choice == "2":
            years = _ask_years()
            self.run_multi_category(
                today - timedelta(days=years*365), today, categories
            )

        elif choice == "3":
            cat   = _ask_category()
            if cat:
                self.run_multi_year(cat, [1, 2, 3, 5])

        elif choice == "4":
            years = _ask_years()
            self.run_multi_category(today - timedelta(days=years*365), today)

        elif choice == "5":
            start_fy = _ask_start_fy()
            years    = _ask_years()
            cat      = _ask_category()
            if cat:
                self.run_multi_category_multi_year([cat], [years], start_fy)

        elif choice == "6":
            start_fy = _ask_start_fy()
            years    = _ask_years()
            self.run_multi_category_multi_year(categories, [years], start_fy)

        elif choice == "7":
            start_fy  = _ask_start_fy()
            self.run_multi_category_multi_year(categories, [1, 2, 3, 5], start_fy)

        else:
            print("  Cancelled.")

    def run_full_interactively(self) -> None:
        """Custom full backtest with manually entered parameters."""
        from data.symbol_loader import SymbolLoader
        cat = SymbolLoader(self._cfg).select_interactively()
        if not cat:
            return

        bcfg = self._b_cfg()
        today = datetime.now()

        def _prompt(msg, default):
            v = input(f"  {msg} (default: {default}): ").strip()
            return v or str(default)

        start_str  = _prompt("Start date (YYYY-MM-DD)", (today - timedelta(days=5*365)).strftime("%Y-%m-%d"))
        end_str    = _prompt("End date (YYYY-MM-DD)",   today.strftime("%Y-%m-%d"))
        top_n_str  = _prompt("Top N",                  bcfg.get("TOP_N", 20))
        freq_str   = _prompt("Frequency (M/Q/A)",      bcfg.get("REBALANCE_FREQUENCY", "M"))
        cost_str   = _prompt("Transaction cost",        bcfg.get("TRANSACTION_COST", 0.001))

        try:
            start = datetime.strptime(start_str, "%Y-%m-%d")
            end   = datetime.strptime(end_str,   "%Y-%m-%d")
            top_n = int(top_n_str)
            cost  = float(cost_str)
        except ValueError as exc:
            print(f"  Invalid input: {exc}")
            return

        if freq_str.upper() not in ("M", "Q", "A", "W"):
            print("  Invalid frequency. Use M / Q / A / W.")
            return

        df_r, df_e, df_t, df_b = self.run_single(cat, start, end, top_n, freq_str.upper(), cost)

        if not df_e.empty:
            if input("  Export results? (y/n): ").strip().lower() == "y":
                default_name = f"{cat}_full_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                file_name = input(
                    f"  Output file name (.xlsx or .csv) [default: {default_name}]: "
                ).strip() or default_name
                self._exporter.export_backtest_any(cat, df_r, df_e, df_t, df_b, file_name)

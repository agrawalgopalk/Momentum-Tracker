"""
data_downloader.py – Factory + provider implementations for market data.

Architecture
------------
  DataDownloaderBase          Abstract interface every provider must satisfy
  ├─ YahooFinanceDownloader   Concrete implementation using yfinance
  ├─ FyersDownloader          Placeholder – wire up Fyers SDK here
  └─ ZerodhaDownloader        Placeholder – wire up Zerodha / KiteConnect here

  DataDownloaderFactory       Creates the correct downloader from a string key.

All providers return DataFrames normalised to lowercase OHLCV columns:
  open, high, low, close, volume  (index: DatetimeIndex named 'Date')
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class DataDownloaderBase(ABC):
    """
    Every data provider must implement these two methods so the rest of the
    system can swap providers without changing any calling code.
    """

    @abstractmethod
    def download_single(
        self,
        ticker: str,
        period: Optional[str] = None,
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Download OHLCV data for *ticker*.

        Provide **either** a *period* string (e.g. ``'5y'``) **or** explicit
        *start* / *end* dates for incremental updates.

        Returns a normalised DataFrame or ``None`` on failure.
        """
        ...

    @abstractmethod
    def download_fundamental_info(self, ticker: str) -> dict:
        """
        Return the raw fundamental info dictionary for *ticker*
        (keys like ``priceToBook``, ``trailingPE``, ``priceToSales``).
        Returns an empty dict on failure.
        """
        ...

    # ------------------------------------------------------------------
    # Shared normalisation helper (available to all subclasses)
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise(df: pd.DataFrame, ticker: str) -> Optional[pd.DataFrame]:
        """
        Flatten MultiIndex columns (yfinance v0.2+), lowercase column names,
        map common aliases, and strip future rows to prevent lookahead bias.
        """
        if df is None or df.empty:
            return None

        # ── Flatten MultiIndex ─────────────────────────────────────────
        if isinstance(df.columns, pd.MultiIndex):
            try:
                df.columns = [col[0] for col in df.columns]
            except Exception as exc:
                print(f"[Downloader] MultiIndex flatten failed for {ticker}: {exc}")

        # ── Lowercase ──────────────────────────────────────────────────
        df.columns = [str(c).lower().strip() for c in df.columns]

        # ── Rename common aliases ──────────────────────────────────────
        aliases = {
            "adj close": "adj_close",
            "adj_close": "adj_close",
        }
        df = df.rename(columns=aliases)

        # ── Ensure 'close' exists (fall back to adj_close) ────────────
        if "close" not in df.columns and "adj_close" in df.columns:
            df = df.rename(columns={"adj_close": "close"})

        if "close" not in df.columns:
            print(
                f"[Downloader] {ticker}: no 'close' column found "
                f"({list(df.columns)}). Skipping."
            )
            return None

        # ── Name the index ─────────────────────────────────────────────
        df.index.name = "Date"
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)

        # ── Strip future rows (no lookahead bias) ──────────────────────
        df = df[df.index <= pd.Timestamp.now()]

        return df if not df.empty else None


# ---------------------------------------------------------------------------
# Yahoo Finance implementation
# ---------------------------------------------------------------------------

class YahooFinanceDownloader(DataDownloaderBase):
    """
    Concrete provider using the public ``yfinance`` library.

    This is the default provider for Indian (NSE) markets; all tickers are
    expected to carry the ``.NS`` suffix already.
    """

    def download_single(
        self,
        ticker: str,
        period: Optional[str] = None,
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> Optional[pd.DataFrame]:

        if period:
            kwargs: dict = {"period": period}
            range_desc = period
        elif start and end:
            # yfinance 'end' is exclusive → +1 day so the end date is included
            kwargs = {"start": start, "end": end + timedelta(days=1)}
            range_desc = f"{start} → {end}"
        else:
            print(f"[YF] {ticker}: must supply 'period' OR 'start'+'end'.")
            return None

        try:
            raw = yf.download(ticker, interval="1d", progress=False, **kwargs)
            return self._normalise(raw, ticker)
        except Exception as exc:
            print(f"[YF] {ticker} download failed ({range_desc}): {exc}")
            return None

    def download_fundamental_info(self, ticker: str) -> dict:
        try:
            info = yf.Ticker(ticker).info
            if info and len(info) > 10:
                return info
            return {}
        except Exception as exc:
            print(f"[YF] Fundamental fetch failed for {ticker}: {exc}")
            return {}


# ---------------------------------------------------------------------------
# Fyers placeholder
# ---------------------------------------------------------------------------

class FyersDownloader(DataDownloaderBase):
    """
    Placeholder for Fyers API integration.

    To activate:
      1. Install the Fyers SDK:  ``pip install fyers-apiv3``
      2. Initialise the client with your ``client_id`` and ``access_token``
         (typically via ``FyersModel``).
      3. Implement ``download_single`` by calling
         ``fyers.history(data={...})`` and normalising the response.
      4. Implement ``download_fundamental_info`` (Fyers does not expose
         fundamentals natively – proxy through another source or leave as stub).

    Reference: https://myapi.fyers.in/docs/
    """

    def __init__(self, client_id: str = "", access_token: str = "") -> None:
        self._client_id = client_id
        self._access_token = access_token
        # self._fyers = FyersModel(client_id=client_id, token=access_token)

    def download_single(
        self,
        ticker: str,
        period: Optional[str] = None,
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> Optional[pd.DataFrame]:
        raise NotImplementedError(
            "FyersDownloader.download_single – not yet implemented. "
            "Wire up the Fyers SDK and call fyers.history(...)."
        )

    def download_fundamental_info(self, ticker: str) -> dict:
        raise NotImplementedError(
            "FyersDownloader.download_fundamental_info – "
            "Fyers does not expose fundamentals natively. "
            "Proxy through another source (e.g. NSE API) or leave empty."
        )


# ---------------------------------------------------------------------------
# Zerodha / KiteConnect placeholder
# ---------------------------------------------------------------------------

class ZerodhaDownloader(DataDownloaderBase):
    """
    Placeholder for Zerodha KiteConnect integration.

    To activate:
      1. Install: ``pip install kiteconnect``
      2. Complete the login flow to obtain an ``access_token``.
      3. Implement ``download_single`` using
         ``kite.historical_data(instrument_token, from_date, to_date, "day")``.
         Note: you will need to map NSE ticker symbols → instrument tokens
         via ``kite.instruments("NSE")``.
      4. Implement ``download_fundamental_info`` using the Zerodha instruments
         endpoint or a third-party fundamental data source.

    Reference: https://kite.trade/docs/connect/v3/
    """

    def __init__(self, api_key: str = "", access_token: str = "") -> None:
        self._api_key = api_key
        self._access_token = access_token
        # from kiteconnect import KiteConnect
        # self._kite = KiteConnect(api_key=api_key)
        # self._kite.set_access_token(access_token)

    def download_single(
        self,
        ticker: str,
        period: Optional[str] = None,
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> Optional[pd.DataFrame]:
        raise NotImplementedError(
            "ZerodhaDownloader.download_single – not yet implemented. "
            "Wire up KiteConnect and call kite.historical_data(...)."
        )

    def download_fundamental_info(self, ticker: str) -> dict:
        raise NotImplementedError(
            "ZerodhaDownloader.download_fundamental_info – "
            "not yet implemented."
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, type[DataDownloaderBase]] = {
    "yahoo":   YahooFinanceDownloader,
    "yfinance": YahooFinanceDownloader,
    "fyers":   FyersDownloader,
    "zerodha": ZerodhaDownloader,
    "kite":    ZerodhaDownloader,
}


class DataDownloaderFactory:
    """
    Creates and returns a configured ``DataDownloaderBase`` instance.

    Example
    -------
    >>> dl = DataDownloaderFactory.create("yahoo")
    >>> dl = DataDownloaderFactory.create("fyers", client_id="XYZ", access_token="...")
    """

    @staticmethod
    def create(provider: str = "yahoo", **kwargs) -> DataDownloaderBase:
        key = provider.lower().strip()
        cls = _REGISTRY.get(key)
        if cls is None:
            available = ", ".join(_REGISTRY)
            raise ValueError(
                f"Unknown data provider '{provider}'. "
                f"Available: {available}"
            )
        return cls(**kwargs)

    @staticmethod
    def available_providers() -> list[str]:
        return list(_REGISTRY.keys())

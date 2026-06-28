"""
chart_tool.py – CrewAI tool that calculates technical chart indicators for stocks.
Uses existing TechnicalIndicators and StockDatabaseManager.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field
import pandas as pd
import numpy as np

# Setup path so we can do flat imports from momentum_tracker/src/
_root = Path(__file__).resolve().parent.parent   # Momentum-Tracker/
_pkg  = _root / "momentum_tracker"
_src  = _pkg / "src"

if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from strategy.technical_indicators import TechnicalIndicators

class ChartToolInput(BaseModel):
    ticker: str = Field(..., description="The stock ticker symbol to analyze, e.g., 'INFY.NS'.")

class TechnicalChartTool(BaseTool):
    name: str = "Technical Chart Tool"
    description: str = (
        "Calculates technical stats for a stock ticker. "
        "Returns the current price, 50-day EMA, 200-day EMA, 14-day RSI, "
        "and 20-day Support and Resistance. Input must be a stock ticker symbol."
    )
    args_schema: Type[BaseModel] = ChartToolInput

    def _run(self, ticker: str) -> str:
        ticker = ticker.strip().upper()
        try:
            # Initialize components inside the run method to avoid loading issues during startup
            from config import Config
            from data.data_downloader import DataDownloaderFactory
            from data.stock_database_manager import StockDatabaseManager

            config_json = _pkg / "config.json"
            config = Config(str(config_json) if config_json.exists() else "config.json")

            # Resolve paths
            symbols_dir = config["DATA_CONFIG"].get("SYMBOLS_DIR", "data/symbols")
            if not Path(symbols_dir).is_absolute():
                config["DATA_CONFIG"]["SYMBOLS_DIR"] = str(_root / symbols_dir)

            cache_dir = config.get("SYSTEM_CONFIG", {}).get("CACHE_DIR", "data_cache")
            if not Path(cache_dir).is_absolute():
                resolved_cache = str(_root / cache_dir)
            else:
                resolved_cache = cache_dir

            downloader = DataDownloaderFactory.create("yahoo")
            db = StockDatabaseManager(config, downloader, cache_dir=resolved_cache)

            # Ensure data is loaded
            ok = db.ensure_price(ticker)
            if not ok:
                return f"Could not load price history for {ticker}. The ticker might be invalid or not in cache."

            df = db.get_price(ticker)
            if df is None or df.empty:
                return f"No price data found for {ticker}."

            # Calculate technical parameters using existing TechnicalIndicators module
            # We explicitly pass the periods to override defaults
            ema_50 = TechnicalIndicators.ema(df, period=50)
            ema_200 = TechnicalIndicators.ema(df, period=200)
            rsi = TechnicalIndicators.rsi(df, period=14)

            # Simple support and resistance using 20-day min/max close
            close_series = df["close"]
            current_price = float(close_series.iloc[-1])
            support_20d = float(close_series.iloc[-20:].min())
            resistance_20d = float(close_series.iloc[-20:].max())

            # Format the output report for the Agent
            trend = "Bullish (Uptrend)" if current_price > ema_50 > ema_200 else (
                "Bearish (Downtrend)" if current_price < ema_50 < ema_200 else "Neutral (Consolidating)"
            )

            report = (
                f"=== TECHNICAL SUMMARY FOR {ticker} ===\n"
                f"Current Price: ₹{current_price:.2f}\n"
                f"50-day EMA:    ₹{ema_50:.2f}\n"
                f"200-day EMA:   ₹{ema_200:.2f}\n"
                f"Trend State:   {trend}\n"
                f"14-day RSI:    {rsi:.1f}\n"
                f"20-day Support: ₹{support_20d:.2f}\n"
                f"20-day Resistance: ₹{resistance_20d:.2f}\n"
                f"====================================="
            )
            return report

        except Exception as exc:
            return f"Error executing Technical Chart Tool for {ticker}: {exc}\n{traceback.format_exc()}"

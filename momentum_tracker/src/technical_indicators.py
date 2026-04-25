"""
technical_indicators.py – Pure, stateless technical indicator calculations.

All functions accept a DataFrame with lowercase OHLCV columns
(open, high, low, close, volume) and return a scalar float (or np.nan).

No global state, no Config dependency – fully unit-testable in isolation.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


class TechnicalIndicators:
    """
    Namespace for technical indicator calculations.
    All methods are static – no instance needed.
    """

    # ─────────────────────────────────────────────────────────────────────
    # Momentum
    # ─────────────────────────────────────────────────────────────────────
    
    @staticmethod
    def ema(df: pd.DataFrame, period: int = 50) -> float:
        """Exponential Moving Average."""
        if df.empty or "close" not in df.columns or len(df) < period:
            return np.nan
        return float(df["close"].ewm(span=period, adjust=False).mean().iloc[-1])
    
    @staticmethod
    def rsi(df: pd.DataFrame, period: int = 14) -> float:
        """Wilder RSI (Relative Strength Index)."""
        if df.empty or "close" not in df.columns or len(df) < period:
            return np.nan
        try:
            delta = df["close"].diff()
            gain = delta.where(delta > 0, 0.0).rolling(period).mean()
            loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
            loss = loss.replace(0, np.finfo(float).eps)
            rs = gain / loss
            return float((100 - 100 / (1 + rs)).iloc[-1])
        except Exception:
            return np.nan

    @staticmethod
    def roc(df: pd.DataFrame, period: int = 20) -> float:
        """Rate of Change (percentage)."""
        if df.empty or "close" not in df.columns or len(df) <= period:
            return np.nan
        try:
            return float(df["close"].pct_change(period).iloc[-1])
        except Exception:
            return np.nan

    @staticmethod
    def cci(df: pd.DataFrame, period: int = 20) -> float:
        """Commodity Channel Index."""
        cols = ("high", "low", "close")
        if df.empty or len(df) < period or any(c not in df.columns for c in cols):
            return np.nan
        try:
            tp = (df["high"] + df["low"] + df["close"]) / 3
            sma = tp.rolling(period).mean()
            mad = tp.rolling(period).apply(
                lambda x: np.mean(np.abs(x - np.mean(x))), raw=True
            )
            result = (tp - sma) / (0.015 * mad)
            return float(result.iloc[-1])
        except Exception:
            return np.nan

    @staticmethod
    def mfi(df: pd.DataFrame, period: int = 14) -> float:
        """Money Flow Index."""
        cols = ("high", "low", "close", "volume")
        if df.empty or len(df) < period or any(c not in df.columns for c in cols):
            return np.nan
        try:
            tp = (df["high"] + df["low"] + df["close"]) / 3
            mf = tp * df["volume"]
            p_mf = mf.where(tp.diff() > 0, 0.0)
            n_mf = mf.where(tp.diff() < 0, 0.0)
            p_sum = p_mf.rolling(period).sum()
            n_sum = n_mf.rolling(period).sum().replace(0, np.finfo(float).eps)
            mr = p_sum / n_sum
            return float((100 - 100 / (1 + mr)).iloc[-1])
        except Exception:
            return np.nan

    @staticmethod
    def ema(df: pd.DataFrame, period: int = 21) -> float:
        """Exponential Moving Average (last value)."""
        if df.empty or "close" not in df.columns or len(df) < period:
            return np.nan
        try:
            return float(df["close"].ewm(span=period, adjust=False).mean().iloc[-1])
        except Exception:
            return np.nan

    @staticmethod
    def weighted_roc_composite(
        df: pd.DataFrame,
        periods: list[int],
        weights: list[float],
    ) -> float:
        """
        Composite ROC score (WMS ROC).

        weighted_sum(ROC_p * w) / sum(valid_weights)
        """
        if df.empty or "close" not in df.columns:
            return np.nan
        if len(periods) != len(weights):
            return np.nan

        total_w = 0.0
        total_v = 0.0
        for p, w in zip(periods, weights):
            if len(df) > p:
                try:
                    roc = df["close"].pct_change(p).iloc[-1]
                    if not np.isnan(roc):
                        total_v += float(roc) * w
                        total_w += w
                except Exception:
                    pass

        return float(total_v / total_w) * 100 if total_w > 0 else np.nan

    # ─────────────────────────────────────────────────────────────────────
    # Relative strength vs benchmark
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def rs_ratio_ma(
        stock_df: pd.DataFrame,
        bench_df: pd.DataFrame,
        lookback: int = 55,
    ) -> float:
        """
        Relative-strength ratio = stock_close / bench_close, smoothed
        over *lookback* days.  Returns the latest value minus 1
        (positive → outperforming).
        Calculates the Smoothed Relative Strength (RS-MA) Ratio.

        Formula:
        1. RS_Line = (Stock_Close / Bench_Close)
        2. RS_MA = Simple_Moving_Average(RS_Line, period=lookback)
        3. Result = (RS_Line_Today / RS_MA_Today) - 1

        Logic:
        - Measures if the current Relative Strength is above its own average.
        - Result > 0: Relative Strength is trending UP (Momentum is accelerating).
        - Result < 0: Relative Strength is trending DOWN (Mean reversion or weakness).
        """
        
        # if stock_df is None or bench_df is None:
        #     return np.nan
        # try:
        #     ratio = (stock_df["close"] / bench_df["close"]).dropna()
        #     smoothed = ratio.rolling(lookback).mean()
        #     last = smoothed.dropna()
        #     if last.empty:
        #         return np.nan
        #     return float(last.iloc[-1]) - 1.0
        # except Exception:
        #     return np.nan
        
        if stock_df is None or bench_df is None or stock_df.empty or bench_df.empty:
            return np.nan

        try:
            # 1. Align dates to ensure row-wise division is accurate
            combined = pd.concat([stock_df['close'], bench_df['close']], axis=1, join='inner')
            combined.columns = ['stock', 'bench']

            if len(combined) < lookback:
                return np.nan

            # 2. Generate the RS Line (Ratio of prices)
            rs_line = combined['stock'] / combined['bench']

            # 3. Calculate the Moving Average of the RS Line
            rs_ma = rs_line.rolling(window=lookback).mean()

            # 4. Compare current RS value to its own average
            current_rs = rs_line.iloc[-1]
            current_ma = rs_ma.iloc[-1]

            if current_ma == 0 or np.isnan(current_ma):
                return np.nan

            return float((current_rs / current_ma) - 1.0)

        except Exception:
            return np.nan        

    @staticmethod
    def rs_ratio(
        stock_df: pd.DataFrame,
        bench_df: pd.DataFrame,
        lookback: int = 55,
    ) -> float:
        """
        Calculates the Vivek Bajaj RS-N Ratio (Return-based Relative Strength).

        Formula:
        RS_Ratio = [(Stock_Close_Today / Stock_Close_N_Days_Ago) / 
                    (Bench_Close_Today / Bench_Close_N_Days_Ago)] - 1

        Returns:
            float: Outperformance ratio (e.g., 0.05 for 5% outperformance).
        """
        if stock_df is None or bench_df is None or stock_df.empty or bench_df.empty:
            return np.nan

        try:
            # 1. Align the dataframes by date (index) to ensure we compare the same days
            # We only need the 'close' columns
            combined = pd.concat([stock_df['close'], bench_df['close']], axis=1, join='inner')
            combined.columns = ['stock', 'bench']
            
            if len(combined) <= lookback:
                return np.nan

            # 2. Extract the current and historical prices
            # iloc[-1] is today, iloc[-(lookback + 1)] is exactly N days ago
            price_stock_now = combined['stock'].iloc[-1]
            price_stock_old = combined['stock'].iloc[-(lookback + 1)]
            
            price_bench_now = combined['bench'].iloc[-1]
            price_bench_old = combined['bench'].iloc[-(lookback + 1)]

            # 3. Calculate Point-to-Point Performance
            stock_return = price_stock_now / price_stock_old
            bench_return = price_bench_now / price_bench_old

            if bench_return == 0:
                return np.nan

            # 4. Return the relative ratio minus 1
            return float((stock_return / bench_return) - 1.0)

        except Exception:
            return np.nan

    # ─────────────────────────────────────────────────────────────────────
    # Price momentum composite (for P-Score)
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def price_momentum_composite(df: pd.DataFrame) -> float:
        """
        Multi-period price momentum composite.
        Components: 12M ROC, 6M ROC, 3M ROC, distance from 52W high.
        """
        if df.empty or "close" not in df.columns:
            return np.nan

        try:
            latest = float(df["close"].iloc[-1])
        except Exception:
            return np.nan

        roc_12m = float(df["close"].pct_change(252).iloc[-1]) if len(df) > 252 else np.nan
        roc_6m  = float(df["close"].pct_change(126).iloc[-1]) if len(df) > 126 else np.nan
        roc_3m  = float(df["close"].pct_change(63).iloc[-1])  if len(df) > 63  else np.nan

        high_52w = float(df["high"].tail(252).max()) if "high" in df.columns and len(df) > 252 else np.nan
        dist_from_high = (latest / high_52w) - 1.0 if (not np.isnan(high_52w) and high_52w > 0) else np.nan

        score, wt = 0.0, 0.0
        for val, w in [(roc_12m, 1.0), (roc_6m, 2.0), (roc_3m, 2.0), (dist_from_high, 0.5)]:
            if not np.isnan(val):
                score += val * w
                wt += w

        return float(score / wt) * 100 if wt > 0 else np.nan

    # ─────────────────────────────────────────────────────────────────────
    # Interest on idle cash
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def apply_cash_interest(cash: float, days: int, annual_rate: float) -> float:
        """Simple interest: cash * (1 + rate * days/365.25)."""
        if cash <= 0 or days <= 0 or annual_rate <= 0:
            return cash
        return cash * (1.0 + annual_rate * days / 365.25)

"""
momentum_strategy.py – Multi-factor momentum strategy: scoring, filtering, ranking.

Stages
------
Stage 1  Technical / price filters (price floor, volume floor, RSI range).
         Optional: consistency check over recent N days.
Stage 2  Relative percentile filters (P-Score ≥ MIN_P_SCORE_PCT,
                                       V-Score ≥ MIN_V_SCORE_PCT,
                                       RS-55 > 0, RSI > 50).
Stage 3  Final Weighted Momentum Score (WMS) from ranked percentile components.

The class is intentionally *stateless with respect to market data* – it
receives data via the DatabaseManager and returns scored dicts / DataFrames.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config import Config
from database_manager import DatabaseManager
from technical_indicators import TechnicalIndicators as TI


class MomentumStrategy:
    """
    Scores and ranks a universe of stocks according to the multi-factor
    WMS (Weighted Momentum Score) methodology.

    Parameters
    ----------
    config  : Config instance
    db      : DatabaseManager instance (provides price & fundamental data)
    """

    def __init__(self, config: Config, db: DatabaseManager) -> None:
        self._cfg = config
        self._db = db

    # ─────────────────────────────────────────────────────────────────────
    # Public entry point
    # ─────────────────────────────────────────────────────────────────────

    def score_universe(
        self,
        symbols: List[str],
        target_date: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Score all *symbols* as of *target_date* (defaults to now).

        Returns a list of result dicts, each containing:
          Symbol, PassedFilters, FilterReason, raw scores, percentile ranks,
          FinalWeightedScore (WMS), and consistency metadata.
        """
        if target_date is None:
            target_date = datetime.now()

        benchmark_ticker: str = self._cfg["DATA_CONFIG"]["INDEX_BENCHMARK"]
        print(f"Scoring {len(symbols)} symbols as of {target_date.date()} against benchmark {benchmark_ticker}...")
        bench_df = self._db.get_price(benchmark_ticker)

        raw_results: List[Dict[str, Any]] = []
        total = len(symbols)

        for i, symbol in enumerate(symbols):
            import sys
            sys.stdout.write(
                f"  Scoring [{i+1}/{total}] {symbol} …           \r"
            )
            sys.stdout.flush()

            df = self._db.get_price(symbol)
            if df is None or df.empty:
                raw_results.append(self._empty_result(symbol, "No price data"))
                continue

            df_up_to = df.loc[:target_date]
            if df_up_to.empty:
                raw_results.append(
                    self._empty_result(symbol, f"No data up to {target_date.date()}")
                )
                continue

            # ── Stage 1: technical filters ─────────────────────────────
            # 1.1 Apply Technical/Consistency Filters
            passed, reason, tech, consistency = self._apply_tech_filters(
                df_up_to, target_date
            )

            # ── Raw factor scores ──────────────────────────────────────
            momentum_cfg = self._cfg["MOMENTUM_CONFIG"]
            bench_up_to = (
                bench_df.loc[:target_date]
                if bench_df is not None else None
            )

            rs_raw    = TI.rs_ratio(df_up_to, bench_up_to, momentum_cfg["RS_LOOKBACK_DAYS"])
            wms_roc   = TI.weighted_roc_composite(
                df_up_to,
                momentum_cfg["WMS_ROC_PERIODS"],
                momentum_cfg["WMS_ROC_WEIGHTS"],
            )
            p_mom_raw = TI.price_momentum_composite(df_up_to)

            fundamentals = self._db.get_fundamental(symbol)
            value_raw    = self._composite_value_score(fundamentals)

            raw_results.append({
                "Symbol":        symbol,
                "PassedFilters": passed,
                "FilterReason":  reason,
                "RS_Raw":        rs_raw,
                "WMS_ROC_Raw":   wms_roc,
                "P_Mom_Raw":     p_mom_raw,
                "Value_Raw":     value_raw,
                "RSI_Raw":       tech.get("RSI_Raw"),
                "MFI_Raw":       tech.get("MFI_Raw"),
                "CCI_Raw":       tech.get("CCI_Raw"),
                "ConsistencyOK": consistency.get("ConsistencyOK"),
                "TotalPassed":   consistency.get("TotalPassed"),
                "RecentPassed":  consistency.get("RecentPassed"),
                "Details":       consistency.get("Details"),
            })

        import sys
        sys.stdout.write(" " * 90 + "\r")
        sys.stdout.flush()

        # ── Stage 2 + 3: rank, relative filter, final WMS ─────────────
        return self._rank_and_filter(raw_results)

    # ─────────────────────────────────────────────────────────────────────
    # Stage 1: Technical filters
    # ─────────────────────────────────────────────────────────────────────

    def _apply_tech_filters(
        self, df: pd.DataFrame, target_date: datetime
    ) -> Tuple[bool, str, Dict[str, float], Dict[str, Any]]:
        """
        Applies mandatory technical filters (Price, Volume, Consistency, MA200/MA50 position) 
        and calculates the raw WMS-contributing scores (RSI, MFI, CCI).   
             
        Returns (passed, reason, tech_details, consistency_stats).
        """
        f_cfg = self._cfg["FILTER_CONFIG"]
        passed = True
        reason = ""

        latest_price  = float(df["close"].iloc[-1]) if not df.empty else 0.0
        avg_volume_20 = float(df["volume"].tail(20).mean()) if "volume" in df.columns else 0.0

        # Absolute floors
        # F6: Minimum Price & Volume (Mandatory Base Filters)
        min_price  = f_cfg.get("MIN_PRICE",      1.0)
        min_volume = f_cfg.get("MIN_VOLUME_AVG", 100_000)
        # print(f"Momentun_strategy.py:161 - "
        #       f"Tech filters for {df.index[-1].date()}: Price={latest_price:.2f} (min {min_price}), "
        #       f"AvgVol20={avg_volume_20:,.0f} (min {min_volume:,.0f})")

        if f_cfg.get("ENABLE_FILTERS", True):
            if latest_price < min_price:
                passed, reason = False, f"Price {latest_price:.2f} < {min_price}"
            elif avg_volume_20 < min_volume:
                passed, reason = (
                    False,
                    f"Avg vol {avg_volume_20:,.0f} < {min_volume:,.0f}",
                )

        # Technical indicator values (computed regardless of filter pass)
        rsi = TI.rsi(df)
        mfi = TI.mfi(df)
        cci = TI.cci(df)
        ema50 = TI.ema(df, f_cfg.get("EMA_PERIOD_50", 50))
        ema200 = TI.ema(df, f_cfg.get("EMA_PERIOD_200", 200))

        tech_details = {
            "RSI_Raw": rsi, 
            "MFI_Raw": mfi, 
            "CCI_Raw": cci,
            "EMA50": ema50, 
            "EMA200": ema200
        }
        
        # 3. EMA Alignment Check (If enabled)
        if passed and f_cfg.get("ENABLE_EMA_FILTER", True):
            # Check for bullish alignment: Price > EMA50 > EMA200
            if any(np.isnan([latest_price, ema50, ema200])):
                passed = False
                reason = "Insufficient data for EMA calculation"
            elif not (latest_price > ema50 > ema200):
                passed = False
                reason = f"EMA Alignment Fail: P:{latest_price:.2f} < E50:{ema50:.2f} or E50 < E200:{ema200:.2f}"        

        # Consistency check (optional)
        consistency = self._consistency_check(df, target_date)

        c_cfg = f_cfg.get("CONSISTENCY_CHECK", {})
        if passed and c_cfg.get("ENABLE", False):
            if not consistency.get("ConsistencyOK", True):
                passed = False
                reason = f"Failed consistency check: {consistency.get('Details', '')}"

        return passed, reason, tech_details, consistency

    def _consistency_check(
        self, df: pd.DataFrame, target_date: datetime
    ) -> Dict[str, Any]:
        """Check if stock passed momentum criteria on enough recent days."""
        c_cfg = self._cfg["FILTER_CONFIG"].get("CONSISTENCY_CHECK", {})
        if not c_cfg.get("ENABLE", False):
            return {"ConsistencyOK": True, "TotalPassed": None,
                    "RecentPassed": None, "Details": "Disabled"}

        check_days   = c_cfg.get("CHECK_DAYS",           30)
        min_total    = c_cfg.get("MIN_TOTAL_DAYS_PASS",  15)
        recent_win   = c_cfg.get("RECENT_WINDOW",        10)
        min_recent   = c_cfg.get("MIN_RECENT_DAYS_PASS", 10)

        window_df = df.loc[
            df.index <= target_date
        ].tail(check_days)

        if len(window_df) < check_days // 2:
            return {"ConsistencyOK": False, "TotalPassed": 0,
                    "RecentPassed": 0, "Details": "Insufficient history"}

        momentum_cfg = self._cfg["MOMENTUM_CONFIG"]
        total_pass   = 0
        recent_pass  = 0

        for i in range(len(window_df)):
            sub = window_df.iloc[: i + 1]
            rsi_v  = TI.rsi(sub)
            roc_v  = TI.roc(sub, momentum_cfg["WMS_ROC_PERIODS"][0])
            ok = (not np.isnan(rsi_v) and rsi_v > 50) and (
                not np.isnan(roc_v) and roc_v > 0
            )
            if ok:
                total_pass += 1
                if i >= len(window_df) - recent_win:
                    recent_pass += 1

        ok = (total_pass >= min_total) and (recent_pass >= min_recent)
        return {
            "ConsistencyOK": ok,
            "TotalPassed":   total_pass,
            "RecentPassed":  recent_pass,
            "Details":       f"Total:{total_pass}/{check_days}, Recent:{recent_pass}/{recent_win}",
        }

    # ─────────────────────────────────────────────────────────────────────
    # Stage 2 + 3: ranking, relative filters, final WMS
    # ─────────────────────────────────────────────────────────────────────

    def _rank_and_filter(
        self, raw_results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        1. Build a DataFrame from raw_results.
        2. Percentile-rank each raw score column.
        3. Apply Stage-2 relative filters (P-pct, V-pct, RS, RSI).
        4. Compute final WMS.
        5. Return list of enriched dicts.
        """
        if not raw_results:
            return []

        df = pd.DataFrame(raw_results).set_index("Symbol")

        score_cols = {
            "WMS_ROC_Raw": "WMS_ROC_Raw_Pct",
            "RSI_Raw":     "RSI_Raw_Pct",
            "MFI_Raw":     "MFI_Raw_Pct",
            "CCI_Raw":     "CCI_Raw_Pct",
            "RS_Raw":      "RS_Raw_Pct",
            "P_Mom_Raw":   "P_Mom_Raw_Pct",
            "Value_Raw":   "Value_Raw_Pct",
        }

        # Percentile rank (0–100, ignoring NaN)
        for raw_col, pct_col in score_cols.items():
            if raw_col in df.columns:
                df[pct_col] = df[raw_col].rank(pct=True, na_option="keep") * 100

        # Impute missing WMS_ROC_Raw_Pct with median (carry-forward for new listings)
        if "WMS_ROC_Raw_Pct" in df.columns:
            median_pct = df["WMS_ROC_Raw_Pct"].median()
            df["WMS_ROC_Raw_Pct"] = df["WMS_ROC_Raw_Pct"].fillna(median_pct)

        # Final WMS: weighted sum of percentile ranks
        w_cfg = self._cfg["SCORING_WEIGHTS"]
        wms_mapping = {
            "WMS_ROC_Raw_Pct": w_cfg.get("WMS_ROC_Composite", 0.60),
            "RSI_Raw_Pct":     w_cfg.get("RSI_Score",         0.05),
            "MFI_Raw_Pct":     w_cfg.get("MFI_Score",         0.20),
            "CCI_Raw_Pct":     w_cfg.get("CCI_Score",         0.15),
        }

        wms_series = pd.Series(0.0, index=df.index)
        for col, w in wms_mapping.items():
            if col in df.columns:
                wms_series += df[col].fillna(0) * w
        df["FinalWeightedScore"] = wms_series.round(2)

        # Relative P/V + RS + RSI stage-2 filters
        f_cfg  = self._cfg["FILTER_CONFIG"]
        min_p  = f_cfg.get("MIN_P_SCORE_PCT", 50)
        min_v  = f_cfg.get("MIN_V_SCORE_PCT", 50)

        results: List[Dict[str, Any]] = []

        for symbol, row in df.iterrows():
            r = row.to_dict()
            r["Symbol"] = symbol

            if not r.get("PassedFilters", False):
                results.append(r)
                continue

            # P/V percentile screen
            p_pct = r.get("P_Mom_Raw_Pct", np.nan)
            v_pct = r.get("Value_Raw_Pct",  np.nan)

            if not np.isnan(p_pct) and p_pct < min_p:
                r["PassedFilters"] = False
                r["FilterReason"]  = (
                    f"Failed P-Score percentile filter: {p_pct:.1f} < {min_p}"
                )
            elif not np.isnan(v_pct) and v_pct < min_v:
                r["PassedFilters"] = False
                r["FilterReason"]  = (
                    f"Failed V-Score percentile filter: {v_pct:.1f} < {min_v}"
                )
            elif not np.isnan(r.get("RS_Raw", np.nan)) and r["RS_Raw"] < 0:
                r["PassedFilters"] = False
                r["FilterReason"]  = f"Failed RS-55 > 0 filter: {r['RS_Raw']:.2f}"
            elif not np.isnan(r.get("RSI_Raw", np.nan)) and r["RSI_Raw"] < 50:
                r["PassedFilters"] = False
                r["FilterReason"]  = f"Failed RSI > 50 filter: {r['RSI_Raw']:.2f}"

            results.append(r)

        return results

    # ─────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _composite_value_score(
        fundamentals: Dict[str, Optional[float]]
    ) -> float:
        """Average of BookToPrice, EarningsYield, SalesToPrice (non-NaN only)."""
        vals = [
            v for v in fundamentals.values()
            if v is not None and not np.isnan(v)
        ]
        return float(np.mean(vals)) if vals else np.nan

    @staticmethod
    def _empty_result(symbol: str, reason: str) -> Dict[str, Any]:
        return {
            "Symbol":        symbol,
            "PassedFilters": False,
            "FilterReason":  reason,
            "RS_Raw": np.nan, "WMS_ROC_Raw": np.nan,
            "P_Mom_Raw": np.nan, "Value_Raw": np.nan,
            "RSI_Raw": np.nan, "MFI_Raw": np.nan, "CCI_Raw": np.nan,
            "ConsistencyOK": False, "TotalPassed": 0,
            "RecentPassed": 0, "Details": "No data",
            "FinalWeightedScore": 0.0,
        }

    # ─────────────────────────────────────────────────────────────────────
    # Convenience: top-N filtered results
    # ─────────────────────────────────────────────────────────────────────

    def top_n_recommendations(
        self,
        symbols: List[str],
        top_n: int,
        target_date: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """
        Score *symbols* and return a DataFrame of the top *top_n* stocks
        that passed all filters, sorted by FinalWeightedScore descending.
        """
        all_results = self.score_universe(symbols, target_date)
        passed = [r for r in all_results if r.get("PassedFilters") and r.get("FinalWeightedScore", 0) > 0]
        df_out = pd.DataFrame(passed).sort_values("FinalWeightedScore", ascending=False).head(top_n)
        df_out = df_out.reset_index(drop=True)
        df_out.index += 1
        df_out.index.name = "Rank"
        return df_out

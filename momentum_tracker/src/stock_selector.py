"""
stock_selector.py – Generates today's top recommendations and scores
                    custom stock universes.

StockSelector wraps MomentumStrategy.score_universe() with user-facing
display formatting and export logic.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd

from config import Config
from database_manager import DatabaseManager
from momentum_strategy import MomentumStrategy
from symbol_loader import SymbolLoader
from report_exporter import ReportExporter


class StockSelector:
    """
    Generates scored recommendations for interactive use.

    Parameters
    ----------
    config   : Config
    db       : DatabaseManager
    strategy : MomentumStrategy
    exporter : ReportExporter
    """

    # Column display order for all recommendation outputs
    _EXPORT_COLS = [
        "Rank",'Symbol', 'WMS', 'P_Pct', 'V_Pct', 
        # Percentile versions (if you still need them, keeping them at the end)
        'WMS_ROC_Raw_Pct', 'RSI_Raw_Pct', 'MFI_Raw_Pct', 'CCI_Raw_Pct', 'RS_Raw_Pct', 
        # Raw versions (if you still need them, keeping them at the end)
        'P_Mom_Raw', 'Value_Raw', 'WMS_ROC_Raw', 'RSI_Raw', 'MFI_Raw', 'CCI_Raw', 'RS_Raw', 
        # Filters and details
        'PassedFilters', 'FilterReason', 'Consistency', 'FilterDetails', 
        'TotalPassed', 'RecentPassed'
    ]

    def __init__(
        self,
        config: Config,
        db: DatabaseManager,
        strategy: MomentumStrategy,
        exporter: ReportExporter,
    ) -> None:
        self._cfg      = config
        self._db       = db
        self._strategy = strategy
        self._exporter = exporter
        self._loader   = SymbolLoader(config)

    # ─────────────────────────────────────────────────────────────────────
    # Today's recommendations for one category
    # ─────────────────────────────────────────────────────────────────────

    def top_recommendations(
        self,
        category: str,
        top_n: int,
        target_date: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """
        Score all stocks in *category* and return the top *top_n* that
        passed all filters, sorted by WMS descending.

        Also exports the full filtered set to Excel.
        """
        target_date = target_date or datetime.now()
        symbols = self._loader.load(category)
        if not symbols:
            print(f"[Selector] No symbols for '{category}'.")
            return pd.DataFrame()

        print(f"\n[Selector] Scoring {len(symbols)} stocks in '{category}' …")
        self._db.ensure_prices(symbols, self._cfg["DATA_CONFIG"]["INDEX_BENCHMARK"])

        scored = self._strategy.score_universe(symbols, target_date)
        passed = [
            r for r in scored
            if r.get("PassedFilters") and r.get("FinalWeightedScore", 0) > 0
        ]

        if not passed:
            print(f"[Selector] No stocks passed all filters in '{category}'.")
            return pd.DataFrame()

        df = pd.DataFrame(passed)

        # Friendly column renames
        df = df.rename(columns={
            "FinalWeightedScore": "WMS",
            "P_Mom_Raw_Pct":      "P_Pct",
            "Value_Raw_Pct":      "V_Pct",
            "ConsistencyOK":      "Consistency",
            "Details":            "FilterDetails",
        })

        # df = df.sort_values("WMS", ascending=False)
        df = df.sort_values(
            by=['PassedFilters', 'WMS', 'P_Pct', 'V_Pct'], 
            ascending=[False, False, False, False]
        ) 

        # Export full set
        export_df = self._select_export_cols(df)
        if self._exporter is not None and not export_df.empty:
            self._exporter.export_scores(
                export_df,
                base_dir="output",
                filename=f"{category}_Top_Recommendations",
            )

        # Display top N
        display_cols = ["Symbol", "WMS", "P_Pct", "V_Pct", "RS_Raw", "RSI_Raw", "MFI_Raw", "CCI_Raw"]
        disp = df[
            [c for c in display_cols if c in df.columns]
        ].head(top_n).reset_index(drop=True)
        disp.index += 1
        disp.index.name = "Rank"

        # Round floats for display
        for col in disp.select_dtypes(include="float").columns:
            disp[col] = disp[col].round(2)

        print(f"\n── Top {min(top_n, len(passed))} Recommendations ({category}) ──")
        try:
            print(disp.to_markdown(index=True, numalign="left", stralign="left"))
        except ImportError:
            print(disp.to_string())

        return disp

    # ─────────────────────────────────────────────────────────────────────
    # Export full universe scores for all categories
    # ─────────────────────────────────────────────────────────────────────

    def export_all_raw_scores(self, category: str) -> None:
        """
        Exports the raw scores of every stock in the universe, 
        ignoring filter status.
        """
        from symbol_loader import SymbolLoader # Ensure circular imports handled
        symbols = SymbolLoader(self._cfg).load(category)
        
        print(f"  [Selector] Scoring full universe for '{category}' ({len(symbols)} symbols) …")
        
        # 1. Get raw scores (all stocks)
        all_results = self._strategy.score_universe(symbols)
        
        df_out = pd.DataFrame(all_results)
        # Friendly column renames
        df_out = df_out.rename(columns={
            "FinalWeightedScore": "WMS",
            "P_Mom_Raw_Pct":      "P_Pct",
            "Value_Raw_Pct":      "V_Pct",
            "ConsistencyOK":      "Consistency",
            "Details":            "FilterDetails",
        })
        
        # print(f" df.columns: {df_out.columns.tolist()}")
        
        # 2. Export all results without filtering for PassedFilters
        # We sort by FinalWeightedScore for readability
        df_out = df_out.sort_values(
            by=['PassedFilters', 'WMS', 'P_Pct', 'V_Pct'], 
            ascending=[False, False, False, False]
        )        
        
        # 3. Let the helper handle Rank and reordering
        df_final = self._select_export_cols(df_out)
        
        # 4. Export
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = Path("Backtest_Results") / f"Full_Universe_{category}_{ts}.xlsx"
        df_final.to_excel(out_path, index=False)
        
        print(f"  ✅ Exported {len(df_out)} stocks to {out_path}")
        
    def export_all_category_scores(self) -> None:
        """Score and export every configured category to Excel."""
        for cat in self._loader.available_categories():
            print(f"\n[Selector] Exporting scores for '{cat}' …")
            # self.top_recommendations(cat, top_n=9999)  # export all
            self.export_all_raw_scores(cat)

    # ─────────────────────────────────────────────────────────────────────
    # Score a custom universe from an Excel workbook
    # ─────────────────────────────────────────────────────────────────────

    def score_custom_universe_from_excel(self, file_name: str) -> None:
        """
        Read each sheet of *file_name* as a separate stock universe.

        Each sheet should have:
          * A 'Symbol' (or 'Ticker') column with ticker symbols.
          * An optional 'Date' / 'Score Date' column (falls back to today).

        Scores are computed and exported sheet-by-sheet to a merged Excel.
        """
        p = Path(file_name)
        if not p.exists():
            print(f"[Selector] File not found: '{file_name}'.")
            return

        try:
            xls = pd.ExcelFile(p)
        except Exception as exc:
            print(f"[Selector] Cannot open '{file_name}': {exc}")
            return

        all_results: dict = {}

        for sheet in xls.sheet_names:
            print(f"\n── Sheet: '{sheet}' ──")
            try:
                df_raw = xls.parse(sheet)
            except Exception as exc:
                print(f"  [Skip] Cannot parse sheet: {exc}")
                continue

            if df_raw.empty:
                print("  [Skip] Empty sheet.")
                continue

            # ── Detect score date ──────────────────────────────────────
            score_date = self._detect_score_date(df_raw)

            # ── Detect tickers ─────────────────────────────────────────
            tickers = self._detect_tickers(df_raw)
            if not tickers:
                print("  [Skip] No valid tickers found.")
                continue

            print(f"  {len(tickers)} tickers, scoring as of {score_date}")

            # ── Download & score ───────────────────────────────────────
            self._db.ensure_prices(tickers)
            scored = self._strategy.score_universe(
                tickers,
                target_date=datetime.combine(score_date, datetime.min.time()),
            )

            df_scored = pd.DataFrame(scored).rename(columns={
                "FinalWeightedScore": "WMS",
                "P_Mom_Raw_Pct":      "P_Pct",
                "Value_Raw_Pct":      "V_Pct",
                "Symbol":             "Ticker_YF",
            })

            # Merge original data with scores
            ticker_col = self._find_ticker_col(df_raw)
            if ticker_col:
                df_raw["Ticker_YF"] = df_raw[ticker_col].apply(
                    lambda t: (str(t).strip().upper() + ".NS")
                    if "." not in str(t) else str(t).strip().upper()
                )
                merged = df_raw.merge(df_scored, on="Ticker_YF", how="left")
            else:
                merged = df_scored

            all_results[sheet] = merged

        if all_results:
            ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_file = Path("output") / f"custom_universe_scores_{ts}.xlsx"
            out_file.parent.mkdir(exist_ok=True)
            with pd.ExcelWriter(out_file, engine="xlsxwriter") as writer:
                for sheet_name, df in all_results.items():
                    df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
            print(f"\n✅ Custom universe scores exported → {out_file}")

    # ─────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────

    def _detect_score_date(self, df: pd.DataFrame):
        """Try to parse a score date from the sheet; fall back to today."""
        from datetime import date
        date_cols = [c for c in df.columns if "date" in c.lower()]
        if date_cols:
            raw = df[date_cols[0]].dropna()
            if not raw.empty:
                val = raw.iloc[0]
                try:
                    if isinstance(val, str) and "to" in val.lower():
                        val = val.split("to")[0].strip()
                    return pd.to_datetime(val).date()
                except Exception:
                    pass
        return date.today()

    @staticmethod
    def _detect_tickers(df: pd.DataFrame) -> List[str]:
        col = None
        for c in df.columns:
            if "symbol" in c.lower() or "ticker" in c.lower():
                col = c
                break
        if col is None and len(df.columns) >= 1:
            col = df.columns[0]
        if col is None:
            return []

        tickers = []
        for raw in df[col].dropna():
            t = str(raw).strip().upper()
            if t and t != "NA":
                tickers.append(t if "." in t else t + ".NS")
        return list(dict.fromkeys(tickers))  # deduplicate, preserve order

    @staticmethod
    def _find_ticker_col(df: pd.DataFrame) -> Optional[str]:
        for c in df.columns:
            if "symbol" in c.lower() or "ticker" in c.lower():
                return c
        return None

    def _select_export_cols(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Standardizes the output format:
        1. Ensures 'Rank' exists (based on current order).
        2. Filters for allowed columns defined in _EXPORT_COLS.
        3. Maintains exact export order.
        """
        # Ensure copy to avoid mutating the source
        df_out = df.copy()

        # 1. Add Rank if not present, assuming the input df is already sorted
        if "Rank" not in df_out.columns:
            df_out["Rank"] = range(1, len(df_out) + 1)

        # 2. Select only columns defined in _EXPORT_COLS that actually exist in the df
        cols = [c for c in self._EXPORT_COLS if c in df_out.columns]
        df_final = df_out[cols].reset_index(drop=True)
    
        # 3. Round all numeric columns to 2 decimal places
        # This keeps integers/IDs intact while cleaning up floats
        numeric_cols = df_final.select_dtypes(include=['float64', 'float32']).columns
        df_final[numeric_cols] = df_final[numeric_cols].round(2)
        return df_final

"""
report_exporter.py – Centralised export of all reports, charts, and Excel files.

All file-writing operations in the system flow through this class so that
output paths, naming conventions, and chart styles are managed in one place.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


class ReportExporter:
    """
    Writes backtest results, score tables, and comparison charts to disk.

    Parameters
    ----------
    base_output_dir : Root output directory (e.g. 'Backtest_Results').
    """

    def __init__(self, base_output_dir: Optional[str] = None) -> None:
        if base_output_dir is None:
            try:
                from config import Config
                cfg = Config()
                base_output_dir = cfg.get("SYSTEM_CONFIG", {}).get("BACKTEST_RESULTS_DIR", "Backtest_Results")
            except Exception:
                base_output_dir = "Backtest_Results"
        self._base_dir = Path(base_output_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    # ─────────────────────────────────────────────────────────────────────
    # Single-run backtest export
    # ─────────────────────────────────────────────────────────────────────

    def export_backtest(
        self,
        category: str,
        df_rebalance: pd.DataFrame,
        df_equity: pd.DataFrame,
        df_transactions: pd.DataFrame,
        df_benchmarks: pd.DataFrame,
        filename: Optional[str] = None,
    ) -> Path:
        """
        Write backtest results to a 4-sheet Excel file and a comparison chart.

        Returns the path to the Excel file.
        """
        ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
        name   = filename or f"{category}_{ts}"
        folder = self._base_dir / "single_runs"
        folder.mkdir(parents=True, exist_ok=True)
        xlsx   = folder / f"{name}.xlsx"

        # Normalise column names
        df_rebalance    = _norm_cols(df_rebalance)
        df_equity       = _norm_cols(df_equity)
        df_transactions = _norm_cols(df_transactions)
        df_benchmarks   = _norm_cols(df_benchmarks)

        # Deduplicate & sort equity / benchmark by date
        for df in (df_equity, df_benchmarks):
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                df.sort_values("date", inplace=True)
                df.drop_duplicates(subset=["date"], keep="first", inplace=True)

        try:
            with pd.ExcelWriter(xlsx, engine="xlsxwriter") as writer:
                df_rebalance.to_excel(   writer, sheet_name="Rebalance_Summary", index=False)
                df_equity.to_excel(      writer, sheet_name="Equity_Curve",      index=False)
                df_transactions.to_excel(writer, sheet_name="Transaction_Log",   index=False)
                df_benchmarks.to_excel(  writer, sheet_name="Benchmark",         index=False)
            print(f"✅ Backtest exported → {xlsx}")
        except Exception as exc:
            print(f"[Exporter] Excel write failed: {exc}")

        # Chart
        chart_path = folder / f"{name}_chart.png"
        self._plot_equity_vs_benchmark(
            df_equity, df_benchmarks,
            title=f"{category} – Equity vs Benchmark",
            out_path=chart_path,
        )

        return xlsx

    def export_backtest_any(
        self,
        category: str,
        df_rebalance: pd.DataFrame,
        df_equity: pd.DataFrame,
        df_transactions: pd.DataFrame,
        df_benchmarks: pd.DataFrame,
        file_name: str,
    ) -> Path:
        """
        Export backtest results to either Excel or CSV set depending on extension.

        - If file_name ends with .csv → writes 4 CSVs: *_Summary, *_Equity, *_Transactions, *_Benchmark
        - Otherwise               → writes a 4-sheet .xlsx (same as export_backtest)

        Returns the primary output path (xlsx or the summary csv).
        """
        # Normalise column names once
        df_rebalance    = _norm_cols(df_rebalance)
        df_equity       = _norm_cols(df_equity)
        df_transactions = _norm_cols(df_transactions)
        df_benchmarks   = _norm_cols(df_benchmarks)

        # Deduplicate & sort equity / benchmark by date
        for df in (df_equity, df_benchmarks):
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                df.sort_values("date", inplace=True)
                df.drop_duplicates(subset=["date"], keep="first", inplace=True)

        folder = self._base_dir / "single_runs"
        folder.mkdir(parents=True, exist_ok=True)

        target = Path(file_name)
        if not target.suffix:
            target = target.with_suffix(".xlsx")

        # Treat relative paths as inside the backtest output folder
        if not target.is_absolute():
            target = folder / target.name

        if target.suffix.lower() != ".csv":
            # Excel path (respect caller-provided name)
            try:
                with pd.ExcelWriter(target, engine="xlsxwriter") as writer:
                    df_rebalance.to_excel(   writer, sheet_name="Rebalance_Summary", index=False)
                    df_equity.to_excel(      writer, sheet_name="Equity_Curve",      index=False)
                    df_transactions.to_excel(writer, sheet_name="Transaction_Log",   index=False)
                    df_benchmarks.to_excel(  writer, sheet_name="Benchmark",         index=False)
                print(f"✅ Backtest exported → {target}")
            except Exception as exc:
                print(f"[Exporter] Excel write failed: {exc}")

            # Chart (best-effort; use same base name)
            chart_path = target.with_suffix("").with_name(target.stem + "_chart.png")
            self._plot_equity_vs_benchmark(
                df_equity, df_benchmarks,
                title=f"{category} – Equity vs Benchmark",
                out_path=chart_path,
            )
            return target

        # CSV set export
        base_no_ext = str(target.with_suffix(""))
        summary_csv = Path(f"{base_no_ext}_Summary.csv")
        equity_csv  = Path(f"{base_no_ext}_Equity.csv")
        txn_csv     = Path(f"{base_no_ext}_Transactions.csv")
        bench_csv   = Path(f"{base_no_ext}_Benchmark.csv")
        try:
            df_rebalance.to_csv(summary_csv, index=False)
            df_equity.to_csv(equity_csv, index=False)
            df_transactions.to_csv(txn_csv, index=False)
            df_benchmarks.to_csv(bench_csv, index=False)
            print("✅ Backtest exported to CSV files →")
            print(f"   {summary_csv.name}")
            print(f"   {equity_csv.name}")
            print(f"   {txn_csv.name}")
            print(f"   {bench_csv.name}")
        except Exception as exc:
            print(f"[Exporter] CSV write failed: {exc}")
        return summary_csv

    # ─────────────────────────────────────────────────────────────────────
    # Multi-year comparison export
    # ─────────────────────────────────────────────────────────────────────

    def export_multi_year_comparison(
        self,
        category: str,
        df_summary: pd.DataFrame,
        equity_curves: Dict[str, "pd.Series"],
        bench_curves: Dict[str, "pd.Series"],
    ) -> Path:
        """Export multi-lookback comparison Excel + overlay chart."""
        ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder = self._base_dir / "multi_year"
        folder.mkdir(parents=True, exist_ok=True)
        xlsx   = folder / f"{category}_multi_year_{ts}.xlsx"

        try:
            with pd.ExcelWriter(xlsx, engine="xlsxwriter") as writer:
                df_summary.to_excel(writer, sheet_name="Summary", index=False)
                for label, ser in equity_curves.items():
                    ser.reset_index().rename(
                        columns={ser.index.name or "index": "Date", 0: "Equity"}
                    ).to_excel(writer, sheet_name=f"Eq_{label}"[:31], index=False)
                for label, ser in bench_curves.items():
                    ser.reset_index().rename(
                        columns={ser.index.name or "index": "Date", 0: "Benchmark"}
                    ).to_excel(writer, sheet_name=f"Bm_{label}"[:31], index=False)
            print(f"✅ Multi-year comparison → {xlsx}")
        except Exception as exc:
            print(f"[Exporter] Excel write failed: {exc}")

        # Overlay chart
        chart_path = folder / f"{category}_multi_year_{ts}.png"
        self._plot_multi_equity_overlay(
            equity_curves, bench_curves,
            title=f"{category} – Multiple Lookback Windows",
            out_path=chart_path,
        )

        return xlsx

    # ─────────────────────────────────────────────────────────────────────
    # Multi-category × multi-year master export
    # ─────────────────────────────────────────────────────────────────────

    def export_multi_category_multi_year(
        self,
        df_summary: pd.DataFrame,
        curves_by_fy: Dict[int, Dict],
    ) -> Path:
        """Export master Excel with summary + all equity curves, one chart per FY."""
        ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder = self._base_dir / ts
        folder.mkdir(parents=True, exist_ok=True)
        xlsx   = folder / f"multi_category_multi_year_{ts}.xlsx"

        strat_rows: list = []
        bench_rows: list = []

        for fy_year, data in curves_by_fy.items():
            for label, ser in data.get("strategy", {}).items():
                for dt, val in ser.items():
                    strat_rows.append({"FY_Year": fy_year, "Label": label,
                                       "Date": dt, "Equity": float(val)})
            for label, b_ser in data.get("benchmark", {}).items():
                for dt, val in b_ser.items():
                    bench_rows.append({"FY_Year": fy_year, "Label": label,
                                       "Date": dt, "Benchmark": float(val)})

        try:
            with pd.ExcelWriter(xlsx, engine="xlsxwriter") as writer:
                df_summary.to_excel(writer, sheet_name="Summary", index=False)
                if strat_rows:
                    pd.DataFrame(strat_rows).to_excel(
                        writer, sheet_name="All_Equity_Curves", index=False
                    )
                if bench_rows:
                    pd.DataFrame(bench_rows).to_excel(
                        writer, sheet_name="All_Benchmark_Curves", index=False
                    )
            print(f"✅ Master backtest export → {xlsx}")
        except Exception as exc:
            print(f"[Exporter] Excel write failed: {exc}")

        # One chart per FY
        for fy_year, data in curves_by_fy.items():
            self._plot_multi_equity_overlay(
                data.get("strategy", {}),
                data.get("benchmark", {}),
                title=f"FY {fy_year} – All Categories",
                out_path=folder / f"FY{fy_year}_chart.png",
            )

        return xlsx

    # ─────────────────────────────────────────────────────────────────────
    # Generic score / recommendations export
    # ─────────────────────────────────────────────────────────────────────

    def export_scores(
        self,
        df: pd.DataFrame,
        base_dir: Optional[str] = None,
        filename: str = "scores",
    ) -> Path:
        """Write *df* to a timestamped Excel file in *base_dir*."""
        if base_dir is None:
            try:
                from config import Config
                cfg = Config()
                base_dir = cfg.get("SYSTEM_CONFIG", {}).get("OUTPUT_DIR", "output")
            except Exception:
                base_dir = "output"
        out = Path(base_dir)
        out.mkdir(parents=True, exist_ok=True)
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = filename.replace(" ", "_").replace("/", "-")
        xlsx = out / f"{safe}_{ts}.xlsx"
        try:
            df.to_excel(xlsx, index=True)
            print(f"✅ Scores exported → {xlsx}")
        except Exception as exc:
            print(f"[Exporter] Excel write failed: {exc}")
        return xlsx

    def export_scores_any(
        self,
        df: pd.DataFrame,
        base_dir: Optional[str] = None,
        filename: str = "scores",
        file_ext: str = ".xlsx",
    ) -> Path:
        """
        Export scores to Excel or CSV based on *file_ext* ('.xlsx' or '.csv').
        Returns the written file path.
        """
        if base_dir is None:
            try:
                from config import Config
                cfg = Config()
                base_dir = cfg.get("SYSTEM_CONFIG", {}).get("OUTPUT_DIR", "output")
            except Exception:
                base_dir = "output"
        out = Path(base_dir)
        out.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = filename.replace(" ", "_").replace("/", "-")

        ext = (file_ext or ".xlsx").lower().strip()
        if not ext.startswith("."):
            ext = "." + ext

        target = out / f"{safe}_{ts}{ext}"
        try:
            if ext == ".csv":
                df.to_csv(target, index=False)
                print(f"✅ Scores exported → {target}")
            else:
                df.to_excel(target, index=True)
                print(f"✅ Scores exported → {target}")
        except Exception as exc:
            print(f"[Exporter] Write failed: {exc}")
        return target

    # ─────────────────────────────────────────────────────────────────────
    # Charts
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _plot_equity_vs_benchmark(
        df_equity: pd.DataFrame,
        df_bench: pd.DataFrame,
        title: str,
        out_path: Path,
    ) -> None:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(12, 6))

            if not df_equity.empty and "date" in df_equity.columns and "equity" in df_equity.columns:
                eq = df_equity.set_index("date")["equity"]
                (eq / eq.iloc[0] * 100).plot(ax=ax, label="Strategy", linewidth=2)

            if not df_bench.empty and "date" in df_bench.columns and "close" in df_bench.columns:
                bm = df_bench.set_index("date")["close"]
                (bm / bm.iloc[0] * 100).plot(ax=ax, label="Benchmark", linewidth=1.5, linestyle="--")

            ax.set_title(title)
            ax.set_ylabel("Normalised Value (base = 100)")
            ax.legend()
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.savefig(out_path, dpi=150)
            plt.close(fig)
            print(f"✅ Chart saved → {out_path}")
        except Exception as exc:
            print(f"[Exporter] Chart generation failed: {exc}")

    @staticmethod
    def _plot_multi_equity_overlay(
        equity_curves: Dict[str, "pd.Series"],
        bench_curves: Dict[str, "pd.Series"],
        title: str,
        out_path: Path,
    ) -> None:
        if not equity_curves:
            return
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(14, 7))
            colours = plt.cm.tab10.colors  # type: ignore

            for idx, (label, ser) in enumerate(equity_curves.items()):
                if not ser.empty:
                    norm = ser / ser.iloc[0] * 100
                    norm.plot(ax=ax, label=f"Strategy – {label}",
                              color=colours[idx % len(colours)], linewidth=2)

            for idx, (label, ser) in enumerate(bench_curves.items()):
                if not ser.empty:
                    norm = ser / ser.iloc[0] * 100
                    norm.plot(ax=ax, label=f"Benchmark – {label}",
                              color=colours[idx % len(colours)], linewidth=1.2,
                              linestyle="--", alpha=0.7)

            ax.set_title(title)
            ax.set_ylabel("Normalised Value (base = 100)")
            ax.legend(fontsize=8)
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.savefig(out_path, dpi=150)
            plt.close(fig)
            print(f"✅ Chart saved → {out_path}")
        except Exception as exc:
            print(f"[Exporter] Chart generation failed: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase and strip column names."""
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df

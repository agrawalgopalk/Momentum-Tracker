"""
portfolio_manager.py – Live portfolio tracking and rebalancing assistant.

PortfolioManager maintains a persisted JSON file of the current live
portfolio (holdings, purchase prices, dates) and can:

  * load / save the portfolio from/to disk
  * value the portfolio at the latest market prices
  * compare the live portfolio against the model's top-N recommendations
    and generate a structured BUY / HOLD / SELL action report
  * export the rebalance report to a timestamped Excel file

The class is deliberately independent of the backtester – it works on
*live* data (today's scores) rather than simulated history.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from config import Config
from database_manager import DatabaseManager
from momentum_strategy import MomentumStrategy


class PortfolioManager:
    """
    Manages the live momentum portfolio.

    Parameters
    ----------
    config   : Config instance
    db       : DatabaseManager instance
    strategy : MomentumStrategy instance
    file_path: Path to the JSON file that persists the live portfolio.
               Created automatically if absent.
    """

    _DEFAULT_FILE = "live_portfolio.json"

    def __init__(
        self,
        config: Config,
        db: DatabaseManager,
        strategy: MomentumStrategy,
        file_path: str | Path = _DEFAULT_FILE,
    ) -> None:
        self._cfg       = config
        self._db        = db
        self._strategy  = strategy
        self._file      = Path(file_path)

        # holdings: {symbol: {"shares": int, "avg_cost": float, "date_added": str}}
        self._holdings: Dict[str, Dict[str, Any]] = {}
        self._load_holdings()

        # Ensure rebalance history folder exists
        Path("Rebalance_history").mkdir(exist_ok=True)

    # ─────────────────────────────────────────────────────────────────────
    # Persistence
    # ─────────────────────────────────────────────────────────────────────

    def _load_holdings(self) -> None:
        if self._file.exists():
            try:
                with open(self._file, "r") as fh:
                    self._holdings = json.load(fh)
                print(f"[Portfolio] Loaded {len(self._holdings)} holdings from '{self._file}'.")
            except Exception as exc:
                print(f"[Portfolio] Could not read '{self._file}': {exc}. Starting empty.")
        else:
            print(f"[Portfolio] No portfolio file found – starting empty.")

    def save(self) -> None:
        """Persist current holdings to disk."""
        try:
            with open(self._file, "w") as fh:
                json.dump(self._holdings, fh, indent=4)
            print(f"[Portfolio] Saved {len(self._holdings)} holdings to '{self._file}'.")
        except Exception as exc:
            print(f"[Portfolio] Error saving: {exc}")

    # ─────────────────────────────────────────────────────────────────────
    # Holdings management
    # ─────────────────────────────────────────────────────────────────────

    def add_holding(
        self, symbol: str, shares: int, avg_cost: float, date_added: Optional[str] = None
    ) -> None:
        """Add or update a holding."""
        self._holdings[symbol.upper()] = {
            "shares":     shares,
            "avg_cost":   avg_cost,
            "date_added": date_added or datetime.now().strftime("%Y-%m-%d"),
        }
        print(f"[Portfolio] Added/updated: {symbol} – {shares} shares @ ₹{avg_cost:.2f}")

    def remove_holding(self, symbol: str) -> None:
        symbol = symbol.upper()
        if symbol in self._holdings:
            del self._holdings[symbol]
            print(f"[Portfolio] Removed: {symbol}")
        else:
            print(f"[Portfolio] {symbol} not found in portfolio.")

    @property
    def holdings(self) -> Dict[str, Dict[str, Any]]:
        return self._holdings.copy()

    @property
    def symbols(self) -> List[str]:
        return list(self._holdings.keys())

    # ─────────────────────────────────────────────────────────────────────
    # Valuation
    # ─────────────────────────────────────────────────────────────────────

    def current_value(self) -> pd.DataFrame:
        """
        Return a DataFrame with current market value for each holding.

        Columns: Symbol, Shares, Avg_Cost, Current_Price,
                 Market_Value, Unrealised_PnL, PnL_%
        """
        rows = []
        for symbol, info in self._holdings.items():
            df = self._db.get_price(symbol)
            price = float(df["close"].iloc[-1]) if (df is not None and not df.empty) else np.nan
            shares    = info["shares"]
            avg_cost  = info.get("avg_cost", np.nan)
            mkt_value = shares * price if not np.isnan(price) else np.nan
            pnl       = mkt_value - shares * avg_cost if not np.isnan(mkt_value) else np.nan
            pnl_pct   = (pnl / (shares * avg_cost) * 100) if (avg_cost > 0 and not np.isnan(pnl)) else np.nan

            rows.append({
                "Symbol":          symbol,
                "Shares":          shares,
                "Avg_Cost":        round(avg_cost, 2),
                "Current_Price":   round(price, 2) if not np.isnan(price) else None,
                "Market_Value":    round(mkt_value, 2) if not np.isnan(mkt_value) else None,
                "Unrealised_PnL":  round(pnl, 2) if not np.isnan(pnl) else None,
                "PnL_%":           round(pnl_pct, 2) if not np.isnan(pnl_pct) else None,
            })

        df_out = pd.DataFrame(rows)
        if not df_out.empty:
            total_val = df_out["Market_Value"].sum()
            total_pnl = df_out["Unrealised_PnL"].sum()
            print(f"\n  Total Market Value : ₹{total_val:>15,.0f}")
            print(f"  Total Unrealised PnL: ₹{total_pnl:>15,.0f}")
        return df_out

    # ─────────────────────────────────────────────────────────────────────
    # Rebalance assistant
    # ─────────────────────────────────────────────────────────────────────

    def generate_rebalance_report(
        self,
        universe_symbols: List[str],
        target_size: int = 20,
    ) -> pd.DataFrame:
        """
        Compare current holdings against the model's top-N recommendations
        and produce a BUY / HOLD / SELL action report.

        Parameters
        ----------
        universe_symbols : Full list of candidate symbols for scoring.
        target_size      : Desired portfolio size (used to determine BUY slots).

        Returns
        -------
        pd.DataFrame with columns:
            Symbol, WMS, P_Pct, V_Pct, Action, (+ all raw score columns)
        """
        print("\n[Portfolio] Scoring universe for rebalance …")
        self._db.ensure_prices(universe_symbols)
        scored_list = self._strategy.score_universe(universe_symbols)

        if not scored_list:
            print("[Portfolio] No scores returned.")
            return pd.DataFrame()

        scores_df = pd.DataFrame(scored_list)
        scores_df = scores_df.rename(columns={
            "FinalWeightedScore": "WMS",
            "P_Mom_Raw_Pct":      "P_Pct",
            "Value_Raw_Pct":      "V_Pct",
        })

        # Top 40 = hold pool (2× target_size), Top 20 = buy candidates
        hold_pool_size = target_size * 2
        top_symbols    = scores_df[scores_df["PassedFilters"] == True].sort_values(
            "WMS", ascending=False
        )

        top_40_symbols = set(top_symbols.head(hold_pool_size)["Symbol"])
        top_20_symbols = list(top_symbols.head(target_size)["Symbol"])

        rebalance_results: List[Dict] = []
        hold_list: List[str]          = []

        # Step A: decide HOLD or SELL for existing holdings
        for symbol in self._holdings:
            stock_row = scores_df[scores_df["Symbol"] == symbol]

            if stock_row.empty:
                action = "SELL (Data Missing / Delisted)"
            elif symbol in top_40_symbols:
                action = "HOLD"
                hold_list.append(symbol)
            else:
                action = "SELL"

            if not stock_row.empty:
                row_dict = stock_row.iloc[0].to_dict()
                row_dict["Action"] = action
                rebalance_results.append(row_dict)
            else:
                rebalance_results.append({"Symbol": symbol, "Action": action})

        # Step B: fill BUY slots from Top 20
        slots_needed = max(0, target_size - len(hold_list))
        buy_list = [s for s in top_20_symbols if s not in hold_list][:slots_needed]

        for symbol in buy_list:
            row_dict = scores_df[scores_df["Symbol"] == symbol].iloc[0].to_dict()
            row_dict["Action"] = "BUY"
            rebalance_results.append(row_dict)

        # Build report DataFrame
        report_df = pd.DataFrame(rebalance_results)

        # Sort: BUY first, then HOLD, then SELL
        action_order = {"BUY": 1, "HOLD": 2, "SELL": 3}
        report_df["_order"] = report_df["Action"].map(
            lambda a: action_order.get(a, 4)
        )
        report_df = (
            report_df.sort_values(by=["_order", "WMS"], ascending=[True, False])
            .drop(columns=["_order"])
            .reset_index(drop=True)
        )
        report_df.index += 1
        report_df.index.name = "Rank"

        # Export to Excel
        ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = Path("Rebalance_history") / f"Rebalance_Action_{ts}.xlsx"
        try:
            report_df.to_excel(filename, index=False)
            print(f"\n[Portfolio] Rebalance report saved → {filename}")
        except Exception as exc:
            print(f"[Portfolio] Export failed: {exc}")

        # Summary
        print(f"\n--- Rebalance Summary ---")
        print(f"  HOLD  : {len(hold_list)}")
        print(f"  SELL  : {len([r for r in rebalance_results if 'SELL' in r.get('Action', '')])}")
        print(f"  BUY   : {len(buy_list)}")
        print(f"  Final : {len(hold_list) + len(buy_list)} stocks")

        return report_df

    def compare_with_last_recommendation_file(
        self,
        universe_symbols: List[str],
        last_file_path: str,
        target_size: int = 20,
    ) -> pd.DataFrame:
        """
        Generate today's rebalance report and enrich it with information from a
        previous recommendations file (Excel/CSV).

        The previous file is treated as a "last run" snapshot and is used only
        for comparison columns (Prev_Rank / Prev_WMS). It does not change the
        BUY/HOLD/SELL logic (which is based on today's scores + holdings).
        """
        prev_df = self._load_prev_reco_file(last_file_path)
        prev_lookup = self._build_prev_lookup(prev_df)

        today_df = self.generate_rebalance_report(universe_symbols, target_size=target_size)
        if today_df is None or today_df.empty:
            return pd.DataFrame()

        # Add previous rank / WMS columns where possible
        today_df = today_df.copy()
        today_df["Prev_Rank"] = today_df["Symbol"].apply(lambda s: prev_lookup.get(str(s).upper(), {}).get("rank"))
        today_df["Prev_WMS"] = today_df["Symbol"].apply(lambda s: prev_lookup.get(str(s).upper(), {}).get("wms"))

        # Reorder a little for readability
        preferred = ["Symbol", "Action", "WMS", "Prev_WMS", "Prev_Rank", "P_Pct", "V_Pct"]
        cols = preferred + [c for c in today_df.columns if c not in preferred]
        today_df = today_df[[c for c in cols if c in today_df.columns]]

        # Export comparison file
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = Path("Rebalance_history") / f"Rebalance_Compare_{ts}.xlsx"
        try:
            today_df.to_excel(out, index=False)
            print(f"[Portfolio] Comparison report saved → {out}")
        except Exception as exc:
            print(f"[Portfolio] Comparison export failed: {exc}")

        return today_df

    @staticmethod
    def _load_prev_reco_file(path: str) -> pd.DataFrame:
        p = Path(path)
        if not p.exists():
            print(f"[Portfolio] Previous file not found: '{path}'")
            return pd.DataFrame()
        try:
            if p.suffix.lower() == ".csv":
                return pd.read_csv(p)
            return pd.read_excel(p)  # first sheet
        except Exception as exc:
            print(f"[Portfolio] Could not read previous file: {exc}")
            return pd.DataFrame()

    @staticmethod
    def _build_prev_lookup(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
        """
        Create a {SYMBOL -> {rank, wms}} mapping from a previous recommendation export.
        Tries to detect common column names.
        """
        if df is None or df.empty:
            return {}

        cols = {c.lower().strip(): c for c in df.columns}

        # Symbol column candidates
        sym_col = (
            cols.get("symbol")
            or cols.get("ticker_yf")
            or cols.get("ticker")
            or cols.get("symbols")
        )
        if not sym_col:
            # fall back to first column
            sym_col = df.columns[0]

        # WMS column candidates
        wms_col = cols.get("wms") or cols.get("finalweightedscore")

        lookup: Dict[str, Dict[str, Any]] = {}
        for i, row in df.iterrows():
            raw_sym = row.get(sym_col)
            if raw_sym is None:
                continue
            sym = str(raw_sym).strip().upper()
            if not sym or sym == "NA":
                continue
            try:
                wms = float(row.get(wms_col)) if wms_col and row.get(wms_col) is not None else None
            except Exception:
                wms = None
            lookup[sym] = {"rank": int(i) + 1, "wms": wms}

        return lookup

    # ─────────────────────────────────────────────────────────────────────
    # Interactive entry point
    # ─────────────────────────────────────────────────────────────────────

    def interactive_menu(self) -> None:
        """Simple CLI for live portfolio management."""
        while True:
            total = sum(
                h.get("shares", 0) * h.get("avg_cost", 0)
                for h in self._holdings.values()
            )
            print(f"\n--- Portfolio Manager ({len(self._holdings)} holdings) ---")
            print("  [1] View current holdings & valuation")
            print("  [2] Add / update holding")
            print("  [3] Remove holding")
            print("  [4] Generate rebalance report")
            print("  [5] Compare with last recommendation file (Excel/CSV)")
            print("  [6] Save portfolio to disk")
            print("  [0] Back")

            choice = input("Choose: ").strip()

            if choice == "0":
                break

            elif choice == "1":
                df = self.current_value()
                print(df.to_string(index=False))

            elif choice == "2":
                sym    = input("  Symbol (e.g. TCS.NS): ").strip().upper()
                shares = int(input("  Number of shares: ").strip())
                cost   = float(input("  Average cost per share (₹): ").strip())
                dt     = input("  Date added (YYYY-MM-DD, blank=today): ").strip() or None
                self.add_holding(sym, shares, cost, dt)

            elif choice == "3":
                sym = input("  Symbol to remove: ").strip().upper()
                self.remove_holding(sym)

            elif choice == "4":
                from symbol_loader import SymbolLoader
                cat = SymbolLoader(self._cfg).select_interactively()
                if not cat:
                    continue
                from symbol_loader import SymbolLoader
                universe = SymbolLoader(self._cfg).load(cat)
                top_n    = self._cfg["BACKTEST_CONFIG"].get("TOP_N", 20)
                self.generate_rebalance_report(universe, target_size=top_n)

            elif choice == "5":
                from symbol_loader import SymbolLoader
                cat = SymbolLoader(self._cfg).select_interactively()
                if not cat:
                    continue
                universe = SymbolLoader(self._cfg).load(cat)
                top_n = self._cfg["BACKTEST_CONFIG"].get("TOP_N", 20)
                prev = input("  Path to LAST_Recommendation (Excel/CSV): ").strip()
                if not prev:
                    print("  Cancelled.")
                    continue
                self.compare_with_last_recommendation_file(universe, prev, target_size=top_n)

            elif choice == "6":
                self.save()

            else:
                print("  Invalid choice.")

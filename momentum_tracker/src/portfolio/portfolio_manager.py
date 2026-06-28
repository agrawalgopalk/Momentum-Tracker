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

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
import numpy as np
import pandas as pd

# Add project root to sys.path to allow imports from core/ and utils/
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from database.portfolio_service import PortfolioService
from database import get_db
from config import Config
from data.stock_database_manager import StockDatabaseManager
from strategy.momentum_strategy import MomentumStrategy


class PortfolioManager:
    """
    Manages the live momentum portfolio backed by the SQL Database.

    Parameters
    ----------
    config   : Config instance
    db       : StockDatabaseManager instance
    strategy : MomentumStrategy instance
    user_id  : Django User ID (default: 3 for GOPAL)
    """

    def __init__(
        self,
        config: Config,
        db: StockDatabaseManager,
        strategy: MomentumStrategy,
        user_id: int = 3,
    ) -> None:
        self._cfg       = config
        self._db        = db
        self._strategy  = strategy
        self._user_id   = user_id

        # Instantiate the database-backed portfolio service
        self._portfolio_service = PortfolioService(get_db(), self._db)

        # holdings: {symbol: {"shares": int, "avg_cost": float, "date_added": str}}
        self._holdings: Dict[str, Dict[str, Any]] = {}
        self._load_holdings()

        # Ensure rebalance history folder exists
        rebalance_dir = Path(self._cfg.get("SYSTEM_CONFIG", {}).get("REBALANCE_HISTORY_DIR", "Rebalance_history"))
        if not rebalance_dir.is_absolute():
            rebalance_dir = _project_root / rebalance_dir
        rebalance_dir.mkdir(parents=True, exist_ok=True)

    # ─────────────────────────────────────────────────────────────────────
    # Persistence
    # ─────────────────────────────────────────────────────────────────────

    def _load_holdings(self) -> None:
        try:
            self._holdings = self._portfolio_service.get_holdings(user_id=self._user_id)
            print(f"[Portfolio] Loaded {len(self._holdings)} holdings from the SQL Database.")
        except Exception as exc:
            print(f"[Portfolio] Error loading from DB: {exc}. Starting empty.")
            self._holdings = {}

    def save(self) -> None:
        """Positions are persisted in real-time in the SQL Database. No-op for compatibility."""
        print("[Portfolio] Database changes already committed in real-time.")

    # ─────────────────────────────────────────────────────────────────────
    # Holdings management
    # ─────────────────────────────────────────────────────────────────────

    def add_holding(
        self, symbol: str, shares: int, avg_cost: float, date_added: Optional[str] = None
    ) -> None:
        """Add or update a holding in the database."""
        try:
            self._portfolio_service.add_holding(symbol, shares, avg_cost, date_added, user_id=self._user_id)
            print(f"[Portfolio] Added/updated in database: {symbol} – {shares} shares @ ₹{avg_cost:.2f}")
            self._load_holdings()
        except Exception as exc:
            print(f"[Portfolio] Error adding position to database: {exc}")

    def remove_holding(self, symbol: str, sell_price: Optional[float] = None) -> None:
        """Close a position in the database with a sell price."""
        symbol = symbol.upper()
        if symbol not in self._holdings:
            print(f"[Portfolio] {symbol} not found in portfolio.")
            return

        if sell_price is None:
            # Attempt to fetch the latest price from the database price cache
            df = self._db.get_price(symbol)
            default_price = float(df["close"].iloc[-1]) if (df is not None and not df.empty) else self._holdings[symbol]["avg_cost"]
            price_input = input(f"  Enter sell price for {symbol} (default: ₹{default_price:.2f}): ").strip()
            if price_input:
                try:
                    sell_price = float(price_input)
                except ValueError:
                    print("  Invalid price input. Aborted.")
                    return
            else:
                sell_price = default_price

        try:
            self._portfolio_service.remove_holding(symbol, sell_price, user_id=self._user_id)
            print(f"[Portfolio] Closed position in database for: {symbol} at ₹{sell_price:.2f}")
            self._load_holdings()
        except Exception as exc:
            print(f"[Portfolio] Error closing position: {exc}")

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
        df_out = self._portfolio_service.get_portfolio_valuation(user_id=self._user_id)
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

    def compare_and_rebalance(self, portfolio_file: str, last_reco_file: str) -> pd.DataFrame:
        """
        Compare the current portfolio (from Excel) with the last recommendation file (Excel/CSV)
        and output a rebalancing action report showing WMS, prev score, ranks, and BUY/HOLD/SELL.
        """
        # Read portfolio
        try:
            if portfolio_file.endswith(".csv"):
                df_port = pd.read_csv(portfolio_file)
            else:
                df_port = pd.read_excel(portfolio_file)
        except Exception as e:
            print(f"[ERROR] Could not read portfolio file: {e}")
            return pd.DataFrame()

        df_port.columns = [c.strip() for c in df_port.columns]
        sym_col = next((c for c in df_port.columns if c.lower() in ["symbol", "ticker"]), df_port.columns[0])
        df_port[sym_col] = df_port[sym_col].astype(str).str.strip().str.upper()
        current_symbols = set(df_port[sym_col].tolist())

        # Read last reco
        try:
            if last_reco_file.endswith(".csv"):
                df_reco = pd.read_csv(last_reco_file)
            else:
                df_reco = pd.read_excel(last_reco_file)
        except Exception as e:
            print(f"[ERROR] Could not read last recommendation file: {e}")
            return pd.DataFrame()

        df_reco.columns = [c.strip() for c in df_reco.columns]
        reco_sym_col = next((c for c in df_reco.columns if c.lower() in ["symbol", "ticker", "symbol_yf"]), df_reco.columns[0])
        df_reco[reco_sym_col] = df_reco[reco_sym_col].astype(str).str.strip().str.upper()

        wms_col = next((c for c in df_reco.columns if c.lower() in ["wms", "finalweightedscore"]), None)
        passed_col = next((c for c in df_reco.columns if c.lower() in ["passedfilters", "passed_filters"]), None)

        actions = []
        target_size = self._cfg["BACKTEST_CONFIG"].get("TOP_N", 20)

        if wms_col:
            df_reco = df_reco.sort_values(wms_col, ascending=False).reset_index(drop=True)

        reco_list = df_reco.to_dict(orient="records")
        reco_by_sym = {row[reco_sym_col]: row for row in reco_list}

        hold_set = set()
        
        # Step A: process current holdings
        for sym in current_symbols:
            if sym in reco_by_sym:
                row = reco_by_sym[sym]
                passed = row.get(passed_col, True) if passed_col else True
                rank = df_reco[df_reco[reco_sym_col] == sym].index[0] + 1 if wms_col else 999
                
                if passed and rank <= target_size * 2:  # hold pool
                    hold_set.add(sym)
                    actions.append({
                        "Symbol": sym,
                        "Action": "HOLD",
                        "WMS": row.get(wms_col),
                        "PassedFilters": passed,
                        "Rank": rank
                    })
                else:
                    actions.append({
                        "Symbol": sym,
                        "Action": "SELL",
                        "WMS": row.get(wms_col),
                        "PassedFilters": passed,
                        "Rank": rank
                    })
            else:
                actions.append({
                    "Symbol": sym,
                    "Action": "SELL",
                    "WMS": 0.0,
                    "PassedFilters": False,
                    "Rank": 999
                })

        # Step B: process buy recommendations
        slots_needed = max(0, target_size - len(hold_set))
        candidates = []
        for idx, row in df_reco.iterrows():
            sym = row[reco_sym_col]
            passed = row.get(passed_col, True) if passed_col else True
            if passed and sym not in hold_set:
                candidates.append((sym, row, idx + 1))

        buy_candidates = candidates[:slots_needed]
        for sym, row, rank in buy_candidates:
            actions.append({
                "Symbol": sym,
                "Action": "BUY",
                "WMS": row.get(wms_col),
                "PassedFilters": True,
                "Rank": rank
            })

        df_actions = pd.DataFrame(actions)

        # Save the output comparison Excel in Rebalance_history
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        rebalance_dir = Path(self._cfg.get("SYSTEM_CONFIG", {}).get("REBALANCE_HISTORY_DIR", "Rebalance_history"))
        if not rebalance_dir.is_absolute():
            rebalance_dir = _project_root / rebalance_dir
        rebalance_dir.mkdir(parents=True, exist_ok=True)
        out_path = rebalance_dir / f"Portfolio_Update_Compare_{ts}.xlsx"
        try:
            df_actions.to_excel(out_path, index=False)
            print(f"[REBALANCE] Action comparison saved to {out_path}")
        except Exception as e:
            print(f"[REBALANCE] Export failed: {e}")

        return df_actions

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
    # Historical Momentum Tracker
    # ─────────────────────────────────────────────────────────────────────

    def get_portfolio_momentum_history(self, days: int = 30) -> Dict[str, Any]:
        """
        Retrieve daily Weighted Momentum Score (WMS) history from the database cache.
        If scores for any required symbols/sectors are missing for dates in the range,
        computes them on the fly and saves them in the database for instant subsequent load.
        """
        print(f"\n[Portfolio] Retrieving historical momentum tracker for last {days} trading days ...")

        # 1. Get current portfolio symbols
        portfolio_symbols = self.symbols
        if not portfolio_symbols:
            print("[Portfolio] Portfolio is empty.")
            return {
                "dates": [],
                "portfolio": {},
                "sectors": {},
                "index": [],
                "sector_map": {}
            }

        # 2. Get benchmark index ticker
        benchmark_ticker = self._cfg["DATA_CONFIG"].get("INDEX_BENCHMARK", "^NSEI")

        # Ensure benchmark price data is loaded into memory (from cache/disk/yfinance)
        self._db.ensure_price(benchmark_ticker, is_benchmark=True)

        # 3. Load benchmark price series to determine trading dates
        bench_df = self._db.get_price(benchmark_ticker)
        if bench_df is None or bench_df.empty:
            print("[Portfolio] Benchmark price series missing. Cannot track history.")
            return {
                "dates": [],
                "portfolio": {},
                "sectors": {},
                "index": [],
                "sector_map": {}
            }

        # Get last N trading dates
        trading_dates = list(bench_df.index[-days:])
        date_strs = [str(d.date()) for d in trading_dates]

        # 4. Map portfolio sectors
        sectors = {}
        for ticker in portfolio_symbols:
            sectors[ticker] = self._db.get_sector(ticker) or "Other"

        portfolio_sectors = list(set(sec for sec in sectors.values() if sec not in ("Other", "Index")))

        # 5. Determine the earliest date we need to track (from purchase date)
        earliest_purchase = None
        for h in self._holdings.values():
            dt_added = h.get("date_added")
            if dt_added:
                dt_added = dt_added.split("T")[0]
                if earliest_purchase is None or dt_added < earliest_purchase:
                    earliest_purchase = dt_added

        # Set check window: starting from earliest purchase date OR start of the 30-day window
        thirty_days_ago_str = date_strs[0]
        if earliest_purchase:
            # Clean format
            earliest_purchase = earliest_purchase.split(" ")[0]
            # Restrict lookback to max 120 trading dates (approx 6 months) for safety
            all_dates_from_purchase = list(bench_df.index[bench_df.index.strftime('%Y-%m-%d') >= earliest_purchase])
            max_lookback = 120
            if len(all_dates_from_purchase) > max_lookback:
                all_dates_from_purchase = all_dates_from_purchase[-max_lookback:]
            check_dates = sorted(list(set(all_dates_from_purchase + trading_dates)))
        else:
            check_dates = trading_dates

        start_date_str = str(check_dates[0].date())
        end_date_str = str(check_dates[-1].date())

        # 6. Check database for existing scores
        check_symbols = portfolio_symbols + [benchmark_ticker] + portfolio_sectors
        print(f"[Portfolio] Querying momentum score cache for {len(check_symbols)} symbols across {len(check_dates)} dates...")
        existing_rows = get_db().get_momentum_scores(check_symbols, start_date_str, end_date_str)

        existing_lookup = {}
        for row in existing_rows:
            d_str = row['date']
            sym = row['symbol']
            wms = row['wms']
            if d_str not in existing_lookup:
                existing_lookup[d_str] = {}
            existing_lookup[d_str][sym] = wms

        # 7. Identify missing dates
        missing_dates = []
        for dt in check_dates:
            d_str = str(dt.date())
            if d_str not in existing_lookup:
                missing_dates.append(dt)
                continue

            day_scores = existing_lookup[d_str]
            is_complete = True
            for sym in portfolio_symbols:
                h = self._holdings.get(sym, {})
                dt_added = h.get("date_added")
                if dt_added:
                    dt_added_str = dt_added.split("T")[0].split(" ")[0]
                    if d_str < dt_added_str:
                        continue
                if sym not in day_scores:
                    is_complete = False
                    break
            if benchmark_ticker not in day_scores:
                is_complete = False
            for sec in portfolio_sectors:
                # Check if this sector has at least one active stock on this date
                sec_has_active_stock = False
                for sym in portfolio_symbols:
                    if sectors.get(sym) == sec:
                        h = self._holdings.get(sym, {})
                        dt_added = h.get("date_added")
                        if dt_added:
                            dt_added_str = dt_added.split("T")[0].split(" ")[0]
                            if d_str >= dt_added_str:
                                sec_has_active_stock = True
                                break
                        else:
                            sec_has_active_stock = True
                            break
                if sec_has_active_stock and sec not in day_scores:
                    is_complete = False
                    break

            if not is_complete:
                missing_dates.append(dt)

        # 8. Compute scores for missing dates
        if missing_dates:
            print(f"[Portfolio] Caching required: calculating WMS scores for {len(missing_dates)} missing dates...")

            # Load active universe for relative ranking reference
            from data.symbol_loader import SymbolLoader
            loader = SymbolLoader(self._cfg)
            category = self._cfg["DATA_CONFIG"].get("DEFAULT_CATEGORY", "Nifty500")
            universe_symbols = loader.load(category)
            if not universe_symbols:
                universe_symbols = loader.all_symbols()

            # Combine all to form scoring universe
            score_symbols = list(set(universe_symbols + portfolio_symbols + [benchmark_ticker]))

            # Ensure price cache is warm
            print(f"[Portfolio] Loading price cache for {len(score_symbols)} tickers...")
            self._db.ensure_prices(score_symbols, benchmark_ticker)

            all_sectors = {}
            for ticker in score_symbols:
                if ticker == benchmark_ticker:
                    all_sectors[ticker] = "Index"
                else:
                    all_sectors[ticker] = self._db.get_sector(ticker) or "Other"

            # Compute indicators series by date
            rsi_by_date = {dt: {} for dt in missing_dates}
            mfi_by_date = {dt: {} for dt in missing_dates}
            cci_by_date = {dt: {} for dt in missing_dates}
            roc_by_date = {dt: {} for dt in missing_dates}
            rs_by_date = {dt: {} for dt in missing_dates}
            pmom_by_date = {dt: {} for dt in missing_dates}
            value_by_date = {dt: {} for dt in missing_dates}

            from strategy.technical_indicators import TechnicalIndicators as TI
            import numpy as np

            total_tickers = len(score_symbols)
            for idx, ticker in enumerate(score_symbols, 1):
                sys.stdout.write(f"  Calculating series [{idx}/{total_tickers}] {ticker} …         \r")
                sys.stdout.flush()

                df = self._db.get_price(ticker)
                if df is None or df.empty:
                    continue

                rsi_s = TI.rsi_series(df)
                mfi_s = TI.mfi_series(df)
                cci_s = TI.cci_series(df)
                roc_s = TI.weighted_roc_composite_series(df, self._cfg["MOMENTUM_CONFIG"]["WMS_ROC_PERIODS"], self._cfg["MOMENTUM_CONFIG"]["WMS_ROC_WEIGHTS"])
                rs_s = TI.rs_ratio_series(df, bench_df, self._cfg["MOMENTUM_CONFIG"]["RS_LOOKBACK_DAYS"])
                pmom_s = TI.price_momentum_composite_series(df)

                fundamentals = self._db.get_fundamental(ticker)
                val_raw = self._strategy._composite_value_score(fundamentals)

                for dt in missing_dates:
                    if dt in rsi_s.index:
                        rsi_by_date[dt][ticker] = float(rsi_s.loc[dt])
                    if dt in mfi_s.index:
                        mfi_by_date[dt][ticker] = float(mfi_s.loc[dt])
                    if dt in cci_s.index:
                        cci_by_date[dt][ticker] = float(cci_s.loc[dt])
                    if dt in roc_s.index:
                        roc_by_date[dt][ticker] = float(roc_s.loc[dt])
                    if dt in rs_s.index:
                        rs_by_date[dt][ticker] = float(rs_s.loc[dt])
                    if dt in pmom_s.index:
                        pmom_by_date[dt][ticker] = float(pmom_s.loc[dt])
                    value_by_date[dt][ticker] = val_raw

            sys.stdout.write(" " * 80 + "\r")
            sys.stdout.flush()

            # Rank daily
            wms_by_date = {dt: {} for dt in missing_dates}
            w_cfg = self._cfg["SCORING_WEIGHTS"]
            wms_mapping = {
                "WMS_ROC_Raw_Pct": w_cfg.get("WMS_ROC_Composite", 0.60),
                "RSI_Raw_Pct":     w_cfg.get("RSI_Score",         0.05),
                "MFI_Raw_Pct":     w_cfg.get("MFI_Score",         0.20),
                "CCI_Raw_Pct":     w_cfg.get("CCI_Score",         0.15),
            }

            print("[Portfolio] Computing relative WMS rankings...")
            for dt in missing_dates:
                day_data = []
                for ticker in score_symbols:
                    day_data.append({
                        "Symbol": ticker,
                        "WMS_ROC_Raw": roc_by_date[dt].get(ticker, np.nan),
                        "RSI_Raw": rsi_by_date[dt].get(ticker, np.nan),
                        "MFI_Raw": mfi_by_date[dt].get(ticker, np.nan),
                        "CCI_Raw": cci_by_date[dt].get(ticker, np.nan),
                        "RS_Raw": rs_by_date[dt].get(ticker, np.nan),
                        "P_Mom_Raw": pmom_by_date[dt].get(ticker, np.nan),
                        "Value_Raw": value_by_date[dt].get(ticker, np.nan),
                    })

                day_df = pd.DataFrame(day_data).set_index("Symbol")

                score_cols = {
                    "WMS_ROC_Raw": "WMS_ROC_Raw_Pct",
                    "RSI_Raw":     "RSI_Raw_Pct",
                    "MFI_Raw":     "MFI_Raw_Pct",
                    "CCI_Raw":     "CCI_Raw_Pct",
                }
                for raw_col, pct_col in score_cols.items():
                    day_df[pct_col] = day_df[raw_col].rank(pct=True, na_option="keep") * 100

                if "WMS_ROC_Raw_Pct" in day_df.columns:
                    day_df["WMS_ROC_Raw_Pct"] = day_df["WMS_ROC_Raw_Pct"].fillna(day_df["WMS_ROC_Raw_Pct"].median())

                for ticker, row in day_df.iterrows():
                    weighted_sum = 0.0
                    total_weight = 0.0
                    for pct_col, w in wms_mapping.items():
                        val = row.get(pct_col)
                        if val is not None and not np.isnan(val):
                            weighted_sum += val * w
                            total_weight += w

                    if total_weight > 0:
                        wms_by_date[dt][ticker] = round(weighted_sum / total_weight, 2)
                    else:
                        wms_by_date[dt][ticker] = 0.0

            # Save scores for missing dates
            scores_to_save = []
            for dt in missing_dates:
                d_str = str(dt.date())

                # 1. Save portfolio tickers
                for sym in portfolio_symbols:
                    wms_val = wms_by_date[dt].get(sym, 0.0)
                    scores_to_save.append({'symbol': sym, 'date': d_str, 'wms': wms_val})

                # 2. Save benchmark index
                bench_wms = wms_by_date[dt].get(benchmark_ticker, 0.0)
                scores_to_save.append({'symbol': benchmark_ticker, 'date': d_str, 'wms': bench_wms})

                # 3. Compute and save sector averages
                sector_groups = {}
                for ticker, wms in wms_by_date[dt].items():
                    if ticker == benchmark_ticker:
                        continue
                    sec = all_sectors.get(ticker)
                    if sec and sec not in ("Other", "Index"):
                        if sec not in sector_groups:
                            sector_groups[sec] = []
                        sector_groups[sec].append(wms)

                for sec, scores in sector_groups.items():
                    if scores:
                        sec_avg = round(float(np.mean(scores)), 2)
                        scores_to_save.append({'symbol': sec, 'date': d_str, 'wms': sec_avg})

            print(f"[Portfolio] Saving {len(scores_to_save)} calculated scores to database cache...")
            get_db().save_momentum_scores(scores_to_save)

        # 9. Load final scores from database cache
        final_rows = get_db().get_momentum_scores(check_symbols, start_date_str, end_date_str)
        final_lookup = {}
        for row in final_rows:
            d_str = row['date']
            sym = row['symbol']
            wms = row['wms']
            if d_str not in final_lookup:
                final_lookup[d_str] = {}
            final_lookup[d_str][sym] = wms

        check_dates = check_dates[-days:]

        portfolio_out = {sym: [] for sym in portfolio_symbols}
        sector_out = {}
        index_out = []

        # Setup sector_out keys
        for sym in portfolio_symbols:
            sec = sectors.get(sym)
            if sec and sec not in ("Other", "Index"):
                if sec not in sector_out:
                    sector_out[sec] = []

        for dt in check_dates:
            d_str = str(dt.date())
            day_scores = final_lookup.get(d_str, {})

            # Benchmark Index WMS
            index_out.append(day_scores.get(benchmark_ticker, 0.0))

            # Portfolio Stocks WMS
            for sym in portfolio_symbols:
                h = self._holdings.get(sym, {})
                dt_added = h.get("date_added")
                if dt_added:
                    dt_added_str = dt_added.split("T")[0].split(" ")[0]
                    if d_str < dt_added_str:
                        portfolio_out[sym].append(None)
                        continue
                portfolio_out[sym].append(day_scores.get(sym, 0.0))

        # Fill Sector lists
        for dt in check_dates:
            d_str = str(dt.date())
            day_scores = final_lookup.get(d_str, {})
            for sec in sector_out.keys():
                # Check if sector has any active stock on this date
                sec_has_active = False
                for sym in portfolio_symbols:
                    if sectors.get(sym) == sec:
                        h = self._holdings.get(sym, {})
                        dt_added = h.get("date_added")
                        if dt_added:
                            dt_added_str = dt_added.split("T")[0].split(" ")[0]
                            if d_str >= dt_added_str:
                                sec_has_active = True
                                break
                        else:
                            sec_has_active = True
                            break
                if sec_has_active:
                    sector_out[sec].append(day_scores.get(sec, 0.0))
                else:
                    sector_out[sec].append(None)

        output_date_strs = [str(d.date()) for d in check_dates]

        return {
            "dates": output_date_strs,
            "portfolio": portfolio_out,
            "sectors": sector_out,
            "index": index_out,
            "sector_map": {sym: sectors.get(sym) for sym in portfolio_symbols}
        }


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
            print("  [5] Compare live DB portfolio with last recommendation file")
            print("  [6] Compare portfolio Excel file with last recommendation file (Option 12)")
            print("  [7] Historical Momentum Score Tracker (portfolio vs index vs sector)")
            print("  [8] Save portfolio to disk")
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
                from data.symbol_loader import SymbolLoader
                cat = SymbolLoader(self._cfg).select_interactively()
                if not cat:
                    continue
                universe = SymbolLoader(self._cfg).load(cat)
                top_n    = self._cfg["BACKTEST_CONFIG"].get("TOP_N", 20)
                self.generate_rebalance_report(universe, target_size=top_n)

            elif choice == "5":
                from data.symbol_loader import SymbolLoader
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
                port = input("  Path to current portfolio Excel file: ").strip()
                if not port:
                    print("  Cancelled.")
                    continue
                prev = input("  Path to LAST_Recommendation (Excel/CSV): ").strip()
                if not prev:
                    print("  Cancelled.")
                    continue
                self.compare_and_rebalance(port, prev)

            elif choice == "7":
                days_input = input("  Enter number of days to track (default: 30): ").strip()
                days = int(days_input) if days_input.isdigit() else 30
                history = self.get_portfolio_momentum_history(days=days)
                if history and history.get("dates"):
                    dates = history["dates"]
                    portfolio = history["portfolio"]
                    index = history["index"]
                    sectors = history["sectors"]
                    sector_map = history["sector_map"]
                    
                    print("\n" + "=" * 110)
                    print("  PORTFOLIO HISTORICAL MOMENTUM SCORES")
                    print("=" * 110)
                    for sym, scores in portfolio.items():
                        if scores:
                            latest = scores[-1]
                            change_7d = round(latest - (scores[-6] if len(scores) >= 6 else scores[0]), 2)
                            change_30d = round(latest - scores[0], 2)
                            sec = sector_map.get(sym, "N/A")
                            sec_latest = sectors.get(sec, [])[-1] if sectors.get(sec) else 0.0
                            print(f"  {sym:<12} | Sector: {sec:<20} | WMS: {latest:>6.2f} | 7d change: {change_7d:>+6.2f} | 30d change: {change_30d:>+6.2f} | Sector WMS: {sec_latest:>6.2f}")
                    print("-" * 110)
                    print(f"  Index (^NSEI) Latest WMS: {index[-1]:.2f}")
                    print("=" * 110)

            elif choice == "8":
                self.save()

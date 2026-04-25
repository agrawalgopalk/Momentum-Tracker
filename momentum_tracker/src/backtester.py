"""
backtester.py – Single-run backtest simulation engine.

The Backtester class simulates a momentum portfolio over a historical
period using the smart rebalancing logic from the original script:

  * Periodic rebalance (W / M / Q / A).
  * Sell pool = TOP_N × STOCK_SCALING_FACTOR (hold if still in pool).
  * Forced sell if WMS drops by ≥ MOMENTUM_DROP_THRESHOLD_PCT.
  * Buy candidates restricted to NEW_STOCK_ADDITION_LIMIT rank.
  * Non-fractional share purchases (floor).
  * Transaction costs on both sides.
  * Idle-cash interest at ANNUAL_CASH_RETURN_RATE.
  * Daily equity tracking between rebalances.
  * Benchmark return calculation per period.

Returns four DataFrames:
  df_rebalance    – one row per rebalance period (start, end, return, …)
  df_equity       – daily equity curve
  df_transactions – every BUY / SELL event
  df_benchmarks   – benchmark close prices for the test window
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from config import Config
from database_manager import DatabaseManager
from momentum_strategy import MomentumStrategy
from technical_indicators import TechnicalIndicators as TI


class Backtester:
    """
    Full historical simulation of the momentum strategy.

    Parameters
    ----------
    config   : Config instance
    db       : DatabaseManager instance (provides price data)
    strategy : MomentumStrategy instance (provides scores)
    """

    def __init__(
        self,
        config: Config,
        db: DatabaseManager,
        strategy: MomentumStrategy,
    ) -> None:
        self._cfg      = config
        self._db       = db
        self._strategy = strategy

    # ─────────────────────────────────────────────────────────────────────
    # Public: run
    # ─────────────────────────────────────────────────────────────────────

    def run(
        self,
        category: str,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime,
        top_n: int,
        rebalance_freq: str = "M",
        transaction_cost: float = 0.001,
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Execute one complete backtest.

        Returns
        -------
        (df_rebalance, df_equity, df_transactions, df_benchmarks)
        """
        b_cfg = self._cfg["BACKTEST_CONFIG"]
        initial_capital       = b_cfg.get("INITIAL_CAPITAL",             1_000_000.0)
        scaling_factor        = b_cfg.get("STOCK_SCALING_FACTOR",        2)
        drop_threshold        = b_cfg.get("MOMENTUM_DROP_THRESHOLD_PCT", 50.0)
        new_addition_limit    = b_cfg.get("NEW_STOCK_ADDITION_LIMIT",    20)
        annual_cash_rate      = b_cfg.get("ANNUAL_CASH_RETURN_RATE",     0.04)

        benchmark_ticker = self._cfg["DATA_CONFIG"]["INDEX_BENCHMARK"]
        bench_df = self._db.get_price(benchmark_ticker)
        category_bench_ticker = self._cfg["DATA_CONFIG"]["INDICES"].get(category, benchmark_ticker)
        # cat_bench_df = self._db.get_price(category_bench_ticker) or bench_df
        cat_bench_df = self._db.get_price(category_bench_ticker)

        # If the returned DF is None or completely empty, use the fallback bench_df
        if cat_bench_df is None or cat_bench_df.empty:
            cat_bench_df = bench_df        

        # Generate calendar rebalance dates
        rebalance_dates = _calendar_dates(start_date, end_date, rebalance_freq)
        if len(rebalance_dates) < 2:
            print("[Backtest] Not enough rebalance dates – aborting.")
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

        # Ensure price data for all symbols
        self._db.ensure_prices(symbols, benchmark_ticker)

        # State
        total_capital   = initial_capital
        current_holdings: Dict[str, Dict[str, Union[int, float]]] = {}
        equity_curve_data  : List[Dict] = []
        transaction_log    : List[Dict] = []
        rebalance_results  : List[Dict] = []
        total_fees = total_trades = total_buys = 0.0

        # ── Main rebalance loop ────────────────────────────────────────
        for i in range(len(rebalance_dates) - 1):
            current_date = rebalance_dates[i]
            next_date    = rebalance_dates[i + 1]
            period_days  = (next_date - current_date).days

            print(f"\n{'─'*65}")
            print(f"Period {i+1}: {current_date.date()} → {next_date.date()}")
            print("─" * 65)

            # ── Apply interest to carry-over cash ──────────────────────
            if i > 0:
                interest_days = (current_date - rebalance_dates[i - 1]).days
                total_capital = TI.apply_cash_interest(
                    total_capital, interest_days, annual_cash_rate
                )

            # ── A. Opening portfolio value ─────────────────────────────
            trade_day_data = _prices_on_date(self._db, symbols, current_date)
            start_value = total_capital
            for ticker, h in current_holdings.items():
                try:
                    start_value += h["shares"] * float(trade_day_data.loc[ticker, "open"])
                except KeyError:
                    pass

            print(f"Start value: ₹{start_value:,.0f}  Cash: ₹{total_capital:,.0f}  Holdings: {len(current_holdings)}")

            if trade_day_data.empty:
                print("[WARNING] No opening prices for rebalance day – skipping.")
                rebalance_results.append(
                    _zero_period_row(current_date, next_date, start_value, current_holdings)
                )
                continue

            # ── B. Score all candidates ────────────────────────────────
            print("  1. Scoring candidates …")
            scored_list = self._strategy.score_universe(symbols, target_date=current_date)
            
            scored_df   = pd.DataFrame(scored_list)
            scored_df   = (
                scored_df[
                    (scored_df["PassedFilters"] == True) &
                    (scored_df["FinalWeightedScore"] > 0)
                ]
                .sort_values("FinalWeightedScore", ascending=False)
                .reset_index(drop=True)
            )

            if scored_df.empty:
                print("  [WARNING] No qualifying stocks – maintaining holdings.")
                continue

            print(f"  2. {len(scored_df)} fully-qualified candidates found.")

            # ── C. SELL / HOLD decision ────────────────────────────────
            pool_size            = top_n * scaling_factor
            top_pool             = set(scored_df["Symbol"].head(pool_size))
            symbols_to_sell      : set = set()
            symbols_to_hold      : set = set()
            holdings_to_remove   : set = set()

            for ticker, h in current_holdings.items():
                score_row = scored_df[scored_df["Symbol"] == ticker]

                if score_row.empty:
                    symbols_to_sell.add(ticker)
                    continue

                latest_wms = float(score_row["FinalWeightedScore"].iloc[0])
                prev_wms   = float(h.get("wms", 0.0))

                # Forced sell on momentum drop
                if prev_wms > 0 and latest_wms < prev_wms:
                    drop_pct = (prev_wms - latest_wms) / prev_wms * 100
                    if drop_pct >= drop_threshold:
                        symbols_to_sell.add(ticker)
                        self._cfg.debug_print(
                            f"   {ticker} FORCED SELL (WMS {prev_wms:.2f}→{latest_wms:.2f}, drop {drop_pct:.1f}%)"
                        )
                        continue

                if ticker in top_pool:
                    symbols_to_hold.add(ticker)
                    current_holdings[ticker]["wms"] = latest_wms
                else:
                    symbols_to_sell.add(ticker)

            # Execute sells
            total_sale_value = 0.0
            for ticker in symbols_to_sell:
                shares = current_holdings[ticker]["shares"]
                try:
                    sell_price = float(trade_day_data.loc[ticker, "open"])
                    value      = shares * sell_price
                    fee        = value * transaction_cost
                    total_capital    += value - fee
                    total_fees       += fee
                    total_sale_value += value
                    total_trades     += 1
                    transaction_log.append({
                        "Date": current_date.date(), "Type": "SELL",
                        "Symbol": ticker, "Shares": shares,
                        "Price": sell_price, "Value": round(value, 2),
                        "Fee": round(fee, 2), "Net_Capital": round(total_capital, 2),
                    })
                    holdings_to_remove.add(ticker)
                except KeyError:
                    holdings_to_remove.add(ticker)

            for ticker in holdings_to_remove:
                current_holdings.pop(ticker, None)

            print(
                f"   Sold: {len(symbols_to_sell)}  Held: {len(symbols_to_hold)}  "
                f"Sale proceeds: ₹{total_sale_value:,.0f}  Cash: ₹{total_capital:,.0f}"
            )

            # ── D. BUY new additions ───────────────────────────────────
            slots_free = top_n - len(symbols_to_hold)
            if slots_free <= 0:
                print("   Portfolio full – no new purchases.")
                continue

            new_candidates: List[Dict] = []
            for _, row in scored_df.head(new_addition_limit).iterrows():
                sym = row["Symbol"]
                if sym not in symbols_to_hold and sym not in current_holdings:
                    if sym in trade_day_data.index:
                        new_candidates.append(row.to_dict())

            buys = new_candidates[:slots_free]
            if not buys:
                print(f"   No eligible buy candidates. Cash: ₹{total_capital:,.0f}")
                continue

            cash_per = (total_capital * 0.99) / len(buys)
            total_spent = 0.0

            for candidate in buys:
                ticker     = candidate["Symbol"]
                wms_at_buy = candidate["FinalWeightedScore"]
                try:
                    buy_price  = float(trade_day_data.loc[ticker, "open"])
                    shares     = int(np.floor(cash_per / buy_price))
                    if shares <= 0:
                        continue
                    cost = shares * buy_price
                    fee  = cost * transaction_cost
                    if total_capital >= cost + fee:
                        total_capital  -= cost + fee
                        total_fees     += fee
                        total_spent    += cost
                        total_trades   += 1
                        total_buys     += 1
                        current_holdings[ticker] = {"shares": shares, "wms": wms_at_buy}
                        transaction_log.append({
                            "Date": current_date.date(), "Type": "BUY",
                            "Symbol": ticker, "Shares": shares,
                            "Price": buy_price, "Value": round(cost, 2),
                            "Fee": round(fee, 2), "Net_Capital": round(total_capital, 2),
                        })
                except KeyError:
                    pass

            print(
                f"   Purchased: {len(current_holdings) - len(symbols_to_hold)}  "
                f"Spent: ₹{total_spent:,.0f}  Remaining cash: ₹{total_capital:,.0f}"
            )

            # ── E. Daily equity tracking ───────────────────────────────
            self._db.ensure_prices(list(current_holdings.keys()))
            tracked = list(current_holdings.keys())

            if bench_df is not None:
                period_trading_days = bench_df.loc[current_date:next_date].index.tolist()
            else:
                period_trading_days = []

            for day in period_trading_days:
                day_data = _prices_on_date(self._db, tracked, day)
                equity = total_capital
                for ticker, h in current_holdings.items():
                    try:
                        equity += h["shares"] * float(day_data.loc[ticker, "close"])
                    except KeyError:
                        pass
                equity_curve_data.append({"Date": day.date(), "Equity": round(equity, 2)})

            # ── F. Period performance summary ──────────────────────────
            end_data   = _prices_on_date(self._db, list(current_holdings.keys()), next_date)
            end_value  = total_capital
            for ticker, h in current_holdings.items():
                try:
                    end_value += h["shares"] * float(end_data.loc[ticker, "close"])
                except KeyError:
                    pass

            period_return = (end_value / start_value - 1.0) if start_value > 0 else np.nan

            # Benchmark return for the period
            bench_return = _benchmark_period_return(cat_bench_df, current_date, next_date)

            rebalance_results.append({
                "Start_Date":      current_date.date(),
                "End_Date":        next_date.date(),
                "Start_Value":     round(start_value, 2),
                "End_Value":       round(end_value, 2),
                "Return_%":        round(period_return * 100, 2),
                "Benchmark_Return_%": round(bench_return * 100, 2) if not np.isnan(bench_return) else np.nan,
                "Holdings_Count":  len(current_holdings),
                "Total_Fees":      round(total_fees, 2),
                "Trades":          total_trades,
            })
            print(
                f"   Period return: {period_return*100:.2f}%  "
                f"Benchmark: {bench_return*100:.2f}%  "
                f"End value: ₹{end_value:,.0f}"
            )

        # ── Final reports ──────────────────────────────────────────────
        df_rebalance    = pd.DataFrame(rebalance_results)
        df_equity       = pd.DataFrame(equity_curve_data)
        df_transactions = pd.DataFrame(transaction_log)

        # Benchmark price series for the full window
        bench_series = _benchmark_series(cat_bench_df, start_date, end_date)
        df_benchmarks = bench_series.reset_index().rename(columns={"index": "date"})

        self._print_summary(df_equity, initial_capital, total_fees, int(total_trades))
        return df_rebalance, df_equity, df_transactions, df_benchmarks

    # ─────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────

    def _print_summary(
        self, df_equity: pd.DataFrame, initial: float, fees: float, trades: int
    ) -> None:
        if df_equity.empty:
            print("[Backtest] No equity data.")
            return
        final = float(df_equity["Equity"].iloc[-1])
        total_ret = (final / initial - 1.0) * 100
        years = max(1, len(df_equity) / 252)
        cagr  = ((final / initial) ** (1 / years) - 1) * 100
        print(f"\n{'═'*65}")
        print(f"  BACKTEST SUMMARY")
        print(f"{'═'*65}")
        print(f"  Initial capital : ₹{initial:>15,.0f}")
        print(f"  Final equity    : ₹{final:>15,.0f}")
        print(f"  Total return    : {total_ret:>10.2f} %")
        print(f"  CAGR            : {cagr:>10.2f} %")
        print(f"  Total trades    : {trades}")
        print(f"  Total fees      : ₹{fees:>15,.0f}")
        print(f"{'═'*65}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Module-level helpers
# ─────────────────────────────────────────────────────────────────────────────

def _calendar_dates(
    start: datetime, end: datetime, freq: str
) -> List[datetime]:
    """Generate rebalance dates from *start* to *end* at *freq* frequency."""
    freq_map = {"W": "W", "M": "MS", "Q": "QS", "A": "AS"}
    pd_freq  = freq_map.get(freq.upper(), "MS")

    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    end   = end.replace(  hour=0, minute=0, second=0, microsecond=0)

    dates = pd.date_range(start=start, end=end, freq=pd_freq).tolist()
    if start.date() not in [d.date() for d in dates]:
        dates.insert(0, start)

    dates = [d for d in dates if start.date() <= d.date() <= end.date()]
    return sorted(set(dates))


def _prices_on_date(
    db: DatabaseManager, tickers: List[str], target: datetime
) -> pd.DataFrame:
    """Retrieve open + close for *tickers* on or before *target* (no lookahead)."""
    rows = []
    for ticker in tickers:
        df = db.get_price(ticker)
        if df is None or df.empty:
            continue
        try:
            row = df.loc[:target].iloc[-1]
            rows.append({
                "Ticker": ticker,
                "open":   row.get("open",   np.nan),
                "close":  row.get("close",  np.nan),
                "volume": row.get("volume", np.nan),
            })
        except IndexError:
            pass
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index("Ticker")


def _benchmark_period_return(
    bench_df: Optional[pd.DataFrame],
    start: datetime,
    end: datetime,
) -> float:
    if bench_df is None or bench_df.empty:
        return np.nan
    try:
        s = bench_df.loc[:start]["close"].iloc[-1]
        e = bench_df.loc[:end]["close"].iloc[-1]
        return float(e / s) - 1.0
    except (IndexError, KeyError):
        return np.nan


def _benchmark_series(
    bench_df: Optional[pd.DataFrame],
    start: datetime,
    end: datetime,
) -> pd.Series:
    if bench_df is None or bench_df.empty:
        return pd.Series(dtype=float)
    ser = bench_df.loc[start:end, "close"]
    return ser.to_frame(name="close").reset_index().rename(columns={"Date": "date"}).set_index("date")["close"]


def _zero_period_row(
    start: datetime,
    end: datetime,
    value: float,
    holdings: dict,
) -> Dict[str, Any]:
    return {
        "Start_Date": start.date(), "End_Date": end.date(),
        "Start_Value": round(value, 2), "End_Value": round(value, 2),
        "Return_%": 0.0, "Benchmark_Return_%": np.nan,
        "Holdings_Count": len(holdings), "Total_Fees": 0.0, "Trades": 0,
    }

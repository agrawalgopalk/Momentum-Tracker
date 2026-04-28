"""
db_interface.py  –  Abstract base class for all database backends.

Every method here is the single source of truth for what the DB layer
must provide.  Both SQLite (persistence.py) and PostgreSQL
(persistence_postgresql.py) implement this interface.

Callers (dashboard.py, scheduler.py, cleanup.py) depend ONLY on this
contract — they never import a concrete implementation directly.

Usage
─────
  # You never instantiate this directly.
  # Use db_config.py to get the right concrete instance:
  from db_config import get_db
  DB = get_db()
  DB.save_scan(...)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class DatabaseInterface(ABC):
    """
    Contract that every database backend must satisfy.

    All methods mirror the existing SQLite persistence.py API exactly
    so switching backends requires zero changes in callers.
    """

    # ── Schema management ─────────────────────────────────────────────────────

    @abstractmethod
    def init(self) -> None:
        """
        Create all tables and indexes if they do not exist.
        Apply any pending schema migrations.
        Safe to call on every startup — fully idempotent.
        """

    # ── Write helpers ─────────────────────────────────────────────────────────

    @abstractmethod
    def save_scan(
        self,
        category: str,
        results: list[dict],
        top_n: int = 20,
    ) -> int:
        """
        Persist a full momentum scan run.

        Parameters
        ----------
        category : str   e.g. "Nifty100"
        results  : list of dicts — keys: Symbol, WMS, RS_Raw, RSI_Raw, MFI_Raw, CCI_Raw
        top_n    : int   how many candidates were requested

        Returns
        -------
        run_id : int  — use this to link save_picks() and save_scan_report()
        """

    @abstractmethod
    def save_picks(self, run_id: int, picks: list[dict]) -> None:
        """
        Persist analyst BUY/HOLD/AVOID classifications for a scan run.

        Each dict in picks must have:
          symbol, classification, confidence, momentum_quality,
          sector_backdrop, fundamental, news_catalysts, risk_flags, rationale
        """

    @abstractmethod
    def save_alerts(self, alerts: list[dict]) -> None:
        """
        Persist portfolio monitor alerts.

        Each dict must have: symbol, alert_level (RED|YELLOW|GREEN).
        Optional: confidence, trigger, action, risk_flags, raw_news.
        """

    @abstractmethod
    def add_position(self, symbol: str, buy_price: float, qty: int) -> None:
        """Add or upsert a position in the portfolio table."""

    @abstractmethod
    def close_position(
        self,
        symbol: str,
        sell_price: float,
        exit_reason: str = "MANUAL",
    ) -> None:
        """
        Mark a position as closed, compute P&L, and write to performance table.
        Raises ValueError if no open position exists for the symbol.
        """

    @abstractmethod
    def save_scan_report(
        self,
        run_id: int,
        category: str,
        scout_raw: str,
        analyst_raw: str,
        report_type: str = "SCOUT",
    ) -> int:
        """
        Save the full raw text of both crew task outputs.

        Returns
        -------
        report_id : int
        """

    # ── Read helpers ──────────────────────────────────────────────────────────

    @abstractmethod
    def held_positions(self) -> list[dict]:
        """Return all currently open positions."""

    @abstractmethod
    def recent_picks(self, symbol: str, n: int = 10) -> list[dict]:
        """Return the last N analyst picks for a given ticker."""

    @abstractmethod
    def latest_scan(self, category: str = "Nifty100") -> list[dict]:
        """Return ranked stocks from the most recent scan of a category."""

    @abstractmethod
    def alert_history(
        self,
        symbol: str | None = None,
        level: str | None = None,
        n: int = 50,
    ) -> list[dict]:
        """Return recent alerts, optionally filtered by symbol and/or level."""

    @abstractmethod
    def performance_summary(self) -> dict:
        """
        Return aggregate P&L stats across all closed trades.

        Keys: total_trades, winning_trades, win_rate_pct, total_pnl,
              avg_pnl_pct, best_trade, worst_trade, avg_hold_days,
              by_classification (dict keyed by BUY/HOLD/AVOID/UNKNOWN).
        """

    @abstractmethod
    def export_picks_csv(self, path: str = "picks_export.csv") -> str:
        """Export all picks to CSV. Returns the file path written."""

    @abstractmethod
    def get_scan_reports(self, category: str = "Nifty100", n: int = 10) -> list[dict]:
        """Return last N scan report summaries for a category."""

    @abstractmethod
    def get_scan_report_detail(self, report_id: int) -> dict | None:
        """Return full text of a specific scan report."""

    @abstractmethod
    def delete_scan_report(self, report_id: int) -> None:
        """Delete a specific scan report."""

    @abstractmethod
    def get_stock_analyst_report(
        self,
        symbol: str,
        category: str = "Nifty100",
    ) -> str | None:
        """
        Extract the analyst block for a specific stock from the latest
        scan report for the given category.
        """

    @abstractmethod
    def get_stock_monitor_report(self, symbol: str) -> str | None:
        """
        Extract the monitor alert block for a specific stock from the
        latest Monitor report.
        """

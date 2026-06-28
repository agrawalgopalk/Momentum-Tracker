"""
db_interface.py  –  Abstract base class for all database backends.

Every method here is the single source of truth for what the DB layer
must provide.  Both SQLite (persistence.py) and PostgreSQL
(persistence_postgresql.py) implement this interface.

Callers (dashboard.py, scheduler.py, cleanup.py) depend ONLY on this
contract — they never import a concrete implementation directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class DatabaseInterface(ABC):
    """
    Contract that every database backend must satisfy.
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
        """

    @abstractmethod
    def save_picks(self, run_id: int, picks: list[dict]) -> None:
        """
        Persist analyst BUY/HOLD/AVOID classifications for a scan run.
        """

    @abstractmethod
    def save_alerts(self, alerts: list[dict], user_id: int | None = None) -> None:
        """
        Persist portfolio monitor alerts.
        """

    @abstractmethod
    def add_position(
        self,
        symbol: str,
        buy_price: float,
        qty: int,
        user_id: int | None = None,
        added_at: str | None = None,
    ) -> None:
        """Add or upsert a position in the portfolio table."""

    @abstractmethod
    def close_position(
        self,
        symbol: str,
        sell_price: float,
        exit_reason: str = "MANUAL",
        user_id: int | None = None,
    ) -> None:
        """
        Mark a position as closed, compute P&L, and write to performance table.
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
        """

    # ── Read helpers ──────────────────────────────────────────────────────────

    @abstractmethod
    def held_positions(self, user_id: int | None = None) -> list[dict]:
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
        user_id: int | None = None,
    ) -> list[dict]:
        """Return recent alerts, optionally filtered by symbol and/or level."""

    @abstractmethod
    def performance_summary(self, user_id: int | None = None) -> dict:
        """
        Return aggregate P&L stats across all closed trades.
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
    def get_picks_by_run(self, run_id: int) -> list[dict]:
        """Return all analyst picks for a given scan run ID."""

    @abstractmethod
    def get_category_stock_progressions(self, category: str, limit: int = 30) -> list[dict]:
        """Return stock momentum score progressions over past N scan runs for a category."""

    @abstractmethod
    def get_portfolio_positions_with_reports(self, user_id: int | None = None) -> list[dict]:
        """Return all open portfolio positions joined with their latest picks report."""

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
    def closed_positions(self, user_id: int | None = None) -> list[dict]:
        """Return all closed trades from performance table, newest first."""

    @abstractmethod
    def table_row_counts(self) -> dict[str, int]:
        """Return {table_name: row_count} for all system tables."""

    @abstractmethod
    def clear_alerts(self, user_id: int | None = None) -> None:
        """Delete all rows from the alerts table."""

    @abstractmethod
    def clear_reports(self) -> None:
        """Delete all rows from the scan_reports table."""

    @abstractmethod
    def clear_runs_before(self, date_str: str) -> None:
        """Delete all scan runs and related data older than date_str (YYYY-MM-DD)."""

    @abstractmethod
    def clear_all(self) -> None:
        """Delete all scan/alert/performance data. Portfolio positions preserved."""
        
    @abstractmethod
    def clear_stock_performance_history(self, user_id: int | None = None) -> None:
        """Delete all rows from the performance table."""

    @abstractmethod
    def save_rebalance_run(self, user_id: int, report_data: list[dict]) -> int:
        """Save a rebalance report run to database. Returns the run id."""

    @abstractmethod
    def get_rebalance_runs(self, user_id: int, n: int = 10) -> list[dict]:
        """Return the last N rebalance runs for a user, newest first."""

    @abstractmethod
    def get_rebalance_run_detail(self, run_id: int) -> dict | None:
        """Return detail of a specific rebalance run."""

    @abstractmethod
    def add_closed_performance_record(
        self,
        symbol: str,
        buy_price: float,
        sell_price: float,
        qty: int,
        opened_at: str,
        user_id: int | None = None,
    ) -> None:
        """Add a closed trade performance record to the performance table."""

    @abstractmethod
    def save_momentum_scores(self, scores: list[dict]) -> None:
        """
        Save calculated daily momentum scores.
        """

    @abstractmethod
    def get_momentum_scores(self, symbols: list[str], start_date: str, end_date: str) -> list[dict]:
        """
        Retrieve daily momentum scores for symbols in date range.
        """

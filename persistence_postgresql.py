"""
persistence_postgresql.py  –  PostgreSQL backend for the Momentum Portfolio System.

Implements the same DatabaseInterface as SQLite (persistence.py) so all
callers work unchanged.  Switch providers by setting DB_TYPE=postgresql
in your .env — no other code changes required.

Setup
─────
  pip install psycopg2-binary   # or psycopg2 for production

  # Render / Railway / Heroku — automatic:
  DATABASE_URL is set for you when you attach a Postgres addon.

  # Local Docker:
  docker run -d -e POSTGRES_PASSWORD=secret -p 5432:5432 postgres:16
  PG_HOST=localhost PG_DATABASE=momentum PG_USER=postgres PG_PASSWORD=secret

Key differences from SQLite
────────────────────────────
  • Placeholder:  ? → %s
  • Last insert:  cursor.lastrowid → cursor.fetchone()["id"]  (RETURNING id)
  • Upsert:       ON CONFLICT syntax is identical — PostgreSQL supports it natively
  • executemany:  execute_batch() from psycopg2.extras (same semantics, faster)
  • executescript: not available — each CREATE TABLE is a separate execute()
  • Row factory:  sqlite3.Row → psycopg2.extras.RealDictCursor
  • Migration:    catch PostgreSQL error code 42701 (duplicate_column)
  • No PRAGMA:    WAL / foreign_keys not needed — PG handles this natively
"""

from __future__ import annotations

import csv
import json
import re
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from db_interface import DatabaseInterface
from logger import get_logger

log = get_logger(__name__)


class PostgreSQLDatabase(DatabaseInterface):
    """PostgreSQL implementation of the Momentum Portfolio System database layer."""

    def __init__(self, config) -> None:
        """
        Parameters
        ----------
        config : DBConfig
            Imported from db_config.py.  Provides pg_connect_kwargs().
        """
        self._config = config

    # ── Connection context manager ────────────────────────────────────────────

    @contextmanager
    def _conn(self):
        """
        Yield a psycopg2 connection with RealDictCursor as the default cursor.

        • Commits on clean exit, rolls back on exception.
        • RealDictCursor makes every row behave like a dict — same API as
          sqlite3.Row in the SQLite backend.
        """
        import psycopg2
        import psycopg2.extras

        con = psycopg2.connect(
            **self._config.pg_connect_kwargs(),
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    # ── Schema ────────────────────────────────────────────────────────────────

    _TABLES = [
        # 1. scan_runs
        """
        CREATE TABLE IF NOT EXISTS scan_runs (
            id            SERIAL PRIMARY KEY,
            run_at        TEXT    NOT NULL,
            category      TEXT    NOT NULL,
            total_scored  INTEGER,
            top_n         INTEGER
        )
        """,
        # 2. scans
        """
        CREATE TABLE IF NOT EXISTS scans (
            id      SERIAL PRIMARY KEY,
            run_id  INTEGER NOT NULL REFERENCES scan_runs(id),
            symbol  TEXT    NOT NULL,
            rank    INTEGER,
            wms     REAL,
            rs      REAL,
            rsi     REAL,
            mfi     REAL,
            cci     REAL
        )
        """,
        # 3. picks
        """
        CREATE TABLE IF NOT EXISTS picks (
            id                SERIAL PRIMARY KEY,
            run_id            INTEGER NOT NULL REFERENCES scan_runs(id),
            symbol            TEXT    NOT NULL,
            classification    TEXT    NOT NULL,
            confidence        INTEGER,
            momentum_quality  TEXT,
            sector_backdrop   TEXT,
            fundamental       TEXT,
            news_catalysts    TEXT,
            risk_flags        TEXT,
            rationale         TEXT,
            picked_at         TEXT    NOT NULL
        )
        """,
        # 4. alerts
        """
        CREATE TABLE IF NOT EXISTS alerts (
            id          SERIAL PRIMARY KEY,
            symbol      TEXT    NOT NULL,
            alert_level TEXT    NOT NULL,
            confidence  TEXT,
            trigger     TEXT,
            action      TEXT,
            risk_flags  TEXT,
            raw_news    TEXT,
            alerted_at  TEXT    NOT NULL
        )
        """,
        # 5. portfolio
        """
        CREATE TABLE IF NOT EXISTS portfolio (
            id          SERIAL PRIMARY KEY,
            symbol      TEXT    NOT NULL UNIQUE,
            buy_price   REAL    NOT NULL,
            qty         INTEGER NOT NULL,
            added_at    TEXT    NOT NULL,
            status      TEXT    NOT NULL DEFAULT 'OPEN'
        )
        """,
        # 6. performance
        """
        CREATE TABLE IF NOT EXISTS performance (
            id                   SERIAL PRIMARY KEY,
            symbol               TEXT    NOT NULL,
            buy_price            REAL    NOT NULL,
            sell_price           REAL    NOT NULL,
            qty                  INTEGER NOT NULL,
            pnl                  REAL    NOT NULL,
            pnl_pct              REAL    NOT NULL,
            hold_days            INTEGER,
            opened_at            TEXT,
            closed_at            TEXT    NOT NULL,
            pick_classification  TEXT,
            exit_reason          TEXT
        )
        """,
        # 7. scan_reports
        """
        CREATE TABLE IF NOT EXISTS scan_reports (
            id           SERIAL PRIMARY KEY,
            run_id       INTEGER REFERENCES scan_runs(id),
            category     TEXT    NOT NULL,
            scout_raw    TEXT,
            analyst_raw  TEXT,
            report_type  TEXT    DEFAULT 'SCOUT',
            created_at   TEXT    NOT NULL
        )
        """,
    ]

    _INDEXES = [
        "CREATE INDEX IF NOT EXISTS idx_scans_symbol  ON scans(symbol)",
        "CREATE INDEX IF NOT EXISTS idx_picks_symbol  ON picks(symbol)",
        "CREATE INDEX IF NOT EXISTS idx_alerts_symbol ON alerts(symbol)",
        "CREATE INDEX IF NOT EXISTS idx_alerts_level  ON alerts(alert_level)",
    ]

    # Migrations: add new columns that appeared after initial schema.
    # Each tuple is (table, column, definition).
    # The migration runner catches the "column already exists" error (PG code 42701).
    _MIGRATIONS: list[tuple[str, str, str]] = [
        # Example future migration:
        # ("scan_reports", "report_type", "TEXT DEFAULT 'SCOUT'"),
    ]

    def init(self) -> None:
        """Create all tables, indexes, and apply pending migrations."""
        with self._conn() as con:
            cur = con.cursor()
            for ddl in self._TABLES:
                cur.execute(ddl)
            for idx in self._INDEXES:
                cur.execute(idx)
            self._run_migrations(cur)
        log.info("PostgreSQL schema ready.")

    def _run_migrations(self, cur) -> None:
        """
        Apply ALTER TABLE migrations idempotently.
        PostgreSQL raises error code 42701 for duplicate columns — we catch it.
        """
        import psycopg2
        for table, column, definition in self._MIGRATIONS:
            try:
                cur.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                )
                log.info("Migration applied: %s.%s", table, column)
            except psycopg2.errors.DuplicateColumn:
                pass   # already applied — safe to ignore

    # ── Write helpers ─────────────────────────────────────────────────────────

    def save_scan(
        self,
        category: str,
        results: list[dict],
        top_n: int = 20,
    ) -> int:
        """Persist a full scan run.  Returns run_id."""
        import psycopg2.extras
        now = datetime.now().isoformat(timespec="seconds")

        with self._conn() as con:
            cur = con.cursor()

            # Insert header row — RETURNING id replaces sqlite3 lastrowid
            cur.execute(
                "INSERT INTO scan_runs (run_at, category, total_scored, top_n) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (now, category, len(results), top_n),
            )
            run_id: int = cur.fetchone()["id"]

            # Bulk-insert scan rows
            rows = [
                (
                    run_id,
                    r.get("Symbol", ""),
                    idx + 1,
                    r.get("WMS"),
                    r.get("RS_Raw"),
                    r.get("RSI_Raw"),
                    r.get("MFI_Raw"),
                    r.get("CCI_Raw"),
                )
                for idx, r in enumerate(results)
            ]
            psycopg2.extras.execute_batch(
                cur,
                "INSERT INTO scans (run_id, symbol, rank, wms, rs, rsi, mfi, cci) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                rows,
            )

        return run_id

    def save_picks(self, run_id: int, picks: list[dict]) -> None:
        """Persist analyst classifications for a scan run."""
        import psycopg2.extras
        now = datetime.now().isoformat(timespec="seconds")

        rows = [
            (
                run_id,
                p["symbol"],
                p.get("classification", ""),
                p.get("confidence"),
                p.get("momentum_quality", ""),
                p.get("sector_backdrop", ""),
                p.get("fundamental", ""),
                p.get("news_catalysts", ""),
                p.get("risk_flags", ""),
                p.get("rationale", ""),
                now,
            )
            for p in picks
        ]
        with self._conn() as con:
            cur = con.cursor()
            psycopg2.extras.execute_batch(
                cur,
                "INSERT INTO picks "
                "(run_id, symbol, classification, confidence, momentum_quality, "
                " sector_backdrop, fundamental, news_catalysts, risk_flags, rationale, picked_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                rows,
            )

    def save_alerts(self, alerts: list[dict]) -> None:
        """Persist portfolio monitor alerts."""
        import psycopg2.extras
        now = datetime.now().isoformat(timespec="seconds")

        rows = [
            (
                a["symbol"],
                a["alert_level"],
                a.get("confidence", ""),
                a.get("trigger", ""),
                a.get("action", ""),
                a.get("risk_flags", ""),
                json.dumps(a.get("raw_news", [])),
                now,
            )
            for a in alerts
        ]
        with self._conn() as con:
            cur = con.cursor()
            psycopg2.extras.execute_batch(
                cur,
                "INSERT INTO alerts "
                "(symbol, alert_level, confidence, trigger, action, "
                " risk_flags, raw_news, alerted_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                rows,
            )

    def add_position(self, symbol: str, buy_price: float, qty: int) -> None:
        """Add or upsert a position in the portfolio table."""
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as con:
            cur = con.cursor()
            cur.execute(
                """
                INSERT INTO portfolio (symbol, buy_price, qty, added_at, status)
                VALUES (%s, %s, %s, %s, 'OPEN')
                ON CONFLICT (symbol) DO UPDATE SET
                    buy_price = EXCLUDED.buy_price,
                    qty       = EXCLUDED.qty,
                    status    = 'OPEN'
                """,
                (symbol, buy_price, qty, now),
            )

    def close_position(
        self,
        symbol: str,
        sell_price: float,
        exit_reason: str = "MANUAL",
    ) -> None:
        """Close a position, compute P&L, write to performance."""
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as con:
            cur = con.cursor()

            cur.execute(
                "SELECT buy_price, qty, added_at FROM portfolio "
                "WHERE symbol = %s AND status = 'OPEN'",
                (symbol,),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"No open position found for {symbol}")

            buy_price = row["buy_price"]
            qty       = row["qty"]
            opened_at = row["added_at"]

            pnl     = (sell_price - buy_price) * qty
            pnl_pct = (sell_price / buy_price - 1) * 100

            cur.execute(
                "SELECT classification FROM picks "
                "WHERE symbol = %s ORDER BY picked_at DESC LIMIT 1",
                (symbol,),
            )
            pick_row = cur.fetchone()
            pick_cls = pick_row["classification"] if pick_row else None

            try:
                open_dt   = datetime.fromisoformat(opened_at)
                hold_days = (datetime.now() - open_dt).days
            except Exception:
                hold_days = None

            cur.execute(
                "INSERT INTO performance "
                "(symbol, buy_price, sell_price, qty, pnl, pnl_pct, hold_days, "
                " opened_at, closed_at, pick_classification, exit_reason) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (symbol, buy_price, sell_price, qty, pnl, pnl_pct,
                 hold_days, opened_at, now, pick_cls, exit_reason),
            )
            cur.execute(
                "UPDATE portfolio SET status = 'CLOSED' WHERE symbol = %s",
                (symbol,),
            )

    def save_scan_report(
        self,
        run_id: int,
        category: str,
        scout_raw: str,
        analyst_raw: str,
        report_type: str = "SCOUT",
    ) -> int:
        """Save full raw text of both crew task outputs. Returns report_id."""
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as con:
            cur = con.cursor()
            cur.execute(
                "INSERT INTO scan_reports "
                "(run_id, category, scout_raw, analyst_raw, report_type, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (run_id, category, scout_raw, analyst_raw, report_type, now),
            )
            return cur.fetchone()["id"]

    # ── Read helpers ──────────────────────────────────────────────────────────

    def held_positions(self) -> list[dict]:
        """Return all currently open positions."""
        with self._conn() as con:
            cur = con.cursor()
            cur.execute(
                "SELECT symbol, buy_price, qty, added_at "
                "FROM portfolio WHERE status = 'OPEN'"
            )
            return [dict(r) for r in cur.fetchall()]

    def recent_picks(self, symbol: str, n: int = 10) -> list[dict]:
        """Return the last N analyst picks for a given ticker."""
        with self._conn() as con:
            cur = con.cursor()
            cur.execute(
                "SELECT classification, confidence, momentum_quality, rationale, picked_at "
                "FROM picks WHERE symbol = %s ORDER BY picked_at DESC LIMIT %s",
                (symbol, n),
            )
            return [dict(r) for r in cur.fetchall()]

    def latest_scan(self, category: str = "Nifty100") -> list[dict]:
        """Return ranked stocks from the most recent scan of a category."""
        with self._conn() as con:
            cur = con.cursor()
            cur.execute(
                "SELECT id FROM scan_runs WHERE category = %s ORDER BY run_at DESC LIMIT 1",
                (category,),
            )
            run = cur.fetchone()
            if not run:
                return []
            cur.execute(
                "SELECT s.symbol, s.rank, s.wms, s.rsi, s.mfi, s.cci, "
                "       p.classification, p.confidence "
                "FROM scans s "
                "LEFT JOIN picks p ON p.symbol = s.symbol AND p.run_id = s.run_id "
                "WHERE s.run_id = %s ORDER BY s.rank",
                (run["id"],),
            )
            return [dict(r) for r in cur.fetchall()]

    def alert_history(
        self,
        symbol: str | None = None,
        level: str | None = None,
        n: int = 50,
    ) -> list[dict]:
        """Return recent alerts, optionally filtered by symbol and/or level."""
        query  = "SELECT * FROM alerts WHERE 1=1"
        params: list[Any] = []
        if symbol:
            query += " AND symbol = %s"; params.append(symbol)
        if level:
            query += " AND alert_level = %s"; params.append(level)
        query += " ORDER BY alerted_at DESC LIMIT %s"
        params.append(n)

        with self._conn() as con:
            cur = con.cursor()
            cur.execute(query, params)
            return [dict(r) for r in cur.fetchall()]

    def performance_summary(self) -> dict:
        """Return aggregate P&L stats across all closed trades."""
        with self._conn() as con:
            cur = con.cursor()
            cur.execute("SELECT * FROM performance")
            rows = cur.fetchall()

        if not rows:
            return {}

        trades    = [dict(r) for r in rows]
        total     = len(trades)
        winners   = sum(1 for t in trades if t["pnl"] > 0)
        total_pnl = sum(t["pnl"] for t in trades)
        pnl_pcts  = [t["pnl_pct"] for t in trades]
        hold_days = [t["hold_days"] for t in trades if t["hold_days"] is not None]

        by_cls: dict[str, dict] = {}
        for t in trades:
            cls = t.get("pick_classification") or "UNKNOWN"
            if cls not in by_cls:
                by_cls[cls] = {"trades": 0, "wins": 0, "pnl": 0.0}
            by_cls[cls]["trades"] += 1
            by_cls[cls]["wins"]   += 1 if t["pnl"] > 0 else 0
            by_cls[cls]["pnl"]    += t["pnl"]

        return {
            "total_trades":      total,
            "winning_trades":    winners,
            "win_rate_pct":      round(winners / total * 100, 1) if total else 0,
            "total_pnl":         round(total_pnl, 2),
            "avg_pnl_pct":       round(sum(pnl_pcts) / len(pnl_pcts), 2) if pnl_pcts else 0,
            "best_trade":        max(trades, key=lambda t: t["pnl_pct"]),
            "worst_trade":       min(trades, key=lambda t: t["pnl_pct"]),
            "avg_hold_days":     round(sum(hold_days) / len(hold_days)) if hold_days else None,
            "by_classification": by_cls,
        }

    def export_picks_csv(self, path: str = "picks_export.csv") -> str:
        """Export all picks to CSV. Returns the file path written."""
        with self._conn() as con:
            cur = con.cursor()
            cur.execute(
                "SELECT p.*, r.category, r.run_at "
                "FROM picks p JOIN scan_runs r ON r.id = p.run_id "
                "ORDER BY p.picked_at DESC"
            )
            rows = cur.fetchall()

        if not rows:
            return "No picks to export."

        dicts = [dict(r) for r in rows]
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=dicts[0].keys())
            writer.writeheader()
            writer.writerows(dicts)
        return path

    def get_scan_reports(self, category: str = "Nifty100", n: int = 10) -> list[dict]:
        """Return last N scan report summaries for a category."""
        with self._conn() as con:
            cur = con.cursor()
            cur.execute(
                "SELECT id, run_id, category, report_type, created_at, "
                "       substr(analyst_raw, 1, 200) AS preview "
                "FROM scan_reports WHERE category = %s "
                "ORDER BY created_at DESC LIMIT %s",
                (category, n),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_scan_report_detail(self, report_id: int) -> dict | None:
        """Return full text of a specific scan report."""
        with self._conn() as con:
            cur = con.cursor()
            cur.execute("SELECT * FROM scan_reports WHERE id = %s", (report_id,))
            row = cur.fetchone()
        return dict(row) if row else None

    def delete_scan_report(self, report_id: int) -> None:
        """Delete a specific scan report."""
        with self._conn() as con:
            cur = con.cursor()
            cur.execute("DELETE FROM scan_reports WHERE id = %s", (report_id,))

    def get_stock_analyst_report(
        self,
        symbol: str,
        category: str = "Nifty100",
    ) -> str | None:
        """Extract the analyst block for a specific stock from the latest report."""
        with self._conn() as con:
            cur = con.cursor()
            cur.execute(
                "SELECT analyst_raw FROM scan_reports WHERE category = %s "
                "ORDER BY created_at DESC LIMIT 1",
                (category,),
            )
            row = cur.fetchone()

        if not row or not row["analyst_raw"]:
            return None

        text    = row["analyst_raw"]
        pattern = rf"(?i)SYMBOL\s*:\s*{re.escape(symbol)}\b(.*?)(?=\bSYMBOL\s*:|$)"
        match   = re.search(pattern, text, re.DOTALL)

        return (f"SYMBOL: {symbol}" + match.group(1).strip()) if match else None

    def get_stock_monitor_report(self, symbol: str) -> str | None:
        """Extract the monitor alert block for a specific stock from the latest Monitor report."""
        with self._conn() as con:
            cur = con.cursor()
            cur.execute(
                "SELECT analyst_raw FROM scan_reports WHERE category = 'Monitor' "
                "ORDER BY created_at DESC LIMIT 1",
            )
            row = cur.fetchone()

        if not row or not row["analyst_raw"]:
            return None

        text    = row["analyst_raw"]
        pattern = rf"(?:SYMBOL|TICKER)\s*:\s*{re.escape(symbol)}\b(.*?)(?=(?:SYMBOL|TICKER)\s*:|$)"
        match   = re.search(pattern, text, re.DOTALL | re.IGNORECASE)

        return (f"SYMBOL: {symbol}" + match.group(1).strip()) if match else None

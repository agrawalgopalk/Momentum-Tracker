"""
persistence.py  –  SQLite persistence layer for the Momentum Portfolio System.

Creates and manages five tables:
  scans_runs   – one row per time you ran the momentum tool — timestamp, category, how many stocks scored
  — 
  scans        – every MomentumBackboneTool result (one row per stock per run)
  — these two work together. scan_runs is the header (one row per time you ran 
  the momentum tool — timestamp, category, how many stocks scored). 
  scans is the detail (one row per stock per run). This separation lets 
  you ask "show me every time TATAMOTORS appeared in the top 20 over the last 3 months" — 
  which is how you spot consistent momentum vs a one-off blip
  
  picks        – analyst classifications (BUY / HOLD / AVOID) with confidence: 
  — stores what the analyst decided, not just what the quant scored. This is the accountability layer. 
  Every BUY/HOLD/AVOID call is timestamped with its confidence score, 
  momentum quality (SUPPORTED/STRETCHED/UNSUPPORTED), and rationale. 
  Six months later you can compare the BUY calls that had SUPPORTED momentum vs 
  STRETCHED momentum and see which actually performed.
  
  alerts       – portfolio monitor outputs (RED / YELLOW / GREEN per ticker)
  — stores every RED/YELLOW/GREEN from the monitor. The critical column here 
  is alerted_at. If you get a RED on ADANIENT today and another RED three days later, 
  that escalating pattern is a stronger signal than a single alert. 
  Without persistence you'd never see the pattern.
  
  portfolio    – held positions (source of truth for the monitor)
  — this is your single source of truth for what you currently hold. The monitor reads from here automatically 
  — you don't manually type your positions into portfolio_monitor.py each time. 
  You add a position once (DB.add_position("RELIANCE.NS", 2850, 50)) and every subsequent monitor run picks it up.
  
  performance  – closed-trade P&L (written when you sell a position)
  — this is the feedback loop that makes the whole system smarter over time. 
  When you close a position (DB.close_position("RELIANCE.NS", 3050)), 
  it automatically calculates P&L, looks up what the analyst originally 
  classified it as, and stores everything together. 
  This is what powers the "win rate by classification" chart in the dashboard 
  — you can literally see whether your BUY signals are better than chance.
  
  
  _conn() context manager uses WAL journal mode. This matters because 
  the scheduler and dashboard might both try to read the database 
  at the same time — WAL prevents one from locking the other out.

Usage
─────
  from persistence import DB

  # Save a scan run
  run_id = DB.save_scan(category="Nifty100", results=top_results_df)

  # Save analyst picks for that run
  DB.save_picks(run_id, picks_list)

  # Save an alert batch
  DB.save_alerts(alerts_list)

  # Manage portfolio
  DB.add_position("RELIANCE.NS", buy_price=2850.0, qty=50)
  DB.close_position("RELIANCE.NS", sell_price=3050.0)

  # Query
  history = DB.recent_picks("RELIANCE.NS", n=10)
  held    = DB.held_positions()
  report  = DB.performance_summary()
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from utils import normalise_ticker as _normalise  # normalise symbol-field aliases in monitor output

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

DB_PATH = Path(__file__).resolve().parent / "momentum_tracker" / "mps_cache" / "momentum.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# Connection helper
# ─────────────────────────────────────────────────────────────────────────────

@contextmanager
def _conn():
    con = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")   # safe concurrent reads
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


# ─────────────────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────────────────

_SCHEMA = """
-- One row per full scan run (header record)
CREATE TABLE IF NOT EXISTS scan_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at      TEXT    NOT NULL,
    category    TEXT    NOT NULL,
    total_scored INTEGER,
    top_n       INTEGER
);

-- One row per stock returned by a scan run
CREATE TABLE IF NOT EXISTS scans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES scan_runs(id),
    symbol      TEXT    NOT NULL,
    rank        INTEGER,
    wms         REAL,
    rs          REAL,
    rsi         REAL,
    mfi         REAL,
    cci         REAL
);

-- Analyst classifications (one row per stock per run)
CREATE TABLE IF NOT EXISTS picks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES scan_runs(id),
    symbol          TEXT    NOT NULL,
    classification  TEXT    NOT NULL,   -- BUY | HOLD | AVOID
    confidence      INTEGER,            -- 1–5
    momentum_quality TEXT,              -- SUPPORTED | STRETCHED | UNSUPPORTED
    sector_backdrop TEXT,
    fundamental     TEXT,
    news_catalysts  TEXT,
    risk_flags      TEXT,
    rationale       TEXT,
    picked_at       TEXT    NOT NULL
);

-- Portfolio monitor alerts (one row per ticker per monitor run)
CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT    NOT NULL,
    alert_level TEXT    NOT NULL,       -- RED | YELLOW | GREEN
    confidence  TEXT,                   -- HIGH | MEDIUM | LOW
    trigger     TEXT,
    action      TEXT,
    risk_flags  TEXT,
    raw_news    TEXT,                   -- JSON array of story dicts
    alerted_at  TEXT    NOT NULL
);

-- Held positions (source of truth for monitor)
CREATE TABLE IF NOT EXISTS portfolio (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT    NOT NULL UNIQUE,
    buy_price   REAL    NOT NULL,
    qty         INTEGER NOT NULL,
    added_at    TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'OPEN'  -- OPEN | CLOSED
);

-- Closed trade P&L
CREATE TABLE IF NOT EXISTS performance (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT    NOT NULL,
    buy_price   REAL    NOT NULL,
    sell_price  REAL    NOT NULL,
    qty         INTEGER NOT NULL,
    pnl         REAL    NOT NULL,       -- (sell - buy) * qty
    pnl_pct     REAL    NOT NULL,       -- (sell/buy - 1) * 100
    hold_days   INTEGER,
    opened_at   TEXT,
    closed_at   TEXT    NOT NULL,
    pick_classification TEXT,           -- BUY / HOLD / AVOID at time of purchase
    exit_reason TEXT                    -- RED_ALERT | MANUAL | TARGET_HIT | STOP_LOSS
);

-- scan report storage (one row per scan run, storing full raw text of both scout and analyst outputs for audit/debugging)
CREATE TABLE IF NOT EXISTS scan_reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER REFERENCES scan_runs(id),
    category    TEXT    NOT NULL,
    scout_raw   TEXT,        -- full WMS table text
    analyst_raw TEXT,        -- full analyst block text
    created_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scans_symbol  ON scans(symbol);
CREATE INDEX IF NOT EXISTS idx_picks_symbol  ON picks(symbol);
CREATE INDEX IF NOT EXISTS idx_alerts_symbol ON alerts(symbol);
CREATE INDEX IF NOT EXISTS idx_alerts_level  ON alerts(alert_level);
"""

def init_db() -> None:
    with _conn() as con:
        con.executescript(_SCHEMA)
        _migrate(con)


def _migrate(con) -> None:
    """
    Applies schema changes that can't go into _SCHEMA because the table
    already exists in production.  Safe to run on every startup —
    each block is idempotent (catches 'duplicate column' errors).
    """
    migrations = [
        "ALTER TABLE scan_reports ADD COLUMN report_type TEXT DEFAULT 'SCOUT'",
    ]
    for sql in migrations:
        try:
            con.execute(sql)
        except Exception as e:
            if "duplicate column" in str(e).lower():
                pass   # already applied — safe to ignore
            else:
                raise  # real error — let it bubble up

# ─────────────────────────────────────────────────────────────────────────────
# Write helpers
# ─────────────────────────────────────────────────────────────────────────────

def save_scan(category: str, results: list[dict], top_n: int = 20) -> int:
    """
    Persist a full scan run.  Returns the run_id for linking picks.

    Parameters
    ----------
    category : str
        e.g. "Nifty100"
    results : list of dicts
        Each dict must have keys: Symbol, rank, WMS, RS_Raw, RSI_Raw, MFI_Raw, CCI_Raw
    top_n : int
        How many candidates were requested.
    """
    now = datetime.now().isoformat(timespec="seconds")
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO scan_runs (run_at, category, total_scored, top_n) VALUES (?,?,?,?)",
            (now, category, len(results), top_n),
        )
        run_id = cur.lastrowid
        con.executemany(
            "INSERT INTO scans (run_id, symbol, rank, wms, rs, rsi, mfi, cci) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [
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
            ],
        )
    return run_id


def save_picks(run_id: int, picks: list[dict]) -> None:
    """
    Persist analyst classifications for a scan run.

    Each dict in picks must have:
      symbol, classification, confidence, momentum_quality,
      sector_backdrop, fundamental, news_catalysts, risk_flags, rationale
    """
    now = datetime.now().isoformat(timespec="seconds")
    with _conn() as con:
        con.executemany(
            "INSERT INTO picks "
            "(run_id, symbol, classification, confidence, momentum_quality, "
            " sector_backdrop, fundamental, news_catalysts, risk_flags, rationale, picked_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
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
            ],
        )


def save_alerts(alerts: list[dict]) -> None:
    """
    Persist monitor alerts.

    Each dict must have:
      symbol, alert_level, confidence, trigger, action, risk_flags
    Optional: raw_news (list of story dicts – will be JSON-serialised)
    """
    now = datetime.now().isoformat(timespec="seconds")
    with _conn() as con:
        con.executemany(
            "INSERT INTO alerts "
            "(symbol, alert_level, confidence, trigger, action, risk_flags, raw_news, alerted_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [
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
            ],
        )


def add_position(symbol: str, buy_price: float, qty: int) -> None:
    """Add or update a position in the portfolio table."""
    now = datetime.now().isoformat(timespec="seconds")
    with _conn() as con:
        con.execute(
            "INSERT INTO portfolio (symbol, buy_price, qty, added_at, status) "
            "VALUES (?,?,?,?,'OPEN') "
            "ON CONFLICT(symbol) DO UPDATE SET "
            "  buy_price=excluded.buy_price, qty=excluded.qty, status='OPEN'",
            (symbol, buy_price, qty, now),
        )


def close_position(
    symbol: str,
    sell_price: float,
    exit_reason: str = "MANUAL",
) -> None:
    """
    Mark a position as closed, compute P&L, and write to performance table.
    Automatically looks up buy_price and qty from portfolio table.
    """
    now = datetime.now().isoformat(timespec="seconds")
    with _conn() as con:
        row = con.execute(
            "SELECT buy_price, qty, added_at FROM portfolio WHERE symbol=? AND status='OPEN'",
            (symbol,),
        ).fetchone()
        if not row:
            raise ValueError(f"No open position found for {symbol}")

        buy_price = row["buy_price"]
        qty       = row["qty"]
        opened_at = row["added_at"]

        pnl     = (sell_price - buy_price) * qty
        pnl_pct = (sell_price / buy_price - 1) * 100

        # Try to get the original pick classification
        pick_row = con.execute(
            "SELECT classification FROM picks WHERE symbol=? ORDER BY picked_at DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        pick_cls = pick_row["classification"] if pick_row else None

        # Hold days
        try:
            open_dt  = datetime.fromisoformat(opened_at)
            hold_days = (datetime.now() - open_dt).days
        except Exception:
            hold_days = None

        con.execute(
            "INSERT INTO performance "
            "(symbol, buy_price, sell_price, qty, pnl, pnl_pct, hold_days, "
            " opened_at, closed_at, pick_classification, exit_reason) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (symbol, buy_price, sell_price, qty, pnl, pnl_pct,
             hold_days, opened_at, now, pick_cls, exit_reason),
        )
        con.execute(
            "UPDATE portfolio SET status='CLOSED' WHERE symbol=?", (symbol,)
        )


# ─────────────────────────────────────────────────────────────────────────────
# Read helpers
# ─────────────────────────────────────────────────────────────────────────────

def held_positions() -> list[dict]:
    """Return all currently open positions."""
    with _conn() as con:
        rows = con.execute(
            "SELECT symbol, buy_price, qty, added_at FROM portfolio WHERE status='OPEN'"
        ).fetchall()
    return [dict(r) for r in rows]


def recent_picks(symbol: str, n: int = 10) -> list[dict]:
    """Return the last N analyst picks for a given ticker."""
    with _conn() as con:
        rows = con.execute(
            "SELECT classification, confidence, momentum_quality, rationale, picked_at "
            "FROM picks WHERE symbol=? ORDER BY picked_at DESC LIMIT ?",
            (symbol, n),
        ).fetchall()
    return [dict(r) for r in rows]


def latest_scan(category: str = "Nifty100") -> list[dict]:
    """Return the top-ranked stocks from the most recent scan of a category."""
    with _conn() as con:
        run = con.execute(
            "SELECT id FROM scan_runs WHERE category=? ORDER BY run_at DESC LIMIT 1",
            (category,),
        ).fetchone()
        if not run:
            return []
        rows = con.execute(
            "SELECT s.symbol, s.rank, s.wms, s.rsi, s.mfi, s.cci, "
            "       p.classification, p.confidence "
            "FROM scans s "
            "LEFT JOIN picks p ON p.symbol=s.symbol AND p.run_id=s.run_id "
            "WHERE s.run_id=? ORDER BY s.rank",
            (run["id"],),
        ).fetchall()
    return [dict(r) for r in rows]


def alert_history(symbol: str | None = None, level: str | None = None, n: int = 50) -> list[dict]:
    """Return recent alerts, optionally filtered by symbol or level (RED/YELLOW/GREEN)."""
    query = "SELECT * FROM alerts WHERE 1=1"
    params: list[Any] = []
    if symbol:
        query += " AND symbol=?"; params.append(symbol)
    if level:
        query += " AND alert_level=?"; params.append(level)
    query += " ORDER BY alerted_at DESC LIMIT ?"
    params.append(n)
    with _conn() as con:
        rows = con.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def performance_summary() -> dict:
    """
    Return aggregate P&L stats across all closed trades.

    Returns
    -------
    dict with keys:
      total_trades, winning_trades, win_rate_pct,
      total_pnl, avg_pnl_pct, best_trade, worst_trade,
      avg_hold_days, by_classification (dict)
    """
    with _conn() as con:
        rows = con.execute("SELECT * FROM performance").fetchall()
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
        "total_trades":   total,
        "winning_trades": winners,
        "win_rate_pct":   round(winners / total * 100, 1) if total else 0,
        "total_pnl":      round(total_pnl, 2),
        "avg_pnl_pct":    round(sum(pnl_pcts) / len(pnl_pcts), 2) if pnl_pcts else 0,
        "best_trade":     max(trades, key=lambda t: t["pnl_pct"]),
        "worst_trade":    min(trades, key=lambda t: t["pnl_pct"]),
        "avg_hold_days":  round(sum(hold_days) / len(hold_days)) if hold_days else None,
        "by_classification": by_cls,
    }


def export_picks_csv(path: str = "picks_export.csv") -> str:
    """Export all picks to CSV. Returns the path written."""
    import csv
    with _conn() as con:
        rows = con.execute(
            "SELECT p.*, r.category, r.run_at "
            "FROM picks p JOIN scan_runs r ON r.id=p.run_id "
            "ORDER BY p.picked_at DESC"
        ).fetchall()
    if not rows:
        return "No picks to export."
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows([dict(r) for r in rows])
    return path

# ─────────────────────────────────────────────────────────────────────────────
# Export Scan Report
# ─────────────────────────────────────────────────────────────────────────────

def save_scan_report(run_id: int, category: str,
                     scout_raw: str, analyst_raw: str,
                     report_type: str = "SCOUT") -> int:
    """Save full raw text of both task outputs for a scan run."""
    now = datetime.now().isoformat(timespec="seconds")
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO scan_reports (run_id, category, scout_raw, analyst_raw, report_type, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (run_id, category, scout_raw, analyst_raw, report_type, now),
        )
    return cur.lastrowid


def get_scan_reports(category: str = "Nifty100", n: int = 10) -> list[dict]:
    """Return last N scan reports for a category."""
    with _conn() as con:
        rows = con.execute(
            "SELECT id, run_id, category, report_type, created_at, "
            "       substr(analyst_raw, 1, 200) as preview "
            "FROM scan_reports WHERE category=? "
            "ORDER BY created_at DESC LIMIT ?",
            (category, n),
        ).fetchall()
    return [dict(r) for r in rows]


def get_scan_report_detail(report_id: int) -> dict | None:
    """Return full text of a specific report."""
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM scan_reports WHERE id=?", (report_id,)
        ).fetchone()
    return dict(row) if row else None


def delete_scan_report(report_id: int) -> None:
    """Delete a specific scan report."""
    with _conn() as con:
        con.execute("DELETE FROM scan_reports WHERE id=?", (report_id,))
        
        
import re
def get_stock_analyst_report(symbol: str, category: str = "Nifty100") -> str | None:
    """Extract the analyst block for a specific stock from the latest scan report."""
    with _conn() as con:
        row = con.execute(
            "SELECT analyst_raw FROM scan_reports WHERE category=? "
            "ORDER BY created_at DESC LIMIT 1",
            (category,),
        ).fetchone()

    if not row or not row["analyst_raw"]:
        return None

    text    = row["analyst_raw"]
    pattern = rf"(?i)SYMBOL\s*:\s*{re.escape(symbol)}\b(.*?)(?=\bSYMBOL\s*:|$)"
    match   = re.search(pattern, text, re.DOTALL)

    return (f"SYMBOL: {symbol}" + match.group(1).strip()) if match else None


# def get_stock_monitor_report(symbol: str) -> str | None:
#     """Extract the monitor alert block for a specific stock from the latest Monitor report."""
#     with _conn() as con:
#         row = con.execute(
#             "SELECT analyst_raw FROM scan_reports WHERE category='Monitor' "
#             "ORDER BY created_at DESC LIMIT 1",
#         ).fetchone()

#     if not row or not row["analyst_raw"]:
#         return None

#     text    = row["analyst_raw"]
#     # Handles both SYMBOL and TICKER — LLM uses either interchangeably
#     pattern = rf"(?:SYMBOL|TICKER)\s*:\s*{re.escape(symbol)}\b(.*?)(?=(?:SYMBOL|TICKER)\s*:|$)"
#     match   = re.search(pattern, text, re.DOTALL | re.IGNORECASE)

#     return (f"SYMBOL: {symbol}" + match.group(1).strip()) if match else None

# def save_monitor_report(self, alert_data: dict, raw_text: str):
#     with self._conn() as con:
#         con.execute(
#             """INSERT INTO monitor_reports 
#                 (symbol, alert_level, confidence, trigger, action, risk_flags, raw_text, created_at) 
#                 VALUES (?,?,?,?,?,?,?,?)""",
#             (
#                 alert_data.get("symbol"),
#                 alert_data.get("alert_level"),
#                 alert_data.get("confidence"),
#                 alert_data.get("trigger"),
#                 alert_data.get("action"),
#                 alert_data.get("risk_flags"),
#                 raw_text,
#                 datetime.now()
#             )
#         )

# def delete_old_monitor_reports(days_old: int = 30):
#     """Cleanup utility to keep your database lean."""
#     conn = get_db_connection()
#     try:
#         threshold_date = datetime.datetime.now() - datetime.timedelta(days=days_old)
#         conn.execute("DELETE FROM monitor_reports WHERE created_at < ?", (threshold_date,))
#         conn.commit()
#     finally:
#         conn.close()
        
        
# ─────────────────────────────────────────────────────────────────────────────
# SQLiteDatabase  –  DatabaseInterface implementation
# ─────────────────────────────────────────────────────────────────────────────

from db_interface import DatabaseInterface

class SQLiteDatabase(DatabaseInterface):
    """
    SQLite implementation of DatabaseInterface.

    Wraps all the module-level functions above so the rest of the codebase
    can use DB.method() regardless of which backend is active.
    The config parameter is accepted for API symmetry with PostgreSQLDatabase
    but is not used — SQLite path is baked into _conn() via _DB_PATH.
    """

    def __init__(self, config=None) -> None:
        pass   # SQLite path is already resolved by _DB_PATH at module level

    def init(self) -> None:
        init_db()

    def save_scan(self, category, results, top_n=20):
        return save_scan(category, results, top_n)

    def save_picks(self, run_id, picks):
        return save_picks(run_id, picks)

    def save_alerts(self, alerts):
        return save_alerts(alerts)

    def add_position(self, symbol, buy_price, qty):
        return add_position(symbol, buy_price, qty)

    def close_position(self, symbol, sell_price, exit_reason="MANUAL"):
        return close_position(symbol, sell_price, exit_reason)

    def save_scan_report(self, run_id, category, scout_raw, analyst_raw, report_type="SCOUT"):
        return save_scan_report(run_id, category, scout_raw, analyst_raw, report_type)

    def held_positions(self):
        return held_positions()

    def recent_picks(self, symbol, n=10):
        return recent_picks(symbol, n)

    def latest_scan(self, category="Nifty100"):
        return latest_scan(category)

    def alert_history(self, symbol=None, level=None, n=50):
        return alert_history(symbol, level, n)

    def performance_summary(self):
        return performance_summary()

    def export_picks_csv(self, path="picks_export.csv"):
        return export_picks_csv(path)

    def get_scan_reports(self, category="Nifty100", n=10):
        return get_scan_reports(category, n)

    def get_scan_report_detail(self, report_id):
        return get_scan_report_detail(report_id)

    def delete_scan_report(self, report_id):
        return delete_scan_report(report_id)

    def get_stock_analyst_report(self, symbol, category="Nifty100"):
        return get_stock_analyst_report(symbol, category)

    # def get_stock_monitor_report(self, symbol):
    #     return get_stock_monitor_report(symbol)


# ─────────────────────────────────────────────────────────────────────────────
# DB singleton  –  use db_config to pick the right backend
# ─────────────────────────────────────────────────────────────────────────────

try:
    from db_config import get_db
    DB = get_db()
except Exception:
    # db_config.py not present yet (e.g. running tests or standalone scripts)
    # Fall back to SQLite directly so existing code never breaks.
    DB = SQLiteDatabase()
    DB.init()

"""
scheduler.py  
–  Daily automation + CrewAI memory configuration.
–  Daily automation for the Momentum Portfolio System.

What this file does
───────────────────
  - Imports build_crew()   from main.py            (discovery pipeline)
  - Imports run_monitor()  from portfolio_monitor.py (alert pipeline)
  - Imports DB             from persistence.py       (save results)
  - Schedules both jobs on a weekday cron

This file contains ZERO crew/agent/task logic — all of that lives in
main.py and portfolio_monitor.py. scheduler.py is purely the timer
and the glue between the crew output and the database.


Jobs
────
Runs two jobs on a schedule:
  08:15 IST Mon-Fri  →  job_scan_and_classify()  (main.py crew)
  08:15 IST – Momentum scan + analyst classification  (main crew)

  08:45 IST – Portfolio monitor alerts                (monitor crew)
  08:45 IST Mon-Fri  →  job_monitor()            (portfolio_monitor.py crew)

CrewAI memory tiers configured here:
  Short-term  – in-memory RAG, scoped to one crew run
  Short-term memory is already partially working via context=[task_scan] in your task definition. 
  But enabling it properly means the analyst agent can refer back to earlier parts of its own reasoning 
  within a single run without re-reading the full Task 1 output. 
  
  Small efficiency gain but it reduces token waste on long runs.
  Entity memory is the useful one for your domain. It builds a named-entity store of stock tickers, 
  company names, and sector labels. 
  Without it, the LLM might say "INFY" in one place and "Infosys" in another and not connect them. 
  With entity memory, the analyst knows these are the same thing and can aggregate signals across both forms.

  Entity      – named-entity store (stock names, sectors)
  Long-term   – ChromaDB-backed store, persists across runs

Usage
─────
  python scheduler.py          # start the blocking scheduler
  python scheduler.py --once   # fire both jobs immediately and exit (for testing)
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

# ── All crew logic lives in these two files ────────────────────────────────
from discovery_crew import build_crew              # discovery pipeline
from portfolio_monitor import run_monitor          # alert pipeline
from persistence import DB                         # save to SQLite
from utils import normalise_ticker as _normalise  # normalise symbol-field aliases in monitor output

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────

# _LOG_FILE = Path(__file__).parent / "momentum_tracker" / "mps_cache" / "scheduler.log"
# _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s  %(levelname)-8s  %(message)s",
#     datefmt="%Y-%m-%d %H:%M:%S",
#     handlers=[
#         logging.StreamHandler(open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False)),
#         logging.FileHandler(_LOG_FILE),
#     ],
# )
# log = logging.getLogger("scheduler")

IST = ZoneInfo("Asia/Kolkata")
from logger import get_logger
log = get_logger("scheduler")

# ─────────────────────────────────────────────────────────────────────────────
# Job 1 – Scan + classify  (delegates entirely to main.py)
# ─────────────────────────────────────────────────────────────────────────────

def job_scan_and_classify(category: str = "Nifty100"):
    """
    Runs the discovery crew from main.py, then saves results to persistence.py.
    No crew logic here — just orchestration.
    """
    log.info("=== JOB 1: Momentum scan + classification (via main.py) ===")
    try:
        crew   = build_crew(category=category, top_n=20, use_memory=False)
        result = crew.kickoff()

        # Save raw scan rows and analyst picks to SQLite
        scout_text   = result.tasks_output[0].raw   # WMS table lives here
        analyst_text = result.tasks_output[1].raw   # BUY/HOLD/AVOID blocks live here

        # log.info("Scout preview:\n%s", scout_text[:300].encode('ascii', 'replace').decode())

        scan_rows = _parse_scan_rows(scout_text)
        picks     = _parse_picks(analyst_text)

        if not scan_rows:
            log.warning("No scan rows parsed — skipping DB save. Check scout output above.")
            return

        run_id = DB.save_scan(category=category, results=scan_rows, top_n=20)
        DB.save_picks(run_id, picks)
        DB.save_scan_report(run_id, category, scout_text, analyst_text, report_type="SCOUT")        
        
        # REPLACE both preview logs with
        # log.info("Scout preview:\n%s", scout_text[:300].encode('ascii', 'replace').decode())
        # log.info("Analyst preview:\n%s", analyst_text[:500].encode('ascii', 'replace').decode())

        # log.info("Scout output preview:\n%s", scout_text[:300])
        # log.info("Sample row: %s", scan_rows[0] if scan_rows else "EMPTY")
        log.info("Job 1 complete – run_id=%d, %d stocks, %d picks saved",
                run_id, len(scan_rows), len(picks))

    except Exception as exc:
        log.exception("Job 1 failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Job 2 – Portfolio monitor  (delegates entirely to portfolio_monitor.py)
# ─────────────────────────────────────────────────────────────────────────────

def job_monitor():
    """
    Loads held positions from persistence.py, runs portfolio_monitor.py crew,
    then saves any alerts back to persistence.py.
    No crew logic here — just orchestration.
    """
    log.info("=== JOB 2: Portfolio monitor (via portfolio_monitor.py) ===")
    try:
        held = DB.held_positions()
        if not held:
            log.info("No open positions – monitor skipped.")
            return

        # run_monitor() is fully defined in portfolio_monitor.py
        log.info("Running monitor for %d held positions: %s",
                 len(held), ", ".join(p["symbol"] for p in held))
        report = run_monitor(held)

        # Parse RED alerts and save them
        alerts = _parse_alerts(report)
        if alerts:
            DB.save_alerts(alerts)
            
        # Save the raw report ALWAYS — even if all are GREEN
        DB.save_scan_report(
            run_id=0,              # no scan run linked — monitor is independent
            category="Monitor",   # distinguishes from discovery scans in the UI
            scout_raw="",         # monitor has no WMS table
            analyst_raw=report,   # full monitor report text
            report_type="MONITOR"
        )
        log.info("Monitor report saved to scan_reports.")

        red = [a for a in alerts if a["alert_level"] == "RED"]
        if red:
            log.warning("RED ALERTS: %s", ", ".join(a["symbol"] for a in red))
        else:
            log.info("Job 2 complete – no RED alerts.")

    except Exception as exc:
        log.exception("Job 2 failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Text parsers  (convert crew string output → dicts for DB)
# ─────────────────────────────────────────────────────────────────────────────
#
# These are deliberately minimal — they just extract what the DB needs.
# If you want richer structured output, swap to a JSON-mode LLM call
# or use regex on the known task output format.
# ─────────────────────────────────────────────────────────────────────────────

def _parse_scan_rows(text: str) -> list[dict]:
    """Extract WMS table rows from the momentum tool output."""
    rows = []
    for line in text.splitlines():
        parts = line.split()
        # Table rows: Rank  Symbol  WMS  RS  RSI  MFI  CCI
        if len(parts) >= 7 and parts[0].isdigit():
            try:
                rows.append({
                    "Symbol":   parts[1],
                    "WMS":      float(parts[2]),
                    "RS_Raw":   float(parts[3]),
                    "RSI_Raw":  float(parts[4]),
                    "MFI_Raw":  float(parts[5]),
                    "CCI_Raw":  float(parts[6]),
                })
            except (ValueError, IndexError):
                pass
    return rows

def _parse_picks(text: str) -> list[dict]:
    picks: list[dict] = []
    current: dict = {}

    field_map = {
        "SYMBOL":             "symbol",
        "CLASSIFICATION":     "classification",
        "CONFIDENCE":         "confidence",
        "MOMENTUM QUALITY":   "momentum_quality",
        "SECTOR BACKDROP":    "sector_backdrop",
        "FUNDAMENTAL HEALTH": "fundamental",
        "NEWS CATALYSTS":     "news_catalysts",
        "RISK FLAGS":         "risk_flags",
        "ONE-LINE RATIONALE": "rationale",
    }

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("SYMBOL:"):
            if current.get("symbol"):       # save previous block first
                picks.append(current)
            current = {"symbol": line.split(":", 1)[1].strip()}
            continue
        for label, key in field_map.items():
            if line.startswith(f"{label}:"):
                value = line.split(":", 1)[1].strip()
                if key == "confidence":
                    try:
                        value = int(value[0])
                    except (ValueError, IndexError):
                        value = None
                current[key] = value
                break

    if current.get("symbol"):               # save the final block
        picks.append(current)
    return picks

def _parse_alerts_old(text: str) -> list[dict]:
    """Extract alert records from the monitor report."""
    alerts: list[dict] = []
    current: dict      = {}

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("TICKER"):
            if current.get("symbol"):
                alerts.append(current)
            current = {"symbol": line.split(":", 1)[1].strip().split()[0]}
        elif line.startswith("ALERT"):
            raw = line.split(":", 1)[1].strip()
            for level in ("RED", "YELLOW", "GREEN"):
                if level in raw:
                    current["alert_level"] = level
                    break
        elif line.startswith("TRIGGER SUMMARY"):
            current["trigger"] = line.split(":", 1)[1].strip()
        elif line.startswith("RECOMMENDED ACTION"):
            current["action"] = line.split(":", 1)[1].strip()
        elif line.startswith("RISK FLAGS"):
            current["risk_flags"] = line.split(":", 1)[1].strip()
        elif line.startswith("=" * 10) and current.get("symbol"):
            alerts.append(current)
            current = {}

    if current.get("symbol") and current.get("alert_level"):
        alerts.append(current)
    return alerts

def _parse_alerts(text: str) -> list[dict]:
    alerts: list[dict] = []
    current: dict = {}

    for line in text.splitlines():
        line = line.strip()

        # Normalise: treat TICKER as an alias for SYMBOL
        normalised = _normalise(line.strip())

        if normalised.startswith("SYMBOL") and ":" in normalised:
            if current.get("symbol") and current.get("alert_level"):
                alerts.append(current)
            val = normalised.split(":", 1)[1].strip()
            current = {"symbol": val}

        elif normalised.startswith("ALERT") and ":" in normalised:
            raw = normalised.split(":", 1)[1].strip()
            for level in ("RED", "YELLOW", "GREEN"):
                if level in raw.upper():
                    current["alert_level"] = level
                    break

        elif normalised.startswith("CONFIDENCE") and ":" in normalised:
            current["confidence"] = normalised.split(":", 1)[1].strip()

        elif normalised.startswith("TRIGGER SUMMARY") and ":" in normalised:
            current["trigger"] = normalised.split(":", 1)[1].strip()

        elif normalised.startswith("RECOMMENDED ACTION") and ":" in normalised:
            current["action"] = normalised.split(":", 1)[1].strip()

        elif normalised.startswith("RISK FLAGS") and ":" in normalised:
            current["risk_flags"] = normalised.split(":", 1)[1].strip()

    if current.get("symbol") and current.get("alert_level"):
        alerts.append(current)

    return alerts

# ─────────────────────────────────────────────────────────────────────────────
# Scheduler setup
# ─────────────────────────────────────────────────────────────────────────────

def start_scheduler():
    scheduler = BlockingScheduler(timezone=IST)

    scheduler.add_job(
        job_scan_and_classify,
        CronTrigger(day_of_week="mon-fri", hour=8, minute=15, timezone=IST),
        id="scan_classify",
        name="Momentum scan + classify (main.py)",
        misfire_grace_time=300,
    )

    scheduler.add_job(
        job_monitor,
        CronTrigger(day_of_week="mon-fri", hour=8, minute=45, timezone=IST),
        id="monitor",
        name="Portfolio monitor (portfolio_monitor.py)",
        misfire_grace_time=300,
    )

    log.info("Scheduler started — jobs fire Mon-Fri at 08:15 and 08:45 IST.")
    log.info("Press Ctrl+C to stop.")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        log.info("Scheduler stopped.")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Momentum system scheduler")
    parser.add_argument(
        "--once", action="store_true",
        help="Fire both jobs immediately and exit (for testing)"
    )
    args = parser.parse_args()

    if args.once:
        log.info("--once mode: running both jobs now.")
        job_scan_and_classify()
        job_monitor()
        log.info("Done.")
    else:
        start_scheduler()
        
        
# pip install apscheduler streamlit plotly chromadb
        
# pip install crewai crewai-tools langchain-community duckduckgo-search \
            # apscheduler streamlit plotly chromadb python-dotenv
# python scheduler.py --once       # runs scan + monitor, writes to DB
# streamlit run dashboard.py       # open browser to see results        


# streamlit run dashboard.py
# Opens at http://localhost:8501. Add your first position in the sidebar before running the monitor so it has something to watch.

# Option C — Start the daily scheduler (leave running in background)
# python scheduler.py

# nohup python scheduler.py > scheduler.log 2>&1 &

# 1. python scheduler.py --once     ← verify the whole pipeline works
# 2. streamlit run dashboard.py     ← check data appeared in DB
# 3. Add positions via dashboard sidebar
# 4. python scheduler.py            ← start daily automation
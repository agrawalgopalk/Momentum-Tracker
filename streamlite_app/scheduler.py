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


from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

# ── All crew logic lives in these two files ────────────────────────────────
from crew import run_momentun_discovery  # discovery pipeline
from crew import run_monitor          # alert pipeline
from database import get_db
from utils import normalise_ticker as _normalise    # normalise symbol-field aliases in monitor output
from utils import clean_text                        # remove emojis and clean whitespace in monitor output
from utils import get_logger
log = get_logger("scheduler")
DB = get_db()

IST = ZoneInfo("Asia/Kolkata")
# ─────────────────────────────────────────────────────────────────────────────
# Exceptions and Helpers
# ─────────────────────────────────────────────────────────────────────────────

import re

class RateLimitScanError(Exception):
    def __init__(self, message, run_id, tickers, scout_raw, accumulated_text):
        super().__init__(message)
        self.run_id = run_id
        self.tickers = tickers
        self.scout_raw = scout_raw
        self.accumulated_text = accumulated_text

def parse_retry_delay(error_msg: str) -> float:
    match = re.search(r'(?:retry|try again) in ([\d\.]+)\s*(?:s|second)', error_msg, re.IGNORECASE)
    if match:
        return float(match.group(1))
    match2 = re.search(r'([\d\.]+)\s*(?:s|second|min|minute)', error_msg, re.IGNORECASE)
    if match2:
        val = float(match2.group(1))
        if 'min' in error_msg.lower():
            val *= 60
        return val
    return 60.0

# ─────────────────────────────────────────────────────────────────────────────
# Job 1 – Scan + classify  (delegates entirely to main.py & agents)
# ─────────────────────────────────────────────────────────────────────────────

from crew.momentum_tool import MomentumBackboneTool
from crew.stock_discovery_agents import process_tickers_batch

def job_scan_and_classify(category: str = "Nifty100"):
    """
    Runs the discovery crew from main.py, then saves results to persistence.py.
    No crew logic here — just orchestration.
    """
    log.info("=== JOB 1: Momentum scan + classification (via scheduler.py) ===")
    try:
        # Run quantitative MomentumBackboneTool directly to get candidate list
        tool = MomentumBackboneTool()
        scout_text = tool._run(category=category, top_n=20)
        scan_rows = _parse_scan_rows(scout_text)

        if not scan_rows:
            log.error("No scan rows parsed — skipping DB save. Check scout output above.")
            raise ValueError("No stock scan rows could be parsed from the scanner output. Please check the logs.")

        run_id = DB.save_scan(category=category, results=scan_rows, top_n=20)
        
        tickers = [row["Symbol"] for row in scan_rows]
        batches = [tickers[i:i+5] for i in range(0, len(tickers), 5)]
        
        accumulated_text = ""
        picks = []
        
        for batch_index, batch in enumerate(batches):
            try:
                batch_analyst_text = process_tickers_batch(batch)
                if accumulated_text:
                    accumulated_text += "\n---\n" + batch_analyst_text
                else:
                    accumulated_text = batch_analyst_text
                
                batch_picks = _parse_picks(batch_analyst_text)
                picks.extend(batch_picks)
                
                # Save picks incrementally
                DB.save_picks(run_id, batch_picks)
                
            except Exception as e:
                # Calculate remaining tickers (current batch + subsequent ones)
                remaining = []
                for b in batches[batch_index:]:
                    remaining.extend(b)
                
                # Save partial report
                DB.save_scan_report(run_id, category, scout_text, accumulated_text, report_type="SCOUT")
                
                raise RateLimitScanError(
                    message=f"Rate limit hit during batch {batch_index+1}: {str(e)}",
                    run_id=run_id,
                    tickers=remaining,
                    scout_raw=scout_text,
                    accumulated_text=accumulated_text
                )
                
        # Save final complete report
        DB.save_scan_report(run_id, category, scout_text, accumulated_text, report_type="SCOUT")
        log.info("Job 1 complete – run_id=%d, %d stocks, %d picks saved",
                 run_id, len(scan_rows), len(picks))

    except RateLimitScanError as rle:
        # Re-raise to let views.py/workers handle retry queueing
        raise rle
    except Exception as exc:
        log.exception("Job 1 failed: %s", exc)
        raise exc


def job_scan_and_classify_remaining(run_id: int, category: str, tickers: list[str], scout_raw: str, accumulated_text: str):
    """
    Worker retry execution for the remaining tickers.
    Processes the remaining tickers in batches of 5.
    Appends new picks to DB and updates the scan report.
    """
    log.info("=== JOB 1 RETRY: Remaining tickers %s ===", tickers)
    try:
        batches = [tickers[i:i+5] for i in range(0, len(tickers), 5)]
        current_accumulated = accumulated_text
        picks = []
        
        for batch_index, batch in enumerate(batches):
            try:
                batch_analyst_text = process_tickers_batch(batch)
                if current_accumulated:
                    current_accumulated += "\n---\n" + batch_analyst_text
                else:
                    current_accumulated = batch_analyst_text
                
                batch_picks = _parse_picks(batch_analyst_text)
                picks.extend(batch_picks)
                
                # Save picks incrementally
                DB.save_picks(run_id, batch_picks)
                
            except Exception as e:
                # Calculate remaining tickers (current batch + subsequent ones)
                remaining = []
                for b in batches[batch_index:]:
                    remaining.extend(b)
                
                # Save partial report
                DB.save_scan_report(run_id, category, scout_raw, current_accumulated, report_type="SCOUT")
                
                raise RateLimitScanError(
                    message=f"Rate limit hit during retry batch {batch_index+1}: {str(e)}",
                    run_id=run_id,
                    tickers=remaining,
                    scout_raw=scout_raw,
                    accumulated_text=current_accumulated
                )
                
        # Save final complete report
        DB.save_scan_report(run_id, category, scout_raw, current_accumulated, report_type="SCOUT")
        log.info("Job 1 Retry complete – run_id=%d, remaining tickers successfully processed", run_id)
        
    except RateLimitScanError as rle:
        raise rle
    except Exception as exc:
        log.exception("Job 1 Retry failed: %s", exc)
        raise exc


def job_portfolio_daily_scan(force: bool = False):
    """
    Scans held portfolio stocks daily in the background.
    """
    log.info("=== DAILY PORTFOLIO BACKGROUND SCAN ===")
    try:
        today_str = datetime.now().strftime("%Y-%m-%d")
        if not force:
            with DB._conn() as con:
                row = con.execute(
                    "SELECT max(run_at) as last_run FROM scan_runs WHERE category='Portfolio'"
                ).fetchone()
                last_run = row['last_run'] if row else None
            if last_run and last_run[:10] == today_str:
                log.info(f"Daily portfolio scan already completed today ({last_run}) – skipping background run.")
                return

        held = DB.held_positions()
        if not held:
            log.info("No open portfolio positions – skipping daily scan.")
            return
        tickers = [p['symbol'] for p in held]
        log.info(f"Running daily analyst scan on portfolio tickers: {tickers}")
        
        # Save a header run record
        run_id = DB.save_scan(category="Portfolio", results=[{"Symbol": t} for t in tickers], top_n=len(tickers))
        
        # Process in batches of 5
        batches = [tickers[i:i+5] for i in range(0, len(tickers), 5)]
        accumulated_text = ""
        for batch in batches:
            batch_text = process_tickers_batch(batch)
            batch_picks = _parse_picks(batch_text)
            DB.save_picks(run_id, batch_picks)
            if accumulated_text:
                accumulated_text += "\n---\n" + batch_text
            else:
                accumulated_text = batch_text
        DB.save_scan_report(run_id, "Portfolio", "Portfolio Daily Scan", accumulated_text, report_type="SCOUT")
        log.info("Daily portfolio background scan complete.")
    except Exception as e:
        log.error(f"Daily portfolio background scan failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Job 2 – Portfolio monitor  (delegates entirely to portfolio_monitor.py)
# ─────────────────────────────────────────────────────────────────────────────

def job_monitor(user_id=None):
    """
    Loads held positions from persistence.py, runs portfolio_monitor.py crew,
    then saves any alerts back to persistence.py.
    No crew logic here — just orchestration.
    """
    import time
    log.info("=== JOB 2: Portfolio monitor (via portfolio_monitor.py) ===")
    
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            held = DB.held_positions(user_id=user_id)
            if not held:
                log.info("No open positions – monitor skipped.")
                return

            # run_monitor() is fully defined in portfolio_monitor.py
            log.info("Running monitor for %d held positions (Attempt %d/%d): %s",
                     len(held), attempt, max_retries, ", ".join(p["symbol"] for p in held))
            report = run_monitor(held)

            # Parse RED alerts and save them
            alerts = _parse_alerts(report)
            if alerts:
                DB.save_alerts(alerts, user_id=user_id)
                
            red = [a for a in alerts if a["alert_level"] == "RED"]
            if red:
                log.warning("RED ALERTS: %s", ", ".join(a["symbol"] for a in red))
            else:
                log.info("Job 2 complete – no RED alerts.")
            return # Successful
            
        except Exception as exc:
            error_msg = str(exc)
            is_rate_limit = "RESOURCE_EXHAUSTED" in error_msg or "rate_limit" in error_msg.lower() or "429" in error_msg
            if is_rate_limit and attempt < max_retries:
                delay = parse_retry_delay(error_msg)
                log.warning("Rate limit hit during portfolio monitor. Retrying in %.1fs (Attempt %d/%d)...", delay, attempt, max_retries)
                time.sleep(delay)
            else:
                log.exception("Job 2 failed: %s", exc)
                if attempt == max_retries:
                    raise exc


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

    import re
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
            
        # Parse potential key-value pair
        if ":" in line:
            parts = line.split(":", 1)
            raw_key = parts[0].strip()
            # Clean key of markdown bullets (*, -, +) and bold formatting
            cleaned_key = re.sub(r'^[-*+\s]+', '', raw_key)
            cleaned_key = cleaned_key.replace("*", "").strip().upper()
            
            value = parts[1].strip()
            # Clean value of leading/trailing quotes or asterisks if any
            value = re.sub(r'^["\'*_\s]+|["\'*_\s]+$', '', value)
            
            if cleaned_key == "SYMBOL":
                if current.get("symbol"):       # save previous block first
                    picks.append(current)
                current = {"symbol": value}
                continue
                
            for label, key in field_map.items():
                if cleaned_key == label:
                    if key == "confidence":
                        try:
                            # Extract first digit from confidence (e.g. "4 out of 5" -> 4)
                            conf_match = re.search(r'\d', value)
                            value = int(conf_match.group(0)) if conf_match else None
                        except (ValueError, IndexError):
                            value = None
                    current[key] = value
                    break

    if current.get("symbol"):               # save the final block
        picks.append(current)
    return picks

def _parse_alerts(text: str) -> list[dict]:
    alerts: list[dict] = []
    current: dict = {}
    active_key = None  # Tracks the field we are currently appending to

    # Mapping logic for headers
    # We use a dictionary to easily identify which header is being read
    field_map = {
        "SYMBOL": "symbol",
        "ALERT": "alert_level",
        "CONFIDENCE": "confidence",
        "TRIGGER SUMMARY": "trigger",
        "RECOMMENDED ACTION": "action",
        "RISK FLAGS": "risk_flags",
        "NEWS STORIES CONSIDERED": "raw_news",
    }

    import re
    for line in text.splitlines():
        # 1. Clean line
        clean_line = line.replace("|", "").replace("═", "").strip()
        if not clean_line:
            continue

        # Clean line of markdown bullets and bold symbols on the left for header checking
        cleaned_header_candidate = re.sub(r'^[-*+\s]+', '', clean_line)
        cleaned_header_candidate = cleaned_header_candidate.replace("*", "").strip()

        # 2. Check if this line is a Header
        # We normalise the line to handle aliases, then check if it starts with one of our known keys
        norm_line = _normalise(cleaned_header_candidate).upper()
        
        found_header = None
        for header, key in field_map.items():
            if norm_line.startswith(header):
                found_header = key
                break
        
        if found_header:
            active_key = found_header
            # If the header contains the value on the same line (e.g. "SYMBOL: INFY.NS")
            if ":" in cleaned_header_candidate:
                val = cleaned_header_candidate.split(":", 1)[1].strip()
                
                # Clean value of markdown bold and quotes
                val = val.replace("*", "").strip()
                val = re.sub(r'^["\'_]+|["\'_]+$', '', val)
                
                # Special handling for ALERT: clean the emoji immediately
                if active_key == "alert_level":
                    val = clean_text(val)
                
                # If we encounter a new SYMBOL header, save the previous record
                if active_key == "symbol" and "symbol" in current:
                    alerts.append(current)
                    current = {}
                
                current[active_key] = val
            
            # If header is on its own line (e.g. "TRIGGER SUMMARY:"), 
            # we just initialized the active_key, so we wait for content on the next iteration
            continue

        # 3. Accumulate content if not a header
        else:
            # Clean markdown bold/bullets from the line content
            line_val = clean_line.replace("*", "").strip()
            line_val = re.sub(r'^[-+]+', '', line_val).strip() # remove bullet characters
            if not line_val:
                continue

            if active_key and active_key in current:
                # Append multi-line content to the existing value
                current[active_key] += f" {line_val}"
            elif active_key:
                # First line of content for a header that didn't have value on same line
                current[active_key] = line_val

    # Append the final record
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
        CronTrigger(day_of_week="mon", hour=8, minute=15, timezone=IST),
        id="scan_classify",
        name="Weekly index scan + classify (main.py)",
        misfire_grace_time=300,
    )

    scheduler.add_job(
        job_portfolio_daily_scan,
        CronTrigger(day_of_week="mon-fri", hour=8, minute=30, timezone=IST),
        id="portfolio_daily_scan",
        name="Daily portfolio analyst scan",
        misfire_grace_time=300,
    )

    scheduler.add_job(
        job_monitor,
        CronTrigger(day_of_week="mon-fri", hour=8, minute=45, timezone=IST),
        id="monitor",
        name="Portfolio monitor (portfolio_monitor.py)",
        misfire_grace_time=300,
    )

    log.info("Scheduler started — weekly index scan Mon at 08:15, daily portfolio scan at 08:30, and monitor at 08:45 IST.")
    log.info("Press Ctrl+C to stop.")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        log.info("Scheduler stopped.")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

import argparse
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
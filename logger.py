"""
logger.py  –  Centralised logging for the Momentum Portfolio System.

Usage
─────
  from logger import get_logger
  log = get_logger(__name__)
  log.info("something happened")

Entry point detection
─────────────────────
  Called from scheduler.py   →  writes to momentum_scheduler.log
  Called from dashboard.py   →  writes to momentum_dashboard.log
  Called from anywhere else  →  writes to momentum.log

All log files live in momentum_tracker/mps_cache/.
All entry points share the same format and level.
Internal modules (momentum_tracker/src/) replace print() with get_logger(__name__).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Log directory
# ─────────────────────────────────────────────────────────────────────────────

_CACHE_DIR = Path(__file__).resolve().parent / "momentum_tracker" / "mps_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# Detect entry point → choose log file name
# ─────────────────────────────────────────────────────────────────────────────

def _detect_log_file() -> Path:
    """
    Inspect sys.argv[0] to decide which log file to write to.
    This runs once at import time.
    """
    entry = Path(sys.argv[0]).stem.lower() if sys.argv else ""

    if "scheduler" in entry:
        return _CACHE_DIR / "momentum_scheduler.log"
    elif "dashboard" in entry or "streamlit" in entry:
        return _CACHE_DIR / "momentum_dashboard.log"
    else:
        return _CACHE_DIR / "momentum.log"


_LOG_FILE = _detect_log_file()

# ─────────────────────────────────────────────────────────────────────────────
# Root logger — configured once, shared by all modules
# ─────────────────────────────────────────────────────────────────────────────

_FORMAT  = "%(asctime)s  %(levelname)-8s  [%(name)s]  %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

def _setup_root_logger() -> None:
    """Configure the root logger exactly once."""
    root = logging.getLogger()
    if root.handlers:
        return   # already configured — don't add duplicate handlers

    root.setLevel(logging.INFO)

    # File handler — UTF-8 so Unicode symbols don't crash on Windows
    fh = logging.FileHandler(_LOG_FILE, encoding="utf-8")
    fh.setFormatter(logging.Formatter(_FORMAT, _DATEFMT))
    root.addHandler(fh)

    # Console handler — UTF-8 safe on Windows
    try:
        stream = open(sys.stdout.fileno(), mode="w", encoding="utf-8", closefd=False)
    except Exception:
        stream = sys.stdout
    ch = logging.StreamHandler(stream)
    ch.setFormatter(logging.Formatter(_FORMAT, _DATEFMT))
    root.addHandler(ch)


_setup_root_logger()

# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger.  Call this at the top of every module:

        from logger import get_logger
        log = get_logger(__name__)
    """
    return logging.getLogger(name)


def get_log_file() -> Path:
    """Return the active log file path (useful for the dashboard log viewer)."""
    return _LOG_FILE
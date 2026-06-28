"""
db_config.py  –  Database provider configuration.

This is the ONLY file you change when switching between SQLite and
PostgreSQL.  Set the environment variable DB_TYPE before launching:

  SQLite (default — no setup needed):
    DB_TYPE=sqlite                   # or just don't set it
    SQLITE_PATH=/optional/custom/path/momentum.db   # optional override

  PostgreSQL (for cloud / production deployment):
    DB_TYPE=postgresql
    DATABASE_URL=postgresql://user:password@host:5432/momentum
      — OR —
    PG_HOST=localhost
    PG_PORT=5432
    PG_DATABASE=momentum
    PG_USER=postgres
    PG_PASSWORD=secret

  Render / Railway / Heroku: they set DATABASE_URL automatically when
  you provision a Postgres addon — just set DB_TYPE=postgresql and
  everything else is wired up.

Usage
─────
  from db_config import get_db
  DB = get_db()      # returns SQLiteDatabase or PostgreSQLDatabase

  # In persistence.py and dashboard imports, DB comes from here —
  # you never import the concrete class directly.
"""

from __future__ import annotations

import os
from pathlib import Path

from config import Config
from .db_interface import DatabaseInterface

# 1. Dynamically resolve the project root.
# __file__ is the path to db_config.py (momentum_tracker/src/core/db_config.py)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# Resolve absolute path of config.json in momentum_tracker/
_pkg = Path(__file__).resolve().parent.parent.parent # momentum_tracker/
config_file = _pkg / "config.json"
config = Config(str(config_file) if config_file.exists() else "config.json")

# ─────────────────────────────────────────────────────────────────────────────
# Config values (all read from environment or config.json — safe for cloud deployment)
# ─────────────────────────────────────────────────────────────────────────────

class DBConfig:
    """
    Central config for the database layer.

    All values come from environment variables or config.json so you never hard-code
    credentials in source code.
    """

    # ── Provider selection ────────────────────────────────────────────────────
    DB_TYPE: str = os.getenv("DB_TYPE", "sqlite").lower()
    # Valid values: "sqlite" | "postgresql"
    
    DEFAULT_SQLITE_PATH = config.get("SYSTEM_CONFIG", {}).get(
        "SQLITE_PATH", 
        str(PROJECT_ROOT / "data_cache" / "momentum.db")
    )
    
    SQLITE_PATH = os.getenv("SQLITE_PATH", DEFAULT_SQLITE_PATH)

    # ── PostgreSQL settings ───────────────────────────────────────────────────
    PG_URL:      str | None = os.getenv("DATABASE_URL")
    PG_HOST:     str        = os.getenv("PG_HOST",     "localhost")
    PG_PORT:     int        = int(os.getenv("PG_PORT", "5432"))
    PG_DATABASE: str        = os.getenv("PG_DATABASE", "momentum")
    PG_USER:     str        = os.getenv("PG_USER",     "postgres")
    PG_PASSWORD: str        = os.getenv("PG_PASSWORD", "")

    @classmethod
    def pg_connect_kwargs(cls) -> dict:
        """
        Return the kwargs needed for psycopg2.connect().
        Prefers DATABASE_URL (single string) over individual params.
        """
        if cls.PG_URL:
            return {"dsn": cls.PG_URL}
        return {
            "host":     cls.PG_HOST,
            "port":     cls.PG_PORT,
            "dbname":   cls.PG_DATABASE,
            "user":     cls.PG_USER,
            "password": cls.PG_PASSWORD,
        }

    @classmethod
    def summary(cls) -> str:
        """Human-readable summary of active config (safe to log — no passwords)."""
        if cls.DB_TYPE == "postgresql":
            target = cls.PG_URL.split("@")[-1] if cls.PG_URL else f"{cls.PG_HOST}:{cls.PG_PORT}/{cls.PG_DATABASE}"
            return f"postgresql → {target}"
        return f"sqlite → {cls.SQLITE_PATH}"


# ─────────────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────────────

def get_db() -> DatabaseInterface:
    """
    Return the correct database backend based on DBConfig.DB_TYPE.
    """
    db_type = DBConfig.DB_TYPE

    if db_type == "postgresql":
        from .persistence_postgresql import PostgreSQLDatabase
        db = PostgreSQLDatabase(DBConfig)
        db.init()
        return db

    if db_type == "sqlite":
        from .persistence import SQLiteDatabase
        db = SQLiteDatabase(DBConfig)
        db.init()
        return db

    raise ValueError(
        f"Unknown DB_TYPE='{db_type}'. "
        "Valid values: 'sqlite' | 'postgresql'."
    )

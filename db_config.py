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

from db_interface import DatabaseInterface


# ─────────────────────────────────────────────────────────────────────────────
# Config values (all read from environment — safe for cloud deployment)
# ─────────────────────────────────────────────────────────────────────────────

class DBConfig:
    """
    Central config for the database layer.

    All values come from environment variables so you never hard-code
    credentials in source code.  A .env file (loaded by python-dotenv
    in llm_config.py) works fine for local development.

    To switch providers:
        1. Set DB_TYPE=postgresql in your .env or shell
        2. Set DATABASE_URL (or individual PG_* vars)
        3. Restart — no code changes required anywhere else
    """

    # ── Provider selection ────────────────────────────────────────────────────
    DB_TYPE: str = os.getenv("DB_TYPE", "sqlite").lower()
    # Valid values: "sqlite" | "postgresql"

    # ── SQLite settings ───────────────────────────────────────────────────────
    # Default path mirrors the existing persistence.py behaviour.
    # Override with SQLITE_PATH env var if needed.
    SQLITE_PATH: Path = Path(
        os.getenv(
            "SQLITE_PATH",
            str(
                Path(__file__).resolve().parent
                / "momentum_tracker"
                / "mps_cache"
                / "momentum.db"
            ),
        )
    )

    # ── PostgreSQL settings ───────────────────────────────────────────────────
    # Render / Railway / Heroku set DATABASE_URL automatically.
    # For local Docker or manual setup, use the individual PG_* vars.
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

    Called once at import time by persistence.py:

        DB = get_db()

    All other modules import DB from persistence.py — they never call
    get_db() directly, so switching providers requires zero changes there.
    """
    db_type = DBConfig.DB_TYPE

    if db_type == "postgresql":
        from persistence_postgresql import PostgreSQLDatabase
        db = PostgreSQLDatabase(DBConfig)
        db.init()
        return db

    if db_type == "sqlite":
        from persistence import SQLiteDatabase
        db = SQLiteDatabase(DBConfig)
        db.init()
        return db

    raise ValueError(
        f"Unknown DB_TYPE='{db_type}'. "
        "Valid values: 'sqlite' | 'postgresql'. "
        "Check your .env file or environment variables."
    )

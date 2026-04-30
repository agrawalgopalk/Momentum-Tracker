"""
core  –  Infrastructure layer: database, logging, utilities.
No CrewAI or LLM dependencies. Safe to import anywhere.
"""

from core.db_config import get_db, DBConfig
from core.db_interface import DatabaseInterface

__all__ = [
    "get_db", 
    "DBConfig",
    "DatabaseInterface",
]
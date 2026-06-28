"""
core  –  Infrastructure database services layer.
No CrewAI or LLM dependencies. Safe to import anywhere.
"""

from .db_config import get_db, DBConfig
from .db_interface import DatabaseInterface

__all__ = [
    "get_db", 
    "DBConfig",
    "DatabaseInterface",
]

"""
fii_dii_provider.py – Core module to fetch, store, and query FII/DII institutional flows and holdings.
Integrates stock-level shareholdings and sector-level index aggregate structures.
"""

from __future__ import annotations

import sqlite3
import time
import requests
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import pandas as pd
from io import StringIO

logger = logging.getLogger(__name__)

from config import Config
# Resolve absolute path of config.json in momentum_tracker/
_pkg = Path(__file__).resolve().parent.parent # momentum_tracker/
config_file = _pkg / "config.json"
config = Config(str(config_file) if config_file.exists() else "config.json")

# Single source of truth for the DB path (read from config settings)
_root = Path(__file__).resolve().parent.parent.parent # Momentum-Tracker/
DB_PATH = Path(config.get("SYSTEM_CONFIG", {}).get("SQLITE_PATH", str(_root / "data_cache" / "momentum.db")))

# Nifty Sector mappings
SECTOR_INDICES = {
    "IT":           "NIFTY IT",
    "BANK":         "NIFTY BANK",
    "AUTO":         "NIFTY AUTO",
    "PHARMA":       "NIFTY PHARMA",
    "FMCG":         "NIFTY FMCG",
    "METAL":        "NIFTY METAL",
    "REALTY":       "NIFTY REALTY",
    "ENERGY":       "NIFTY ENERGY",
    "INFRASTRUCTURE": "NIFTY INFRASTRUCTURE",
    "FINANCIAL":    "NIFTY FINANCIAL SERVICES",
    "MEDIA":        "NIFTY MEDIA",
    "PSU BANK":     "NIFTY PSU BANK",
    "HEALTHCARE":   "NIFTY HEALTHCARE INDEX",
    "CONSUMER DURABLES": "NIFTY CONSUMER DURABLES",
    "OIL & GAS":    "NIFTY OIL AND GAS",
}

# ─── Database setup ────────────────────────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_database():
    """Create FII/DII database schemas."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Aggregate FII/DII provisional daily flows
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fii_dii_aggregate (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            DATE NOT NULL,
            category        TEXT NOT NULL,        -- 'FII/FPI' or 'DII'
            buy_value_cr    REAL DEFAULT 0,
            sell_value_cr   REAL DEFAULT 0,
            net_value_cr    REAL DEFAULT 0,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, category)
        )
    """)
    
    # Stock holdings quarterly patterns
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_holdings (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol          TEXT NOT NULL,
            quarter         TEXT NOT NULL,
            promoter_pct    REAL DEFAULT 0,
            fii_pct         REAL DEFAULT 0,
            dii_pct         REAL DEFAULT 0,
            public_pct      REAL DEFAULT 0,
            other_pct       REAL DEFAULT 0,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(symbol, quarter)
        )
    """)
    
    # Sector constituents stocks cache
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sector_stocks (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol              TEXT NOT NULL,
            company_name        TEXT,
            sector_index        TEXT NOT NULL,
            last_price          REAL,
            pchange             REAL,
            total_traded_volume REAL,
            total_traded_value  REAL,
            snapshot_date       DATE NOT NULL,
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(symbol, sector_index, snapshot_date)
        )
    """)

    conn.commit()
    conn.close()

# Initialize DB on import
init_database()

# ─── NSE Session & API Fetchers ───────────────────────────────────────────────

def get_nse_session() -> requests.Session:
    """Create a session mimicking a standard web browser for NSE."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.nseindia.com/reports/fii-dii",
        "Connection": "keep-alive",
    })
    try:
        session.get("https://www.nseindia.com", timeout=10)
        time.sleep(1)
        session.get("https://www.nseindia.com/reports/fii-dii", timeout=10)
        time.sleep(1)
    except Exception as e:
        logger.warning(f"Failed warming up NSE session: {e}")
    return session

def fetch_shareholder_pattern(symbol: str) -> pd.DataFrame:
    """Fetch quarterly FII/DII/Promoter shareholding weights for a stock."""
    session = get_nse_session()
    url = f"https://www.nseindia.com/api/corporate-share-holdings-master?symbol={symbol.upper()}&corpType=share&market=equities"
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        rows = []
        for quarter_data in (data if isinstance(data, list) else data.get("data", [])):
            quarter = quarter_data.get("period", "")
            holders = quarter_data.get("shareHolderList", [])
            row = {"quarter": quarter, "symbol": symbol.upper()}
            for holder in holders:
                category = holder.get("shareHolderName", "").strip()
                pct = holder.get("shareHoldingPercentage", 0)
                row[category] = float(pct or 0)
            rows.append(row)
        
        return pd.DataFrame(rows)
    except Exception as e:
        logger.error(f"Error fetching shareholding pattern for {symbol}: {e}")
        return pd.DataFrame()

def fetch_sector_constituents(index_name: str) -> pd.DataFrame:
    """Fetch constituent stocks of a Nifty sector index."""
    session = get_nse_session()
    encoded = requests.utils.quote(index_name)
    url = f"https://www.nseindia.com/api/equity-stockIndices?index={encoded}"
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        rows = []
        for stock in data.get("data", []):
            if stock.get("symbol") == index_name:
                continue
            rows.append({
                "symbol": stock.get("symbol", ""),
                "company_name": stock.get("meta", {}).get("companyName", stock.get("symbol", "")),
                "sector": index_name,
                "last_price": stock.get("lastPrice", 0),
                "pchange": stock.get("pChange", 0),
                "total_traded_volume": stock.get("totalTradedVolume", 0),
                "total_traded_value": stock.get("totalTradedValue", 0),
            })
        return pd.DataFrame(rows)
    except Exception as e:
        logger.error(f"Error fetching constituents for sector {index_name}: {e}")
        return pd.DataFrame()

# ─── Database Operations ──────────────────────────────────────────────────────

def upsert_stock_holdings(symbol: str, df: pd.DataFrame) -> int:
    """Write shareholding patterns to SQLite database."""
    if df.empty:
        return 0
    conn = get_connection()
    saved = 0
    for _, row in df.iterrows():
        try:
            # Map column categories to standard names
            promoter = row.get("Promoter & Promoter Group", 0)
            fii = row.get("Foreign Portfolio Investor (FII/FPI)", row.get("FII/FPI", row.get("FII", 0)))
            dii = row.get("Mutual Funds/ UTI", 0) + row.get("Financial Institutions/ Banks", 0) + row.get("Insurance Companies", 0)
            public = row.get("Public", 0)
            other = 100.0 - (promoter + fii + dii + public)

            conn.execute("""
                INSERT OR REPLACE INTO stock_holdings 
                    (symbol, quarter, promoter_pct, fii_pct, dii_pct, public_pct, other_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol.upper(),
                str(row.get("quarter", "")),
                float(promoter),
                float(fii),
                float(dii),
                float(public),
                float(other)
            ))
            saved += 1
        except Exception as e:
            logger.warning(f"Error saving holdings row: {e}")
    conn.commit()
    conn.close()
    return saved

# ─── Public Query APIs ─────────────────────────────────────────────────────────

def get_stock_fii_dii(symbol: str) -> Dict[str, Any]:
    """
    Get FII/DII shareholding patterns for a specific stock.
    Automatically fetches live data if database record is missing.
    """
    symbol = symbol.strip().upper()
    if "." in symbol:
        symbol = symbol.split(".")[0]
        
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT quarter, promoter_pct, fii_pct, dii_pct, public_pct 
        FROM stock_holdings 
        WHERE symbol = ? 
        ORDER BY quarter DESC LIMIT 1
    """, (symbol,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "symbol": symbol,
            "quarter": row["quarter"],
            "promoter": row["promoter_pct"],
            "fii": row["fii_pct"],
            "dii": row["dii_pct"],
            "public": row["public_pct"]
        }
        
    # Fetch live from NSE API
    logger.info(f"FII/DII holdings not in DB for {symbol}. Fetching live...")
    df = fetch_shareholder_pattern(symbol)
    if not df.empty:
        upsert_stock_holdings(symbol, df)
        # Re-query
        return get_stock_fii_dii(symbol)
        
    return {
        "symbol": symbol,
        "quarter": "N/A",
        "promoter": 0.0,
        "fii": 0.0,
        "dii": 0.0,
        "public": 0.0
    }

def get_sector_fii_dii(sector_name: str) -> Dict[str, Any]:
    """
    Get average FII/DII patterns for a sector.
    Returns sector aggregates and top holdings.
    """
    sector_key = sector_name.strip().upper()
    index_name = SECTOR_INDICES.get(sector_key)
    if not index_name:
        # Check if they passed NIFTY IT instead of IT
        if sector_key in SECTOR_INDICES.values():
            index_name = sector_key
        else:
            return {"sector": sector_name, "error": f"Unknown sector: {sector_name}"}

    # Fetch live constituents
    logger.info(f"Fetching constituents for index: {index_name}")
    const_df = fetch_sector_constituents(index_name)
    if const_df.empty:
        return {"sector": index_name, "error": "Failed to fetch constituents."}

    results = []
    # Query or load FII/DII holdings for each constituent
    for _, row in const_df.head(15).iterrows():  # Limit to top 15 constituents to keep it fast
        sym = row["symbol"]
        holdings = get_stock_fii_dii(sym)
        if holdings["quarter"] != "N/A":
            results.append(holdings)

    if not results:
        return {"sector": index_name, "error": "No holdings data could be resolved."}

    df_holdings = pd.DataFrame(results)
    
    # Calculate sector average percentages
    avg_fii = float(df_holdings["fii"].mean())
    avg_dii = float(df_holdings["dii"].mean())
    avg_prom = float(df_holdings["promoter"].mean())

    # Get top 3 holdings by FII percentage
    top_fii = (
        df_holdings.sort_values("fii", ascending=False)
        .head(3)[["symbol", "fii", "dii", "quarter"]]
        .to_dict("records")
    )

    return {
        "sector": index_name,
        "constituents_analyzed": len(df_holdings),
        "average_promoter_pct": round(avg_prom, 2),
        "average_fii_pct": round(avg_fii, 2),
        "average_dii_pct": round(avg_dii, 2),
        "top_fii_holdings": top_fii
    }

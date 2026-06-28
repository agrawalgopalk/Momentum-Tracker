import os
import sqlite3
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from data.fii_dii_provider import (
    DB_PATH, get_connection, init_database, get_stock_fii_dii, get_sector_fii_dii
)

# Use a temporary test database during testing to prevent altering production data
TEST_DB_PATH = "test_fii_dii_data.db"

@pytest.fixture(autouse=True)
def setup_test_db():
    # Override DB_PATH for tests
    with patch("data.fii_dii_provider.DB_PATH", TEST_DB_PATH):
        # Create test DB and schemas
        init_database()
        
        yield
        
        # Clean up test DB after tests complete
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except OSError:
                pass

def test_init_database():
    with patch("data.fii_dii_provider.DB_PATH", TEST_DB_PATH):
        conn = sqlite3.connect(TEST_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cursor.fetchall()]
        conn.close()
        
        assert "fii_dii_aggregate" in tables
        assert "stock_holdings" in tables
        assert "sector_stocks" in tables

def test_get_stock_fii_dii_cached():
    with patch("data.fii_dii_provider.DB_PATH", TEST_DB_PATH):
        conn = sqlite3.connect(TEST_DB_PATH)
        # Seed test database with a stock holding pattern
        conn.execute("""
            INSERT INTO stock_holdings 
                (symbol, quarter, promoter_pct, fii_pct, dii_pct, public_pct, other_pct)
            VALUES ('INFY', 'Dec 2025', 34.50, 18.50, 12.30, 34.00, 0.70)
        """)
        conn.commit()
        conn.close()

        # Call get_stock_fii_dii (should return cached data without calling API)
        with patch("data.fii_dii_provider.fetch_shareholder_pattern") as mock_fetch:
            data = get_stock_fii_dii("INFY")
            assert data["symbol"] == "INFY"
            assert data["quarter"] == "Dec 2025"
            assert data["fii"] == 18.50
            assert data["dii"] == 12.30
            mock_fetch.assert_not_called()

def test_get_stock_fii_dii_uncached():
    with patch("data.fii_dii_provider.DB_PATH", TEST_DB_PATH):
        # Create fake API dataframe response
        fake_df = pd.DataFrame([{
            "quarter": "Sep 2025",
            "symbol": "INFY",
            "Promoter & Promoter Group": 34.50,
            "Foreign Portfolio Investor (FII/FPI)": 20.00,
            "Mutual Funds/ UTI": 10.00,
            "Financial Institutions/ Banks": 2.00,
            "Insurance Companies": 3.00,
            "Public": 30.50
        }])

        with patch("data.fii_dii_provider.fetch_shareholder_pattern", return_value=fake_df) as mock_fetch:
            data = get_stock_fii_dii("INFY")
            
            assert data["symbol"] == "INFY"
            assert data["quarter"] == "Sep 2025"
            # FII: 20.0
            assert data["fii"] == 20.00
            # DII: Mutual Funds (10.0) + Financial Inst (2.0) + Insurance (3.0) = 15.0
            assert data["dii"] == 15.00
            
            mock_fetch.assert_called_once_with("INFY")
            
            # Verify DB was cached
            conn = sqlite3.connect(TEST_DB_PATH)
            row = conn.execute("SELECT * FROM stock_holdings WHERE symbol='INFY'").fetchone()
            conn.close()
            assert row is not None
            assert row[4] == 20.00 # fii_pct

def test_get_sector_fii_dii():
    with patch("data.fii_dii_provider.DB_PATH", TEST_DB_PATH):
        # Fake sector constituents
        fake_const = pd.DataFrame([
            {"symbol": "INFY", "company_name": "Infosys", "sector": "NIFTY IT"},
            {"symbol": "TCS", "company_name": "TCS", "sector": "NIFTY IT"}
        ])
        
        # Mock fetch_sector_constituents and get_stock_fii_dii calls
        with patch("data.fii_dii_provider.fetch_sector_constituents", return_value=fake_const), \
             patch("data.fii_dii_provider.get_stock_fii_dii") as mock_get_stock:
                 
            mock_get_stock.side_effect = lambda sym: {
                "symbol": sym,
                "quarter": "Dec 2025",
                "promoter": 40.0,
                "fii": 20.0 if sym == "INFY" else 30.0,
                "dii": 15.0 if sym == "INFY" else 10.0,
                "public": 25.0
            }
            
            sector_data = get_sector_fii_dii("IT")
            
            assert sector_data["sector"] == "NIFTY IT"
            assert sector_data["constituents_analyzed"] == 2
            # Average FII: (20.0 + 30.0) / 2 = 25.0
            assert sector_data["average_fii_pct"] == 25.0
            # Average DII: (15.0 + 10.0) / 2 = 12.5
            assert sector_data["average_dii_pct"] == 12.5
            
            # Top FII holdings
            top_fii = sector_data["top_fii_holdings"]
            assert len(top_fii) == 2
            assert top_fii[0]["symbol"] == "TCS"
            assert top_fii[0]["fii"] == 30.0
            assert top_fii[1]["symbol"] == "INFY"
            assert top_fii[1]["fii"] == 20.0

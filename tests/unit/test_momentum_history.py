import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock, patch
from strategy.technical_indicators import TechnicalIndicators as TI
from portfolio.portfolio_manager import PortfolioManager

def _make_dummy_df(size: int = 100) -> pd.DataFrame:
    dates = pd.date_range(start="2026-01-01", periods=size, freq="D")
    prices = np.linspace(100, 200, size)
    return pd.DataFrame({
        "open": prices * 0.99,
        "high": prices * 1.01,
        "low": prices * 0.98,
        "close": prices,
        "volume": np.random.randint(1000, 5000, size)
    }, index=dates)

def test_series_rsi():
    df = _make_dummy_df(50)
    rsi_s = TI.rsi_series(df, period=14)
    assert isinstance(rsi_s, pd.Series)
    assert len(rsi_s) == len(df)
    assert not np.isnan(rsi_s.iloc[-1])
    assert rsi_s.iloc[-1] > 50

def test_series_mfi():
    df = _make_dummy_df(50)
    mfi_s = TI.mfi_series(df, period=14)
    assert isinstance(mfi_s, pd.Series)
    assert len(mfi_s) == len(df)
    assert not np.isnan(mfi_s.iloc[-1])

def test_series_cci():
    df = _make_dummy_df(50)
    cci_s = TI.cci_series(df, period=20)
    assert isinstance(cci_s, pd.Series)
    assert len(cci_s) == len(df)
    assert not np.isnan(cci_s.iloc[-1])

def test_series_weighted_roc():
    df = _make_dummy_df(80)
    roc_s = TI.weighted_roc_composite_series(df, [60, 40, 20], [0.35, 0.40, 0.25])
    assert isinstance(roc_s, pd.Series)
    assert len(roc_s) == len(df)
    assert not np.isnan(roc_s.iloc[-1])

def test_series_rs_ratio():
    stock_df = _make_dummy_df(100)
    bench_df = _make_dummy_df(100)
    rs_s = TI.rs_ratio_series(stock_df, bench_df, lookback=55)
    assert isinstance(rs_s, pd.Series)
    assert len(rs_s) == len(stock_df)

def test_series_pmom():
    df = _make_dummy_df(300)
    pmom_s = TI.price_momentum_composite_series(df)
    assert isinstance(pmom_s, pd.Series)
    assert len(pmom_s) == len(df)
    assert not np.isnan(pmom_s.iloc[-1])

@patch("portfolio.portfolio_manager.get_db")
@patch("portfolio.portfolio_manager.PortfolioService")
def test_empty_portfolio_history(mock_portfolio_service, mock_get_db):
    # Mocking PortfolioManager construction
    config_dict = {
        "SYSTEM_CONFIG": {
            "REBALANCE_HISTORY_DIR": "Rebalance_history"
        },
        "DATA_CONFIG": {
            "DEFAULT_CATEGORY": "Nifty500",
            "INDEX_BENCHMARK": "^NSEI"
        }
    }
    mock_config = MagicMock()
    mock_config.__getitem__.side_effect = lambda k: config_dict[k]
    mock_config.get.side_effect = lambda k, default=None: config_dict.get(k, default)

    mock_db = MagicMock()
    mock_get_db.return_value = mock_db
    mock_strategy = MagicMock()
    
    # Return empty holdings
    mock_service_instance = MagicMock()
    mock_service_instance.get_holdings.return_value = {}
    mock_portfolio_service.return_value = mock_service_instance

    pm = PortfolioManager(mock_config, mock_db, mock_strategy)
    history = pm.get_portfolio_momentum_history(days=30)
    
    assert history["dates"] == []
    assert history["portfolio"] == {}
    assert history["sectors"] == {}
    assert history["index"] == []

@patch("portfolio.portfolio_manager.get_db")
@patch("portfolio.portfolio_manager.PortfolioService")
@patch("data.symbol_loader.SymbolLoader.load")
@patch("data.symbol_loader.SymbolLoader.all_symbols")
def test_get_portfolio_momentum_history_caching(mock_all_symbols, mock_load_symbols, mock_portfolio_service, mock_get_db):
    # Mock SymbolLoader returning a very small universe
    mock_load_symbols.return_value = ["RELIANCE.NS"]
    mock_all_symbols.return_value = ["RELIANCE.NS"]

    # Setup holdings
    mock_service_instance = MagicMock()
    mock_service_instance.get_holdings.return_value = {
        "RELIANCE.NS": {
            "symbol": "RELIANCE.NS",
            "shares": 10,
            "avg_cost": 1000.0,
            "date_added": "2026-01-01T00:00:00"
        }
    }
    mock_portfolio_service.return_value = mock_service_instance

    # Mock database
    mock_db = MagicMock()
    mock_get_db.return_value = mock_db
    mock_db.get_sector.side_effect = lambda ticker: "Energy" if ticker == "RELIANCE.NS" else "Index"

    # Create dummy pricing data (at least 90 trading days for indicators to calculate)
    df_rel = _make_dummy_df(90)
    df_bench = _make_dummy_df(90)
    
    def mock_get_price(ticker):
        if ticker == "RELIANCE.NS":
            return df_rel
        elif ticker == "^NSEI":
            return df_bench
        return None
    mock_db.get_price.side_effect = mock_get_price

    # Mock settings / config
    config_dict = {
        "SYSTEM_CONFIG": {
            "REBALANCE_HISTORY_DIR": "Rebalance_history"
        },
        "DATA_CONFIG": {
            "DEFAULT_CATEGORY": "Nifty500",
            "INDEX_BENCHMARK": "^NSEI"
        },
        "SCORING_WEIGHTS": {
            "WMS_ROC_Composite": 0.60,
            "RSI_Score": 0.05,
            "MFI_Score": 0.20,
            "CCI_Score": 0.15
        },
        "MOMENTUM_CONFIG": {
            "WMS_ROC_PERIODS": [60, 40, 20],
            "WMS_ROC_WEIGHTS": [0.35, 0.40, 0.25],
            "RS_LOOKBACK_DAYS": 55
        }
    }
    mock_config = MagicMock()
    mock_config.__getitem__.side_effect = lambda k: config_dict[k]
    mock_config.get.side_effect = lambda k, default=None: config_dict.get(k, default)

    # Mock strategy
    mock_strategy = MagicMock()
    mock_strategy._composite_value_score.return_value = 50.0

    # Capture saves
    saved_scores = []
    def mock_save_scores(scores):
        saved_scores.extend(scores)
    mock_db.save_momentum_scores.side_effect = mock_save_scores

    # First call: no scores cached (empty)
    # Second call: returns saved scores
    call_count = 0
    def mock_get_scores(symbols, start_date, end_date):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return []
        else:
            return saved_scores
    mock_db.get_momentum_scores.side_effect = mock_get_scores

    # Construct PortfolioManager and call get_portfolio_momentum_history
    pm = PortfolioManager(mock_config, mock_db, mock_strategy)
    history = pm.get_portfolio_momentum_history(days=5)

    # Assertions
    assert len(history["dates"]) == 5
    assert "RELIANCE.NS" in history["portfolio"]
    assert "Energy" in history["sectors"]
    assert len(saved_scores) > 0
    
    # Verify saved scores contain portfolio ticker, benchmark index, and sector Energy
    saved_symbols = {s["symbol"] for s in saved_scores}
    assert "RELIANCE.NS" in saved_symbols
    assert "^NSEI" in saved_symbols
    assert "Energy" in saved_symbols

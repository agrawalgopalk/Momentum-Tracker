import numpy as np
import pandas as pd
import pytest

from strategy.technical_indicators import TechnicalIndicators

# ─────────────────────────────────────────────────────────────────────────────
# Helper to generate dummy price dataframes
# ─────────────────────────────────────────────────────────────────────────────

def _make_dummy_df(size: int = 100, trend: str = "up") -> pd.DataFrame:
    """Generate dummy stock price data for testing."""
    dates = pd.date_range(start="2026-01-01", periods=size, freq="D")
    
    if trend == "up":
        prices = np.linspace(100, 200, size)
    elif trend == "down":
        prices = np.linspace(200, 100, size)
    else:
        prices = np.sin(np.linspace(0, 20, size)) * 10 + 150 # oscillating
        
    df = pd.DataFrame({
        "open": prices * 0.99,
        "high": prices * 1.01,
        "low": prices * 0.98,
        "close": prices,
        "volume": np.random.randint(1000, 5000, size)
    }, index=dates)
    return df

# ─────────────────────────────────────────────────────────────────────────────
# Test Technical Indicators
# ─────────────────────────────────────────────────────────────────────────────

def test_ema():
    df = _make_dummy_df(size=60, trend="up")
    val = TechnicalIndicators.ema(df, period=20)
    assert not np.isnan(val)
    assert val > 100
    
    # Check invalid frame handles NaN
    assert np.isnan(TechnicalIndicators.ema(pd.DataFrame(), period=20))

def test_rsi():
    df = _make_dummy_df(size=30, trend="up")
    val = TechnicalIndicators.rsi(df, period=14)
    assert not np.isnan(val)
    # uptrending price should have high RSI
    assert val > 50
    
    df_down = _make_dummy_df(size=30, trend="down")
    val_down = TechnicalIndicators.rsi(df_down, period=14)
    assert not np.isnan(val_down)
    assert val_down < 50

def test_roc():
    df = _make_dummy_df(size=30, trend="up")
    val = TechnicalIndicators.roc(df, period=10)
    assert not np.isnan(val)
    assert val > 0 # uptrend -> positive rate of change

def test_cci():
    df = _make_dummy_df(size=30, trend="up")
    val = TechnicalIndicators.cci(df, period=20)
    assert not np.isnan(val)

def test_mfi():
    df = _make_dummy_df(size=30, trend="up")
    val = TechnicalIndicators.mfi(df, period=14)
    assert not np.isnan(val)
    assert val > 50

def test_weighted_roc_composite():
    df = _make_dummy_df(size=80, trend="up")
    periods = [60, 40, 20]
    weights = [0.35, 0.40, 0.25]
    val = TechnicalIndicators.weighted_roc_composite(df, periods, weights)
    assert not np.isnan(val)
    assert val > 0

def test_rs_ratio_ma():
    stock_df = _make_dummy_df(size=100, trend="up") # rising faster
    bench_df = _make_dummy_df(size=100, trend="up")
    # Make stock perform better than benchmark
    stock_df["close"] = stock_df["close"] * 2.0
    
    val = TechnicalIndicators.rs_ratio_ma(stock_df, bench_df, lookback=55)
    assert not np.isnan(val)

def test_rs_ratio():
    stock_df = _make_dummy_df(size=100, trend="up")
    bench_df = _make_dummy_df(size=100, trend="up")
    stock_df["close"] = stock_df["close"] * 1.5
    
    val = TechnicalIndicators.rs_ratio(stock_df, bench_df, lookback=55)
    assert not np.isnan(val)

def test_price_momentum_composite():
    df = _make_dummy_df(size=300, trend="up")
    val = TechnicalIndicators.price_momentum_composite(df)
    assert not np.isnan(val)
    assert val > 0

def test_apply_cash_interest():
    # Annual rate 5% for 1 year (365.25 days) on 1000 cash
    val = TechnicalIndicators.apply_cash_interest(cash=1000.0, days=365, annual_rate=0.05)
    # Simple interest formula: cash * (1 + 0.05 * 365/365.25)
    assert round(val, 2) == 1049.97
    
    # Boundary checks
    assert TechnicalIndicators.apply_cash_interest(0.0, 10, 0.05) == 0.0
    assert TechnicalIndicators.apply_cash_interest(1000.0, 0, 0.05) == 1000.0

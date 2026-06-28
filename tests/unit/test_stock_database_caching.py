import shutil
from pathlib import Path
from unittest.mock import MagicMock
import numpy as np
import pandas as pd
import pytest

from config import Config
from data.data_downloader import DataDownloaderBase
from data.stock_database_manager import StockDatabaseManager


class MockDownloader(DataDownloaderBase):
    def __init__(self):
        self.download_single_mock = MagicMock()
        self.download_fundamental_info_mock = MagicMock()

    def download_single(self, ticker, period=None, start=None, end=None):
        return self.download_single_mock(ticker, period=period, start=start, end=end)

    def download_fundamental_info(self, ticker):
        return self.download_fundamental_info_mock(ticker)


@pytest.fixture
def temp_cache_dir():
    cache_path = Path(__file__).resolve().parent.parent / "temp_cache_test"
    if cache_path.exists():
        shutil.rmtree(cache_path)
    cache_path.mkdir(parents=True, exist_ok=True)
    yield cache_path
    if cache_path.exists():
        shutil.rmtree(cache_path)


def test_price_download_failure_caching(temp_cache_dir):
    cfg = Config()
    cfg["DATA_CONFIG"]["MAX_CACHE_DAYS"] = 3
    cfg["DATA_CONFIG"]["DOWNLOAD_HISTORY_YEARS"] = 2  # Only try 2y -> 1y fallback to keep it fast

    downloader = MockDownloader()
    # Downloader returns None to simulate failure
    downloader.download_single_mock.return_value = None

    db_manager = StockDatabaseManager(cfg, downloader, cache_dir=temp_cache_dir)

    ticker = "DELISTED_STOCK"
    # First attempt: should try to download and fail
    result = db_manager.ensure_price(ticker)
    assert result is False
    assert downloader.download_single_mock.call_count == 2  # 2y and 1y period attempts

    # The failure file should now be present on disk
    failed_file = temp_cache_dir / "price" / f"{ticker}.failed"
    assert failed_file.exists()

    # Reset downloader call count
    downloader.download_single_mock.reset_mock()

    # Second attempt: should read from failure cache and return False immediately without calling downloader
    result = db_manager.ensure_price(ticker)
    assert result is False
    downloader.download_single_mock.assert_not_called()


def test_price_download_success_clears_failure_cache(temp_cache_dir):
    cfg = Config()
    downloader = MockDownloader()
    db_manager = StockDatabaseManager(cfg, downloader, cache_dir=temp_cache_dir)

    ticker = "RECOVERED_STOCK"
    failed_file = temp_cache_dir / "price" / f"{ticker}.failed"
    
    # Touch failure file manually to cache failure
    failed_file.touch()
    assert failed_file.exists()

    # Prepare dummy dataframe
    idx = pd.date_range("2026-06-01", periods=5)
    df = pd.DataFrame({"open": [10.0]*5, "high": [11.0]*5, "low": [9.0]*5, "close": [10.0]*5, "volume": [1000]*5}, index=idx)

    # Save to disk using db_manager
    db_manager._save_price_disk(ticker, df)

    # The failure cache file should have been deleted
    assert not failed_file.exists()


def test_fundamental_download_failure_caching(temp_cache_dir):
    cfg = Config()
    downloader = MockDownloader()
    downloader.download_fundamental_info_mock.return_value = {}  # Returns empty dict

    db_manager = StockDatabaseManager(cfg, downloader, cache_dir=temp_cache_dir)

    ticker = "FAILED_FUND"
    # First attempt: downloads and fails
    derived = db_manager.get_fundamental(ticker)
    assert all(val is None for val in derived.values())
    downloader.download_fundamental_info_mock.assert_called_once_with(ticker)

    failed_file = temp_cache_dir / "fundamental" / f"{ticker}_info.failed"
    assert failed_file.exists()

    # Reset downloader call count
    downloader.download_fundamental_info_mock.reset_mock()

    # Second attempt: should skip yfinance download and return empty from failure cache
    derived = db_manager.get_fundamental(ticker)
    assert all(val is None for val in derived.values())
    downloader.download_fundamental_info_mock.assert_not_called()

    # Sector check should also skip download
    sector = db_manager.get_sector(ticker)
    assert sector is None
    downloader.download_fundamental_info_mock.assert_not_called()


def test_fundamental_download_success_clears_failure_cache(temp_cache_dir):
    cfg = Config()
    downloader = MockDownloader()
    db_manager = StockDatabaseManager(cfg, downloader, cache_dir=temp_cache_dir)

    ticker = "OK_FUND"
    failed_file = temp_cache_dir / "fundamental" / f"{ticker}_info.failed"

    # Touch failure file manually
    failed_file.parent.mkdir(parents=True, exist_ok=True)
    failed_file.touch()
    assert failed_file.exists()

    # Save actual fundamentals
    db_manager._save_fund_raw(ticker, {"sector": "Finance", "priceToBook": 1.2})

    # Failure file should be cleared
    assert not failed_file.exists()

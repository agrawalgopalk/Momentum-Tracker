"""
api.py – High-level programmatic API facade for the Momentum Portfolio System.

Exposes standard client methods to trigger calculations, recommendations, precaching,
and rebalancing, designed to be called directly from Django or other client wrappers.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd

# Ensure internal src imports work correctly by prepending src/ to sys.path
_pkg = Path(__file__).resolve().parent
_src = _pkg / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from config import Config
from data.data_downloader import DataDownloaderFactory
from data.stock_database_manager import StockDatabaseManager
from strategy.momentum_strategy import MomentumStrategy
from reporting.report_exporter import ReportExporter
from portfolio.backtest_runner import BacktestRunner
from portfolio.portfolio_manager import PortfolioManager
from reporting.stock_selector import StockSelector
from data.symbol_loader import SymbolLoader


class MomentumTrackerAPI:
    """
    Programmatic facade class. Wires together all sub-components of the
    Momentum Portfolio System and exposes non-interactive methods for Django,
    scheduler jobs, and CLI scripts.
    """

    def __init__(self, config_file: str = "config.json", user_id: int = 3) -> None:
        _project_root = _pkg.parent
        resolved_config = Path(config_file)
        if not resolved_config.is_absolute() and not resolved_config.exists():
            pkg_config = _pkg / config_file
            if pkg_config.exists():
                config_file = str(pkg_config)
            else:
                config_file = str(_pkg / "config.json")

        self.config = Config(config_file)

        # Resolve relative directories to the project root
        symbols_dir = self.config["DATA_CONFIG"].get("SYMBOLS_DIR", "data/symbols")
        if not Path(symbols_dir).is_absolute():
            self.config["DATA_CONFIG"]["SYMBOLS_DIR"] = str(_project_root / symbols_dir)

        # Cache folder configuration
        cache_dir = self.config.get("SYSTEM_CONFIG", {}).get("CACHE_DIR", "data_cache")
        if not Path(cache_dir).is_absolute():
            resolved_cache = str(_project_root / cache_dir)
        else:
            resolved_cache = cache_dir

        self.downloader = DataDownloaderFactory.create("yahoo")
        self.db = StockDatabaseManager(self.config, self.downloader, cache_dir=resolved_cache)
        self.strategy = MomentumStrategy(self.config, self.db)

        # Backtest results folder
        results_dir = self.config.get("SYSTEM_CONFIG", {}).get("BACKTEST_RESULTS_DIR", "Backtest_Results")
        if not Path(results_dir).is_absolute():
            results_dir = str(_project_root / results_dir)

        self.exporter = ReportExporter(base_output_dir=results_dir)
        self.runner = BacktestRunner(self.config, self.db, self.strategy, self.exporter)
        self.portfolio = PortfolioManager(self.config, self.db, self.strategy, user_id=user_id)
        self.selector = StockSelector(self.config, self.db, self.strategy, self.exporter)
        self.loader = SymbolLoader(self.config)

    def run_precache(self) -> Dict[str, Any]:
        """Download price and fundamental data for all configured symbols."""
        stock_tickers = self.loader.all_symbols()
        bench_tickers = self.loader.all_benchmark_tickers()
        ok_price, total = self.db.bulk_precache(stock_tickers, bench_tickers)
        ok_fund = self.db.bulk_precache_fundamentals(stock_tickers)
        return {
            "price_success": ok_price,
            "price_total": total,
            "fundamental_success": ok_fund,
            "fundamental_total": len(stock_tickers),
        }

    def get_top_recommendations(self, category: str, top_n: Optional[int] = None) -> pd.DataFrame:
        """Score stocks for a category and return the top recommendations."""
        if top_n is None:
            top_n = self.config["BACKTEST_CONFIG"].get("TOP_N", 20)
        return self.selector.top_recommendations(category, top_n)

    def export_all_scores(self) -> None:
        """Export scores for all configured categories to Excel files."""
        self.selector.export_all_category_scores()

    def score_custom_universe(self, excel_path: str) -> None:
        """Score custom stocks from an input Excel file and save results."""
        self.selector.score_custom_universe_from_excel(excel_path)

    def run_rebalance(self) -> pd.DataFrame:
        """Run rebalance calculation against current holdings and return actions report."""
        stock_tickers = self.loader.all_symbols()
        target_size = self.config["BACKTEST_CONFIG"].get("TOP_N", 20)
        return self.portfolio.generate_rebalance_report(stock_tickers, target_size=target_size)

    def run_rebalance_with_comparison(self, last_file_path: str) -> pd.DataFrame:
        """Run rebalance report enriched with comparison to a previous recommendations file."""
        stock_tickers = self.loader.all_symbols()
        target_size = self.config["BACKTEST_CONFIG"].get("TOP_N", 20)
        return self.portfolio.compare_with_last_recommendation_file(
            stock_tickers, last_file_path, target_size=target_size
        )

    def get_portfolio_momentum_history(self, days: int = 30) -> Dict[str, Any]:
        """Get 30-day historical WMS scores for portfolio stocks, the benchmark, and sectors."""
        return self.portfolio.get_portfolio_momentum_history(days=days)

    def analyze_tickers(
        self, 
        tickers: list[str], 
        run_technical: bool = True, 
        run_fii_dii: bool = True
    ) -> str:
        """
        Run deep-dive stock analysis using selectable technical chart,
        FII/DII flow, and fundamental sentiment agents.
        """
        from crew.stock_discovery_agents import process_tickers_batch
        return process_tickers_batch(
            tickers, 
            run_technical=run_technical, 
            run_fii_dii=run_fii_dii
        )

"""
application.py – Main application class and CLI entry point.

The Application class wires together every component of the system and
does the interactive main menu. It is the only place where the concrete
class instances are constructed, ensuring the rest of the code depends only
on abstractions.

Usage
-----
  python cli_application/application.py                # launches interactive menu
  python cli_application/application.py --config my.json
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Absolute path to project root and momentum_tracker/ — single source of truth for all paths
_project_root = Path(__file__).resolve().parent.parent
_root    = _project_root / "momentum_tracker"          # momentum_tracker/
_pkg     = _root              # momentum_tracker
_src     = _pkg / "src"                             # momentum_tracker/src/

if not _src.exists():
    raise FileNotFoundError(
        f"Cannot locate momentum_tracker/src at '{_src}'. "
        "Ensure momentum_tool.py is in the Momentum-Tracker/ project root."
    )

# Prepend src/ and project root so plain imports resolve correctly
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from momentum_tracker import MomentumTrackerAPI

class Application:
    """
    Top-level orchestrator.

    Responsible for:
      * constructing all component instances
      * running the interactive main menu
      * dispatching menu choices to the appropriate component
    """

    def __init__(self, config_file: str = "config.json") -> None:
        print("\n" + "═" * 65)
        print("   Momentum Portfolio System – Initialising …")
        print("═" * 65)

        self.api = MomentumTrackerAPI(config_file, user_id=3)
        self.config = self.api.config
        self.downloader = self.api.downloader
        self.db = self.api.db
        self.strategy = self.api.strategy
        self.exporter = self.api.exporter
        self.runner = self.api.runner
        self.portfolio = self.api.portfolio
        self.selector = self.api.selector
        self.loader = self.api.loader

        print("✅ All components ready.\n")

    # ─────────────────────────────────────────────────────────────────────
    # Main menu
    # ─────────────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Start the interactive main menu loop."""
        while True:
            version = self.config.get("VERSION", "v11")
            print("\n" + "═" * 65)
            print(f"  Momentum Portfolio System ({version}) – Main Menu")
            print("═" * 65)
            print("  [1]  Run Quick Backtest (scenario sub-menu)")
            print("  [2]  Run Full Backtest (custom parameters)")
            print("  [3]  Today's Top Recommendations")
            print("  [4]  Export Full Universe Scores (all categories)")
            print("  [5]  Score Custom Universe from Excel")
            print("  [6]  Portfolio Manager (live holdings & rebalance)")
            print("  ─" * 32)
            print("  [7]  Edit Configuration")
            print("  [8]  Load Configuration File")
            print("  [9]  Save Configuration")
            print("  [10] Force Data Pre-cache / Update All")
            print("  [11] Clear Cache & Reset")
            debug_state = self.config["SYSTEM_CONFIG"]["DEBUG_MODE"]
            print(f"  [12] Toggle Debug Mode (current: {debug_state})")
            print("  [13] Add New Index Category (update SYMBOL_FILE_MAP)")
            print("  [14] Historical Momentum Tracker (portfolio vs index vs sector)")
            print("  [15] Compare Portfolio with Last Recommendation (Option 12)")
            print("  ─" * 32)
            print("  [0]  Exit")
            print("─" * 65)

            choice = input("  Enter choice: ").strip()

            try:
                if   choice == "1":  self._quick_backtest()
                elif choice == "2":  self._full_backtest()
                elif choice == "3":  self._recommendations()
                elif choice == "4":  self._export_all_scores()
                elif choice == "5":  self._score_custom_universe()
                elif choice == "6":  self.portfolio.interactive_menu()
                elif choice == "7":  self.config.edit_interactively()
                elif choice == "8":  self._load_config()
                elif choice == "9":  self._save_config()
                elif choice == "10": self._precache()
                elif choice == "11": self._clear_cache()
                elif choice == "12": self.config.toggle_debug()
                elif choice == "13": self._add_category()
                elif choice == "14": self._historical_momentum_tracker()
                elif choice == "15": self._rebalance_comparison()
                elif choice == "0":  self._exit(); break
                else:
                    print("  ⚠  Invalid choice – try again.")
            except KeyboardInterrupt:
                print("\n  Interrupted.")
            except Exception as exc:
                print(f"  ❌ Error: {exc}")
                import traceback
                traceback.print_exc()

    # ─────────────────────────────────────────────────────────────────────
    # Menu handlers
    # ─────────────────────────────────────────────────────────────────────

    def _quick_backtest(self) -> None:
        if not self.db._price_mem and not any(self.db._price_dir.iterdir()):
            print("  ⚠  No cached data. Run [10] first.")
            return
        self.runner.run_quick_interactively()

    def _full_backtest(self) -> None:
        if not self.db._price_mem and not any(self.db._price_dir.iterdir()):
            print("  ⚠  No cached data. Run [10] first.")
            return
        self.runner.run_full_interactively()

    def _recommendations(self) -> None:
        if not any(self.db._price_dir.iterdir()):
            print("  ⚠  No cached data. Run [10] first.")
            return
        cat = self.loader.select_interactively("Select category for recommendations: ")
        if not cat:
            return
        top_n = self.config["BACKTEST_CONFIG"].get("TOP_N", 20) * 2
        self.selector.top_recommendations(cat, top_n)

    def _export_all_scores(self) -> None:
        if not any(self.db._price_dir.iterdir()):
            print("  ⚠  No cached data. Run [10] first.")
            return
        self.selector.export_all_category_scores()

    def _score_custom_universe(self) -> None:
        file_name = input("  Enter Excel file name: ").strip()
        if file_name:
            self.selector.score_custom_universe_from_excel(file_name)

    def _load_config(self) -> None:
        new_file = input(
            f"  File to load (current: {self.config.current_file}): "
        ).strip()
        if new_file:
            self.config.load(new_file)
        else:
            print("  Load cancelled.")

    def _save_config(self) -> None:
        new_file = input(
            f"  File to save as (current: {self.config.current_file}): "
        ).strip()
        mode = input("  Save mode: [1] Full snapshot  [2] Minimal overrides (diff vs defaults): ").strip()
        minimal = (mode == "2")
        self.config.save(new_file or None, minimal=minimal)

    def _precache(self) -> None:
        """Download price and fundamental data for all configured symbols."""
        print("\n  Starting full data pre-cache …")
        stock_tickers = self.loader.all_symbols()
        bench_tickers = self.loader.all_benchmark_tickers()

        ok_price, total = self.db.bulk_precache(stock_tickers, bench_tickers)
        ok_fund = self.db.bulk_precache_fundamentals(stock_tickers)

        print(f"\n  Pre-cache summary:")
        print(f"    Price data  : {ok_price}/{total}")
        print(f"    Fundamental : {ok_fund}/{len(stock_tickers)}")

    def _clear_cache(self) -> None:
        confirm = input("  Clear ALL cached data? (y/n): ").strip().lower()
        if confirm != "y":
            print("  Aborted.")
            return

        self.db.clear_cache()

        years_str = input(
            f"  New DOWNLOAD_HISTORY_YEARS "
            f"(current: {self.config['DATA_CONFIG']['DOWNLOAD_HISTORY_YEARS']}, "
            f"Enter to keep): "
        ).strip()

        if years_str.isdigit():
            new_years = int(years_str)
            current_years = self.config["DATA_CONFIG"]["DOWNLOAD_HISTORY_YEARS"]
            self.config["DATA_CONFIG"]["DOWNLOAD_HISTORY_YEARS"] = new_years
            self.config.save()

            if new_years > current_years:
                print(f"  History increased to {new_years}y – triggering full re-download.")
                self._precache()

    def _exit(self) -> None:
        print("\n  Saving portfolio …")
        self.portfolio.save()
        print("  Goodbye!\n")

    def _historical_momentum_tracker(self) -> None:
        days_input = input("  Enter number of days to track (default: 30): ").strip()
        days = int(days_input) if days_input.isdigit() else 30
        history = self.portfolio.get_portfolio_momentum_history(days=days)
        if history and history.get("dates"):
            dates = history["dates"]
            portfolio = history["portfolio"]
            index = history["index"]
            sectors = history["sectors"]
            sector_map = history["sector_map"]
            
            print("\n" + "=" * 110)
            print("  PORTFOLIO HISTORICAL MOMENTUM SCORES")
            print("=" * 110)
            for sym, scores in portfolio.items():
                if scores:
                    latest = scores[-1]
                    change_7d = round(latest - (scores[-6] if len(scores) >= 6 else scores[0]), 2)
                    change_30d = round(latest - scores[0], 2)
                    sec = sector_map.get(sym, "N/A")
                    sec_latest = sectors.get(sec, [])[-1] if sectors.get(sec) else 0.0
                    print(f"  {sym:<12} | Sector: {sec:<20} | WMS: {latest:>6.2f} | 7d change: {change_7d:>+6.2f} | 30d change: {change_30d:>+6.2f} | Sector WMS: {sec_latest:>6.2f}")
            print("-" * 110)
            print(f"  Index (^NSEI) Latest WMS: {index[-1]:.2f}")
            print("=" * 110)

    def _rebalance_comparison(self) -> None:
        port = input("  Path to current portfolio Excel file: ").strip()
        if not port:
            print("  Cancelled.")
            return
        prev = input("  Path to LAST_Recommendation (Excel/CSV): ").strip()
        if not prev:
            print("  Cancelled.")
            return
        self.portfolio.compare_and_rebalance(port, prev)

    def _add_category(self) -> None:
        """Interactive addition of a new index category and symbol CSV mapping."""
        self.loader.add_category_interactively()


def main() -> None:
    import warnings
    warnings.filterwarnings("ignore", category=FutureWarning)

    parser = argparse.ArgumentParser(description="Momentum Portfolio System")
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to JSON config file (default: config.json)",
    )
    args = parser.parse_args()

    app = Application(config_file=args.config)
    app.run()


if __name__ == "__main__":
    main()

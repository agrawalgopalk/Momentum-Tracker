"""
momentum_tool.py – CrewAI tool that wraps the Momentum Portfolio System backbone.

The tool wires together:
    Config → DataDownloaderFactory → DatabaseManager → MomentumStrategy → SymbolLoader

and exposes the full scoring pipeline as a single callable for any CrewAI agent.

Input (JSON string or plain category name)
------------------------------------------
{
    "category": "Nifty100",   # Nifty100 | Midcap150 | Smallcap250 | Nifty500
    "top_n":    20,           # How many top candidates to return (default: 20)
}

Plain-string shorthand is also accepted, e.g. just ``"Nifty100"`` → uses that category
with all other params at defaults.

Output
------
A structured text block containing:
  • Ranked table  (Rank | Symbol | WMS | RS | RSI | MFI | CCI)
  • Comma-separated ticker list   (easy for downstream agents to parse)
  • Run metadata  (category, stocks scored, filters applied, timestamp)
"""

from __future__ import annotations

import json
import traceback
from datetime import datetime
from typing import Any

from crewai.tools import BaseTool
from pydantic import Field


# ─────────────────────────────────────────────────────────────────────────────
# Tool
# ─────────────────────────────────────────────────────────────────────────────

class MomentumBackboneTool(BaseTool):
    """
    CrewAI tool that runs the live Momentum Portfolio System scoring pipeline
    and returns ranked stock candidates.
    """

    name: str = "Momentum Strategy Tool"
    description: str = (
        "Executes the multi-factor momentum scoring pipeline to identify "
        "top-ranked stock candidates from an NSE index universe. "
        "Pass a JSON object (or just a category name string) as input.\n"
        "JSON keys:\n"
        "  category  – stock universe to scan. "
        "One of: Nifty100, Midcap150, Smallcap250, Nifty500. (default: Nifty100)\n"
        "  top_n     – number of top candidates to return. (default: 20)\n"
        "Returns a ranked list with WMS, RS, RSI, MFI, CCI scores and a "
        "clean comma-separated ticker list for downstream agents."
    )

    # ── Defaults ──────────────────────────────────────────────────────────
    default_category: str  = Field(default="Nifty100")
    default_top_n:    int  = Field(default=20)

    # ─────────────────────────────────────────────────────────────────────
    # Entry point
    # ─────────────────────────────────────────────────────────────────────

    def _run(self, strategy_params: str = "{}") -> str:
        """
        Execute the momentum backbone and return a formatted results string.

        Parameters
        ----------
        strategy_params : str
            JSON object string or plain category name.
        """
        try:
            params   = self._parse_params(strategy_params)
            category = params["category"]
            top_n    = params["top_n"]
            # ── Bootstrap system components ────────────────────────────
            config, db, strategy, loader, selector = self._init_components()

            # ── Validate category ──────────────────────────────────────
            available = loader.available_categories()
            if category not in available:
                return (
                    f"[MomentumTool] Unknown category '{category}'. "
                    f"Available: {', '.join(available)}"
                )

            top_results = selector.top_recommendations(category, top_n)
            
            if top_results.empty:
                return f"No stocks found for category '{category}' that pass filters."

            # ── Format output ──────────────────────────────────────────
            return self._format_output(
                top_results.to_dict(orient='records'), category, top_results.__len__(),
            )

        except Exception as exc:
            return (
                f"[MomentumTool] Execution failed: {exc}\n"
                f"{traceback.format_exc()}"
            )

    # ─────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────

    def _parse_params(self, raw: str) -> dict:
        """
        Parse the agent's input into a canonical params dict.

        Accepts:
          • Empty string / None  → all defaults
          • Plain category name  → e.g. "Midcap150"
          • JSON object string   → e.g. '{"category":"Nifty500","top_n":30}'
        """
        raw = (raw or "").strip()

        if not raw or raw == "{}":
            pass  # fall through to defaults below

        elif raw.startswith("{"):
            # JSON object
            try:
                user = json.loads(raw)
                return {
                    "category":  str(user.get("category",  self.default_category)),
                    "top_n":     int(user.get("top_n",     self.default_top_n)),
                }
            except json.JSONDecodeError:
                pass  # fall through to defaults

        else:
            # Treat the whole string as a category name
            return {
                "category":  raw,
                "top_n":     self.default_top_n,
            }

        return {
            "category":  self.default_category,
            "top_n":     self.default_top_n,
        }

    @staticmethod
    def _init_components():
        """
        Construct and return (Config, DatabaseManager, MomentumStrategy, SymbolLoader).

        All source modules (config.py, database_manager.py, …) live in
        momentum_tracker/src/ and use plain intra-module imports like
        `from config import Config`.  They must therefore be imported as
        flat modules – NOT as a package – so we add src/ to sys.path first
        and then use plain `import` / `from X import Y` statements.

        Using package-style imports (from momentum_tracker.src.X import Y)
        breaks the internal imports inside those files.

        Paths resolved
        --------------
        momentum_tool.py lives at  <root>/momentum_tool.py
        All data lives under       <root>/momentum_tracker/
          ├── data/symbols/        ← CSV symbol lists
          ├── mps_cache/           ← price + fundamental cache
          └── src/                 ← source modules
        """
        import sys
        from pathlib import Path

        # Absolute path to momentum_tracker/ — single source of truth for all paths
        _root    = Path(__file__).resolve().parent          # Momentum-Tracker/
        _pkg     = _root / "momentum_tracker"               # momentum_tracker/
        _src     = _pkg / "src"                             # momentum_tracker/src/

        if not _src.exists():
            raise FileNotFoundError(
                f"Cannot locate momentum_tracker/src at '{_src}'. "
                "Ensure momentum_tool.py is in the Momentum-Tracker/ project root."
            )

        # Prepend src/ so plain imports resolve correctly (and beat system modules)
        if str(_src) not in sys.path:
            sys.path.insert(0, str(_src))

        # ── Plain imports ────────────────────────────────────────────────
        from config import Config                              # noqa: E402
        from data_downloader import DataDownloaderFactory     # noqa: E402
        from database_manager import DatabaseManager          # noqa: E402
        from momentum_strategy import MomentumStrategy        # noqa: E402
        from symbol_loader import SymbolLoader                # noqa: E402
        from stock_selector import StockSelector              # noqa: E402
        

        # ── Config: load from momentum_tracker/ if config.json exists ───
        config_json = _pkg / "config.json"
        config = Config(str(config_json) if config_json.exists() else "config.json")

        # ── Override relative paths with absolute ones ───────────────────
        # SYMBOLS_DIR: default is "data/symbols" which is relative to cwd.
        # Patch it to the absolute path so SymbolLoader finds the CSVs
        # regardless of where the script is run from.
        config["DATA_CONFIG"]["SYMBOLS_DIR"] = str(_pkg / "data" / "symbols")

        resolved_cache = str(_pkg / "mps_cache")

        downloader = DataDownloaderFactory.create("yahoo")
        db         = DatabaseManager(config, downloader, cache_dir=resolved_cache)
        strategy   = MomentumStrategy(config, db)
        loader     = SymbolLoader(config)
        selector  = StockSelector(config, db, strategy, None)
        

        return config, db, strategy, loader, selector

    @staticmethod
    def _format_output(
        top_results:   list[dict],
        category:      str,
        total_passed:  int,
    ) -> str:
        """
        Render a structured, human-readable (and agent-parseable) results block.

        Section 1 – Ranked table with key scores.
        Section 2 – Plain ticker list for downstream agent consumption.
        Section 3 – Run metadata.
        """
        # ── Ranked table ───────────────────────────────────────────────
        header = (
            f"{'Rank':<5} {'Symbol':<18} {'WMS':>6} "
            f"{'RS':>7} {'RSI':>6} {'MFI':>6} {'CCI':>7}"
        )
        sep = "─" * len(header)

        rows = []
        tickers = []
        for rank, r in enumerate(top_results, 1):
            sym  = r.get("Symbol", "N/A")
            wms  = r.get("WMS", 0.0)
            rs   = r.get("RS_Raw",  float("nan"))
            rsi  = r.get("RSI_Raw", float("nan"))
            mfi  = r.get("MFI_Raw", float("nan"))
            cci  = r.get("CCI_Raw", float("nan"))

            rows.append(
                f"{rank:<5} {sym:<18} {wms:>6.2f} "
                f"{rs:>7.3f} {rsi:>6.1f} {mfi:>6.1f} {cci:>7.1f}"
            )
            tickers.append(sym)

        table = "\n".join([header, sep] + rows)

        # ── Ticker list (easy for downstream CrewAI agents to parse) ───
        ticker_list = ", ".join(tickers)

        # ── Metadata ───────────────────────────────────────────────────
        meta = (
            f"Category : {category}\n"
            f"Passed   : {total_passed} stocks after all filters\n"
            f"Returned : {len(top_results)} top candidates\n"
            f"Run at   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        return (
            "═" * 60 + "\n"
            "  MOMENTUM BACKBONE – TOP CANDIDATES\n"
            + "═" * 60 + "\n\n"
            + table + "\n\n"
            + "─" * 60 + "\n"
            "TICKERS (for downstream agents):\n"
            + ticker_list + "\n\n"
            + "─" * 60 + "\n"
            "RUN METADATA:\n"
            + meta + "\n"
            + "═" * 60
        )
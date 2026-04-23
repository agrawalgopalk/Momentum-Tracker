"""
symbol_loader.py – Load and manage stock symbol lists.

SymbolLoader reads NSE category CSV files (ind_nifty100list.csv, etc.)
and provides helpers for interactive category selection.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import pandas as pd

from config import Config


class SymbolLoader:
    """
    Loads stock symbol lists from configured CSV files.

    Parameters
    ----------
    config : Config instance (provides SYMBOL_FILE_MAP and INDICES).
    """

    def __init__(self, config: Config) -> None:
        self._cfg = config

    def _resolve_symbol_file(self, file_name: str) -> Optional[Path]:
        """
        Resolve a configured symbol CSV filename to an existing path.

        Search order:
        1) As provided (absolute or relative to cwd)
        2) Under DATA_CONFIG.SYMBOLS_DIR (if set) + file_name (when file_name is not absolute)
        """
        if not file_name:
            return None

        p = Path(file_name)
        if p.exists():
            return p

        symbols_dir = self._cfg["DATA_CONFIG"].get("SYMBOLS_DIR")
        if symbols_dir and not p.is_absolute():
            candidate = Path(symbols_dir) / file_name
            if candidate.exists():
                return candidate

        return None

    def load(self, category: str) -> List[str]:
        """Return list of YF-formatted tickers for *category*."""
        file_map = self._cfg["DATA_CONFIG"]["SYMBOL_FILE_MAP"]
        file_name = file_map.get(category)
        if not file_name:
            print(f"[SymbolLoader] No file configured for '{category}'.")
            return []

        p = self._resolve_symbol_file(file_name)
        if p is None:
            print(f"[SymbolLoader] File not found: '{file_name}'.")
            return []

        try:
            df = pd.read_csv(p)
            col = (
                "Symbol" if "Symbol" in df.columns
                else "symbol" if "symbol" in df.columns
                else df.columns[1] if "Company Name" in df.columns and len(df.columns) > 1
                else None
            )
            if col is None:
                print(f"[SymbolLoader] Cannot detect symbol column in '{p}'.")
                return []

            symbols = [
                f"{s}.NS"
                for s in df[col].dropna().unique()
                if isinstance(s, str)
            ]
            print(f"[SymbolLoader] {len(symbols)} symbols loaded for '{category}'.")
            return symbols

        except Exception as exc:
            print(f"[SymbolLoader] Error reading '{p}': {exc}")
            return []

    def load_from_csv(self, file_path: str) -> List[str]:
        """Load symbols from an arbitrary CSV (must have 'Symbol' column)."""
        p = self._resolve_symbol_file(file_path)
        if p is None:
            print(f"[SymbolLoader] File not found: '{file_path}'.")
            return []
        try:
            df   = pd.read_csv(p)
            col  = "Symbol" if "Symbol" in df.columns else "symbol"
            syms = [f"{s}.NS" for s in df[col].dropna().unique() if isinstance(s, str)]
            print(f"[SymbolLoader] {len(syms)} symbols from custom CSV.")
            return syms
        except Exception as exc:
            print(f"[SymbolLoader] Error: {exc}")
            return []

    def all_symbols(self) -> List[str]:
        """Return all symbols across all configured categories (deduplicated)."""
        all_syms: set = set()
        for cat in self._cfg["DATA_CONFIG"]["SYMBOL_FILE_MAP"]:
            all_syms.update(self.load(cat))
        return list(all_syms)

    def all_benchmark_tickers(self) -> List[str]:
        """Return all index benchmark tickers from config."""
        return list(self._cfg["DATA_CONFIG"]["INDICES"].values())

    def available_categories(self) -> List[str]:
        return list(self._cfg["DATA_CONFIG"]["SYMBOL_FILE_MAP"].keys())

    def select_interactively(self, prompt: str = "Select category: ") -> Optional[str]:
        """Print numbered list of categories and return the chosen one."""
        categories = self.available_categories()
        if not categories:
            print("[SymbolLoader] No categories configured.")
            return None

        print(f"\n{prompt}")
        for i, cat in enumerate(categories, 1):
            print(f"  [{i}] {cat}")
        print("  [0] Cancel")

        choice = input("Choice: ").strip()
        if choice == "0":
            return None
        try:
            return categories[int(choice) - 1]
        except (ValueError, IndexError):
            print("  Invalid choice.")
            return None

    def add_category_interactively(self) -> None:
        """
        Interactive helper to add a new category to DATA_CONFIG.SYMBOL_FILE_MAP.

        This updates the in-memory config and persists it via Config.save().
        """
        file_map = self._cfg["DATA_CONFIG"].get("SYMBOL_FILE_MAP", {})
        if not isinstance(file_map, dict):
            print("[SymbolLoader] Invalid SYMBOL_FILE_MAP in config.")
            return

        print("\n--- Add New Index Category ---")
        new_category = input("  New category name (e.g. Sensex30): ").strip()
        if not new_category:
            print("  Cancelled.")
            return

        if new_category in file_map:
            print(f"  '{new_category}' already exists in config.")
            return

        file_name = input(
            "  Symbol list CSV file name (must exist; e.g. ind_sensex30list.csv): "
        ).strip()
        if not file_name:
            print("  Cancelled.")
            return

        p = self._resolve_symbol_file(file_name)
        if p is None:
            symbols_dir = self._cfg["DATA_CONFIG"].get("SYMBOLS_DIR", "data/symbols")
            print(
                f"  File not found: '{file_name}'. Put it in '{symbols_dir}' "
                f"(recommended) or in the project root, or use a full path."
            )
            return

        # Optional benchmark ticker for this category
        idx_map = self._cfg["DATA_CONFIG"].get("INDICES", {})
        if not isinstance(idx_map, dict):
            idx_map = {}
            self._cfg["DATA_CONFIG"]["INDICES"] = idx_map

        bench = input(
            "  Optional benchmark ticker for this category (blank = skip): "
        ).strip()

        file_map[new_category] = file_name
        if bench:
            idx_map[new_category] = bench

        try:
            self._cfg.save()
            print(f"✅ Added category '{new_category}' → '{file_name}'")
        except Exception as exc:
            print(f"[SymbolLoader] Could not save config: {exc}")

"""
config.py – Configuration management for the Momentum Portfolio System.

Handles loading, saving, deep-merging, and live editing of all system
parameters (data, momentum, filters, scoring, backtest).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


# ---------------------------------------------------------------------------
# Default configuration – single source of truth
# ---------------------------------------------------------------------------
DEFAULT_CONFIG: Dict[str, Any] = {
    "VERSION": "v11.0.0",
    "SYSTEM_CONFIG": {
        "DEBUG_MODE": False,
    },
    "DATA_CONFIG": {
        # Where stock-universe CSVs (ind_*list.csv) live.
        # SymbolLoader will also fall back to repo root for backward compatibility.
        "SYMBOLS_DIR": "data/symbols",
        "INDICES": {
            "Nifty50":              "^NSEI",
            "Nifty100":             "^CNX100",
            "Midcap150":            "NIFTYMIDCAP150.NS",
            "Smallcap250":          "^CNXSC",
            "NiftyLargeMidcap250":  "NIFTY_LARGEMID250.NS",
            "NiftyNext50":          "^NSMIDCP",
            "Nifty500":             "^CRSLDX",
            "NiftyMicrocap250":     "NIFTY_MICROCAP250.NS",
        },
        "INDEX_BENCHMARK": "^NSEI",
        "SYMBOL_FILE_MAP": {
            "Nifty50":     "ind_nifty50list.csv",
            "Nifty100":    "ind_nifty100list.csv",
            "Midcap150":   "ind_niftymidcap150list.csv",
            "Smallcap250": "ind_niftysmallcap250list.csv",
            "Nifty500":    "ind_nifty500list.csv",
        },
        # Cache freshness: files older than this many days trigger an update
        "MAX_CACHE_DAYS": 3,
        # Years of price history to download and maintain
        "DOWNLOAD_HISTORY_YEARS": 20,
    },
    "MOMENTUM_CONFIG": {
        # ROC periods (days) used for WMS composite score
        "WMS_ROC_PERIODS":  [60, 40, 20],
        "WMS_ROC_WEIGHTS":  [0.35, 0.40, 0.25],
        # Lookback for relative-strength ratio vs benchmark
        "RS_LOOKBACK_DAYS": 55,
    },
    "FILTER_CONFIG": {
        "ENABLE_FILTERS": True,
        # Minimum percentile rank thresholds for P-score and V-score
        "MIN_P_SCORE_PCT": 50,
        "MIN_V_SCORE_PCT": 50,
        # Absolute price / volume floors
        "MIN_PRICE":      1.0,
        "MIN_VOLUME_AVG": 10_000,
        "ENABLE_EMA_FILTER": True,
        "EMA_PERIOD_50": 50, # Exponential Moving Average period for trend filter
        "EMA_PERIOD_200": 200, # Exponential Moving Average period for trend filter

        "CONSISTENCY_CHECK": {
            "ENABLE":              False,
            "CHECK_DAYS":          30,
            "MIN_TOTAL_DAYS_PASS": 15,
            "RECENT_WINDOW":       10,
            "MIN_RECENT_DAYS_PASS":10,
        },
    },
    "SCORING_WEIGHTS": {
        # Final WMS component weights (must sum to 1.0)
        "WMS_ROC_Composite": 0.60,
        "RSI_Score":         0.05,
        "MFI_Score":         0.20,
        "CCI_Score":         0.15,
    },
    "BACKTEST_CONFIG": {
        "TOP_N":                       20,
        "REBALANCE_FREQUENCY":         "M",   # W / M / Q / A
        "TRANSACTION_COST":            0.001,
        "STOCK_SCALING_FACTOR":        2,     # Hold pool = TOP_N * factor
        "MOMENTUM_DROP_THRESHOLD_PCT": 50.0,  # Forced sell if WMS drops >= this %
        "NEW_STOCK_ADDITION_LIMIT":    20,    # Only consider top-N candidates for BUY
        "ANNUAL_CASH_RETURN_RATE":     0.04,  # 4 % pa return on idle cash
        "INITIAL_CAPITAL":             1_000_000.0,
    },
}


class Config:
    """
    Singleton-style configuration manager.

    Usage
    -----
    cfg = Config()               # loads from default file or uses defaults
    cfg.load("my_config.json")   # reload from a specific file
    cfg.save()                   # save to current file
    value = cfg["BACKTEST_CONFIG"]["TOP_N"]
    cfg["SYSTEM_CONFIG"]["DEBUG_MODE"] = True
    """

    _DEFAULT_FILE = "config.json"

    def __init__(self, file_name: str = _DEFAULT_FILE) -> None:
        self._file_name: str = file_name
        self._data: Dict[str, Any] = {}
        self._reset_to_defaults()
        self.load(file_name)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def load(self, file_name: str | None = None) -> None:
        """Load config from *file_name*, merging over current defaults."""
        target = file_name or self._file_name
        try:
            with open(target, "r") as fh:
                loaded = json.load(fh)
            _deep_update(self._data, loaded)
            self._file_name = target
            print(f"[Config] Loaded from '{target}'.")
        except FileNotFoundError:
            print(f"[Config] '{target}' not found – using defaults.")
        except json.JSONDecodeError as exc:
            print(f"[Config] JSON error in '{target}': {exc} – using defaults.")
        except Exception as exc:
            print(f"[Config] Unexpected error loading '{target}': {exc} – using defaults.")

    def save(
        self,
        file_name: str | None = None,
        *,
        minimal: bool = False,
    ) -> None:
        """
        Persist config to *file_name* (JSON).

        Parameters
        ----------
        minimal:
            - False (default): write the full resolved config snapshot.
            - True:            write only the diff vs DEFAULT_CONFIG (smaller override file).
        """
        target = file_name or self._file_name
        try:
            data = self._data
            if minimal:
                data = _deep_diff(DEFAULT_CONFIG, self._data)
            with open(target, "w") as fh:
                json.dump(data, fh, indent=4)
            self._file_name = target
            label = "minimal overrides" if minimal else "full snapshot"
            print(f"[Config] Saved ({label}) to '{target}'.")
        except Exception as exc:
            print(f"[Config] Error saving to '{target}': {exc}")

    def reset(self) -> None:
        """Restore all values to built-in defaults."""
        self._reset_to_defaults()
        print("[Config] Reset to built-in defaults.")

    def as_dict(self) -> Dict[str, Any]:
        """Return a shallow copy of the config dict."""
        return self._data.copy()

    @property
    def current_file(self) -> str:
        return self._file_name

    # ------------------------------------------------------------------
    # Dict-like access  (cfg["KEY"])
    # ------------------------------------------------------------------

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def debug_print(self, message: str) -> None:
        """Print only when DEBUG_MODE is True."""
        if self._data.get("SYSTEM_CONFIG", {}).get("DEBUG_MODE", False):
            print(f"[DEBUG] {message}")

    def toggle_debug(self) -> bool:
        """Flip DEBUG_MODE and return the new value."""
        current = self._data["SYSTEM_CONFIG"]["DEBUG_MODE"]
        self._data["SYSTEM_CONFIG"]["DEBUG_MODE"] = not current
        print(f"[Config] DEBUG_MODE → {not current}")
        return not current

    # ------------------------------------------------------------------
    # Interactive config editor
    # ------------------------------------------------------------------

    def edit_interactively(self) -> None:
        """Simple CLI for tweaking common settings."""
        sections = list(self._data.keys())
        while True:
            print("\n--- Edit Configuration ---")
            for idx, section in enumerate(sections, 1):
                print(f"  [{idx}] {section}")
            print("  [0] Back")

            choice = input("Select section: ").strip()
            if choice == "0":
                break
            try:
                section_key = sections[int(choice) - 1]
            except (ValueError, IndexError):
                print("Invalid choice.")
                continue

            section = self._data[section_key]
            if not isinstance(section, dict):
                print(f"  {section_key} = {section}  (not a sub-section)")
                continue

            keys = list(section.keys())
            for i, k in enumerate(keys, 1):
                print(f"  [{i}] {k} = {section[k]}")
            print("  [0] Back")

            key_choice = input("Select key to edit: ").strip()
            if key_choice == "0":
                continue
            try:
                edit_key = keys[int(key_choice) - 1]
            except (ValueError, IndexError):
                print("Invalid choice.")
                continue

            current_val = section[edit_key]
            new_val_str = input(
                f"  New value for '{edit_key}' (current: {current_val}): "
            ).strip()
            if not new_val_str:
                continue

            # Try to preserve type
            try:
                if isinstance(current_val, bool):
                    section[edit_key] = new_val_str.lower() in ("true", "1", "yes")
                elif isinstance(current_val, int):
                    section[edit_key] = int(new_val_str)
                elif isinstance(current_val, float):
                    section[edit_key] = float(new_val_str)
                else:
                    section[edit_key] = new_val_str
                print(f"  Updated '{edit_key}' → {section[edit_key]}")
            except ValueError:
                print("  Invalid value – keeping original.")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _reset_to_defaults(self) -> None:
        import copy
        self._data = copy.deepcopy(DEFAULT_CONFIG)


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------

def _deep_update(base: dict, updates: dict) -> None:
    """Recursively update *base* with *updates*, preserving nested dicts."""
    for key, value in updates.items():
        if (
            isinstance(value, dict)
            and key in base
            and isinstance(base[key], dict)
        ):
            _deep_update(base[key], value)
        else:
            base[key] = value


def _deep_diff(defaults: Any, current: Any) -> Any:
    """
    Return a minimal structure containing only values in *current* that differ
    from *defaults*. Used for saving a compact override-style config file.
    """
    # Dicts: recurse and keep only changed keys
    if isinstance(defaults, dict) and isinstance(current, dict):
        out: dict = {}
        for k, cur_v in current.items():
            if k in defaults:
                d = _deep_diff(defaults[k], cur_v)
                if d is not None:
                    out[k] = d
            else:
                out[k] = cur_v
        return out if out else None

    # Lists/tuples: if equal, no diff; else keep full current list
    if isinstance(defaults, (list, tuple)) and isinstance(current, (list, tuple)):
        return None if list(defaults) == list(current) else current

    # Scalars / mismatched types
    return None if defaults == current else current

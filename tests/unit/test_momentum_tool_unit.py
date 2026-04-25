"""
tests/unit/test_momentum_tool.py

Unit tests for MomentumBackboneTool.
All heavy dependencies (Config, DatabaseManager, MomentumStrategy, SymbolLoader)
are mocked so these tests run instantly with zero network or disk I/O.

Run from project root:
    pytest tests/unit/test_momentum_tool.py -v
"""

import json
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_result(symbol: str, wms: float, passed: bool = True) -> dict:
    """Build a minimal scored-stock dict that MomentumStrategy would return."""
    return {
        "Symbol":             symbol,
        "PassedFilters":      passed,
        "FilterReason":       "" if passed else "Low volume",
        "FinalWeightedScore": wms,
        "RS_Raw":             0.05,
        "RSI_Raw":            58.0,
        "MFI_Raw":            62.0,
        "CCI_Raw":            110.0,
    }


def _patch_init_components(mock_results: list):
    """
    Return a context manager that patches _init_components so _run()
    uses synthetic scored results instead of touching disk/network.
    """
    mock_config = MagicMock()
    mock_config.__getitem__ = lambda self, k: {
        "DATA_CONFIG": {"INDEX_BENCHMARK": "^NSEI"}
    }[k]

    mock_loader = MagicMock()
    mock_loader.available_categories.return_value = [
        "Nifty100", "Midcap150", "Smallcap250", "Nifty500"
    ]
    mock_loader.load.return_value = [r["Symbol"] for r in mock_results]

    mock_db = MagicMock()
    mock_strategy = MagicMock()
    mock_strategy.score_universe.return_value = mock_results

    return patch(
        "momentum_tool.MomentumBackboneTool._init_components",
        return_value=(mock_config, mock_db, mock_strategy, mock_loader),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tool():
    from momentum_tool import MomentumBackboneTool
    return MomentumBackboneTool()


SAMPLE_RESULTS = [
    _make_mock_result("INFY.NS",    88.5),
    _make_mock_result("TCS.NS",     85.2),
    _make_mock_result("HCLTECH.NS", 79.1),
    _make_mock_result("WIPRO.NS",   72.3, passed=False),  # should be excluded
]


# ---------------------------------------------------------------------------
# Param parsing
# ---------------------------------------------------------------------------

class TestParseParams:

    def test_empty_string_uses_defaults(self, tool):
        p = tool._parse_params("")
        assert p["category"]  == tool.default_category
        assert p["top_n"]     == tool.default_top_n
        assert p["cache_dir"] == tool.default_cache_dir

    def test_empty_json_object_uses_defaults(self, tool):
        p = tool._parse_params("{}")
        assert p["category"] == tool.default_category

    def test_plain_category_string(self, tool):
        p = tool._parse_params("Midcap150")
        assert p["category"] == "Midcap150"
        assert p["top_n"]    == tool.default_top_n

    def test_full_json(self, tool):
        raw = json.dumps({"category": "Nifty500", "top_n": 5, "cache_dir": "./tmp"})
        p = tool._parse_params(raw)
        assert p["category"]  == "Nifty500"
        assert p["top_n"]     == 5
        assert p["cache_dir"] == "./tmp"

    def test_partial_json_fills_defaults(self, tool):
        p = tool._parse_params('{"category": "Smallcap250"}')
        assert p["category"] == "Smallcap250"
        assert p["top_n"]    == tool.default_top_n

    def test_malformed_json_falls_back_to_defaults(self, tool):
        p = tool._parse_params("{bad json!!}")
        assert p["category"] == tool.default_category

    def test_top_n_coerced_to_int(self, tool):
        p = tool._parse_params('{"top_n": "15"}')
        assert isinstance(p["top_n"], int)
        assert p["top_n"] == 15


# ---------------------------------------------------------------------------
# _run() output content
# ---------------------------------------------------------------------------

class TestRun:

    def test_output_contains_ranked_table_header(self, tool):
        with _patch_init_components(SAMPLE_RESULTS):
            out = tool._run("{}")
        assert "Rank" in out
        assert "Symbol" in out
        assert "WMS" in out

    def test_output_contains_tickers_line(self, tool):
        with _patch_init_components(SAMPLE_RESULTS):
            out = tool._run("{}")
        assert "TICKERS" in out

    def test_passed_stocks_appear_in_output(self, tool):
        with _patch_init_components(SAMPLE_RESULTS):
            out = tool._run("{}")
        assert "INFY.NS" in out
        assert "TCS.NS"  in out

    def test_failed_stocks_excluded_from_output(self, tool):
        with _patch_init_components(SAMPLE_RESULTS):
            out = tool._run("{}")
        # WIPRO.NS has PassedFilters=False and should NOT appear
        assert "WIPRO.NS" not in out

    def test_top_n_limits_results(self, tool):
        with _patch_init_components(SAMPLE_RESULTS):
            out = tool._run('{"top_n": 1}')
        # Only rank 1 should appear; rank 2 (TCS) should be absent
        assert "INFY.NS" in out
        assert "TCS.NS"  not in out

    def test_output_contains_metadata_section(self, tool):
        with _patch_init_components(SAMPLE_RESULTS):
            out = tool._run("{}")
        assert "Category" in out
        assert "Scanned"  in out
        assert "Passed"   in out

    def test_invalid_category_returns_error_message(self, tool):
        with _patch_init_components(SAMPLE_RESULTS):
            out = tool._run('{"category": "BogusIndex"}')
        assert "Unknown category" in out or "Available" in out

    def test_no_passing_stocks_returns_clean_message(self, tool):
        all_fail = [_make_mock_result("X.NS", 0.0, passed=False)]
        with _patch_init_components(all_fail):
            out = tool._run("{}")
        assert "No stocks passed" in out

    def test_run_does_not_raise_on_empty_params(self, tool):
        with _patch_init_components(SAMPLE_RESULTS):
            out = tool._run("")
        assert isinstance(out, str)
        assert len(out) > 0


# ---------------------------------------------------------------------------
# Format output (pure function, no mocking needed)
# ---------------------------------------------------------------------------

class TestFormatOutput:

    def test_returns_string(self, tool):
        results = [_make_mock_result("INFY.NS", 80.0)]
        out = tool._format_output(results, "Nifty100", 100, 30)
        assert isinstance(out, str)

    def test_ticker_present_in_output(self, tool):
        results = [_make_mock_result("RELIANCE.NS", 90.0)]
        out = tool._format_output(results, "Nifty100", 100, 1)
        assert "RELIANCE.NS" in out

    def test_metadata_values_present(self, tool):
        out = tool._format_output([], "Midcap150", 250, 40)
        assert "Midcap150" in out
        assert "250"       in out
        assert "40"        in out

    def test_wms_score_present_in_output(self, tool):
        results = [_make_mock_result("INFY.NS", 77.77)]
        out = tool._format_output(results, "Nifty100", 100, 1)
        assert "77.77" in out

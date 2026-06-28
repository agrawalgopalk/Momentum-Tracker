"""
tests/integration/test_momentum_tool_live.py

Integration tests – call the real MomentumBackboneTool._run() end-to-end.
These tests hit the actual mps_cache (and download data if the cache is cold),
so they are SLOW and should only be run manually.

Prerequisites
─────────────
  1. Run from the Momentum-Tracker project root so that
     momentum_tracker/src is importable.
  2. mps_cache should already be warm (run application.py → [10] first)
     to avoid a full download during testing.

Run:
    pytest tests/integration/ -v -s
    pytest tests/integration/ -v -s -k "nifty100"
"""

import json
import sys
import time
from pathlib import Path

import pytest

# ── Make momentum_tracker/src importable from project root ────────────────
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "momentum_tracker" / "src"))

from momentum_tool import MomentumBackboneTool


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def tool():
    """One tool instance shared across all tests in this module."""
    return MomentumBackboneTool()


CACHE_DIR = "./momentum_tracker/mps_cache"


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------

class TestLiveRun:

    def test_default_params_returns_non_empty_string(self, tool):
        out = tool._run("{}")
        assert isinstance(out, str)
        assert len(out) > 100, "Output looks too short – likely an error message"

    def test_nifty100_returns_ticker_line(self, tool):
        params = json.dumps({"category": "Nifty100", "top_n": 10,
                             "cache_dir": CACHE_DIR})
        out = tool._run(params)
        assert "TICKERS" in out, f"Expected TICKERS section, got:\n{out[:500]}"

    def test_nifty100_returns_ranked_table(self, tool):
        params = json.dumps({"category": "Nifty100", "top_n": 10,
                             "cache_dir": CACHE_DIR})
        out = tool._run(params)
        assert "WMS" in out
        assert "RSI" in out

    def test_top_n_respected(self, tool):
        """Ask for 5; the TICKERS line must have at most 5 entries."""
        params = json.dumps({"category": "Nifty100", "top_n": 5,
                             "cache_dir": CACHE_DIR})
        out = tool._run(params)

        # Extract the TICKERS line
        tickers_line = ""
        for line in out.splitlines():
            if line.strip().startswith("TICKERS"):
                tickers_line = line
                break

        if tickers_line:
            tickers = [t.strip() for t in tickers_line.split(":", 1)[-1].split(",")
                       if t.strip()]
            assert len(tickers) <= 5, f"Expected ≤5 tickers, got {len(tickers)}"

    def test_plain_string_category(self, tool):
        """Plain string input should work the same as JSON."""
        out = tool._run("Nifty100")
        assert "MOMENTUM BACKBONE" in out

    def test_invalid_category_no_exception(self, tool):
        """Bad category must return an error string, not raise."""
        out = tool._run('{"category": "FakeIndex123"}')
        assert isinstance(out, str)
        assert "Unknown category" in out or "Available" in out

    def test_run_completes_within_timeout(self, tool):
        """Full scan should finish within 5 minutes if cache is warm."""
        params = json.dumps({"category": "Nifty100", "top_n": 20,
                             "cache_dir": CACHE_DIR})
        t0  = time.perf_counter()
        out = tool._run(params)
        elapsed = time.perf_counter() - t0
        print(f"\n⏱  Completed in {elapsed:.1f}s")
        assert elapsed < 300, f"Run took {elapsed:.0f}s – cache may be cold"

    # ── Optional: other categories ─────────────────────────────────────

    @pytest.mark.parametrize("category", ["Midcap150", "Smallcap250", "Nifty500"])
    def test_other_categories_return_output(self, tool, category):
        params = json.dumps({"category": category, "top_n": 5,
                             "cache_dir": CACHE_DIR})
        out = tool._run(params)
        # Must be a real result or a graceful no-pass message – never blank
        assert len(out) > 50, f"{category} returned unexpectedly short output"


# ---------------------------------------------------------------------------
# Output structure assertions
# ---------------------------------------------------------------------------

class TestOutputStructure:

    @pytest.fixture(scope="class")
    def live_output(self, tool):
        params = json.dumps({"category": "Nifty100", "top_n": 10,
                             "cache_dir": CACHE_DIR})
        return tool._run(params)

    def test_has_header_banner(self, live_output):
        assert "MOMENTUM BACKBONE" in live_output

    def test_has_metadata_section(self, live_output):
        assert "Category" in live_output
        assert "Returned"  in live_output
        assert "Passed"   in live_output

    def test_tickers_are_ns_suffixed(self, live_output):
        """All NSE tickers should carry the .NS suffix."""
        tickers_line = ""
        for line in live_output.splitlines():
            if "TICKERS" in line and ":" in line:
                tickers_line = line
                break

        if tickers_line:
            tickers = [t.strip() for t in tickers_line.split(":", 1)[-1].split(",")
                       if t.strip()]
            for t in tickers:
                assert t.endswith(".NS"), f"Ticker '{t}' missing .NS suffix"

    def test_wms_scores_are_numeric(self, live_output):
        """Every data row should have a parseable WMS value."""
        import re
        # Rows look like: "1     INFY.NS            77.54  0.023 ..."
        row_pattern = re.compile(r"^\d+\s+\S+\.NS\s+([\d.]+)", re.MULTILINE)
        matches = row_pattern.findall(live_output)
        assert len(matches) > 0, "No data rows found in output"
        for wms_str in matches:
            assert float(wms_str) >= 0, f"Invalid WMS value: {wms_str}"

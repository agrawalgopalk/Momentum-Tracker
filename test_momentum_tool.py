"""
test_momentum_tool.py – Test MomentumBackboneTool without any CrewAI involvement.

Run:
    python test_momentum_tool.py
    python test_momentum_tool.py --category Midcap150 --top_n 10
    python test_momentum_tool.py --category Nifty500 --top_n 5 --cache_dir ./my_cache
"""

import argparse
import json
import sys
import time

# ── Import the tool directly (no CrewAI needed) ───────────────────────────
from momentum_tool import MomentumBackboneTool


def run_test(category: str, top_n: int, cache_dir: str) -> None:

    tool = MomentumBackboneTool()

    # ── Test 1: default params (empty input) ──────────────────────────────
    print("\n" + "═" * 60)
    print("TEST 1 – Empty input (uses all defaults)")
    print("═" * 60)
    result = tool._run("{}")
    print(result)

    # ── Test 2: plain category string ─────────────────────────────────────
    print("\n" + "═" * 60)
    print(f"TEST 2 – Plain string input: '{category}'")
    print("═" * 60)
    result = tool._run(category)
    print(result)

    # ── Test 3: full JSON params ───────────────────────────────────────────
    print("\n" + "═" * 60)
    print(f"TEST 3 – JSON input: category={category}, top_n={top_n}")
    print("═" * 60)
    params = json.dumps({"category": category, "top_n": top_n, "cache_dir": cache_dir})
    t0 = time.perf_counter()
    result = tool._run(params)
    elapsed = time.perf_counter() - t0
    print(result)
    print(f"\n⏱  Completed in {elapsed:.1f}s")

    # ── Test 4: bad category (error handling) ─────────────────────────────
    print("\n" + "═" * 60)
    print("TEST 4 – Invalid category (should return a clean error message)")
    print("═" * 60)
    result = tool._run('{"category": "InvalidIndex"}')
    print(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test MomentumBackboneTool directly")
    parser.add_argument("--category",  default="Nifty100",    help="Stock universe to scan")
    parser.add_argument("--top_n",     default=10, type=int,  help="Number of top stocks to return")
    parser.add_argument("--cache_dir", default="./momentum_tracker/mps_cache", help="Price data cache directory")
    args = parser.parse_args()

    run_test(args.category, args.top_n, args.cache_dir)

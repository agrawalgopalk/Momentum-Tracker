# conftest.py  (place at Momentum-Tracker/ — the project root)
#
# Pytest loads this file automatically before running any test.
# It adds the two directories that tests need to import from:
#
#   1. Project root  →  momentum_tool.py, llm_config.py, main.py
#   2. momentum_tracker/src  →  config.py, database_manager.py, …

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent                        # Momentum-Tracker/
SRC  = ROOT / "momentum_tracker" / "src"                     # momentum_tracker/src/

for p in (ROOT, SRC):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

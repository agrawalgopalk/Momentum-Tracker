import os
import sys
from pathlib import Path

# Add project subdirectories to sys.path so tests can import modules directly
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "crew"))
sys.path.insert(0, str(root / "streamlite_app"))
sys.path.insert(0, str(root / "momentum_tracker"))
sys.path.insert(0, str(root / "momentum_tracker" / "src"))

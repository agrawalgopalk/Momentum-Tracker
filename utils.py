# ─────────────────────────────────────────────────────────────────────────────
# Normalisation for symbol-field aliases in analyst output
# ─────────────────────────────────────────────────────────────────────────────

import re

# One-time compiled pattern — put this at module level in scheduler.py
# _SYMBOL_ALIASES = re.compile(
#     r'\b(TICKER|ticker|Ticker|SCRIP|scrip|Scrip|STOCK|stock|Stock)\b'
# )

_SYMBOL_ALIASES = re.compile(
    r'\b(ticker|scrip|stock|counter|instrument)\b', 
    re.IGNORECASE
)

def normalise_ticker(line: str) -> str:
    """Replace all symbol-field aliases with SYMBOL, preserving rest of line."""
    return _SYMBOL_ALIASES.sub("SYMBOL", line)


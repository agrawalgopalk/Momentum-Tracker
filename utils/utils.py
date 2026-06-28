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

# Helper to remove emojis and clean whitespace
def clean_text(text: str) -> str:
    # Remove emojis (🔴, 🟡, 🟢)
    text = re.sub(r'[🔴🟡🟢]', '', text)
    # Strip whitespace, quotes, and common arrows/delimiters that might linger
    return text.replace("→", "").replace('"', '').strip()

def normalize_symbol(symbol: str) -> str:
    """Consistently formats ticker symbols (e.g. INFY -> INFY.NS)."""
    sym = symbol.strip().upper()
    if not sym:
        return ""
    return sym if "." in sym else f"{sym}.NS"


import re

# One-time compiled pattern — put this at module level in scheduler.py
# _SYMBOL_ALIASES = re.compile(
#     r'\b(TICKER|ticker|Ticker|SCRIP|scrip|Scrip|STOCK|stock|Stock)\b'
# )

_SYMBOL_ALIASES = re.compile(
    r'\b(ticker|scrip|stock|counter|instrument)\b', 
    re.IGNORECASE
)

def _normalise(line: str) -> str:
    """Replace all symbol-field aliases with SYMBOL, preserving rest of line."""
    return _SYMBOL_ALIASES.sub("SYMBOL", line)


def _parse_alerts(text: str) -> list[dict]:
    alerts: list[dict] = []
    current: dict = {}
    active_key = None  # Tracks the field we are currently appending to

    # Mapping logic for headers
    # We use a dictionary to easily identify which header is being read
    field_map = {
        "SYMBOL": "symbol",
        "ALERT": "alert_level",
        "CONFIDENCE": "confidence",
        "TRIGGER SUMMARY": "trigger",
        "RECOMMENDED ACTION": "action",
        "RISK FLAGS": "risk_flags",
        "NEWS STORIES CONSIDERED": "raw_news",
    }

    for line in text.splitlines():
        # 1. Clean line
        clean_line = line.replace("|", "").replace("═", "").strip()
        if not clean_line:
            continue

        # 2. Check if this line is a Header
        # We normalise the line to handle aliases, then check if it starts with one of our known keys
        norm_line = _normalise(clean_line).upper()
        
        found_header = None
        for header, key in field_map.items():
            if norm_line.startswith(header):
                found_header = key
                break
        
        if found_header:
            active_key = found_header
            # If the header contains the value on the same line (e.g. "SYMBOL: INFY.NS")
            if ":" in clean_line:
                val = clean_line.split(":", 1)[1].strip()
                
                # If we encounter a new SYMBOL header, save the previous record
                if active_key == "symbol" and "symbol" in current:
                    alerts.append(current)
                    current = {}
                
                current[active_key] = val
            
            # If header is on its own line (e.g. "TRIGGER SUMMARY:"), 
            # we just initialized the active_key, so we wait for content on the next iteration
            continue

        # 3. Accumulate content if not a header
        elif active_key and active_key in current:
            # Append multi-line content to the existing value
            current[active_key] += f" {clean_line}"
        elif active_key:
            # First line of content for a header that didn't have value on same line
            current[active_key] = clean_line

    # Append the final record
    if current.get("symbol") and current.get("alert_level"):
        alerts.append(current)

    return alerts



input_str = """  ════════════════════════════════════════ 
  SYMBOL     : INFY.NS
  ALERT      : 🟢 GREEN
  CONFIDENCE : HIGH
  ════════════════════════════════════════
  TRIGGER SUMMARY (1–2 sentences):
    INFY.NS has had no material news over the past 7 days, indicating a stable period with no significant negative developments. This scenario supports
  maintaining a green alert.

  NEWS STORIES CONSIDERED:
    1. No material news in past 7 days — NEUTRAL / NEGLIGIBLE

  RECOMMENDED ACTION:
    🟢 GREEN  → "Hold. No action required. Review again in 7 days."

  RISK FLAGS (list up to 3, or "None"):
    None

"""
  
if __name__ == "__main__":
    alerts = _parse_alerts(input_str)
    print(alerts)
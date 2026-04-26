"""
portfolio_monitor.py – CrewAI pipeline that watches your HELD positions
and fires RED / YELLOW / GREEN alerts based on live news analysis.

Usage
─────
  from portfolio_monitor import run_monitor

  held = [
      {"ticker": "RELIANCE.NS", "buy_price": 2850.0, "qty": 50},
      {"ticker": "INFY.NS",     "buy_price": 1540.0, "qty": 100},
      {"ticker": "HDFCBANK.NS", "buy_price": 1620.0, "qty": 80},
  ]

  alerts = run_monitor(held)
  print(alerts)

Or run directly:
  python portfolio_monitor.py

Alert levels
────────────
  🔴 RED    – Exit immediately / place stop-loss order.
              Triggered by: governance failure, fraud allegation, revenue
              guidance cut >10%, heavy FII selling, regulatory ban,
              management exodus, rating downgrade by CRISIL/Moody's.

  🟡 YELLOW – Watch closely, consider trimming position.
              Triggered by: earnings miss, promoter pledge increase,
              sector headwind, analyst downgrade, volume-less rally, or
              any single negative catalyst without offsetting positives.

  🟢 GREEN  – Thesis intact, hold position.
              Triggered by: earnings beat, positive management guidance,
              institutional accumulation, sector tailwind, or absence
              of material negative news.

Architecture
────────────
  Agent 1 – News Scanner   : fetches live news per ticker (SerperDevTool)
  Agent 2 – Alert Classifier: scores each story for impact & severity
  Two sequential tasks → final alert report printed to stdout.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from crewai import Agent, Crew, Task
from search_tool_setup import search_tool  # no API key needed

from llm_config import LLMConfig

# ─────────────────────────────────────────────────────────────────────────────
# LLM setup
# ─────────────────────────────────────────────────────────────────────────────

llm_scanner    = LLMConfig.get_llm(role="scanner")     # fast / cheap model OK
llm_classifier = LLMConfig.get_llm(role="analyst")

# ─────────────────────────────────────────────────────────────────────────────
# Shared tool
# ─────────────────────────────────────────────────────────────────────────────

# search_tool imported from search_tool_setup

# ─────────────────────────────────────────────────────────────────────────────
# Agents
# ─────────────────────────────────────────────────────────────────────────────

news_scanner = Agent(
    role="Portfolio News Scanner",
    goal=(
        "For each held stock, retrieve the latest news (last 7 days) and "
        "summarise every potentially market-moving story in a structured format."
    ),
    backstory=(
        "You are a real-time market intelligence analyst. You monitor NSE-listed "
        "stocks owned by a retail investor and flag any news that could affect "
        "the stock price significantly. You are rigorous, concise, and never "
        "miss a corporate action, regulatory filing, or earnings announcement."
    ),
    llm=llm_scanner,
    tools=[search_tool],
    verbose=True,
    allow_delegation=False,
    # ADD THIS LINE TO PREVENT HALLUCINATED XML
    system_prompt="You are an AI with access to the 'web_search' tool. "
                  "When you need to search the web, you MUST invoke the tool directly. "
                  "DO NOT write XML tags, do not output <function=...> strings, "
                  "and do not simulate tool calls as text. Use the tool interface provided."
)

alert_classifier = Agent(
    role="Portfolio Alert Classifier",
    goal=(
        "For each news summary, assess the potential price impact and assign a "
        "RED / YELLOW / GREEN alert level with a recommended action."
    ),
    backstory=(
        "You are a risk-management specialist for a long-only Indian equity "
        "portfolio. Your job is to protect capital by catching negative catalysts "
        "early – before they fully appear in price. You apply a systematic "
        "severity framework and are deliberately conservative: when in doubt you "
        "escalate to RED rather than miss a real threat."
    ),
    llm=llm_classifier,
    verbose=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# Task factory (created fresh per run so held positions are injected)
# ─────────────────────────────────────────────────────────────────────────────

def _build_tasks(held: list[dict]) -> tuple[Task, Task]:
    """
    Build the two monitoring tasks from the current held-positions list.

    Parameters
    ----------
    held : list of dicts with keys: ticker, buy_price, qty
    """
    # ── Portfolio snapshot for the prompt ─────────────────────────────────
    portfolio_lines = "\n".join(
        f"  • {h['ticker']:20s}  buy @ ₹{h['buy_price']:.2f}  qty {h['qty']}"
        for h in held
    )
    ticker_csv = ", ".join(h["ticker"] for h in held)
    as_of      = datetime.now().strftime("%Y-%m-%d %H:%M IST")

    # ── Task 1: News collection ────────────────────────────────────────────
    task_news = Task(
        description=f"""
As of {as_of}, the investor holds the following positions:

{portfolio_lines}

For EACH ticker above, search for news published in the LAST 7 DAYS using
queries of the form:
  "{'{ticker}'} NSE news site:economictimes.com OR site:moneycontrol.com OR site:bseindia.com"

For each story found, output a block in this EXACT format:

TICKER: {{ticker}}
HEADLINE: {{headline}}
SOURCE: {{source name}}
DATE: {{publication date}}
SUMMARY: {{2–3 sentence factual summary of the story}}
SENTIMENT: POSITIVE | NEGATIVE | NEUTRAL
PRICE_IMPACT_ESTIMATE: HIGH | MEDIUM | LOW | NEGLIGIBLE
RAW_URL: {{url if available}}
---

Rules:
• Include ALL material stories, not just negative ones.
• If no news found in 7 days, output:
    TICKER: {{ticker}}
    HEADLINE: No material news in past 7 days
    SENTIMENT: NEUTRAL
    PRICE_IMPACT_ESTIMATE: NEGLIGIBLE
    ---
• Do NOT hallucinate headlines. If you are not certain a story is real,
  skip it and note "Skipped: could not verify."
• Search separately for each ticker – do not batch them into one query.

Tickers to scan: {ticker_csv}
""",
        agent=news_scanner,
        expected_output=(
            "One structured TICKER / HEADLINE / SUMMARY / SENTIMENT / "
            "PRICE_IMPACT_ESTIMATE block per story per ticker, separated by '---'."
        ),
    )

    # ── Task 2: Alert classification ───────────────────────────────────────
    #
    # SEVERITY MATRIX (encode this logic in the prompt explicitly):
    #
    #   RED triggers (exit immediately):
    #     - Fraud allegation / SEBI investigation
    #     - Revenue / EPS guidance cut > 10 %
    #     - Management exodus (CEO, CFO, promoter sell-off)
    #     - Credit rating downgrade (CRISIL, ICRA, Moody's)
    #     - Regulatory ban or license cancellation
    #     - FII net selling > 3 % of float in one week
    #     - Promoter pledge > 60 % of holding
    #
    #   YELLOW triggers (watch, consider trim):
    #     - Quarterly earnings miss (PAT down YoY)
    #     - Promoter pledge increase > 10 % since last quarter
    #     - Sector regulatory headwind (new compliance cost)
    #     - Analyst downgrade (at least one major broker)
    #     - Insider selling (not promoter)
    #     - Price > 20 % above 200-DMA with no earnings catalyst
    #
    #   GREEN (hold):
    #     - Earnings beat, positive guidance, block deal accumulation,
    #       sector tailwind, no material negative news
    # ─────────────────────────────────────────────────────────────────────
    task_classify = Task(
        description=f"""
You will receive a structured news digest for the investor's held positions.
Your job is to classify each ticker and produce an actionable alert report.

═══════════════════════════════════════════════════════
HELD POSITIONS (reference for context)
═══════════════════════════════════════════════════════
{portfolio_lines}

═══════════════════════════════════════════════════════
CLASSIFICATION FRAMEWORK
═══════════════════════════════════════════════════════

🔴 RED – EXIT IMMEDIATELY
Triggered by ANY ONE of:
  • Fraud allegation / SEBI / ED investigation
  • Revenue or EPS guidance cut > 10%
  • CEO / CFO / MD resignation or promoter bulk sell-off
  • Credit rating downgrade (CRISIL, ICRA, Moody's, India Ratings)
  • Regulatory ban or licence cancellation / suspension
  • FII net selling exceeding 3% of float in a single week
  • Promoter pledge > 60% of total promoter holding
  • Any NEGATIVE story with PRICE_IMPACT_ESTIMATE = HIGH

🟡 YELLOW – WATCH CLOSELY / CONSIDER TRIMMING
Triggered by ANY TWO of (or one HIGH-MEDIUM negative):
  • Quarterly PAT miss vs consensus
  • Promoter pledge increase > 10% vs prior quarter
  • New regulatory compliance burden (cost impact)
  • Major broker downgrade (sell / underperform)
  • Sector input-cost spike (oil, steel, pharma API prices)
  • Unusual volume without matching positive news
  • Any NEGATIVE story with PRICE_IMPACT_ESTIMATE = MEDIUM

🟢 GREEN – HOLD / THESIS INTACT
  • Positive or neutral news only
  • Earnings beat + positive guidance
  • Institutional accumulation
  • No material negative story in 7 days

═══════════════════════════════════════════════════════
CONSERVATIVE BIAS RULE
═══════════════════════════════════════════════════════
When you are uncertain between GREEN and YELLOW, default to YELLOW.
When you are uncertain between YELLOW and RED, default to RED.
Capital protection takes priority over avoiding a missed gain.

═══════════════════════════════════════════════════════
REQUIRED OUTPUT FORMAT (produce this for each ticker)
═══════════════════════════════════════════════════════

════════════════════════════════════════
TICKER     : {{ticker}}
ALERT      : 🔴 RED | 🟡 YELLOW | 🟢 GREEN
CONFIDENCE : HIGH | MEDIUM | LOW
════════════════════════════════════════
TRIGGER SUMMARY (1–2 sentences):
  What specific news or data point drove this alert level?

NEWS STORIES CONSIDERED:
  1. {{headline}} — {{SENTIMENT}} / {{PRICE_IMPACT_ESTIMATE}}
  2. (repeat for each story)

RECOMMENDED ACTION:
  🔴 RED    → "Place stop-loss / exit at market open. Target max loss ₹X
               (based on buy price ₹Y and current estimated loss)."
  🟡 YELLOW → "Monitor daily. Consider trimming {{X}}% of position if
               situation worsens within {{N}} trading days."
  🟢 GREEN  → "Hold. No action required. Review again in 7 days."

RISK FLAGS (list up to 3, or "None"):
  e.g. Governance risk | Leverage spike | Regulatory overhang
════════════════════════════════════════

═══════════════════════════════════════════════════════
PORTFOLIO-LEVEL ALERT SUMMARY (after all tickers)
═══════════════════════════════════════════════════════
• Total RED alerts    : N
• Total YELLOW alerts : N
• Total GREEN signals : N
• Immediate actions required: (list tickers needing action)
• Overall portfolio risk posture: LOW | MODERATE | HIGH | CRITICAL

End with a 2-sentence narrative on the overall portfolio health.
""",
        agent=alert_classifier,
        context=[task_news],
        expected_output=(
            "Per-ticker alert blocks (TICKER / ALERT / CONFIDENCE / TRIGGER SUMMARY "
            "/ NEWS STORIES / RECOMMENDED ACTION / RISK FLAGS) followed by a "
            "portfolio-level summary table."
        ),
    )

    return task_news, task_classify


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_monitor(held: list[dict[str, Any]]) -> str:
    """
    Run the portfolio monitoring crew for the given held positions.

    Parameters
    ----------
    held : list of dicts
        Each dict must have:
          ticker     : str  – e.g. "RELIANCE.NS"
          buy_price  : float – your average cost price in INR
          qty        : int   – number of shares held

    Returns
    -------
    str
        The full alert report as a formatted string.
    """
    if not held:
        return "No held positions provided."

    task_news, task_classify = _build_tasks(held)

    monitor_crew = Crew(
        agents=[news_scanner, alert_classifier],
        tasks=[task_news, task_classify],
        verbose=True,
    )

    result = monitor_crew.kickoff()

    header = (
        "\n" + "═" * 65 + "\n"
        "  PORTFOLIO MONITOR — ALERT REPORT\n"
        f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M IST')}\n"
        + "═" * 65 + "\n"
    )
    return header + str(result)


# ─────────────────────────────────────────────────────────────────────────────
# Standalone test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # ── Replace with your actual positions ───────────────────────────────
    my_portfolio = [
        {"ticker": "RELIANCE.NS",  "buy_price": 2850.0, "qty": 50},
        {"ticker": "INFY.NS",      "buy_price": 1540.0, "qty": 100},
        {"ticker": "HDFCBANK.NS",  "buy_price": 1620.0, "qty": 80},
        {"ticker": "TATAMOTORS.NS","buy_price":  960.0, "qty": 120},
        {"ticker": "ADANIENT.NS",  "buy_price": 2700.0, "qty": 30},
    ]

    report = run_monitor(my_portfolio)
    print(report)

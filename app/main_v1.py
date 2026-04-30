"""
main.py – CrewAI orchestration for the Momentum Portfolio System.

Crew pipeline
─────────────
  Task 1 (Momentum Scout)
      Runs MomentumBackboneTool against a configurable NSE index category.
      Produces a ranked table + clean ticker list.

  Task 2 (Fundamental Analyst)
      Receives Task 1's ranked tickers, applies macro / sentiment analysis,
      and classifies each stock as BUY / HOLD / AVOID with a rationale.

Usage
─────
  python main.py
"""

from crewai import Agent, Task, Crew
from llm_config import LLMConfig
from momentum_tool import MomentumBackboneTool

# ─────────────────────────────────────────────────────────────────────────────
# LLM configuration
# ─────────────────────────────────────────────────────────────────────────────

llm_scout    = LLMConfig.get_llm(role="scout")
llm_analyst  = LLMConfig.get_llm(role="analyst")

# ─────────────────────────────────────────────────────────────────────────────
# Agents
# ─────────────────────────────────────────────────────────────────────────────

scout = Agent(
    role="Momentum Scout",
    goal=(
        "Identify the highest-momentum NSE stocks by running the quantitative "
        "momentum backbone and returning a clean, ranked candidate list."
    ),
    backstory=(
        "You are a quantitative analyst specialising in price-momentum strategies "
        "for Indian equity markets. You operate the multi-factor WMS scoring engine "
        "and surface the stocks with the strongest risk-adjusted momentum."
    ),
    llm=llm_scout,
    tools=[MomentumBackboneTool()],
    verbose=True,
)

analyst = Agent(
    role="Fundamental & Sentiment Analyst",
    goal=(
        "For each momentum candidate, assess macro context, recent news sentiment, "
        "and fundamental health. Classify each as BUY / HOLD / AVOID."
    ),
    backstory=(
        "You are a seasoned fundamental analyst who cross-checks quantitative signals "
        "with qualitative macro and sector narratives. You provide concise, "
        "actionable assessments that complement pure momentum rankings."
    ),
    llm=llm_analyst,
    verbose=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# Tasks
# ─────────────────────────────────────────────────────────────────────────────

# ── Task 1: Momentum Scan ─────────────────────────────────────────────────
#
# The agent must call MomentumBackboneTool.  Pass a JSON string to customise:
#   '{"category": "Nifty100", "top_n": 20}'
# or just a category name string, e.g. '"Midcap150"'.
# Leave as '{}' to use system defaults (Nifty100, top 20).
# ─────────────────────────────────────────────────────────────────────────────
task_scan = Task(
    description=(
        "Run the Momentum Strategy Tool with the following parameters:\n"
        '  {"category": "Nifty100", "top_n": 20}\n\n'
        "The tool will score every stock in the Nifty100 universe using the "
        "multi-factor WMS (Weighted Momentum Score) pipeline – computing RSI, "
        "MFI, CCI, rate-of-change composites, and relative strength vs the "
        "Nifty 50 benchmark – then apply price, volume, and percentile filters.\n\n"
        "Your output must include:\n"
        "  1. The full ranked table exactly as returned by the tool.\n"
        "  2. The plain comma-separated ticker list on its own line "
        "     (label it 'TICKERS:') so the next agent can parse it easily."
    ),
    agent=scout,
    expected_output=(
        "A ranked table of up to 20 momentum candidates with columns "
        "Rank, Symbol, WMS, RS, RSI, MFI, CCI, followed by a "
        "'TICKERS: TICKER1.NS, TICKER2.NS, …' line."
    ),
)

# ── Task 2: Fundamental & Sentiment Classification ────────────────────────
task_analysis = Task(
    description=(
        "You will receive a ranked list of high-momentum NSE stocks from the "
        "previous task (look for the 'TICKERS:' line).\n\n"
        "For each ticker:\n"
        "  1. Briefly assess the macro / sector backdrop (1–2 sentences).\n"
        "  2. Note any significant recent news or earnings surprises.\n"
        "  3. Classify as one of: BUY | HOLD | AVOID, with a one-line rationale.\n\n"
        "Prioritise stocks where momentum is supported by improving fundamentals "
        "or positive sector tailwinds. Flag any stock where momentum may be "
        "driven by short-term noise rather than structural strength.\n\n"
        "Format your output as a table:\n"
        "  Symbol | Classification | Rationale"
    ),
    agent=analyst,
    context=[task_scan],      # receives Task 1 output automatically
    expected_output=(
        "A table with columns Symbol | Classification | Rationale for every "
        "ticker provided, followed by a 2–3 sentence portfolio-level summary."
    ),
)

# ─────────────────────────────────────────────────────────────────────────────
# Crew
# ─────────────────────────────────────────────────────────────────────────────

trading_crew = Crew(
    agents=[scout, analyst],
    tasks=[task_scan, task_analysis],
    verbose=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    result = trading_crew.kickoff()
    print("\n" + "═" * 65)
    print("FINAL CREW OUTPUT")
    print("═" * 65)
    print(result)

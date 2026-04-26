"""
main.py – CrewAI orchestration for the Momentum Portfolio System.

Crew pipeline
─────────────
  Task 1 (Momentum Scout)
      Runs MomentumBackboneTool against a configurable NSE index category.
      Produces a ranked table + clean ticker list.

  Task 2 (Fundamental Analyst)
      Receives Task 1's ranked tickers, applies structured macro / fundamental
      analysis with a confidence score and risk checklist per stock.

Usage
─────
  python main.py
"""

from crewai import Agent, Task, Crew
from crewai_tools import SerperDevTool          # web search for live context
from llm_config import LLMConfig
from momentum_tool import MomentumBackboneTool

# ─────────────────────────────────────────────────────────────────────────────
# LLM configuration
# ─────────────────────────────────────────────────────────────────────────────

llm_scout   = LLMConfig.get_llm(role="scout")
llm_analyst = LLMConfig.get_llm(role="analyst")

# ─────────────────────────────────────────────────────────────────────────────
# Tools
# ─────────────────────────────────────────────────────────────────────────────

search_tool = SerperDevTool()   # grants the analyst live news / earnings data

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
        "For each momentum candidate, deliver a structured, evidence-based "
        "assessment covering sector backdrop, recent catalysts, fundamental health, "
        "and a BUY / HOLD / AVOID classification with a 1–5 confidence score."
    ),
    backstory=(
        "You are a seasoned buy-side analyst covering Indian equities. "
        "You combine top-down macro views (RBI policy, FII flows, commodity cycles) "
        "with bottom-up checks (revenue growth trajectory, debt load, promoter holding, "
        "recent quarterly surprises). You are explicitly trained to spot when "
        "price momentum is unsupported by fundamentals and flag it as a WARNING. "
        "Your output is consumed directly by a portfolio manager making position decisions."
    ),
    llm=llm_analyst,
    tools=[search_tool],        # live news + earnings search
    verbose=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# Tasks
# ─────────────────────────────────────────────────────────────────────────────

# ── Task 1: Momentum Scan ─────────────────────────────────────────────────
task_scan = Task(
    description=(
        "Run the Momentum Strategy Tool with the following parameters:\n"
        '  {"category": "Nifty100", "top_n": 20}\n\n'
        "The tool scores every stock in the Nifty100 universe using the "
        "multi-factor WMS (Weighted Momentum Score) pipeline – RSI, MFI, CCI, "
        "rate-of-change composites, and relative strength vs Nifty 50 – then "
        "applies price, volume, and percentile filters.\n\n"
        "Your output MUST include:\n"
        "  1. The full ranked table exactly as returned by the tool.\n"
        "  2. A plain comma-separated ticker list on its own line "
        "     labelled 'TICKERS:' so the next agent can parse it easily.\n"
        "  3. A one-line note on any obvious cluster (e.g. 'Heavy IT sector "
        "     concentration – 8 of 20 stocks are IT')."
    ),
    agent=scout,
    expected_output=(
        "A ranked table of up to 20 momentum candidates with columns "
        "Rank | Symbol | WMS | RS | RSI | MFI | CCI, followed by "
        "'TICKERS: TICKER1.NS, TICKER2.NS, …' and a sector-concentration note."
    ),
)

# ── Task 2: Structured Fundamental & Sentiment Classification ─────────────
#
# PROMPT DESIGN RATIONALE
# ───────────────────────
# The original prompt was open-ended, giving the LLM latitude to produce
# inconsistent, shallow outputs.  The new prompt enforces:
#
#   a) A MANDATORY per-stock analysis template – forces the model to cover
#      every dimension (macro, fundamentals, news, classification) rather
#      than cherry-picking easy ones.
#
#   b) An explicit CONFIDENCE SCORE (1–5) – quantifies how strongly the
#      analyst conviction backs the momentum signal.  Managers can filter
#      on confidence = 4+ for actual trade entry.
#
#   c) A RISK FLAGS section – separates hard stop-loss triggers (fraud,
#      promoter pledging, governance) from softer flags (valuation stretch,
#      sector rotation risk).  These are easy for the LLM to omit unless
#      explicitly required.
#
#   d) CONTRARIAN RULE – instructs the model to downgrade any stock where
#      the momentum is purely technical (price run without earnings support).
#      Without this, LLMs tend to confirm momentum rather than challenge it.
#
#   e) PORTFOLIO-LEVEL SUMMARY – ensures the agent synthesises across names
#      rather than treating each stock independently.
# ─────────────────────────────────────────────────────────────────────────────

task_analysis = Task(
    description="""
You will receive a ranked list of high-momentum NSE stocks from the previous
task (look for the 'TICKERS:' line).

═══════════════════════════════════════════════════════
STEP 1 — GATHER LIVE CONTEXT (use your search tool)
═══════════════════════════════════════════════════════
For each ticker, search for:
  • Latest quarterly earnings (revenue growth YoY, PAT margin, debt/equity)
  • Significant news in the last 30 days (M&A, management changes, regulatory
    actions, FII/DII buying patterns, block deals)
  • Sector-level macro news (commodity prices, government policy, interest-rate
    sensitivity)

Search query template: "{TICKER} NSE earnings news 2024"

═══════════════════════════════════════════════════════
STEP 2 — PER-STOCK STRUCTURED ANALYSIS
═══════════════════════════════════════════════════════
For EACH ticker produce the following block exactly:

┌─────────────────────────────────────────────────────────────┐
│ SYMBOL: {TICKER}                                            │
│ CLASSIFICATION: BUY | HOLD | AVOID                          │
│ CONFIDENCE: 1–5  (1=very low, 5=very high conviction)       │
├─────────────────────────────────────────────────────────────┤
│ SECTOR BACKDROP (1–2 sentences)                             │
│   State current macro / sector tailwind or headwind.        │
│                                                             │
│ FUNDAMENTAL HEALTH (2–3 sentences)                          │
│   Revenue growth trend, margin direction, leverage level.   │
│   Note any recent earnings surprise (beat/miss).            │
│                                                             │
│ NEWS CATALYSTS (1–2 sentences)                              │
│   Key positive or negative news in the last 30 days.        │
│   If no significant news: state "No material news found."   │
│                                                             │
│ MOMENTUM QUALITY CHECK                                      │
│   ✅ SUPPORTED  – momentum backed by improving earnings /   │
│                  positive sector cycle / institutional buy  │
│   ⚠️  STRETCHED  – price has run significantly ahead of     │
│                  fundamentals; caution on fresh entry       │
│   ❌ UNSUPPORTED – purely technical move; fundamentals       │
│                  deteriorating or neutral; avoid            │
│                                                             │
│ RISK FLAGS (list up to 3; use "None" if clean)              │
│   e.g. High promoter pledge | Regulatory overhang |         │
│        Leverage spike | Sector rotation risk                │
│                                                             │
│ ONE-LINE RATIONALE                                          │
│   Single sentence summarising the investment case or why    │
│   you are cautious.                                         │
└─────────────────────────────────────────────────────────────┘

CONTRARIAN RULE (mandatory):
  If WMS rank is top-5 but MOMENTUM QUALITY is STRETCHED or UNSUPPORTED,
  you MUST downgrade the classification by one level (BUY → HOLD,
  HOLD → AVOID) and call it out explicitly in the rationale.

═══════════════════════════════════════════════════════
STEP 3 — PORTFOLIO-LEVEL SUMMARY (3–5 sentences)
═══════════════════════════════════════════════════════
After all stock blocks, write a portfolio-level summary covering:
  a) Top 3 highest-conviction BUYs and why
  b) Any sector concentration risk flagged by the scout
  c) Overall market regime comment (risk-on / risk-off for Indian equities)
  d) Suggested max position count given current conviction spread
""",
    agent=analyst,
    context=[task_scan],
    expected_output=(
        "Per-stock structured blocks (SYMBOL / CLASSIFICATION / CONFIDENCE / "
        "SECTOR BACKDROP / FUNDAMENTAL HEALTH / NEWS CATALYSTS / MOMENTUM QUALITY "
        "CHECK / RISK FLAGS / ONE-LINE RATIONALE) for every ticker, followed by "
        "a 3–5 sentence portfolio-level summary."
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
"""
discovery_crew.py – CrewAI discovery pipeline for the Momentum Portfolio System.

Two modes:
  1. Imported by scheduler.py  →  call build_crew() to get a configured Crew
  2. Run directly              →  python main.py  (manual one-off scan)

The crew logic lives here exactly once. scheduler.py imports it.
"""

from crewai import Agent, Task, Crew
# from crewai.memory import EntityMemory, LongTermMemory, ShortTermMemory
# from crewai import LongTermMemory, ShortTermMemory, EntityMemory
from pathlib import Path

from llm_config import LLMConfig
from momentum_tool import MomentumBackboneTool
from search_tool_setup import search_tool

# _CHROMA_DIR = str(
#     Path(__file__).resolve().parent / "momentum_tracker" / "mps_cache" / "chroma_db"
# )

from logger import get_logger
log = get_logger(__name__)

def _build_agent_and_tasks(category: str = "Nifty100", top_n: int = 20) -> Crew:
    """
    Build and return a fully configured discovery Crew.

    Parameters
    ----------
    category   : NSE universe – Nifty100 | Midcap150 | Smallcap250 | Nifty500
    top_n      : How many top candidates to return
    use_memory : Enable CrewAI long-term/entity/short-term memory (needs ChromaDB).
                 Pass False for quick one-off runs without persistence overhead.

    Returns
    -------
    crewai.Crew  (not yet kicked off — caller decides when to run)
    """
    llm_scout   = LLMConfig.get_llm(role="scout")
    llm_analyst = LLMConfig.get_llm(role="analyst")

    # ── Agents ────────────────────────────────────────────────────────────
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
            "and a BUY / HOLD / AVOID classification with a 1-5 confidence score."
        ),
        backstory=(
            "You are a seasoned buy-side analyst covering Indian equities. "
            "You combine top-down macro views (RBI policy, FII flows, commodity cycles) "
            "with bottom-up checks (revenue growth, debt load, promoter holding, "
            "recent quarterly surprises). You flag when momentum is unsupported by "
            "fundamentals. If memory is available, note whether this stock was seen "
            "in a prior run and whether the thesis has changed."
        ),
        llm=llm_analyst,
        tools=[search_tool],
        verbose=True,
    )

    # ── Tasks ─────────────────────────────────────────────────────────────
    task_scan = Task(
        description=(
            f"Run the Momentum Strategy Tool with: category={category}, top_n={top_n}.\n\n"
            "Your output MUST include:\n"
            "  1. The full ranked table exactly as returned by the tool.\n"
            "  2. A comma-separated ticker list labelled 'TICKERS:' on its own line.\n"
            "  3. A one-line sector concentration note "
            "     (e.g. 'Heavy IT concentration – 8 of 20 stocks are IT')."
        ),
        agent=scout,
        expected_output=(
            "Ranked table (Rank | Symbol | WMS | RS | RSI | MFI | CCI) "
            "followed by 'TICKERS: ...' and a sector concentration note."
        ),
    )

    task_analysis = Task(
        description="""
From the TICKERS: line, for each stock produce this exact block:

SYMBOL: {TICKER}
CLASSIFICATION: BUY | HOLD | AVOID
CONFIDENCE: 1-5
SECTOR BACKDROP: (1-2 sentences – current macro/sector tailwind or headwind)
FUNDAMENTAL HEALTH: (2-3 sentences – revenue trend, margins, leverage, earnings surprise)
NEWS CATALYSTS: (1-2 sentences – key news last 30 days, or "No material news found.")
MOMENTUM QUALITY: SUPPORTED | STRETCHED | UNSUPPORTED
RISK FLAGS: (up to 3 specific flags, or "None")
MEMORY NOTE: (If you have seen this stock in a prior run, state what changed.
              If first time: "First appearance in scan.")
ONE-LINE RATIONALE: (single sentence summary of the call)
---

CONTRARIAN RULE (mandatory):
  If a stock is top-5 by WMS but MOMENTUM QUALITY is STRETCHED or UNSUPPORTED,
  downgrade classification by one level (BUY→HOLD, HOLD→AVOID) and flag it.

Close with a 3-5 sentence portfolio-level summary:
  a) Top 3 highest-conviction BUYs and why
  b) Sector concentration risk
  c) Market regime (risk-on / risk-off for Indian equities)
  d) Suggested max position count given current conviction spread
""",
        agent=analyst,
        context=[task_scan],
        expected_output=(
            "Per-stock structured blocks with all fields including MEMORY NOTE, "
            "followed by a 3-5 sentence portfolio-level summary."
        ),
    )
    
    return {
        "agents": [scout, analyst],
        "tasks": [task_scan, task_analysis]
    }


# ─────────────────────────────────────────────────────────────────────────────
# run_momentun_discory() is the public entry point for both scheduler.py and direct runs.
# ─────────────────────────────────────────────────────────────────────────────

def run_momentun_discovery(category: str = "Nifty100", use_memory: bool = False) -> str:
    
    agent_n_task = _build_agent_and_tasks(category="Nifty100", top_n=20)
    
    # ── Memory (optional) ─────────────────────────────────────────────────
    memory_kwargs = {}
    if use_memory:
        # memory_kwargs = dict(
        #     memory=True,
        #     short_term_memory=ShortTermMemory(),
        #     entity_memory=EntityMemory(),
        #     long_term_memory=LongTermMemory(storage_path=_CHROMA_DIR),
        # )
        memory_kwargs = dict(memory=True)
        # pip install sentence-transformers
        # for the embedding model used by the memory system
        # memory_kwargs = dict(
        #     memory=True,
        #     embedder={
        #         "provider": "huggingface",
        #         "config": {
        #             "model": "sentence-transformers/all-MiniLM-L6-v2"
        #         }
        #     }
        # )

    crew = Crew(
        agents=agent_n_task["agents"],
        tasks=agent_n_task["tasks"],
        verbose=True,
        **memory_kwargs,
    )
    
    result = crew.kickoff()
    return result



if __name__ == "__main__":
    # Run directly for a one-off manual scan: python discovery_crew.py
    # Changed use_memory=True to False for the direct run because
    # when you're running manually to test, you don't want ChromaDB spinning up. 
    # The scheduler always passes use_memory=True explicitly anyway.
    result = run_momentun_discovery(category="Nifty100", use_memory=False)

    log.info("\n" + "=" * 65)
    log.info("FINAL CREW OUTPUT")
    log.info("=" * 65)
    log.info(result)
    
    
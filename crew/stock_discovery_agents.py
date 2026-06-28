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

from .llm_config import LLMConfig
from .momentum_tool import MomentumBackboneTool
from .search_tool_setup import search_tool
from .chart_tool import TechnicalChartTool
from .institutional_flow_tool import InstitutionalFlowTool

# _CHROMA_DIR = str(
#     Path(__file__).resolve().parent / "momentum_tracker" / "mps_cache" / "chroma_db"
# )

from utils import get_logger
log = get_logger(__name__)

def _build_agent_and_tasks(category: str = "Nifty100", top_n: int = 20) -> Crew:
    """
    Build and return a fully configured discovery Crew.

    Parameters
    ----------
    category   : NSE universe – Nifty100 | Midcap150 | Smallcap250 | Nifty500
    top_n      : How many top candidates to return

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
        use_native_tools=False  # <--- FORCE AGENT TO USE STANDARD REACT/TOOL FORMATTING
    )

    chart_analyst = Agent(
        role="Technical Chart Analyst",
        goal=(
            "Analyze price action, support/resistance levels, trend status (EMAs), "
            "and oscillator states (RSI/CCI) for each stock to identify low-risk entry setups."
        ),
        backstory=(
            "You are an expert technical analyst specialising in swing trading and momentum breakouts. "
            "You use EMAs and RSI to evaluate whether stocks are overextended or at low-risk support levels."
        ),
        llm=llm_scout,
        tools=[TechnicalChartTool()],
        verbose=True,
        use_native_tools=False
    )

    flow_analyst = Agent(
        role="FII & DII Flow Analyst",
        goal=(
            "Analyze market-wide institutional flows (FII and DII activity) and stock-specific "
            "bulk/block deals or shareholding patterns to verify institutional interest and volume support."
        ),
        backstory=(
            "You are an expert on institutional order flow and shareholding structures in Indian equity markets. "
            "You track Foreign Portfolio Investment (FPI/FII) and Domestic Institutional Investment (DII) flows. "
            "You identify if smart money (institutions) is buying or selling momentum candidates."
        ),
        llm=llm_analyst,
        tools=[InstitutionalFlowTool(), search_tool],
        verbose=True,
        use_native_tools=False
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
        use_native_tools=False  # <--- FORCE AGENT TO USE STANDARD REACT/TOOL FORMATTING
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

    task_chart_analysis = Task(
        description=(
            "For the comma-separated ticker list under the TICKERS: line, for each stock:\n"
            "  1. Run the Technical Chart Tool to retrieve technical stats.\n"
            "  2. Analyze the technical trend (price relative to 50 EMA and 200 EMA).\n"
            "  3. Evaluate entry safety: is the stock overextended (RSI > 70/75, or trading far above its 50 EMA)?\n"
            "  4. Output a brief technical assessment for each stock detailing trend, RSI, and entry safety (LOW-RISK, MEDIUM-RISK, HIGH-RISK)."
        ),
        agent=chart_analyst,
        context=[task_scan],
        expected_output="Technical chart summaries for each stock."
    )

    task_flow_analysis = Task(
        description=(
            "For the comma-separated ticker list under the TICKERS: line, for each stock:\n"
            "  1. Run the Institutional Flow Tool to check for FII/DII activity, holdings, or aggregate flows.\n"
            "  2. If stock-level database results are empty, use the web search tool to find the latest FII/DII shareholding percentages or recent block/bulk deals (e.g., 'FII DII shareholding INFY').\n"
            "  3. Evaluate institutional sentiment: is the stock being accumulated by smart money (increasing FII/DII percentage, net positive bulk deals)? Or is it being distributed?\n"
            "  4. Output a brief institutional summary for each stock detailing holdings, deals, and trend (ACCUMULATION | DISTRIBUTION | NEUTRAL)."
        ),
        agent=flow_analyst,
        context=[task_scan],
        expected_output="Institutional flow summaries for each stock."
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
ONE-LINE RATIONALE: (single sentence summary combining fundamental health, the chart analyst's entry safety assessment, and the FII/DII analyst's flow assessment. If either flags the stock as high-risk/overextended or distributed by institutional selling, mention that here and consider holding/avoiding.)
---

CONTRARIAN RULE (mandatory):
  If a stock is top-5 by WMS but MOMENTUM QUALITY is STRETCHED or UNSUPPORTED,
  downgrade classification by one level (BUY→HOLD, HOLD→AVOID) and flag it.

Close with a 3-5 sentence portfolio-level summary:
  a) Top 3 highest-conviction BUYs and why
  b) Sector concentration risk
  c) Market regime (risk-on / risk-off for Indian equities, incorporating latest FII/DII aggregate flows)
  d) Suggested max position count given current conviction spread
""",
        agent=analyst,
        context=[task_scan, task_chart_analysis, task_flow_analysis],
        expected_output=(
            "Per-stock structured blocks with all fields including MEMORY NOTE, "
            "followed by a 3-5 sentence portfolio-level summary."
        ),
    )
    
    return {
        "agents": [scout, chart_analyst, flow_analyst, analyst],
        "tasks": [task_scan, task_chart_analysis, task_flow_analysis, task_analysis]
    }


# ─────────────────────────────────────────────────────────────────────────────
# run_momentun_discory() is the public entry point for both scheduler.py and direct runs.
# ─────────────────────────────────────────────────────────────────────────────

def _parse_scan_rows(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].isdigit():
            rows.append({
                "Symbol": parts[1]
            })
    return rows


def run_momentun_discovery(category: str = "Nifty100", use_memory: bool = False) -> str:
    """
    Runs the momentum discovery workflow:
    1. Instantly computes the top momentum stocks using the local MomentumBackboneTool.
    2. Displays the ranked table to the user.
    3. Prompts the user to select one or more stocks for deep analysis.
    4. Triggers the 3-agent analyst crew (Technical, FII/DII, Fundamentals) only on selected stocks.
    """
    print(f"\n=== Running Quantitative Momentum Scan for {category} ===")
    tool = MomentumBackboneTool()
    scout_text = tool._run(category=category, top_n=20)
    print("\n" + scout_text)

    # Parse tickers
    scan_rows = _parse_scan_rows(scout_text)
    if not scan_rows:
        return "Failed to parse scanned stocks."

    all_tickers = [row["Symbol"] for row in scan_rows]

    # Prompt user for input
    try:
        user_input = input(
            "\nEnter stock symbols to perform deep multi-agent analysis on (comma-separated, e.g. INFY, RELIANCE)\n"
            "Or press Enter to analyze the top 5 momentum stocks: "
        ).strip()
    except (KeyboardInterrupt, EOFError):
        user_input = ""

    if user_input:
        selected_tickers = [t.strip().upper() for t in user_input.split(",") if t.strip()]
        # Resolve suffix if missing
        resolved = []
        for t in selected_tickers:
            match = [a for a in all_tickers if a.startswith(t)]
            if match:
                resolved.append(match[0])
            else:
                # Add fallback suffix if not found in list
                resolved.append(t if "." in t else f"{t}.NS")
        selected_tickers = resolved
    else:
        selected_tickers = all_tickers[:5]

    print(f"\n=== Executing Multi-Agent Analysis for: {selected_tickers} ===")
    return process_tickers_batch(selected_tickers)


def run_analyst_batch(
    tickers: list[str], 
    provider: str = None, 
    run_technical: bool = True, 
    run_fii_dii: bool = True
) -> str:
    """
    Runs the technical, institutional, and fundamental analyst agents on a batch of tickers.
    """
    llm_scout = LLMConfig.get_llm(role="scout", provider=provider)
    llm_analyst = LLMConfig.get_llm(role="analyst", provider=provider)
    
    agents = []
    tasks = []
    context_tasks = []
    
    tickers_str = ", ".join(tickers)
    
    if run_technical:
        chart_analyst = Agent(
            role="Technical Chart Analyst",
            goal=(
                "Analyze price action, support/resistance levels, trend status (EMAs), "
                "and oscillator states (RSI/CCI) for each stock to identify low-risk entry setups."
            ),
            backstory=(
                "You are an expert technical analyst specialising in swing trading and momentum breakouts. "
                "You use EMAs and RSI to evaluate whether stocks are overextended or at low-risk support levels."
            ),
            llm=llm_scout,
            tools=[TechnicalChartTool()],
            verbose=True,
            use_native_tools=False
        )
        task_chart_analysis = Task(
            description=f"For each stock in: {tickers_str}\n"
                        "  1. Run the Technical Chart Tool to retrieve technical stats.\n"
                        "  2. Analyze the technical trend (price relative to 50 EMA and 200 EMA).\n"
                        "  3. Evaluate entry safety: is the stock overextended (RSI > 70/75, or trading far above its 50 EMA)?\n"
                        "  4. Output a brief technical assessment for each stock detailing trend, RSI, and entry safety (LOW-RISK, MEDIUM-RISK, HIGH-RISK).",
            agent=chart_analyst,
            expected_output="Technical chart summaries for each stock."
        )
        agents.append(chart_analyst)
        tasks.append(task_chart_analysis)
        context_tasks.append(task_chart_analysis)

    if run_fii_dii:
        flow_analyst = Agent(
            role="FII & DII Flow Analyst",
            goal=(
                "Analyze market-wide institutional flows (FII and DII activity) and stock-specific "
                "bulk/block deals or shareholding patterns to verify institutional interest and volume support."
            ),
            backstory=(
                "You are an expert on institutional order flow and shareholding structures in Indian equity markets. "
                "You track Foreign Portfolio Investment (FPI/FII) and Domestic Institutional Investment (DII) flows. "
                "You identify if smart money (institutions) is buying or selling momentum candidates."
            ),
            llm=llm_analyst,
            tools=[InstitutionalFlowTool(), search_tool],
            verbose=True,
            use_native_tools=False
        )
        task_flow_analysis = Task(
            description=f"For each stock in: {tickers_str}\n"
                        "  1. Run the Institutional Flow Tool to check for FII/DII activity, holdings, or aggregate flows.\n"
                        "  2. If stock-level database results are empty, use the web search tool to find the latest FII/DII shareholding percentages or recent block/bulk deals (e.g., 'FII DII shareholding {TICKER}').\n"
                        "  3. Evaluate institutional sentiment: is the stock being accumulated by smart money (increasing FII/DII percentage, net positive bulk deals)? Or is it being distributed?\n"
                        "  4. Output a brief institutional summary for each stock detailing holdings, deals, and trend (ACCUMULATION | DISTRIBUTION | NEUTRAL).",
            agent=flow_analyst,
            expected_output="Institutional flow summaries for each stock."
        )
        agents.append(flow_analyst)
        tasks.append(task_flow_analysis)
        context_tasks.append(task_flow_analysis)
    
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
            "recent quarterly surprises). You flag when momentum is unsupported by fundamentals."
        ),
        llm=llm_analyst,
        tools=[search_tool],
        verbose=True,
        use_native_tools=False
    )
    
    # Customize explanation depending on which sub-agents are executed
    rationale_desc = "single sentence summary of the fundamental thesis"
    if run_technical and run_fii_dii:
        rationale_desc = "single sentence summary combining fundamental health, the chart analyst's entry safety assessment, and the FII/DII analyst's flow assessment"
    elif run_technical:
        rationale_desc = "single sentence summary combining fundamental health and the chart analyst's entry safety assessment"
    elif run_fii_dii:
        rationale_desc = "single sentence summary combining fundamental health and the FII/DII analyst's flow assessment"

    task_analysis = Task(
        description=f"""
From the list of stocks below, for each stock produce this exact block:

SYMBOL: {{TICKER}}
CLASSIFICATION: BUY | HOLD | AVOID
CONFIDENCE: 1-5
SECTOR BACKDROP: (1-2 sentences – current macro/sector tailwind or headwind)
FUNDAMENTAL HEALTH: (2-3 sentences – revenue trend, margins, leverage, earnings surprise)
NEWS CATALYSTS: (1-2 sentences – key news last 30 days, or "No material news found.")
MOMENTUM QUALITY: SUPPORTED | STRETCHED | UNSUPPORTED
RISK FLAGS: (up to 3 specific flags, or "None")
MEMORY NOTE: First appearance in scan.
ONE-LINE RATIONALE: ({rationale_desc}.)
---

Ensure that key headers (e.g. SYMBOL, CLASSIFICATION, etc.) are written exactly as shown above. DO NOT add any markdown formatting (no asterisks, no list bullets like '-'). Use a plain '---' separator line between stocks.

Stocks to analyze: {tickers_str}
""",
        agent=analyst,
        context=context_tasks,
        expected_output="Per-stock structured blocks with all fields, separated by '---'."
    )
    agents.append(analyst)
    tasks.append(task_analysis)
    
    crew = Crew(
        agents=agents,
        tasks=tasks,
        verbose=True
    )
    
    result = crew.kickoff()
    return str(result)


def process_tickers_batch(
    tickers: list[str], 
    run_technical: bool = True, 
    run_fii_dii: bool = True
) -> str:
    """
    Executes a batch with primary LLM, falling back to secondary LLM on rate limit.
    """
    import os
    from dotenv import load_dotenv, find_dotenv
    load_dotenv(find_dotenv(), override=True)
    
    primary = os.getenv("LLM_PROVIDER", "gemini")
    fallback = "groq" if primary == "gemini" else "gemini"
    
    try:
        log.info(f"Analyzing batch of stocks: {tickers} using primary provider: {primary.upper()}")
        return run_analyst_batch(tickers, provider=primary, run_technical=run_technical, run_fii_dii=run_fii_dii)
    except Exception as e:
        log.warning(f"Primary provider {primary.upper()} failed with error: {e}. Falling back to {fallback.upper()} instantly...")
        try:
            return run_analyst_batch(tickers, provider=fallback, run_technical=run_technical, run_fii_dii=run_fii_dii)
        except Exception as fe:
            log.error(f"Fallback provider {fallback.upper()} also failed. Error: {fe}")
            raise fe


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

"""
search_tool_setup.py
────────────────────
Drop this file next to main.py and portfolio_monitor.py.
Import `search_tool` from here instead of constructing SerperDevTool inline.

Priority order
──────────────
  1. DuckDuckGo  – zero setup, no API key, free forever
  2. Tavily      – better quality, free tier (1000 calls/month)
                   get key at https://tavily.com → set TAVILY_API_KEY in .env
  3. Serper      – highest quality, paid
                   get key at https://serper.dev  → set SERPER_API_KEY in .env

The module tries option 1 first and falls back gracefully.
"""
import os
from pydantic import BaseModel, Field
from typing import Type
from crewai.tools import BaseTool

# pip install -U duckduckgo-search langchain-community
from utils import get_logger
log = get_logger(__name__)

# 1. Define the input schema
class WebSearchInput(BaseModel):
    """Input for web_search tool."""
    query: str = Field(..., description="The search query string to search for on the web.")

# 2. Define the tool class
class WebSearchTool(BaseTool):
    name: str = "web_search"
    description: str = "Search the web using DuckDuckGo. No API key required."
    args_schema: Type[BaseModel] = WebSearchInput

    def _run(self, query: str) -> str:
        # from langchain_community.tools import DuckDuckGoSearchRun
        # ddg = DuckDuckGoSearchRun()
        # return ddg.run(query)
    
        from langchain_community.tools import DuckDuckGoSearchResults
        # Strip site: operators that resolve to Wikipedia
        clean_query = query.replace("site:wt.wikipedia.org", "").strip()
        ddg = DuckDuckGoSearchResults(output_format="list", num_results=5)        
        try:
            return str(ddg.run(clean_query))
        except Exception as e:
            if "wikipedia" in str(e).lower():
                return f"Search unavailable for query: {clean_query}"
            raise

def get_search_tool():
    # ── Option 1: DuckDuckGo (no API key) ────────────────────────────────
    # We check if DuckDuckGo is installable/importable
    try:
        # from langchain_community.tools import DuckDuckGoSearchRun
        # # Verify it can be initialized
        # _ = DuckDuckGoSearchRun() 
        # log.info("[search_tool] Using DuckDuckGo (BaseTool subclass)")
        from langchain_community.tools import DuckDuckGoSearchResults
        _ = DuckDuckGoSearchResults()
        log.info("[search_tool] Using DuckDuckGoSearchResults (BaseTool subclass)")
        return WebSearchTool()
    except Exception as e:
        log.info(f"[search_tool] DuckDuckGo not available: {e}")

    # ── Option 2: Tavily (free tier) ──────────────────────
    tavily_key = os.getenv("TAVILY_API_KEY")
    if tavily_key:
        try:
            from crewai_tools import TavilySearchTool
            log.info("[search_tool] Using Tavily (TAVILY_API_KEY found)")
            return TavilySearchTool()
        except ImportError:
            log.info("[search_tool] TavilySearchTool not installed")

    # ── Option 3: Serper (paid) ──────────────────────────
    serper_key = os.getenv("SERPER_API_KEY")
    if serper_key:
        try:
            from crewai_tools import SerperDevTool
            log.info("[search_tool] Using Serper (SERPER_API_KEY found)")
            return SerperDevTool()
        except ImportError:
            pass

    raise RuntimeError(
        "\n[search_tool] No search tool could be initialised.\n"
        "Install duckduckgo-search or set TAVILY_API_KEY/SERPER_API_KEY."
    )

search_tool = get_search_tool()
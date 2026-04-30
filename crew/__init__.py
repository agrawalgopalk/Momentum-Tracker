"""
crew  –  CrewAI pipeline layer: agents, tasks, tools, LLM config.
Depends on core. Requires LLM API keys to function.
"""
from crew.stock_discovery_agents import run_momentun_discovery
from crew.portfolio_monitor import run_monitor

__all__ = ["run_momentun_discovery", "run_monitor"]


# llm_config, momentum_tool, search_tool_setup are intentionally NOT exported
# — they are internal wiring, callers should never import them directly
import json
from unittest.mock import MagicMock, patch
import pytest

from streamlite_app.scheduler import _parse_scan_rows, _parse_picks, _parse_alerts
from crew.stock_discovery_agents import _build_agent_and_tasks
from crew.portfolio_monitor import _build_agent_and_tasks as _build_monitor_agent_and_tasks

# ─────────────────────────────────────────────────────────────────────────────
# Test Text Parsers
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_scan_rows_valid():
    text = """
    Some header info here...
    Rank  Symbol  WMS  RS  RSI  MFI  CCI
    1     INFY.NS 88.5 0.05 58.0 62.0 110.0
    2     TCS.NS  85.2 0.04 56.0 60.0 105.0
    Invalid line 3
    3     HCLTECH.NS 79.1 0.03 54.0 58.0 95.0
    """
    rows = _parse_scan_rows(text)
    assert len(rows) == 3
    assert rows[0]["Symbol"] == "INFY.NS"
    assert rows[0]["WMS"] == 88.5
    assert rows[0]["RS_Raw"] == 0.05
    assert rows[1]["Symbol"] == "TCS.NS"
    assert rows[2]["Symbol"] == "HCLTECH.NS"
    assert rows[2]["CCI_Raw"] == 95.0

def test_parse_scan_rows_empty_and_malformed():
    assert _parse_scan_rows("") == []
    assert _parse_scan_rows("not enough parts on this line") == []
    assert _parse_scan_rows("1 Symbol WMS RS RSI MFI") == [] # missing CCI
    # test handles conversion errors gracefully
    assert _parse_scan_rows("1 INFY.NS wms_string 0.05 58 62 110") == []

def test_parse_picks_valid():
    text = """
    SYMBOL: INFY.NS
    CLASSIFICATION: BUY
    CONFIDENCE: 4 out of 5
    MOMENTUM QUALITY: SUPPORTED
    SECTOR BACKDROP: Positive macro tailwinds.
    FUNDAMENTAL HEALTH: Strong revenue growth, low debt.
    NEWS CATALYSTS: Solid quarterly report.
    RISK FLAGS: Margin pressure.
    ONE-LINE RATIONALE: High-quality growth play.
    ---
    SYMBOL: TCS.NS
    CLASSIFICATION: HOLD
    CONFIDENCE: 3
    MOMENTUM QUALITY: STRETCHED
    SECTOR BACKDROP: Stagnant IT demand.
    FUNDAMENTAL HEALTH: Stable, high valuation.
    NEWS CATALYSTS: Management transition.
    RISK FLAGS: High attrition.
    ONE-LINE RATIONALE: A bit overvalued here.
    """
    picks = _parse_picks(text)
    assert len(picks) == 2
    assert picks[0]["symbol"] == "INFY.NS"
    assert picks[0]["classification"] == "BUY"
    assert picks[0]["confidence"] == 4
    assert picks[0]["momentum_quality"] == "SUPPORTED"
    assert picks[0]["rationale"] == "High-quality growth play."

    assert picks[1]["symbol"] == "TCS.NS"
    assert picks[1]["classification"] == "HOLD"
    assert picks[1]["confidence"] == 3
    assert picks[1]["momentum_quality"] == "STRETCHED"
    assert picks[1]["rationale"] == "A bit overvalued here."

def test_parse_alerts_valid():
    text = """
    ════════════════════════════════════════ 
    SYMBOL     : INFY.NS
    ALERT      : 🟢 GREEN
    CONFIDENCE : HIGH
    ════════════════════════════════════════
    TRIGGER SUMMARY:
      No material news over the past 7 days.
    
    RECOMMENDED ACTION:
      🟢 GREEN  → Hold.
      
    RISK FLAGS:
      None
      
    NEWS STORIES CONSIDERED:
      No stories found.
    """
    alerts = _parse_alerts(text)
    assert len(alerts) == 1
    assert alerts[0]["symbol"] == "INFY.NS"
    assert "GREEN" in alerts[0]["alert_level"]
    assert alerts[0]["confidence"] == "HIGH"
    assert "No material news" in alerts[0]["trigger"]
    assert "Hold" in alerts[0]["action"]
    assert "None" in alerts[0]["risk_flags"]
    assert "No stories found" in alerts[0]["raw_news"]


# ─────────────────────────────────────────────────────────────────────────────
# Test Crew Configurations (Mocked LLM)
# ─────────────────────────────────────────────────────────────────────────────

@patch("crew.llm_config.LLMConfig.get_llm")
def test_build_discovery_crew(mock_get_llm):
    from crewai import LLM
    mock_get_llm.return_value = LLM(model="gpt-4", api_key="fake")
    
    crew_components = _build_agent_and_tasks(category="Nifty100", top_n=10)
    
    assert len(crew_components["agents"]) == 4
    assert len(crew_components["tasks"]) == 4
    assert crew_components["agents"][0].role == "Momentum Scout"
    assert crew_components["agents"][1].role == "Technical Chart Analyst"
    assert crew_components["agents"][2].role == "FII & DII Flow Analyst"
    assert crew_components["agents"][3].role == "Fundamental & Sentiment Analyst"
    assert crew_components["tasks"][0].description.startswith("Run the Momentum Strategy Tool")

@patch("crew.llm_config.LLMConfig.get_llm")
def test_build_monitor_crew(mock_get_llm):
    from crewai import LLM
    mock_get_llm.return_value = LLM(model="gpt-4", api_key="fake")
    
    held = [{"symbol": "INFY.NS", "buy_price": 1000.0, "qty": 10}]
    scanner, classifier, task_news, task_classify = _build_monitor_agent_and_tasks(held)
    
    assert scanner.role == "Portfolio News Scanner"
    assert classifier.role == "Portfolio Alert Classifier"
    assert task_news.agent == scanner
    assert task_classify.agent == classifier


# ─────────────────────────────────────────────────────────────────────────────
# Test LLM Initializations (to verify all required SDK dependencies are present)
# ─────────────────────────────────────────────────────────────────────────────

def test_llm_config_initialization_gemini():
    from crew.llm_config import LLMConfig
    import os
    
    with patch("dotenv.load_dotenv"), patch.dict(os.environ, {
        "LLM_PROVIDER": "gemini",
        "GEMINI_MODEL": "gemini-2.0-flash",
        "GEMINI_API_KEY": "AIzaSy_fake_test_key"
    }):
        llm = LLMConfig.get_llm()
        assert llm is not None
        assert "gemini-2.0-flash" in llm.model

def test_llm_config_initialization_groq():
    from crew.llm_config import LLMConfig
    import os
    
    with patch("dotenv.load_dotenv"), patch.dict(os.environ, {
        "LLM_PROVIDER": "groq",
        "GROQ_MODEL": "llama-3.3-70b-versatile",
        "GROQ_API_KEY": "gsk_fake_test_key"
    }):
        llm = LLMConfig.get_llm()
        assert llm is not None
        assert "llama-3.3-70b-versatile" in llm.model


def test_llm_interaction_mocked_gemini():
    from crew.llm_config import LLMConfig
    from crewai import Agent, Task, Crew
    import os
    
    with patch("dotenv.load_dotenv"), patch.dict(os.environ, {
        "LLM_PROVIDER": "gemini",
        "GEMINI_MODEL": "gemini-2.0-flash",
        "GEMINI_API_KEY": "AIzaSy_fake_test_key"
    }):
        llm = LLMConfig.get_llm()
        assert llm is not None
        
        # Mock instance-level call method to prevent any network activity or key validation
        llm.call = MagicMock(return_value="Mocked Gemini Agent Response")
        
        test_agent = Agent(
            role="Test Gemini Agent",
            goal="Provide a mocked Gemini response",
            backstory="A test helper agent.",
            llm=llm,
            verbose=False
        )
        
        test_task = Task(
            description="Write a hello message.",
            expected_output="A hello message.",
            agent=test_agent
        )
        
        crew = Crew(agents=[test_agent], tasks=[test_task], verbose=False)
        result = crew.kickoff()
        
        assert "Mocked Gemini Agent Response" in str(result)
        assert llm.call.call_count >= 1


def test_llm_interaction_mocked_groq():
    from crew.llm_config import LLMConfig
    from crewai import Agent, Task, Crew
    import os
    
    with patch("dotenv.load_dotenv"), patch.dict(os.environ, {
        "LLM_PROVIDER": "groq",
        "GROQ_MODEL": "llama-3.3-70b-versatile",
        "GROQ_API_KEY": "gsk_fake_test_key"
    }):
        llm = LLMConfig.get_llm()
        assert llm is not None
        
        # Mock instance-level call method to prevent any network activity or key validation
        llm.call = MagicMock(return_value="Mocked Groq Agent Response")
        
        test_agent = Agent(
            role="Test Groq Agent",
            goal="Provide a mocked Groq response",
            backstory="A test helper agent.",
            llm=llm,
            verbose=False
        )
        
        test_task = Task(
            description="Write a hello message.",
            expected_output="A hello message.",
            agent=test_agent
        )
        
        crew = Crew(agents=[test_agent], tasks=[test_task], verbose=False)
        result = crew.kickoff()
        
        assert "Mocked Groq Agent Response" in str(result)
        assert llm.call.call_count >= 1


def test_parse_picks_markdown_resilient():
    text = """
    * **SYMBOL**: INFY.NS
    - **CLASSIFICATION**: BUY
    * **CONFIDENCE**: 5 out of 5
    - **MOMENTUM QUALITY**: SUPPORTED
    * **SECTOR BACKDROP**: Sector is showing strong momentum.
    - **FUNDAMENTAL HEALTH**: Outstanding balance sheet.
    * **NEWS CATALYSTS**: New client wins.
    - **RISK FLAGS**: High dependence on US market.
    * **ONE-LINE RATIONALE**: Top tier IT pick.
    """
    picks = _parse_picks(text)
    assert len(picks) == 1
    assert picks[0]["symbol"] == "INFY.NS"
    assert picks[0]["classification"] == "BUY"
    assert picks[0]["confidence"] == 5
    assert picks[0]["momentum_quality"] == "SUPPORTED"
    assert picks[0]["rationale"] == "Top tier IT pick."

def test_parse_alerts_markdown_resilient():
    text = """
    - **SYMBOL**     : INFY.NS
    * **ALERT**      : 🔴 RED
    - **CONFIDENCE** : HIGH
    * **TRIGGER SUMMARY**:
      - Extreme price drop today.
      - Negative earnings news.
    - **RECOMMENDED ACTION**:
      * Sell immediately.
    * **RISK FLAGS**:
      - Macro issues.
    - **NEWS STORIES CONSIDERED**:
      - Bloomberg report.
    """
    alerts = _parse_alerts(text)
    assert len(alerts) == 1
    assert alerts[0]["symbol"] == "INFY.NS"
    assert "RED" in alerts[0]["alert_level"]
    assert alerts[0]["confidence"] == "HIGH"
    assert "Extreme price drop today. Negative earnings news." in alerts[0]["trigger"]
    assert "Sell immediately." in alerts[0]["action"]
    assert "Macro issues." in alerts[0]["risk_flags"]
    assert "Bloomberg report." in alerts[0]["raw_news"]




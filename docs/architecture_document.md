# Momentum Portfolio System — System Architecture Document

This document details the architectural design, component structure, class relationships, sequence of operations, mathematical algorithms, and database schema of the **Momentum Portfolio System** (Momentum-Tracker).

---

## 1. Architectural Overview

The Momentum Portfolio System is a hybrid quantitative-AI trading automation platform. It combines raw mathematical momentum strategy with multi-agent LLM reasoning (via CrewAI) for fundamental verification, sentiment checking, and real-time portfolio monitoring.

### High-Level System Architecture

```mermaid
graph TD
    %% Component Definitions
    subgraph Client Layer
        Dash["Django Dashboard (dashboard/views.py)"]
    end

    subgraph Orchestration & Automation
        Sched["APScheduler Service (app/scheduler.py)"]
    end

    subgraph AI Multi-Agent Core [CrewAI Layer]
        Discovery["Stock Discovery Crew (crew/stock_discovery_agents.py)"]
        Monitor["Portfolio Monitor Crew (crew/portfolio_monitor.py)"]
        ScoutAg["Momentum Scout Agent"]
        ChartAg["Technical Chart Analyst Agent"]
        FlowAg["FII & DII Flow Analyst Agent"]
        AnalystAg["Fundamental & Sentiment Analyst Agent"]
        ScanAg["Portfolio News Scanner Agent"]
        ClassAg["Portfolio Alert Classifier Agent"]
    end

    subgraph Quantitative Engine [Quant Layer]
        Selector["Stock Selector (momentum_tracker/src/reporting/stock_selector.py)"]
        Strategy["Momentum Strategy (momentum_tracker/src/strategy/momentum_strategy.py)"]
        Indicators["Technical Indicators (momentum_tracker/src/strategy/technical_indicators.py)"]
        DataDown["Data Downloader (momentum_tracker/src/data/data_downloader.py)"]
        DiskCache["Parquet Price & JSON Info Cache (data_cache/)"]
    end

    subgraph Data & Persistence Layer [Persistence Layer]
        DbFactory["DB Configuration & Factory (momentum_tracker/src/database/db_config.py)"]
        DbInterface["Database Interface (momentum_tracker/src/database/db_interface.py)"]
        SQLite["SQLite Storage (momentum_tracker/src/database/persistence.py)"]
        Postgres["PostgreSQL DB (momentum_tracker/src/database/persistence_postgresql.py)"]
    end

    subgraph Auxiliary Systems
        FiiDii["FII/DII Core Provider (momentum_tracker/src/data/fii_dii_provider.py)"]
    end

    subgraph External Data Sources
        YF["Yahoo Finance API (yfinance)"]
        NSE["NSE India Exchange Website"]
        Serper["Web Search APIs (search_tool_setup.py)"]
    end

    %% Flows & Connections
    Dash -->|Trigger Scan / Read DB| DbFactory
    Dash -->|Run Jobs Directly| Sched
    Sched -->|Execute Scan & Classify| Discovery
    Sched -->|Execute Portfolio Check| Monitor
    
    %% Discovery Crew Connections
    Discovery --> ScoutAg
    Discovery --> ChartAg
    Discovery --> FlowAg
    Discovery --> AnalystAg
    ScoutAg -->|Invokes| Tool["Momentum Strategy Tool (crew/momentum_tool.py)"]
    Tool --> Selector
    ChartAg -->|Technical Tool| ChartTool["Technical Chart Tool (crew/chart_tool.py)"]
    FlowAg -->|Flow Tool| FlowTool["Institutional Flow Tool (crew/institutional_flow_tool.py)"]
    FlowTool --> FiiDii
    AnalystAg -->|Queries News| Serper
    Serper --> ExternalData["Web Search Result (Google/Bing)"]
    
    %% Monitor Crew Connections
    Monitor --> ScanAg
    Monitor --> ClassAg
    ScanAg -->|Searches News| Serper
    
    %% Quant Pipeline Flows
    Selector --> Strategy
    Selector --> Loader["Symbol Loader (momentum_tracker/src/data/symbol_loader.py)"]
    Strategy --> Indicators
    Strategy -->|Read Prices / Fundamentals| StockDatabaseManager["Stock Database Manager (momentum_tracker/src/data/stock_database_manager.py)"]
    StockDatabaseManager --> DiskCache
    StockDatabaseManager --> DataDown
    DataDown -->|API Pulls| YF
    
    %% Persistence Layer Routing
    Discovery -->|Save Scans & Picks| DbFactory
    Monitor -->|Save Alerts| DbFactory
    DbFactory --> DbInterface
    DbInterface --> SQLite
    DbInterface --> Postgres
    
    %% FII/DII Integration
    FiiDii -->|Queries / CLI commands| NSE
    FiiDii -->|Local DB Consolidation| SQLite
    
    %% Styles
    classDef client fill:#4F46E5,stroke:#fff,stroke-width:2px,color:#fff;
    classDef automation fill:#059669,stroke:#fff,stroke-width:2px,color:#fff;
    classDef ai fill:#D97706,stroke:#fff,stroke-width:2px,color:#fff;
    classDef quant fill:#2563EB,stroke:#fff,stroke-width:2px,color:#fff;
    classDef persist fill:#7C3AED,stroke:#fff,stroke-width:2px,color:#fff;
    classDef external fill:#374151,stroke:#fff,stroke-width:2px,color:#fff;

    class Dash client;
    class Sched automation;
    class Discovery,Monitor,ScoutAg,ChartAg,FlowAg,AnalystAg,ScanAg,ClassAg ai;
    class Selector,Strategy,Indicators,StockDatabaseManager,DataDown,DiskCache quant;
    class DbFactory,DbInterface,SQLite,Postgres persist;
    class YF,NSE,Serper external;
```

---

## 2. Structural & Class Relationships

The core quantitative and persistence APIs are exposed through a unified API Facade (`MomentumTrackerAPI`), which provides modular access to scanners, rebalancers, and database persistence layers.

```mermaid
classDiagram
    class MomentumTrackerAPI {
        +Config config
        +StockDatabaseManager db
        +MomentumStrategy strategy
        +PortfolioManager portfolio
        +StockSelector selector
        +SymbolLoader loader
        +run_precache() Dict
        +get_top_recommendations(category, top_n) DataFrame
        +run_rebalance() DataFrame
        +get_portfolio_momentum_history(days) Dict
        +analyze_tickers(tickers, run_technical, run_fii_dii) str
    }
    
    class DatabaseInterface {
        <<interface>>
        +init()
        +save_scan(category, results, top_n) int
        +save_picks(run_id, picks)
        +save_alerts(alerts, user_id)
        +held_positions(user_id) list
        +closed_positions(user_id) list
        +performance_summary(user_id) dict
        +save_momentum_scores(scores)
        +get_momentum_scores(symbols, start, end) list
    }
    
    class SQLiteDatabase {
        +db_path Path
        +init()
        +save_scan(category, results, top_n) int
    }
    
    class PostgreSQLDatabase {
        +pg_config dict
        +init()
        +save_scan(category, results, top_n) int
    }
    
    class StockDatabaseManager {
        +Config config
        +DataDownloaderBase downloader
        +cache_dir Path
        +bulk_precache(tickers, bench) tuple
        +get_price(ticker) DataFrame
    }

    class MomentumStrategy {
        +Config config
        +StockDatabaseManager db
        +score_universe(tickers, benchmark) list
    }

    DatabaseInterface <|.. SQLiteDatabase
    DatabaseInterface <|.. PostgreSQLDatabase
    MomentumTrackerAPI --> DatabaseInterface : uses
    MomentumTrackerAPI --> StockDatabaseManager : uses
    MomentumTrackerAPI --> MomentumStrategy : uses
```

---

## 3. Dynamic Operations & Sequence Flow

This sequence diagram illustrates the **2-Stage Interactive Scan & Deep-Dive** workflow from the user's browser, through the Django controllers, to the background thread orchestrating the selectable CrewAI sub-agents.

```mermaid
sequenceDiagram
    autonumber
    actor User as Client Browser
    participant Django as Django Dashboard (views.py)
    participant DB as SQLite / Postgres Database
    participant API as MomentumTrackerAPI
    participant Crew as CrewAI Execution Engine
    
    User->>Django: POST /scan (action=fetch_ranks, category)
    Django->>API: get_top_recommendations(category)
    API->>API: Run WMS Funnel & ranks
    API-->>Django: return ranked candidates DataFrame
    Django-->>User: Render Step 2 (symbol checklist & agent options)
    
    User->>Django: POST /scan (action=run_analysis, selected_tickers, run_technical, run_fii_dii)
    Django->>Django: Start background daemon thread (_async_analysis_task)
    Django-->>User: HTTP Redirect /scan (shows spinner & polls status)
    
    Note over Django, Crew: Background Thread Execution
    Django->>Crew: process_tickers_batch(selected_tickers, run_technical, run_fii_dii)
    alt Run Technical Chart Agent
        Crew->>Crew: Chart Analyst fetches stock EMA & RSI stats
    end
    alt Run FII / DII Flow Agent
        Crew->>Crew: Flow Analyst fetches NSE holdings & block deals
    end
    Crew->>Crew: Fundamental Analyst synthesizes reports & scores conviction
    Crew-->>Django: Returns raw markdown report text
    Django->>Django: Parse BUY/HOLD/AVOID classifications & confidence scores
    Django->>DB: save_scan() & save_picks()
    Django->>Django: Convert report markdown to HTML
    
    User->>Django: GET /scan/status (polling)
    Django-->>User: return JSON (running=False, report_html, success=True)
    User->>User: Display completed deep-dive analyst report in UI
```

---

## 4. Component Architecture & System Decomposition

### A. Client Layer (`dashboard/views.py` & templates)
A comprehensive, interactive web interface powered by **Django**. It manages user authentication and partitions data securely.
*   **User Authentication**: Fully partitioned login, signup, and registration modules.
*   **Portfolio Overview**: Displays active open positions, purchase metrics, and real-time color-coded alert badges (🔴 RED, 🟡 YELLOW, 🟢 GREEN) filtered securely for the logged-in user.
*   **Run Momentum Scan (2-Stage Interactive)**: Instantly computes WMS ranked candidates in Stage 1, displays an interactive checklist to choose symbols, exposes switches to enable/disable the Technical and FII/DII Flow agents, and triggers the CrewAI pipeline in a background thread.
*   **Performance Tracker**: Visualizes closed-trade P&L, overall win rate, average holding period, and performance breakdowns.

### B. Orchestration & Automation Layer (`streamlite_app/scheduler.py`)
The background execution harness powered by **APScheduler**.
*   Runs on a weekday cron schedule optimized for the Indian stock market (Monday to Friday):
    *   **08:15 IST**: Triggers `job_scan_and_classify` (scans specified stock universe, extracts top candidates, runs analyst review, saves records).
    *   **08:45 IST**: Triggers `job_monitor` (extracts held positions from the DB, runs news-based risk monitor, records alerts).

### C. CrewAI Layer (`crew/`)
A multi-agent AI system structured into two primary pipelines:
1.  **Stock Discovery Crew** (`stock_discovery_agents.py`):
    *   **Momentum Scout**: Executes the WMS scoring engine using the `MomentumBackboneTool`.
    *   **Technical Chart Analyst** (Selectable): Invokes the `TechnicalChartTool` to check support/resistance and EMA trend status.
    *   **FII & DII Flow Analyst** (Selectable): Invokes the `InstitutionalFlowTool` to query institutional holdings or search block deals.
    *   **Fundamental & Sentiment Analyst**: Delivers final synthesized BUY / HOLD / AVOID calls.
2.  **Portfolio Monitor Crew** (`portfolio_monitor.py`):
    *   **Portfolio News Scanner**: Periodically monitors news articles for held tickers.
    *   **Portfolio Alert Classifier**: Assigns RED, YELLOW, or GREEN severity tags to stories.

### D. Quantitative Core Engine (`momentum_tracker/src/`)
A modular package that calculates metrics, ranks stocks, and manages caches:
*   **`database/`** (Persistence): Abstracts database interfaces (`db_interface.py`) and connection credentials (`db_config.py`).
*   **`data/`** (Ingestion): Downloads price/fundamental data (`data_downloader.py`, `stock_database_manager.py`) and reads NSE holdings (`fii_dii_provider.py`). All data tables are consolidated inside `data_cache/momentum.db`.
*   **`strategy/`** (Quantitative Scoring): Vectorized technical computations (`technical_indicators.py`) and WMS multi-stage funnel processing (`momentum_strategy.py`).
*   **`portfolio/`** (Accounting & Backtesting): Computes rebalance recommendations (`portfolio_manager.py`) and runs historical simulations (`backtester.py`, `backtest_runner.py`).
*   **`reporting/`** (Output): Generates Excel/CSV exports (`report_exporter.py`) and recommendations interfaces (`stock_selector.py`).

---

## 5. Mathematical & Algorithmic Core

The system ranks stocks using a multi-factor quantitative approach:

### Custom Technical Indicators

#### 1. Rate of Change (ROC) Composite
$$\text{Composite ROC} = \frac{\sum (w_i \times \text{ROC}_{p_i})}{\sum w_i} \times 100$$
Where:
*   $p = [60, 40, 20]$ days.
*   $w = [0.35, 0.40, 0.25]$ weights (giving higher prominence to mid-term price velocity).
*   $\text{ROC}_{t} = \frac{\text{Close}_{\text{Today}} - \text{Close}_{t\text{ Days Ago}}}{\text{Close}_{t\text{ Days Ago}}}$.

#### 2. Smoothed Relative Strength Ratio (RS-MA Ratio)
$$\text{RS Line}_t = \frac{\text{Close}_{\text{Stock}, t}}{\text{Close}_{\text{Bench}, t}}$$
$$\text{RS MA}_t = \text{SMA}(\text{RS Line}, \text{lookback}=55)_t$$
$$\text{RS-MA Ratio} = \left( \frac{\text{RS Line}_t}{\text{RS MA}_t} \right) - 1.0$$

#### 3. Price Momentum Composite (P-Score)
$$\text{P-Score} = \frac{1.0 \times \text{ROC}_{12\text{M}} + 2.0 \times \text{ROC}_{6\text{M}} + 2.0 \times \text{ROC}_{3\text{M}} + 0.5 \times \text{Dist}_{52\text{W High}}}{\sum w_i} \times 100$$
$$\text{Dist}_{52\text{W High}} = \frac{\text{Close}_{\text{Today}}}{\max(\text{High}_{\text{Last 252 Days}})} - 1.0$$

---

## 6. Database Schema Design

The consolidated SQLite/PostgreSQL schema consists of:
1.  **`scan_runs`**: Scan header containing execution times, universe totals, and limits.
2.  **`scans`**: Detailed ranked table containing raw momentum metrics (`wms`, `rs`, `rsi`, `mfi`, `cci`).
3.  **`picks`**: Structured analyst classifications (`BUY`, `HOLD`, `AVOID`), conviction confidence, and rationales.
4.  **`alerts`**: Portfolio monitoring flags (`RED`, `YELLOW`, `GREEN`) and triggering news events.
5.  **`portfolio`**: Held stocks, purchase prices, and share quantities (partitioned by user ID).
6.  **`performance`**: Historical closed trades, realized P&L, hold duration, and exit reasons.
7.  **`scan_reports`**: Generative markdown report text audits.
8.  **`momentum_scores`**: Persisted scores enabling rapid UI charting and calculations.
9.  **`stock_holdings`, `fii_dii_aggregate`, `sector_stocks`**: Consolidated FII/DII provisional flow cache tables.

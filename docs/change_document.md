# Change Document – Local Code Modifications

This document summarizes all local changes made to the base code (comparing the current working copy with `origin/main` / initial pushed commit).

---

## 1. Directory Restructuring, Refactoring & Packaging

### Codebase Subdirectory Packaging (Modular Refactor)
- Grouped the flat files in `momentum_tracker/src/` into logical, domain-specific package subdirectories:
  - **`database/`**: Config configuration (`db_config.py`), base contracts (`db_interface.py`), SQLite adapter (`persistence.py`), PostgreSQL adapter (`persistence_postgresql.py`), and transaction helper services (`portfolio_service.py`).
  - **`data/`**: pricing downloader (`data_downloader.py`), constituent retriever (`symbol_loader.py`), NSE holdings fetcher (`fii_dii_provider.py`), and caches manager (`stock_database_manager.py`).
  - **`strategy/`**: pricing mathematics computations (`technical_indicators.py`) and filtering funnels (`momentum_strategy.py`).
  - **`portfolio/`**: holdings metrics (`portfolio_manager.py`), simulation engine (`backtester.py`), and CLI backtesting runner (`backtest_runner.py`).
  - **`reporting/`**: exports generator (`report_exporter.py`) and recommendation views (`stock_selector.py`).
- Added package initialization (`__init__.py`) files inside each subfolder, and created a central `momentum_tracker/src/__init__.py` exposing the public API.
- Renamed the generic root `core/` folder to `momentum_tracker/src/database/` and deleted the original root-level duplicates. Updated import pathways system-wide.

### Consolidated Database Engine
- Consolidated FII/DII holdings tables (`stock_holdings`, `fii_dii_aggregate`, `sector_stocks`) from the redundant `fii_dii_data.db` directly into the unified main database cache: `data_cache/momentum.db`.
- Cleaned up the project by deleting the redundant root-level `fii_dii_data.db`.

### Decoupled Configuration & Paths
- Added `"SQLITE_PATH"` to the default system configuration options.
- Modified the database provider configuration (`db_config.py`) and FII/DII provider (`fii_dii_provider.py`) to resolve database paths dynamically from the central `Config` settings.

### Rename `app/` to `streamlite_app/`
- All files inside `app/` (`dashboard.py`, `main.py`, `main_v1.py`, `scheduler.py`) were moved to [streamlite_app/](../streamlite_app) to clarify its purpose as a Streamlit interface.
- Shared/common files like `conftest.py` were moved out of the application directories to the project root directory.

### CLI Application Relocation
- [application.py](../cli_application/application.py) was moved from `momentum_tracker/application.py` into its own folder `cli_application/` to isolate core business logic from command-line orchestrations.

---

## 2. Django Web Application Interface (New Component)

A premium Django-based dashboard was created from scratch to serve as a comprehensive management interface:
- **Project Structure**: [manage.py](../manage.py) and [momentum_project/](../momentum_project) configuration directories.
- **App Module**: [dashboard/](../dashboard) holding views, static CSS stylesheets, URLs, and template pages:
  - **Overview**: Active position metric cards and alerts log.
  - **Execute Trades**: Interface to add or manually close stock holdings.
  - **Add Transaction**: A dedicated bulk upload page with a glassmorphic drag-and-drop file interface.
  - **2-Stage Interactive Scan**:
    * **Stage 1 (Instant Ranks)**: Calculates quantitative momentum ranks instantly and saves them to the session.
    * **Stage 2 (Targeted Deep-Dive)**: Displays an interactive selection checklist for stocks, exposes checkboxes to enable/disable the "Technical Chart Analyst" and "FII/DII Flow Analyst" agents, and triggers the CrewAI discovery analysis in a background thread only on checked symbols.
  - **Scan History & Reports**: quantitative result sheets, exports (Excel/CSV), and generative LLM analyst briefs.
  - **Performance Analytics**: Histograms and win rate calculators categorized by agent classification tags.

---

## 3. High-level Facade Layer

- Added [api.py](../momentum_tracker/api.py) under `momentum_tracker/` which abstracts initialization of config settings, downloader factories, databases, strategies, and runners. Exposes `analyze_tickers` programmatically with selection parameters to control sub-agent execution.

---

## 4. Core Algorithm & Scoring Enhancements

### Series-based Technical Indicators
- Added vectorized series equivalents of multi-factor technical indicators to [technical_indicators.py](../momentum_tracker/src/strategy/technical_indicators.py):
  - `rsi_series`, `mfi_series`, `cci_series`, `weighted_roc_composite_series`, `rs_ratio_series`, `price_momentum_composite_series`.

### Historical Momentum Tracker
- Implemented `get_portfolio_momentum_history` inside `PortfolioManager` to calculate 30-day historical WMS scores for all holdings, benchmark indices (`^NSEI`), and sector averages in under a second using Parquet cache engines.

### Premium Portfolio Rebalance Assistant
- Developed database tracking for rebalance executions, adding a `rebalance_history` table to SQLite and PostgreSQL schemas.
- REST API endpoint `/rebalance/` now supports choosing a target category universe and target portfolio size, uploading a recommendation sheet, generating BUY/HOLD/SELL actions, and persisting results.

### Bulk Transaction Uploader (with SmallCase Support)
- Added transaction parsing and executing logic to `PortfolioService.upload_transactions` which accepts CSV/Excel uploads.
- **Auto-Detects SmallCase Layout**: Detects single-column SmallCase transaction report structure (e.g. `SmallCasetransaction.xlsx`). 

### Robust LLM Provider Fallback in Portfolio Monitor
- Modified `crew/portfolio_monitor.py` to wrap agent execution inside a primary-vs-fallback try-except block. If the primary provider (e.g., Gemini) triggers a 429 quota error, it automatically falls back to Groq instantly to ensure uninterrupted service when calling the portfolio monitor.

### Background Precache AppConfig Worker & Momentum Score Caching
- Implemented an automatic caching daemon in `DashboardConfig.ready()` (under `dashboard/apps.py`).
- Spawns a background thread that triggers full pricing and fundamentals pre-caching 10 seconds after server startup.

### Download Failure Caching for Yahoo Finance
- Modified `StockDatabaseManager` to cache failed price and fundamental yfinance downloads under `<symbol>.failed` and `<symbol>_info.failed` respectively.

---

## 5. Verification & Test Suite

### New Unit and Integration Tests
- [test_django_features.py](../tests/integration/test_django_features.py): Validates views rendering, authentication redirection, and API routing.
- [test_momentum_history.py](../tests/unit/test_momentum_history.py): Exercises percentile rank calculations and series structures.
- [test_technical_indicators.py](../tests/unit/test_technical_indicators.py): Validates multi-factor series indicators.
- [test_stock_database_caching.py](../tests/unit/test_stock_database_caching.py): Verifies yfinance download failure caching logic.

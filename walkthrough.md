# Walkthrough - Conversion to Django with Authentication & User-Specific Portfolios

We have successfully converted the Streamlit application to a Django web application with full User Authentication support and fully partitioned User-Specific Portfolios. All database tables and system components have been successfully migrated and verified.

---

## Changes Made

### 1. Database User Partitioning
We restructured the database tables to support multi-user security, separating transactions while retaining global calculation cache:
- **User-Specific Tables:**
  - `portfolio`: Partitioned by `user_id`, with a composite unique constraint `UNIQUE(user_id, symbol)`. This permits multiple users to hold the same asset symbols concurrently.
  - `performance`: Partitioned by `user_id` to separate users' closed-trade stats, win rates, and P&L KPIs.
  - `alerts`: Partitioned by `user_id` so that alert timelines only display triggers for assets owned by the logged-in user.
- **Global Shared Tables (Cached):**
  - `scan_runs`, `scans`, `picks`, and `scan_reports` remain shared globally to prevent redundant API queries and allow caching scanner records across all users.

### 2. Automated Self-Healing Migrations
Both SQLite and PostgreSQL persistence layers have been updated with automated startup migrations:
- Renames the old `portfolio` table to `portfolio_old`, creates the new schema, copies existing positions (defaulting them to `user_id = 1`), and drops the old table.
- Appends `user_id` columns to `performance` and `alerts` tables automatically.
- Database checks verified successfully with no warnings.

### 3. App Schedulers & Django Views
- Updated background scheduler (`app/scheduler.py`) to query held positions globally and route generated alerts specifically to the user(s) who hold the correspond tickers.
- Upgraded views (`dashboard/views.py`) to pass `request.user.id` to database operations, enforcing secure dashboard isolation.
- Created a default admin account with username `admin` and password `admin123`.

---

## Verification Results

1. **Schema Check:** Verified that database automatically upgraded columns and keys on startup.
2. **Django Codebase Check:** `python manage.py check` verified successfully with 0 warnings or errors.
3. **Multi-User Isolation:** Logged-in users are restricted to viewing, adding, and closing positions inside their own portfolio context. Performance summaries, metrics, and alert logs are secured by active sessions.

---

## Instructions to Run

1. Open your terminal in the workspace root.
2. Activate your virtual environment:
   - **Command Prompt:** `venv\Scripts\activate`
   - **PowerShell:** `.\venv\Scripts\Activate.ps1`
   - **Git Bash / Linux / macOS:** `source venv/bin/activate`
3. Run the development server:
   ```bash
   python manage.py runserver
   ```
4. Open your browser and navigate to `http://127.0.0.1:8000/`.
5. Log in using:
   - **Username:** `admin`
   - **Password:** `admin123`
   (Or use the signup page to register new users and verify separation).

### Viewing and Managing User Accounts:
1. **Via Web Admin Console:**
   Go to [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/) and log in using the superuser credentials above. Click on **Users** under the Authentication and Authorization module to inspect names, search profiles, and audit user IDs.
2. **Via Command Line Shell:**
   Run this command in the project root to quickly list all active accounts and their unique database IDs:
   ```bash
   python manage.py shell -c "from django.contrib.auth.models import User; [print(f'User ID: {u.id:2d} | Username: {u.username:15s} | Email: {u.email}') for u in User.objects.all()]"
   ```

---

## Unit tests verify quantitative math and configurations without executing live LLM calls:
1. Set the PYTHONPATH environment variable (e.g. on Windows PowerShell):
   ```powershell
   $env:PYTHONPATH=".;crew;app;momentum_tracker"
   ```
2. Execute pytest:
   ```bash
   pytest tests/unit/ -v
   ```

---

## Update: LLM Provider Dependency Tracking & Mocked Interaction Tests

To resolve and prevent missing native Gemini provider package issues, and to protect API token quota during unit tests, the following changes were made:

### 1. LLM Provider Dependency Tracking
- Modified `requirements.txt` to specify `crewai[google-genai]==1.14.3` instead of basic `crewai`, ensuring that both `google-genai` and `crewai` requirements are fully resolved and saved in the project environment.

### 2. Mocked LLM Interaction Unit Tests
- Created `test_llm_interaction_mocked_gemini` and `test_llm_interaction_mocked_groq` in `tests/unit/test_scheduler_and_crew.py`.
- These tests verify the end-to-end integration flow of our CrewAI agents, tasks, and LLM configuration without generating external network queries. They assign a `MagicMock` directly to the `llm.call` method of the instantiated LLM object, simulating valid LLM responses instantly and ensuring zero quota consumption.

---

## Update: Advanced CLI Features Migrated to Django Web UI

We have fully migrated all interactive CLI menus and background operations from `application.py` into Django's dashboard interface, allowing users and administrators to run complex quantitative workflows entirely from their browser:

### 1. Backtesting Dashboard Panel
- **Interface**: Accessible via the "Backtest Panel" link in the sidebar navigation.
- **Parameters**: Customizable fields for Index Universe, Initial Capital, Target Portfolio Size (Top N), Rebalance Frequency (Weekly/Monthly/Quarterly/Annually), Transaction Cost Floor, and historical Start/End date bounds.
- **Asynchronous Execution**: Triggers backtests in background threads using global locks to prevent session freezing. Displays an active spinner during calculation.
- **Results Analysis**:
  - **KPI Summaries**: Compares Strategy CAGR%, Total Return%, and Max Drawdown% side-by-side with benchmark index metrics. Shows profitable Win Rate% and total trades executed.
  - **Equity Charting**: Plots the Strategy Equity Curve and Scaled Benchmark Index Curve using interactive Chart.js graphs.
  - **Transaction Logs**: Renders a searchable grid of the latest 100 executed trade entries (BUY/SELL order values, quantities, prices, P&L cash, and P&L percentages).
  - **Spreadsheet Download**: Generates and serves Excel spreadsheets detailing daily curves, transaction lists, and summary benchmarks.

### 2. Custom Ticker Scorer
- **Interface**: Accessible via the "Custom Scorer" link in the sidebar navigation.
- **Dynamic File Parsing**: Allows uploading arbitrary Excel or CSV files. Automatically identifies the symbol column, formats ticker listings, and appends `.NS` suffixes where required.
- **Scores Grid**: Pre-caches stock pricing dynamically on-the-fly and scores the custom universe. Displays results in a clean, sorted table showing WMS, RS, RSI, MFI, and CCI indicators.

### 3. Settings - Pre-cache Control Center
- **Background Pre-caching**: A dedicated button triggers `api.run_precache()` in a background worker thread.
- **Live Progress Polling**: Polls the server status dynamically using AJAX, updating a progress bar and status message (e.g. `Downloading price data for RELIANCE.NS (45/100)`) in real-time.
- **Cache Resets**: Allows superusers to wipe Parquet pricing files and derived JSON fundamentals cached on disk, and update config download years.

### 4. Settings - Index Category Creator
- **Dynamic Category Registration**: A form to add a new category name, map it to a custom benchmark index symbol, and upload its default constituents list CSV file.
- **In-Memory & Storage persistence**: Automatically saves the CSV to `data/symbols/` and updates configuration files on disk, making the new index immediately available for quant scanning and backtesting.

---

## Update: Portfolio Rebalance Assistant, Transaction Uploader, and Automatic Data Caching

We have completed the implementation of the remaining three core requirements for the system:

### 1. Portfolio Rebalance Assistant (Option `[12]`) with DB History
- **Database Persistence**: Added a `rebalance_history` table to both SQLite and PostgreSQL backends to store all calculated rebalance reports along with execution timestamps.
- **Interface & Configuration**: Fully integrated input selectors (Index Category and Target Portfolio Size) into the `/rebalance/` route. Allows selecting whether to use database live holdings or upload a local positions file.
- **Run History**: Displays a "Run History" side panel listing all past runs. Clicking "View" instantly reloads and visualizes a past report in the table.
- **Excel Downloads**: Implemented dynamic generation of Excel action plans from saved DB rebalance data using a `BytesIO` buffer, served under `/rebalance/download/<run_id>/`.

### 2. Bulk Transaction Uploader
- **Core Processing Engine**: Implemented `PortfolioService.upload_transactions` which chronologically processes Excel or CSV spreadsheets (`Date,Batch Type,Symbol,Price,Qty,Action`).
- **Weighted Cost Averages**: Buying the same stock multiple times dynamically recalculates the weighted cost average buy price in the open holdings table.
- **Closed P&L Logging**: Selling holdings realizes P&L and writes historical closed-trade rows to the `performance` table. Supports partial sells by writing the sold shares' P&L and updating the remaining shares with the original average cost.
- **Dashboard Interface**: Added a drag-and-drop or select uploader card to the "Execute Trades" page posting to `/portfolio/upload-transactions/`.

### 3. Automatic Background Data Caching
- **AppConfig Worker**: Implemented a background thread daemon in `ready()` of `DashboardConfig` (in `dashboard/apps.py`).
- **24-Hour Loop**: 10 seconds after server startup, the worker starts precaching price data and fundamentals for all symbols in the workspace database. Loops and updates every 24 hours.
- **Self-Healing Fallbacks**: If yfinance or data connections fail, it catches the error, registers it, and schedules a retry 1 hour later.
- **Clean Execution Isolation**: Automatically exits and bypasses running the caching thread during test suites, model migrations, database setups, or development server parent processes.




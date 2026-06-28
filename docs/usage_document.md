# Usage Guide – Momentum Portfolio System Dashboard

This document details how to launch and operate the advanced features (Backtesting, Custom Scorer, Scan History & Reports, Cache Updates, and Rebalancing) in the Django web dashboard.

---

## 1. Launching the Web Server
1. Activate your virtual environment and run the Django web server from the project root:
   ```bash
   python manage.py runserver
   ```
2. Open your browser and navigate to `http://127.0.0.1:8000/`.
3. Log in with the default administrator credentials:
   - **Username**: `admin`
   - **Password**: `admin123`

---

## 2. Using the Backtest Panel (Options `[1]` & `[2]`)
1. Click on **Backtest Panel** in the sidebar navigation.
2. Select your desired stock universe category (e.g. *Nifty100*).
3. Set your initial capital (default: ₹1,000,000) and target portfolio size.
4. Set the **Start Date** and **End Date** for the backtest, rebalance frequency (Weekly, Monthly, etc.), and transaction fee rates.
   * *Quick Tip*: You can click the **Scenario** helper buttons to instantly populate inputs for 1y, 3y, or 5y backtest ranges.
5. Click **Start Backtest Run**. A progress spinner will load while the simulation executes in the background.
6. Once completed, the dashboard will display:
   * **KPI Performance Summary**: CAGR%, Total Return%, Max Drawdown%, Win Rate%, and total trades executed vs benchmark.
   * **Equity Curve Chart**: A visual overlay comparing the Strategy Equity Curve and the Scaled Benchmark Index Curve.
   * **Executed Transactions**: A tabular log of all simulated buy/sell orders.
   * **Download Excel**: Click the button to export the simulation files.

---

## 3. Using the Custom Scorer (Option `[5]`)
1. Click on **Custom Scorer** in the sidebar navigation.
2. Upload a constituents spreadsheet (.xlsx or .csv) containing a column named `Symbol` or `symbol` containing stock tickers.
3. Click **Calculate Momentum Scores**. The scorer will download price history for any missing tickers dynamically, calculate scores, and render a ranked sorted table showing WMS and other technical factors.

---

## 4. Using Scan History & Reports (Integrated Viewer)

The **Scan History & Reports** panel is a unified, interactive workspace to audit and download quantitative scans and analyst briefs.

![Scan History & Reports Mockup Dashboard](file:///c:/Users/gopal/GOPAL-SHARE/Stock-market-Project/Momentum-Tracker/docs/assets/scan_history_and_reports_mockup.png)

### A. Index Category View
* **Universe Selection**: Select an index category (e.g. *Nifty100*) to load historical scans.
* **Scan Run Selector**: Use the dropdowns to browse any of the last 15–30 scan runs in the database.
* **Split Layout Inspection**:
  - **Left Side**: A structured table lists stock symbols, ranks, latest WMS scores, and analyst BUY/HOLD/AVOID picks.
  - **Right Side**: Click on any stock row to instantly display the **Multi-Agent Analyst Report** generated during that scan.
* **Exports & Controls**: Export the selected run to CSV or Excel, or delete the run entirely.
* **Progressive WMS Sparkline Charts**: A line chart at the bottom displays the selected stock's WMS score progression over the last 30 scans, letting you track momentum acceleration or decay.

### B. Portfolio Stocks View
* Click the **Portfolio Stocks View** tab to inspect currently held portfolio positions.
* Displays the purchase details, current WMS score, and latest analyst report for all open positions.
* Tapping a position row loads its latest deep-dive report on the right side.

### C. Any Ticker Search & On-Demand Generator
* Click the **Any Ticker Search** tab and search for any ticker symbol (e.g., `TCS`, `INFY`).
* If a report exists in the database, it loads instantly along with its WMS trend progression chart.
* If no report exists, or if you want to refresh the analysis, click **Generate On-Demand Scan Report**. The system kicks off the CrewAI specialist agents in the background, writes the output to the database, and reloads the view.

---

## 5. Database Pre-caching & Clear Controls (Options `[10]` & `[11]`)
1. Log in as an administrator and click on **Settings** in the sidebar navigation.
2. Under **Cache Control Center**:
   * **Start Bulk Cache Update**: Downloads prices and fundamental variables in the background for all configured symbols. A dynamic progress bar showing the active ticker will render live in the browser.
   * **Wipe Local Cache Files**: Wipes raw Parquet price files and fundamental derived JSONs cached on disk, and updates download history years.

---

## 6. Creating New Universes (Option `[13]`)
1. Go to **Settings** in the sidebar navigation.
2. Under **Add Index Category**:
   * Set the category name (e.g. *Sensex30*) and map it to an optional index benchmark ticker.
   * Upload the index constituents CSV file.
3. Click **Register Index Category**. The system will save the file to `data/symbols/` and register the category in `config.json`. The new index category will immediately show up in the **Backtest Panel** and **Run Scan** dropdowns.

---

## 7. Using the Portfolio Rebalance Assistant (Option `[12]`)
1. Click on **Rebalance Assistant** in the sidebar navigation.
2. Configure your inputs:
   * **Index Category**: Select the target stock universe to evaluate.
   * **Target Portfolio Size**: Enter the number of top-ranking stocks you wish to hold (e.g., 20).
   * **Portfolio Positions Source**:
     * Check **Use Database Live Holdings** to evaluate your active portfolio currently stored in the DB.
     * Uncheck it to show a file uploader where you can upload a local portfolio Excel/CSV file instead.
   * **Last Recommendation File**: Upload a constituent recommendation sheet (Excel or CSV). This file is optional for pure rebalance runs and required for detailed comparison.
3. Click **Run Rebalance Analysis**.
4. The calculated action table will display recommendations for each stock (`BUY`, `HOLD`, or `SELL`) marked with appropriate color badges.
5. Click **Download Excel Report** to export the rebalancing action sheet.
6. Under **Run History**, view the list of historical rebalance calculations. Click **View** on any entry to instantly reload the results of a historical run, or download the historical Excel report.

---

## 8. Using the Bulk Transaction Uploader
1. Click on **Execute Trades** in the sidebar navigation.
2. Scroll to the **Bulk Transaction Uploader** card.
3. Choose a spreadsheet file (.csv, .xls, or .xlsx). Ensure the file contains the following columns:
   * `Date`: The date of the transaction (e.g. `2026-06-15`).
   * `Symbol`: The stock ticker (e.g. `TCS.NS`).
   * `Price`: The execution price (e.g. `3500.0`).
   * `Qty`: The number of shares traded (e.g. `5`).
   * `Action`: Either `BUY` or `SELL`.
   * `Batch Type`: Label describing the transaction batch.
4. Click **Process Transactions**. The system will sort all transactions chronologically:
   * Sequential `BUY` transactions are added to holdings (recalculating weighted cost averages).
   * Sequential `SELL` transactions realize P&L, log rows to the closed performance history tables, and update remaining shares.
5. Success notifications will display, and the updated holdings will appear in the **Open Positions** and **Closed Positions History** tables.

---

## 9. Background CrewAI Schedules & Automation

The application uses APScheduler and background threads to automate scans according to stock ownership:

### A. Daily Portfolio Scanning (Held Positions)
* **Frequency**: Every weekday (Monday to Friday) at **08:30 IST**.
* **Operation**: Reads all active open symbols from the portfolio table and executes the deep multi-agent discovery analyst crew (Technical Chart, FII/DII Flow, and Fundamental Sentiment agents) to generate and record fresh daily analyst reports.

### B. Weekly Index Universe Scanning (Non-Portfolio Candidiates)
* **Frequency**: Every Monday at **08:15 IST**.
* **Operation**: Scans the default index categories (e.g., Nifty100) to compile momentum ratings and WMS ranks, executing deep-dive scans to keep non-held category records updated.

### C. Real-Time Portfolio Monitoring
* **Frequency**: Every weekday at **08:45 IST**.
* **Operation**: Conducts news risk scans for open portfolio positions, assigning RED, YELLOW, or GREEN alerts based on corporate news severity.

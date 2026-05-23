# Momentum-Tracker

An automated quantitative tool designed to track, calculate, and analyze the market momentum of financial assets. This system streamlines the evaluation of asset price strengths over multiple custom timeframes to help traders execute systematic, data-driven momentum strategies.

---

## 📌 Project Overview
The Momentum Tracker automatically aggregates historical financial data, processes it through custom technical indicators, and generates structured analytical reports. Its core purpose is to remove human bias from trend trading by mathematically ranking assets based on their absolute and relative price acceleration.

## ✨ Core Features
* **Multi-Timeframe Evaluation**: Calculates asset momentum metrics concurrently across short, mid, and long-term horizons.
* **Relative Strength Scoring**: Ranks a universe of target assets against each other to highlight market leaders.
* **Filtering and Noise Reduction**: Employs baseline filters to exclude low-volume or sideways-moving assets.
* **Automated Reporting**: Outputs compiled momentum scores directly into structured spreadsheets or terminal dataframes.

## 🏗️ Technical Architecture & Code Flow
[ Data Ingestion Engine ] ---> [ Quantitative Processing ] ---> [ Selection Filter ] ---> [ Reporting Node ](Yahoo Finance/APIs)         (Log Return / Momentum)        (Percentile Ranking)       (CSV / Dataframes)
The system processes financial data sequentially across several primary blocks:
1. **Data Ingestion**: Pulls raw historical price data (Open, High, Low, Close, Volume) using financial data APIs.
2. **Quantitative Processing**: Computes logarithmic asset returns and rates of price acceleration over specified lookback windows.
3. **Selection Filter**: Groups assets into percentiles, penalizing high volatility and isolating assets demonstrating smooth upward trajectories.
4. **Reporting Node**: Formats the compiled scores and saves them into readable text or spreadsheet formats.

## Detailed Feature Blueprint
1. Data Ingestion & Storage ManagementMulti-Format Extraction: Collects complete historical pricing data (OHLCV) directly via API endpoints or local files.Incremental Updates: Saves newly requested market data into local files to eliminate redundant network requests.
2. Quantitative Processing EngineLog Return Computation: Measures precise mathematical price velocity instead of simple nominal percentage shifts.Volatility Penalization: Uses standard deviation metrics to lower the score of highly erratic assets experiencing sudden spikes.
3. Algorithmic Trend FiltrationPercentile Matrix Ranking: Sorts the chosen asset universe relative to one another to extract the top performers.Sideways Filtering: Automatically drops assets experiencing stagnant volume or long consolidation periods.
4. Automated Analytical ReportingDynamic Spreadsheets: Exports clean files containing current tickers, individual timeframe ratings, and unified ranks.Terminal Data Visualizations: Prints responsive status feeds directly inside console screens for real-time script tracking.

## Project Directory Structure
Momentum-Tracker/
├── config/                  # Configuration settings and parameters
│   └── settings.json        # Ticker lists, lookback periods, and filter thresholds
├── data/                    # Local storage for asset historical data
│   ├── raw/                 # Unprocessed price data pulled from APIs
│   └── processed/           # Transformed datasets with momentum features
├── src/                     # Core application source code
│   ├── __init__.py
│   ├── data_loader.py       # Handles API connections and data extraction
│   ├── indicators.py        # Contains quantitative math (returns, momentum, volatility)
│   ├── filters.py           # Isolation logic for asset ranking and selection
│   └── reporter.py          # Formats and saves generated analytical reports
├── tests/                   # Unit tests for verification and quality control
├── .gitignore               # Excludes data files and local dependencies
├── README.md                # System documentation
├── main.py                  # Primary controller orchestration script
└── requirements.txt         # Required Python library versions

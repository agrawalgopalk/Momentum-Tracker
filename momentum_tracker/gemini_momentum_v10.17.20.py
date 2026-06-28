"""
Advanced Momentum Portfolio System v10.17.16 (FUNDAMENTAL DATA DISK CACHE)

================================================================
VERSION HISTORY:
================================================================
v10.17.16 (Current) - New Features:
- CRITICAL FIX: Implemented **Persistent Disk Caching** for fundamental data (P/B, P/E, P/S) 
  using JSON files in the cache directory, significantly speeding up subsequent runs 
  and backtests. The cache is validated based on MAX_CACHE_DAYS.

v10.17.15 - New Features:
- CRITICAL FIX: Replaced dummy `get_fundamental_data` function with one that fetches 
  **real fundamental data** (P/B, P/E, P/S) using `yfinance.Ticker().info`. 
  Implemented in-memory caching for fundamental data to speed up backtesting/scoring.

v10.17.14 - New Features:
- FEATURE: Implemented **Benchmark Return Tracking** in the backtest report to compare 
  portfolio performance against the index for each rebalance period.
- FEATURE: Added **CSV/Excel export** functionality for the "Get Today's Top Recommendations" 
  interactive feature.
- CRITICAL FIX: Modified backtest transaction logic to enforce **non-fractional trading** (using `np.floor` for purchases).
- CRITICAL FIX: Transaction cost is now deducted from capital **before** purchasing new 
  orders.
- NEW FEATURE: Added **Export Full Universe Scores** functionality (Option [4]) to save the 
  complete set of scores for all stocks in a selected category.
  
----------------------
Which one should you use?
For a Backtracking/Ranking System like the one in your script:

Use RSI for Selection: Use RSI to find the "hottest" stocks. If a stock's price is moving fast, 
RSI will capture it immediately. Your current code uses RSI_Raw_Pct as a weight in the WMS, which is the correct approach for momentum.

Use MFI as a Filter: Use MFI to ensure you aren't buying a "pump and dump." 
If the RSI is high but the MFI is low, it means the price is rising on thin volume.

The "Power Move": Look for stocks where both are increasing. 
If RSI is rising (price is accelerating) and MFI is rising (volume is increasing), you have the highest probability of a sustained momentum move.

Implementation Tip for your Python Code
In your current logic, both are weighted equally. If you want to reduce "churn" (too many sells), 
you might consider giving MFI a slightly higher weight during the "HOLD" check. 
This ensures that as long as money is still flowing into the stock (high MFI), 
you keep holding it even if the price speed (RSI) fluctuates slightly.
------------------

=============================================================
RSI	----------- MFI	---------------------Meaning
RSI rising ---  MFI rising         ---  Strong buy ✅	
RSI rising ---  MFI flat/dropping  ---  Fake move ⚠️	
RSI flat   ---  MFI rising         ---  Smart money accumulating 🔥	
RSI falling --- MFI rising         ---  Hidden accumulation 👀	
=============================================================

"""


import os
import pandas as pd
import matplotlib.pyplot as plt
import yfinance as yf
import numpy as np
from datetime import datetime, timedelta, date
import warnings
import json
import time
import sys
import shutil
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Union # Ensure Union is imported if needed

"""
import yfinance as yf
import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator, ROCIndicator
from ta.volume import MFIIndicator
from ta.trend import CCIIndicator, EMAIndicator

# ================== SETTINGS ==================
BENCHMARK = "^NSEI"   # NIFTY 50 index
LOOKBACK = 250
TOP_N = 30

# Replace this with your NIFTY 500 list
UNIVERSE = [
    "RELIANCE.NS","TCS.NS","INFY.NS","HDFCBANK.NS","ICICIBANK.NS",
    # add full Nifty 500 here
]

# ==============================================

def add_indicators(df):

    df["RSI_14"] = RSIIndicator(df["Close"], window=14).rsi()
    df["ROC_20"] = ROCIndicator(df["Close"], window=20).roc()
    df["ROC_40"] = ROCIndicator(df["Close"], window=40).roc()
    df["ROC_60"] = ROCIndicator(df["Close"], window=60).roc()

    df["MFI_14"] = MFIIndicator(
        high=df["High"], 
        low=df["Low"], 
        close=df["Close"], 
        volume=df["Volume"], 
        window=14
    ).money_flow_index()

    df["CCI_20"] = CCIIndicator(
        high=df["High"],
        low=df["Low"],
        close=df["Close"],
        window=20
    ).cci()

    df["EMA_21"] = EMAIndicator(df["Close"], window=21).ema_indicator()
    df["EMA_50"] = EMAIndicator(df["Close"], window=50).ema_indicator()
    df["EMA_200"] = EMAIndicator(df["Close"], window=200).ema_indicator()

    return df


def get_rs_55(stock_df, index_df):
    rs = stock_df["Close"] / index_df["Close"]
    rs_55 = rs.rolling(55).mean()
    return rs_55


def monthly_screener():

    index_df = yf.download(BENCHMARK, period="1y", interval="1d", progress=False)

    results = []

    for stock in UNIVERSE:

        df = yf.download(stock, period="1y", interval="1d", progress=False)

        if df.empty or len(df) < 200:
            continue

        df = df.dropna()
        df = add_indicators(df)

        index_slice = index_df.loc[df.index]

        df["RS_55"] = get_rs_55(df, index_slice)

        last = df.iloc[-1]

        # ================== FILTER CONDITIONS ==================
        if (
            last["RS_55"] > 1 and
            last["ROC_60"] > 5 and
            last["ROC_40"] > 0 and
            last["ROC_20"] > 0 and
            50 < last["RSI_14"] < 75 and
            50 < last["MFI_14"] < 80 and
            last["CCI_20"] > -50 and
            last["EMA_21"] > last["EMA_50"] > last["EMA_200"]
        ):

            score = (
                last["ROC_60"] * 0.40 +
                last["ROC_40"] * 0.25 +
                last["ROC_20"] * 0.10 +
                last["RS_55"]  * 0.15 +
                last["RSI_14"] * 0.05 +
                last["MFI_14"] * 0.05
            )

            results.append({
                "Stock": stock,
                "RS_55": round(last["RS_55"], 2),
                "ROC_60": round(last["ROC_60"], 2),
                "ROC_40": round(last["ROC_40"], 2),
                "ROC_20": round(last["ROC_20"], 2),
                "RSI_14": round(last["RSI_14"], 2),
                "MFI_14": round(last["MFI_14"], 2),
                "CCI_20": round(last["CCI_20"], 2),
                "Score": round(score, 2)
            })

    result_df = pd.DataFrame(results).sort_values(by="Score", ascending=False)

    print("\n🔷 TOP SELECTED STOCKS 🔷")
    print(result_df.head(TOP_N))

    result_df.head(TOP_N).to_csv("monthly_selected_stocks.csv", index=False)

    return result_df.head(TOP_N)


# Run
if __name__ == "__main__":
    monthly_screener()


"""

# Suppress warnings for cleaner output
warnings.filterwarnings("ignore", category=FutureWarning)

# ============================================================
# GLOBAL CONFIGURATION & VARIABLES
# ============================================================

# NOTE: Updated cache directory name to reflect the new version/changes
CACHE_DIR = Path("./yfinance_cache_17.13") 
CONFIG_FILE = "config.json"
CACHE_DIR.mkdir(exist_ok=True)

# Global data structures to hold fetched data in memory
GLOBAL_STOCK_DATA: Dict[str, pd.DataFrame] = {}
GLOBAL_BENCHMARK_DATA: Dict[str, pd.DataFrame] = {}
# Global cache for Fundamental Data
GLOBAL_FUNDAMENTAL_DATA: Dict[str, Dict[str, Optional[float]]] = {}
CONFIG: Dict[str, Any] = {}
current_config_file = CONFIG_FILE

# Default Configuration based on PDF logic
DEFAULT_CONFIG_DATA = {
    "VERSION": "v10.17.18", # Updated version
    "SYSTEM_CONFIG": {
        "DEBUG_MODE": False, 
    },
    "DATA_CONFIG": {
        "INDICES": {
            # Benchmark indices for comparison/data fetching
            "Nifty50": "^NSEI",
            "Nifty100": "^CNX100",
            "Midcap150": "NIFTYMIDCAP150.NS",
            "Smallcap250": "MOSMALL250.NS",
            "NiftyLargeMidcap250": "ELM250.NS",
            "NiftyNext50": "^NSMIDCP",
            "Nifty500": "^CRSLDX",
            "NiftyMicrocap250": "MOSMALL250.NS"             
        },
        "INDEX_BENCHMARK": "^NSEI", 
        # Mapped to the actual CSV file names provided by the user
        "SYMBOL_FILE_MAP": {
            # "Nifty50": "ind_nifty50list.csv",
            # "NiftyNext50": "ind_niftynext50list.csv",
            "Nifty100": "ind_nifty100list.csv",           
            "Midcap150": "ind_niftymidcap150list.csv",     
            "Smallcap250": "ind_niftysmallcap250list.csv",
            "Nifty500": "ind_nifty500list.csv", 
        },
        "MAX_CACHE_DAYS": 3,
        "DOWNLOAD_HISTORY_YEARS": 20, # <-- NEW PARAMETER: Default to 5 years 
    },
    "MOMENTUM_CONFIG": {
        "WMS_ROC_PERIODS": [60, 40, 20], 
        "WMS_ROC_WEIGHTS": [0.35, 0.40, 0.25], 
        "RS_LOOKBACK_DAYS": 55, 
    },
    "FILTER_CONFIG": {
        "ENABLE_FILTERS": True,
        # Primary Relative Score Filters (will be checked in post-processing if necessary)
        "MIN_P_SCORE_PCT": 70, 
        "MIN_V_SCORE_PCT": 50,
        
        # Technical Filters 
        "MIN_PRICE": 1.0,      
        "MIN_VOLUME_AVG": 10000, 
        
        # Consistency Check parameters
        "CONSISTENCY_CHECK": {
            "ENABLE": False,
            "CHECK_DAYS": 30,           
            "MIN_TOTAL_DAYS_PASS": 15, 
            "RECENT_WINDOW": 10,
            "MIN_RECENT_DAYS_PASS": 10, 
        }
    }
    ,
    # The SCORING_WEIGHTS is for the FINAL WMS (Stage 3)
    "SCORING_WEIGHTS": {
        "WMS_ROC_Composite": 0.60,
        "RSI_Score": 0.05,
        "MFI_Score": 0.20,
        "CCI_Score": 0.15
    },
    "BACKTEST_CONFIG": {
        "TOP_N": 20, 
        "REBALANCE_FREQUENCY": "M", 
        "TRANSACTION_COST": 0.001,
        "STOCK_SCALING_FACTOR": 2,          # Point 1: Select 2x portfolio size (e.g., 2*TOP_N)
        "MOMENTUM_DROP_THRESHOLD_PCT": 50.0, # Point 4: Percentage drop to trigger a forced sell
        "NEW_STOCK_ADDITION_LIMIT": 20      # Point 5: Max rank for a new stock to be added        
         
    }
}

# ============================================================
# CONFIGURATION & UTILITY FUNCTIONS
# ============================================================

def load_config(file_name: str = CONFIG_FILE):
    """Loads configuration from a JSON file, or uses defaults if not found."""
    global CONFIG, current_config_file
    
    # Initialize CONFIG with defaults to ensure all keys exist
    if not CONFIG: 
         CONFIG.update(DEFAULT_CONFIG_DATA)

    try:
        with open(file_name, 'r') as f:
            loaded_config = json.load(f)
            
            # Merge loaded config with defaults, preferring loaded values
            def deep_update(default_dict, loaded_dict):
                for k, v in loaded_dict.items():
                    if isinstance(v, dict) and k in default_dict and isinstance(default_dict[k], dict):
                        deep_update(default_dict[k], v)
                    else:
                        default_dict[k] = v
            
            deep_update(CONFIG, loaded_config)
            current_config_file = file_name
        
        print(f"Configuration loaded from {file_name}.")
    except FileNotFoundError:
        print(f"Configuration file {file_name} not found. Using default configuration.")
        # Ensure CONFIG is fully defaulted if load failed entirely
        CONFIG.update(DEFAULT_CONFIG_DATA)
    except json.JSONDecodeError:
        print(f"Error reading {file_name}. Using default configuration.")
        CONFIG.update(DEFAULT_CONFIG_DATA)
    except Exception as e:
        print(f"An unexpected error occurred while loading config: {e}. Using default configuration.")
        CONFIG.update(DEFAULT_CONFIG_DATA)
        
def save_config(file_name: str, config_data: Dict[str, Any]):
    """Saves the current configuration to a JSON file."""
    try:
        with open(file_name, 'w') as f:
            json.dump(config_data, f, indent=4)
        print(f"Configuration saved to {file_name}.")
    except Exception as e:
        print(f"Error saving configuration: {e}")

def debug_print(message: str):
    """Prints a message only if DEBUG_MODE is True."""
    if CONFIG.get("SYSTEM_CONFIG", {}).get("DEBUG_MODE", False):
        print(f"[DEBUG] {message}")

def toggle_debug_mode():
    """Toggles the DEBUG_MODE setting."""
    if not CONFIG: load_config()
    current_state = CONFIG["SYSTEM_CONFIG"]["DEBUG_MODE"]
    new_state = not current_state
    CONFIG["SYSTEM_CONFIG"]["DEBUG_MODE"] = new_state
    print(f"DEBUG_MODE toggled to: {new_state}")

def load_symbols(category: str) -> List[str]:
    """Loads the list of symbols for a given category from its CSV file."""
    if not CONFIG: load_config()

    file_name = CONFIG["DATA_CONFIG"]["SYMBOL_FILE_MAP"].get(category)
    if not file_name:
        return []

    file_path = Path(file_name)
    if not file_path.exists():
        print(f"Error: Symbol list file not found at '{file_path}'. Cannot load symbols for '{category}'.")
        return []

    try:
        df = pd.read_csv(file_path)
        
        if 'Symbol' in df.columns:
            symbol_col = 'Symbol'
        elif 'symbol' in df.columns:
            symbol_col = 'symbol'
        elif 'Company Name' in df.columns and len(df.columns) > 1:
            symbol_col = df.columns[1]
        else:
             return []

        # Assuming all stock symbols need the .NS suffix for yfinance (Indian stocks)
        symbols = [f"{s}.NS" for s in df[symbol_col].dropna().unique() if isinstance(s, str)]
        
        return symbols

    except Exception as e:
        print(f"Error loading symbols from {file_name}: {e}")
        return []

def load_symbols_from_csv(file_path: str) -> List[str]:
    """Loads symbols from a user-specified CSV file for custom checks."""
    p = Path(file_path)
    if not p.exists():
        print(f"Error: Custom symbol file not found at '{file_path}'.")
        return []

    try:
        df = pd.read_csv(p)
        
        if 'Symbol' in df.columns:
            symbol_col = 'Symbol'
        elif 'symbol' in df.columns:
            symbol_col = 'symbol'
        else:
             print(f"Error: Could not find a 'Symbol' or 'symbol' column in {file_path}. Please check column headers.")
             return []

        symbols = [f"{s}.NS" for s in df[symbol_col].dropna().unique() if isinstance(s, str)]
        
        print(f"Loaded {len(symbols)} symbols from custom CSV.")
        return symbols

    except Exception as e:
        print(f"Error loading symbols from {file_path}: {e}")
        return []
        
def get_current_global_config_data():
    """Helper to return the current global CONFIG state."""
    return CONFIG.copy()

def get_all_symbols_to_download() -> List[str]:
    """Gathers all symbols from all configured indices and the benchmark."""
    if not CONFIG: load_config()
    all_symbols = set()
    
    # Add benchmark index
    for category in CONFIG["DATA_CONFIG"]["INDICES"].keys():
        index_ticker = CONFIG["DATA_CONFIG"]["INDICES"][category]
        all_symbols.add(index_ticker)

    # Add benchmark
    #benchmark_ticker = CONFIG["DATA_CONFIG"]["INDEX_BENCHMARK"]
    #all_symbols.add(benchmark_ticker)    
    
    # Add all index symbols
    for category in CONFIG["DATA_CONFIG"]["SYMBOL_FILE_MAP"].keys():
        symbols = load_symbols(category)
        all_symbols.update(symbols)
        
    return list(all_symbols)


# ============================================================
# DATA FETCHING AND CACHING (WITH FALLBACK LOGIC)
# ============================================================

def get_cache_path(ticker: str) -> Path:
    """Returns the path to the stock price data cache file for a given ticker, using Parquet format."""
    return CACHE_DIR / f"{ticker.replace('^', 'INDEX_')}.parquet"

# --- NEW CACHING UTILITIES FOR FUNDAMENTAL DATA ---
def get_fundamental_cache_path(ticker: str) -> Path:
    """Returns the path to the fundamental data cache file for a given ticker, using JSON format."""
    return CACHE_DIR / f"{ticker.replace('^', 'INDEX_')}_info_raw.json"

def is_fundamental_cache_valid(ticker: str) -> bool:
    """Checks if the fundamental data cache file exists and is recent enough."""
    cache_path = get_fundamental_cache_path(ticker)
    if not cache_path.exists():
        return False
    
    config = CONFIG.get("DATA_CONFIG", {})
    max_cache_days = config.get("MAX_CACHE_DAYS", 3)
    max_cache_age = timedelta(days=max_cache_days) 
    
    last_modified = datetime.fromtimestamp(cache_path.stat().st_mtime)
    time_since_modified = datetime.now() - last_modified
    
    return time_since_modified <= max_cache_age

def load_fundamental_data_from_cache(ticker: str) -> Optional[Dict[str, Any]]:
    """Loads RAW fundamental (info) data for a ticker from cache using JSON."""
    cache_path = get_fundamental_cache_path(ticker)
    try:
        if cache_path.exists():
            with open(cache_path, 'r') as f:
                data = json.load(f)
            #debug_print(f"{ticker}: Raw fundamental info loaded from Disk Cache")
            # The loaded data is the full raw info dictionary
            return data
    except Exception as e:
        debug_print(f"{ticker}: WARNING - Raw fundamental cache failed to load: {e}. Re-downloading...")
        return None 
    return None

def save_fundamental_data_to_cache(ticker: str, data: Dict[str, Any]):
    """Saves the RAW yfinance info dictionary for a ticker to cache using JSON format."""
    cache_path = get_fundamental_cache_path(ticker)
    try:
        # Recursive function to make all values JSON serializable (handling numpy types and NaNs/Infs)
        def make_json_safe(d):
            if isinstance(d, dict):
                return {k: make_json_safe(v) for k, v in d.items()}
            elif isinstance(d, list):
                return [make_json_safe(v) for v in d]
            elif isinstance(d, (np.floating, np.float64, np.integer, np.int64)):
                # Convert numpy types to standard Python float/int
                if np.isnan(d) or np.isinf(d):
                    return None # Replace NaN/Inf with None (JSON standard)
                return d.item() if hasattr(d, 'item') else d
            elif pd.isna(d):
                 return None
            else:
                return d

        safe_data = make_json_safe(data)
        
        with open(cache_path, 'w') as f:
            # Use skipkeys=True to handle cases where dictionary keys might not be strings
            json.dump(safe_data, f, indent=4, skipkeys=True) 
    except Exception as e:
        debug_print(f"Error saving raw fundamental cache for {ticker}: {e}")

def is_cache_valid(ticker: str) -> bool:
    """
    Checks if the stock price cache file exists and is recent enough using a precise
    timedelta comparison.
    """
    cache_path = get_cache_path(ticker)
    if not cache_path.exists():
        return False
    
    config = CONFIG.get("DATA_CONFIG", {})
    max_cache_days = config.get("MAX_CACHE_DAYS", 3)
    
    # Define the maximum allowed age for the cache file using timedelta
    max_cache_age = timedelta(days=max_cache_days) 
    
    last_modified = datetime.fromtimestamp(cache_path.stat().st_mtime)
    time_since_modified = datetime.now() - last_modified
    
    # Compare the time delta objects directly for precision
    return time_since_modified <= max_cache_age

def load_data_from_cache(ticker: str) -> Optional[pd.DataFrame]:
    """
    Loads data for a ticker from cache using Parquet.
    Uses try/except to handle cache corruption or reading failure.
    """
    cache_path = get_cache_path(ticker)
    try:
        if cache_path.exists():
            # Use read_parquet, which reliably handles the DataFrame structure including the index
            df = pd.read_parquet(cache_path)
            
            # Ensure the Index is a proper DateTimeIndex
            if not isinstance(df.index, pd.DatetimeIndex):
                 df.index = pd.to_datetime(df.index)

            debug_print(f"{ticker}: Stock data loaded from Cache")
            return df
    except Exception:
        # If cache is corrupt or pd.read_parquet fails, treat as non-existent
        print(f"{ticker}: WARNING - Stock cache failed to load (corrupt or format error). Re-downloading...")
        return None 
    return None

def calculate_download_start_date(years_history: int) -> date:
    """
    Calculates the download start date: April 1st of the year corresponding 
    to the requested history depth, ensuring the current financial year is fully covered.
    """
    today = date.today()
    
    # Calculate the year corresponding to the history depth
    target_year = today.year - years_history
    
    # Check if today is before April 1st of the current year (i.e., we are in the
    # first part of the financial year). If so, we need one more year of history
    # to cover the full requested financial year range.
    if today.month < 4:
        target_year -= 1

    # The start date is always April 1st of the calculated target year
    start_date = date(target_year, 4, 1)
    return start_date

def save_data_to_cache(ticker: str, df: pd.DataFrame):
    """Saves stock price data for a ticker to cache using Parquet format."""
    cache_path = get_cache_path(ticker)
    try:
        # Save as Parquet, which preserves index and data types reliably
        df.index.name = 'Date'
        df.to_parquet(cache_path, index=True)
    except Exception as e:
        print(f"Error saving stock cache for {ticker}: {e}")

def download_stock_data_single(ticker: str, period: Optional[str] = None, 
                            start: Optional[date] = None, end: Optional[date] = None) -> Optional[pd.DataFrame]:
    """
    Downloads stock data for a single ticker using either period string 
    (for full history) or start/end dates (for incremental updates).
    """
    if period:
        kwargs = {'period': period}
        range_desc = period
    elif start and end:
        # yfinance 'end' is exclusive, so we use end + 1 day to include the end date.
        kwargs = {'start': start, 'end': end + timedelta(days=1)}
        range_desc = f"{start} to {end}"
    else:
        print(f"[ERROR] Must provide either 'period' or 'start' and 'end' dates for {ticker}.")
        return None
  
    try:
        # Fetch data for the ticker
        #df = yf.download(ticker, period=period, interval='1d', progress=False)
        df = yf.download(ticker, interval='1d', progress=False, **kwargs)
        
        if df.empty:
            return None

        # --- CRITICAL FIX (v10.17.11): Robust MultiIndex Flattening ---
        if isinstance(df.columns, pd.MultiIndex):
             # The correct approach for a single-ticker MultiIndex (like ('Close', 'TKR')) 
             # is to extract the price metric, which is the first element (level 0).
             try:
                 df.columns = [col[0] for col in df.columns]
             except Exception as e:
                 # If explicit extraction fails, log it and let the 'close' check fail later.
                 print(f"[ERROR] Failed to extract price metric from MultiIndex for {ticker}. Error: {e}")
                 # We deliberately do not return None here, allowing the subsequent 'close' check to fail gracefully.
        # --- END FIX ---

        # 1. Ensure columns are standardized to lowercase for internal use
        if df.columns.nlevels == 1 and any(c.isupper() for c in df.columns):
            df.columns = [col.lower() for col in df.columns]

        # 2. Standardize column names (Map common names to required lowercase)
        df = df.rename(columns={'Close': 'close', 'Open': 'open', 
                                'High': 'high', 'Low': 'low', 
                                'Volume': 'volume', 'Adj Close': 'adj_close'})
        df.index.name = 'Date'
        
        # 3. CRITICAL FIX (v10.17.10): Handle missing 'close' by substituting 'adj_close'
        if 'close' not in df.columns and 'adj_close' in df.columns:
            df = df.rename(columns={'adj_close': 'close'})
            
        # 4. FINAL CHECK for 'close'
        if 'close' not in df.columns:
            print(f"[DEBUG] {ticker}: Data downloaded, but essential 'close' column could not be found or derived. Columns found: {list(df.columns)}")
            return None
        
        # --- CRITICAL LOOKAHEAD BIAS CHECK (Enforce only up to current date) ---
        df = df[df.index <= datetime.now()]
        
        return df

    except Exception as e:
        print(f"[ERROR] Failed to download data for {ticker} (Range: {range_desc}). Error: {e}")
        return None
    
def download_stock_data_with_fallback(ticker: str) -> bool:
    """
    Checks cache status and performs an incremental update (start/end) if stale, 
    or a full download (period) using the configurable history years with a 20-year fallback.
    """
    today = date.today()
    config_years = CONFIG["DATA_CONFIG"].get("DOWNLOAD_HISTORY_YEARS", 5)
    
    # Calculate the minimum historical date we must keep (used for filtering merged data)
    # try:
    #     historical_start_date = today.replace(year=today.year - config_years)
    # except ValueError:
    #     historical_start_date = today - timedelta(days=config_years * 365 + 1)
        
    
    is_valid = is_cache_valid(ticker)
    # --- UPDATED: Use the new helper function ---
    cache_file = get_cache_path(ticker)
    cache_exists = cache_file.exists()
    # ------------------------------------------
    
    df_cached = None

    if cache_exists:
        try:
            # load_data_from_cache now uses get_cache_path internally
            df_cached = load_data_from_cache(ticker)
            
            if is_valid and df_cached is not None and not df_cached.empty:
                # Case 1: Cache is valid and sufficient
                GLOBAL_STOCK_DATA[ticker] = df_cached
                debug_print(f"{ticker}: Cache is valid and loaded (up to {df_cached.index.max().date()}).")
                return True
            
            elif not is_valid and df_cached is not None and not df_cached.empty:
                # Case 2: Cache is INVALID (STALE). Attempt incremental update (date-based).
                cache_end_date = df_cached.index.max().date()
                incremental_start_date = cache_end_date + timedelta(days=1)
                
                if incremental_start_date < today:
                    
                    sys.stdout.write(f"  -> Cache stale. Downloading {ticker} incrementally from {incremental_start_date}...")
                    sys.stdout.flush()
                    
                    df_new = download_stock_data_single(ticker, start=incremental_start_date, end=today)
                    
                    if df_new is not None and not df_new.empty:
                        # Merge and save
                        combined_df = pd.concat([df_cached, df_new])
                        # Keep the latest entry for any overlapping dates (new download)
                        combined_df = combined_df[~combined_df.index.duplicated(keep='last')]
                        
                        # Filter combined data to maintain required history depth
                        # combined_df = combined_df[combined_df.index.date >= historical_start_date]
                        
                        # save_data_to_cache now uses get_cache_path internally
                        save_data_to_cache(ticker, combined_df)
                        GLOBAL_STOCK_DATA[ticker] = combined_df
                        sys.stdout.write(f"  -> Success: {ticker} updated incrementally (Total {len(combined_df)} days).    \r")
                        sys.stdout.flush()
                        return True
                    else:
                        print(f" [WARNING] Incremental update failed for {ticker}. Attempting full download...")
                        # Fall through to Case 3
                        
                else:
                    # Cache end date is today or later, no incremental update needed.
                    GLOBAL_STOCK_DATA[ticker] = df_cached
                    print(f" [INFO] Cache for {ticker} is technically stale but dates are current. Using cache.")
                    return True
            
            # If the cache exists but is empty, fall through to full download (Case 3).

        except Exception as e:
            # Catch file read errors, corrupted files, etc. Fall through to full download.
            print(f" [WARNING] Failed to load cache for {ticker}: {e}. Attempting full download...")


    # Case 3: Cache is missing, empty, or update failed. Perform FULL download with fallback (period-based).
    df_full = None
    
    # Try downloading with fallback periods (20 years down to 1 year)
    for years in range(config_years, 0, -1):
        period_str = f'{years}y'
        sys.stdout.write(f"  -> Downloading {ticker} for {period_str}...")
        sys.stdout.flush()
        
        # Use the download_stock_data_single with the period parameter
        df_full = download_stock_data_single(ticker, period=period_str)
        
        if df_full is not None and not df_full.empty:
            # Enforce minimum 1 year of trading days (~252) if we are in the 1y attempt
            if years == 1 and len(df_full) < 252:
                sys.stdout.write(f"  -> Failed for {ticker} at 1y: only {len(df_full)} days available. Moving to next ticker.         \r")
                sys.stdout.flush()
                break # Failed minimum requirement
            
            # Success
            save_data_to_cache(ticker, df_full)
            GLOBAL_STOCK_DATA[ticker] = df_full
            sys.stdout.write(f"  -> Success: {ticker} data fetched for {period_str} and saved to cache.   \r")
            sys.stdout.flush()
            return True
            
    # If the loop completes without success
    sys.stdout.write(f"  -> Failed: Could not download at least 1 year of data for {ticker}.         \r")
    sys.stdout.flush()
    return False


def download_stock_data_with_fallback(ticker: str) -> bool:
    """
    Checks cache status and performs an incremental update (start/end) if stale, 
    or a full download (period) using the configurable history years with a 20-year fallback.
    It forces a full download if the cached history depth is insufficient for the current config.
    """
    today = date.today()
    config_years = CONFIG["DATA_CONFIG"].get("DOWNLOAD_HISTORY_YEARS", 5)
    
    # Calculate the minimum historical date we must keep and require
    try:
        required_start_date = today.replace(year=today.year - config_years)
    except ValueError:
        # Handle February 29th issue gracefully
        required_start_date = today - timedelta(days=config_years * 365 + 5)
        
    
    is_valid = is_cache_valid(ticker)
    cache_file = get_cache_path(ticker)
    cache_exists = cache_file.exists()
    
    df_cached = None
    trigger_full_download = False # Flag to force full download

    if cache_exists:
        try:
            df_cached = load_data_from_cache(ticker)
            
            if df_cached is None or df_cached.empty:
                # Cache file exists but contains no data
                trigger_full_download = True
            
            elif is_valid:
                # Case 1: Cache is valid (timestamp OK). Check depth.
                cache_start_date = df_cached.index.min().date()
                # By passing cache update even if it does have historical data as some stock might not be having Historical data and it lead to data download again and again
                cache_start_date = required_start_date 
                
                if cache_start_date > required_start_date:
                    # Cache is valid but SHALLOW (e.g., 2 years stored, 5 required)
                    print(f" [WARNING] {ticker} cache history ({cache_start_date}) is less than {config_years} years. Triggering full download.")
                    trigger_full_download = True
                else:
                    # Cache is valid and deep enough
                    GLOBAL_STOCK_DATA[ticker] = df_cached
                    debug_print(f"{ticker}: Cache is valid and loaded (up to {df_cached.index.max().date()}).")
                    return True
            
            # If we reach here, the cache is NOT valid (STALE/SHALLOW)
            if not trigger_full_download: 
                # Case 2: Cache is INVALID (STALE) but deep enough. Attempt incremental update.
                
                cache_end_date = df_cached.index.max().date()
                incremental_start_date = cache_end_date + timedelta(days=1)
                
                if incremental_start_date < today:
                    
                    sys.stdout.write(f"  -> Cache stale. Downloading {ticker} incrementally from {incremental_start_date}...")
                    sys.stdout.flush()
                    
                    df_new = download_stock_data_single(ticker, start=incremental_start_date, end=today)
                    
                    if df_new is not None and not df_new.empty:
                        # Merge and save
                        combined_df = pd.concat([df_cached, df_new])
                        # Keep the latest entry for any overlapping dates (new download)
                        combined_df = combined_df[~combined_df.index.duplicated(keep='last')]
                        
                        # Filter combined data to maintain required history depth
                        # RE-ENABLED: Filter to maintain required start date
                        combined_df = combined_df[combined_df.index.date >= required_start_date]
                        
                        save_data_to_cache(ticker, combined_df)
                        GLOBAL_STOCK_DATA[ticker] = combined_df
                        sys.stdout.write(f"  -> Success: {ticker} updated incrementally (Total {len(combined_df)} days).    \r")
                        sys.stdout.flush()
                        return True
                    else:
                        print(f" [WARNING] Incremental update failed for {ticker}. Attempting full download...")
                        trigger_full_download = True # Fall through to Case 3
                        
                else:
                    # Cache end date is today or later, no incremental update needed.
                    GLOBAL_STOCK_DATA[ticker] = df_cached
                    print(f" [INFO] Cache for {ticker} is technically stale but dates are current. Using cache.")
                    return True

        except Exception as e:
            # Catch file read errors, corrupted files, etc. Fall through to full download.
            print(f" [WARNING] Failed to load cache for {ticker}: {e}. Triggering full download...")
            trigger_full_download = True


    # Case 3: Cache is missing, empty, shallow, or update failed. Perform FULL download with fallback (period-based).
    if not cache_exists or trigger_full_download:        
        df_full = None
        # Try downloading with fallback periods (Config years down to 1 year)
        for years in range(config_years, 0, -1):
            period_str = f'{years}y'
            sys.stdout.write(f"  -> Downloading {ticker} for {period_str}...")
            sys.stdout.flush()
            
            # Use the download_stock_data_single with the period parameter
            df_full = download_stock_data_single(ticker, period=period_str)
            
            if df_full is not None and not df_full.empty:
                # Enforce minimum 1 year of trading days (~252) if we are in the 1y attempt
                if years == 1 and len(df_full) < 252:
                    sys.stdout.write(f"  -> Failed for {ticker} at 1y: only {len(df_full)} days available. Moving to next ticker.         \r")
                    sys.stdout.flush()
                    break # Failed minimum requirement
                
                # Success
                save_data_to_cache(ticker, df_full)
                GLOBAL_STOCK_DATA[ticker] = df_full
                sys.stdout.write(f"  -> Success: {ticker} data fetched for {period_str} and saved to cache.   \r")
                sys.stdout.flush()
                return True
                
        # If the loop completes without success
        sys.stdout.write(f"  -> Failed: Could not download at least 1 year of data for {ticker}.         \r")
        sys.stdout.flush()
        return False
        
    return False    

YF_TO_NSE_INDEX = {
    "Nifty50": {
        "yahoo": "^NSEI",
        "nse_name": "NIFTY 50",
        "nse_code": "NIFTY 50",
    },
    "Nifty100": {
        "yahoo": "^CNX100",
        "nse_name": "NIFTY 100",
        "nse_code": "NIFTY 100",
    },
    "Midcap150": {
        "yahoo": "NIFTYMIDCAP150.NS",
        "nse_name": "NIFTY MIDCAP 150",
        "nse_code": "NIFTY MIDCAP 150",
    },
    "Smallcap250": {
        "yahoo": "MOSMALL250.NS",              # legacy YF ticker
        "nse_name": "NIFTY SMALLCAP 250",
        "nse_code": "NIFTY SMALLCAP 250",
    },
    "NiftyLargeMidcap250": {
        "yahoo": "ELM250.NS",
        "nse_name": "NIFTY LARGEMIDCAP 250",
        "nse_code": "NIFTY LARGEMIDCAP 250",
    },
    "NiftyNext50": {
        "yahoo": "^NSMIDCP",
        "nse_name": "NIFTY NEXT 50",
        "nse_code": "NIFTY NEXT 50",
    },
    "NiftyMicrocap250": {
        "yahoo": "MOSMALL250.NS",
        "nse_name": "NIFTY MICROCAP 250",
        "nse_code": "NIFTY MICROCAP 250",
    },
    "Nifty500": {
        "yahoo": "^CRSLDX",
        "nse_name": "NIFTY 500",
        "nse_code": "NIFTY 500",
    },
}

def yf_ticker_to_nse_name(yf_ticker: str) -> str:
    for meta in YF_TO_NSE_INDEX.values():
        if meta["yahoo"] == yf_ticker:
            return meta["nse_name"]
    raise KeyError(f"No NSE mapping found for {yf_ticker}")

def download_stock_from_nse(ticker: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """
    Download data from NSE website and use it as yfinance data frame
    Convert NSE index historical DataFrame (as downloaded from NSE)
    to a yfinance-style OHLCV DataFrame:
      - Date index
      - Columns: Open, High, Low, Close, Adj Close, Volume
    """
    from nsepython import index_history
    start_date_nse = datetime.strptime(start_date, "%Y-%m-%d").strftime("%d-%b-%Y")
    end_date_nse = datetime.strptime(end_date, "%Y-%m-%d").strftime("%d-%b-%Y")
    
    ticker_nse = yf_ticker_to_nse_name(ticker)
    print(f"ticker_nse = {ticker_nse}, start_date = {start_date_nse}, end_date = {end_date_nse}")
    df = index_history(symbol=ticker_nse,
                    start_date=start_date_nse,
                    end_date=end_date_nse)
    print(f"Downloaded Benchmark data for index {ticker} : {df.shape}")
    if df.empty:
        return pd.DataFrame()
    
    # 1) Normalize column names
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    # Now you have: requestnumber, index_name, index_name_(duplicated), historicaldate, open, high, low, close

    # 2) Parse date
    # NSE format: "28 Nov 2025"
    df["historicaldate"] = pd.to_datetime(df["historicaldate"], format="%d %b %Y")
    df = df.sort_values("historicaldate").set_index("historicaldate")

    # 3) Build yfinance-style DataFrame
    out = pd.DataFrame(index=df.index)

    out["Open"] = pd.to_numeric(df["open"], errors="coerce")
    out["High"] = pd.to_numeric(df["high"], errors="coerce")
    out["Low"]  = pd.to_numeric(df["low"], errors="coerce")
    out["Close"] = pd.to_numeric(df["close"], errors="coerce")    

    # No real volume for index; set to 0 or NaN
    out["Volume"] = 0
    out["Volume"] = out["Volume"].astype("int64")

    # Adj Close = Close (no adjustment info for index)
    out["Adj Close"] = out["Close"]

    # Reorder columns to match yfinance
    out = out[["Open", "High", "Low", "Close", "Adj Close", "Volume"]]

    return out

def download_stock_data_single_benchmark(ticker: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """
    Downloads fresh stock data for a single ticker with a specific period,
    including critical fixes for column alignment, lookahead bias, and missing 'close' data.
    """
    try:
        # Fetch data for the ticker
        #df = yf.download(ticker, period=period, interval='1d', progress=False)
        #df = yf.download(ticker, start=start_date, end=end_date, interval="1d")
        df = download_stock_from_nse(ticker, start_date, end_date)
        if df.empty:
            return None

        # --- CRITICAL FIX (v10.17.11): Robust MultiIndex Flattening ---
        if isinstance(df.columns, pd.MultiIndex):
             # The correct approach for a single-ticker MultiIndex (like ('Close', 'TKR')) 
             # is to extract the price metric, which is the first element (level 0).
             try:
                 df.columns = [col[0] for col in df.columns]
             except Exception as e:
                 # If explicit extraction fails, log it and let the 'close' check fail later.
                 print(f"[ERROR] Failed to extract price metric from MultiIndex for {ticker}. Error: {e}")
                 # We deliberately do not return None here, allowing the subsequent 'close' check to fail gracefully.
        # --- END FIX ---

        # 1. Ensure columns are standardized to lowercase for internal use
        if df.columns.nlevels == 1 and any(c.isupper() for c in df.columns):
            df.columns = [col.lower() for col in df.columns]

        # 2. Standardize column names (Map common names to required lowercase)
        df = df.rename(columns={'Close': 'close', 'Open': 'open', 
                                'High': 'high', 'Low': 'low', 
                                'Volume': 'volume', 'Adj Close': 'adj_close'})
        df.index.name = 'Date'
        
        # 3. CRITICAL FIX (v10.17.10): Handle missing 'close' by substituting 'adj_close'
        if 'close' not in df.columns and 'adj_close' in df.columns:
            df = df.rename(columns={'adj_close': 'close'})
            
        # 4. FINAL CHECK for 'close'
        if 'close' not in df.columns:
            print(f"[DEBUG] {ticker}: Data downloaded, but essential 'close' column could not be found or derived. Columns found: {list(df.columns)}")
            return None
        
        # --- CRITICAL LOOKAHEAD BIAS CHECK (Enforce only up to current date) ---
        df = df[df.index <= datetime.now()]
        
        return df

    except Exception as e:
        print(f"[ERROR] Failed to download data for {ticker} (start_date: {start_date}). (end_date: {end_date}) Error: {e}")
        return None

def get_date_range(days_back=20*365, date_str=None):
    """
    Returns today and N years back date strings (default 20 years).
    
    Parameters:
    -----------
    days_back : int, default=20*365 (7300 days ~20 years)
        Number of days to go back from end_date
    date_str : str, optional
        End date in 'YYYY-MM-DD' format. If None, uses today.
    
    Returns:
    --------
    dict: {'start_date': 'YYYY-MM-DD', 'end_date': 'YYYY-MM-DD'}
    """
    # Parse end date (today if not provided)
    if date_str is None:
        end_date = datetime.now().date()
    else:
        end_date = pd.to_datetime(date_str).date()
    
    # Calculate start date
    start_date = end_date - timedelta(days=days_back)
    
    return {
        'start_date': start_date.strftime('%Y-%m-%d'),
        'end_date': end_date.strftime('%Y-%m-%d')
    }

def download_benchmark_data(ticker: str) -> bool:
    """
    Downloads benchmark data. Prioritizes in-memory data, checks cache validity, 
    performs incremental updates if stale, and triggers a full download if the 
    cache is missing, shallow, or needs a full refresh based on configured history years.
    
    NOTE: Uses date-based downloads and the dedicated download_stock_data_single_benchmark function.
    """
    today = date.today()
    # Use the configurable history setting for the required depth
    config_years = CONFIG["DATA_CONFIG"].get("DOWNLOAD_HISTORY_YEARS", 5) 
    
    # Calculate the required start date based on config_years for history check
    try:
        required_start_date = today.replace(year=today.year - config_years)
    except ValueError:
        # Handle February 29th issue gracefully
        required_start_date = today - timedelta(days=config_years * 365 + 5) 
        
    
    # 1. Prioritize In-Memory Data
    if ticker in GLOBAL_BENCHMARK_DATA:
        debug_print(f"{ticker}: Already present in GLOBAL_BENCHMARK_DATA.")
        return True
        
    is_valid = is_cache_valid(ticker)
    cache_file = get_cache_path(ticker) # Use Parquet helper
    cache_exists = cache_file.exists()
    
    df_cached = None
    trigger_full_download = False

    if cache_exists:
        try:
            df_cached = load_data_from_cache(ticker)
            
            if df_cached is None or df_cached.empty:
                 # Cache file exists but contains no data
                 trigger_full_download = True
            
            elif is_valid:
                # Case 1: Cache is valid (timestamp OK).
                
                # Check if the valid cache has sufficient history depth
                cache_start_date = df_cached.index.min().date()
                
                # By passing cache update even if it does have historical data as some stock might not be having Historical data and it lead to data download again and again
                cache_start_date = required_start_date 
                
                if cache_start_date > required_start_date:
                    # Case 1A: Cache is shallow (e.g., 2 years stored, 5 required)
                    print(f" [WARNING] Benchmark {ticker} cache history ({cache_start_date}) is less than {config_years} years. Triggering full download.")
                    trigger_full_download = True
                else:
                    # Cache is valid and deep enough
                    GLOBAL_BENCHMARK_DATA[ticker] = df_cached
                    debug_print(f"{ticker}: Cache is valid and loaded (up to {df_cached.index.max().date()}).")
                    return True
            
            # If we reach here, the cache is either STALE, SHALLOW, or EMPTY.
            if not trigger_full_download: # Only attempt incremental if we haven't decided on a full download yet
                cache_end_date = df_cached.index.max().date()
                incremental_start_date = cache_end_date + timedelta(days=1)
                
                if incremental_start_date < today:
                    # Case 2: Cache is STALE but history depth is sufficient. Attempt incremental update.
                    
                    sys.stdout.write(f"  -> Cache stale. Downloading benchmark {ticker} incrementally from {incremental_start_date}...")
                    sys.stdout.flush()
                    
                    # Use dedicated benchmark function with start/end dates
                    df_new = download_stock_data_single_benchmark(ticker, start_date=incremental_start_date.strftime('%Y-%m-%d'), end_date=today.strftime('%Y-%m-%d'))
                    
                    if df_new is not None and not df_new.empty:
                        # Merge and save
                        combined_df = pd.concat([df_cached, df_new])
                        combined_df = combined_df[~combined_df.index.duplicated(keep='last')]
                        
                        save_data_to_cache(ticker, combined_df)
                        GLOBAL_BENCHMARK_DATA[ticker] = combined_df
                        sys.stdout.write(f"  -> Success: Benchmark {ticker} updated incrementally (Total {len(combined_df)} days).    \r")
                        sys.stdout.flush()
                        return True
                    else:
                        print(f" [WARNING] Incremental update failed for benchmark {ticker}. Attempting full download.")
                        trigger_full_download = True # Fall through to Case 3

                else:
                    # Cache end date is today or later, no download needed despite staleness
                    GLOBAL_BENCHMARK_DATA[ticker] = df_cached
                    print(f" [INFO] Cache for benchmark {ticker} is technically stale but dates are current. Using cache.")
                    return True

        except Exception as e:
            # Catch file read errors, corrupted files, etc. Fall through to full download.
            print(f" [WARNING] Failed to load cache for benchmark {ticker}: {e}. Triggering full download...")
            trigger_full_download = True

    # Case 3: Cache is missing, empty, shallow, or update failed. Perform FULL download.
    if not cache_exists or trigger_full_download:
        
        # --- REINSTATED DATE-BASED DOWNLOAD LOGIC USING GET_DATE_RANGE ---
        # Assuming get_date_range(days_back=N) calculates the required range
        date_range = get_date_range(days_back=int(config_years * 365.25))
        start_date, end_date = date_range['start_date'], date_range['end_date']
        
        sys.stdout.write(f"  -> Downloading benchmark {ticker} for configured period from {start_date} to {end_date}...")
        sys.stdout.flush()
        
        # Use the dedicated download_stock_data_single_benchmark function with start/end dates
        df_full = download_stock_data_single_benchmark(ticker, start_date=start_date, end_date=end_date)
        
        if df_full is None or df_full.empty:
            sys.stdout.write(f"  -> Failed: Could not download benchmark {ticker}.         \r")
            sys.stdout.flush()
            if df_cached is not None:
                # Fallback to stale cache if full download fails
                GLOBAL_BENCHMARK_DATA[ticker] = df_cached
                print(f" [WARNING] Full download failed. Using stale cache for benchmark {ticker} (Last date: {df_cached.index.max().date()}).")
                return True
            return False
            
        # Success
        save_data_to_cache(ticker, df_full)
        GLOBAL_BENCHMARK_DATA[ticker] = df_full
        sys.stdout.write(f"  -> Success: Benchmark {ticker} data fetched and saved to cache.        \r")
        sys.stdout.flush()
        return True

    return False

def initial_data_precache():
    """Executes the mandatory initial download/cache check at program start."""
    print("\n" + "="*70)
    print("MANDATORY INITIAL DATA PRE-CACHE & VALIDATION (20y -> 1y Fallback)")
    print("="*70)
    
    if not CONFIG: load_config()
    
    all_tickers = get_all_symbols_to_download()
    total_tickers = len(all_tickers)
    
    print(f"Total unique tickers to check: {total_tickers}")
    
    benchmark_ticker_global = CONFIG["DATA_CONFIG"]["INDEX_BENCHMARK"]
    benchmark_ticker_dict = CONFIG["DATA_CONFIG"]["INDICES"]
    debug_print(f"benchmark_ticker_dict = {benchmark_ticker_dict}")
    
    successful_price_downloads = 0 # Renamed counter for clarity
    successful_fundamental_downloads = 0 # New counter
    
    for i, ticker in enumerate(all_tickers):
        
        # --- 1. Stock Price Data Download/Check ---
        sys.stdout.write(f"[{i + 1}/{total_tickers}] Processing {ticker} - Price Data... \r")
        sys.stdout.flush()
        
        if ticker in benchmark_ticker_dict.values():
            #print(f"ticker = {ticker} is present in {benchmark_ticker_dict}")
            if download_benchmark_data(ticker):
                 successful_price_downloads += 1
        elif ticker == benchmark_ticker_global:
            if download_benchmark_data(ticker):
                 successful_price_downloads += 1
        else:
            if download_stock_data_with_fallback(ticker):
                successful_price_downloads += 1
        
        # --- 2. Fundamental Data Download/Check ---
        sys.stdout.write(f"[{i + 1}/{total_tickers}] Processing {ticker} - Fundamental Data... \r")
        sys.stdout.flush()
        
        # Calling get_fundamental_data triggers disk cache check/download of RAW info
        fundamental_data = get_fundamental_data(ticker)
        
        # Check if at least one factor was fetched/calculated
        if any(v is not None and not np.isnan(v) for v in fundamental_data.values()):
            successful_fundamental_downloads += 1
                
        sys.stdout.write("                                                                     \r") # Clear line
        sys.stdout.flush() 
        
    
    print("\n" + "="*70)
    print(f"Initial precaching complete.")
    print(f"  - Successfully loaded PRICE data for {successful_price_downloads}/{total_tickers} tickers.")
    print(f"  - Successfully loaded FUNDAMENTAL data for {successful_fundamental_downloads}/{total_tickers} tickers.")
    print("="*70)
    
def update_global_data(tickers: List[str]):
    """
    Ensures all required stock data is in memory. Downloads missing/stale data using the 
    single-ticker fallback logic.
    """
    if not CONFIG: load_config()
    
    all_needed_tickers = set(tickers)
    benchmark_ticker = CONFIG["DATA_CONFIG"]["INDEX_BENCHMARK"]
    all_needed_tickers.add(benchmark_ticker)
    
    tickers_to_check = []
    
    # Check cache/memory status
    for ticker in all_needed_tickers:
        if ticker in GLOBAL_STOCK_DATA or ticker in GLOBAL_BENCHMARK_DATA:
            continue
        
        # If not in memory, check if it needs downloading
        tickers_to_check.append(ticker)
    
    if not tickers_to_check:
        return

    print(f"\nPerforming just-in-time stock data update for {len(tickers_to_check)} missing tickers...")
    
    
    for idx, ticker in enumerate(tickers_to_check):
        sys.stdout.write(f"  -> Updating {ticker} ({idx + 1}/{len(tickers_to_check)})        \r")
        sys.stdout.flush()
        
        if ticker == benchmark_ticker:
            download_benchmark_data(ticker)
        else:
            download_stock_data_with_fallback(ticker)

    sys.stdout.write("Just-in-time stock data update complete.                               \r")
    sys.stdout.flush() 

def get_data_for_symbol_backtest(symbol: str) -> Optional[pd.DataFrame]:
    """Retrieves the stock data from GLOBAL_STOCK_DATA for backtesting."""
    return GLOBAL_STOCK_DATA.get(symbol)

def get_data_for_benchmark_backtest(ticker: str) -> Optional[pd.DataFrame]:
    """Retrieves the benchmark data from GLOBAL_BENCHMARK_DATA for backtesting."""
    return GLOBAL_BENCHMARK_DATA.get(ticker)

# ============================================================
# TECHNICAL INDICATOR HELPERS
# ============================================================


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """Calculates the Relative Strength Index (RSI)."""
    if df.empty or 'close' not in df.columns or len(df) < period:
        return np.nan
    try:
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        # To avoid division by zero, replace 0 with a small epsilon
        loss = loss.replace(0, np.finfo(float).eps) 
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1].item()
    except Exception:
        return np.nan
    # from ta.momentum import RSIIndicator
    # rsi = RSIIndicator(df["close"], window=period).rsi()
    # return rsi.iloc[-1].item()

def calculate_cci(df: pd.DataFrame, period: int = 20) -> Optional[float]:
    """Calculates the Commodity Channel Index (CCI)."""
    if df.empty or len(df) < period or any(col not in df.columns for col in ['high', 'low', 'close']):
        return np.nan
    try:
        df_temp = df.copy()
        df_temp['TP'] = (df_temp['high'] + df_temp['low'] + df_temp['close']) / 3
        df_temp['SMA_TP'] = df_temp['TP'].rolling(window=period).mean()
        # Mean Absolute Deviation
        df_temp['MAD'] = df_temp['TP'].rolling(window=period).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
        # CCI calculation: (TP - SMA_TP) / (0.015 * df_temp['MAD'])
        cci = (df_temp['TP'] - df_temp['SMA_TP']) / (0.015 * df_temp['MAD'])
        return cci.iloc[-1].item()
    except Exception:
        return np.nan
    
    # from ta.trend import CCIIndicator, EMAIndicator
    # cci = CCIIndicator(high=df_temp["high"],low=df_temp["low"], close=df_temp["close"], window=period).cci()
    # return cci.iloc[-1].item()

def calculate_mfi(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """Calculates the Money Flow Index (MFI)."""
    if df.empty or len(df) < period or any(col not in df.columns for col in ['high', 'low', 'close', 'volume']):
        return np.nan
    try:
        df_temp = df.copy()
        df_temp['TP'] = (df_temp['high'] + df_temp['low'] + df_temp['close']) / 3
        df_temp['MF'] = df_temp['TP'] * df_temp['volume']
        # Positive and Negative Money Flow (using diff to check price change)
        df_temp['P_MF'] = np.where(df_temp['TP'].diff() > 0, df_temp['MF'], 0)
        df_temp['N_MF'] = np.where(df_temp['TP'].diff() < 0, df_temp['MF'], 0)
        
        P_MF_Sum = df_temp['P_MF'].rolling(window=period).sum()
        N_MF_Sum = df_temp['N_MF'].rolling(window=period).sum()
        
        # Money Ratio (MR) - replace 0 with epsilon to avoid division by zero
        N_MF_Sum_safe = N_MF_Sum.replace(0, np.finfo(float).eps)
        MR = P_MF_Sum / N_MF_Sum_safe
        mfi = 100 - (100 / (1 + MR))
        return mfi.iloc[-1].item()
    except Exception:
        return np.nan
    
    # from ta.volume import MFIIndicator
    # mfi = MFIIndicator(
    #     high=df_temp["high"], 
    #     low=df_temp["low"], 
    #     close=df_temp["close"], 
    #     volume=df_temp["volume"], 
    #     window=14
    # ).money_flow_index()
    # return mfi.iloc[-1].item()

# ============================================================
# New Interest Calculation Utility
# ============================================================

def apply_interest_to_cash(cash_amount: float, days: int, annual_rate: float) -> float:
    """
    Calculates and applies simple interest to the cash for the rebalance period.
    Annual rate is expected as a decimal (e.g., 0.04 for 4%).
    """
    if cash_amount <= 0 or days <= 0 or annual_rate <= 0:
        return cash_amount
        
    # Interest formula: P * (1 + (Rate * Days / 365.25))
    interest_factor = 1.0 + (annual_rate * (days / 365.25))
    return cash_amount * interest_factor
        
# ============================================================
# SCORING FACTOR CALCULATIONS
# ============================================================
def get_fundamental_data(symbol: str) -> Dict[str, Optional[float]]:
    """
    Fetches real fundamental data for Value Score calculation (BookToPrice, EarningsYield, SalesToPrice)
    using yfinance and implements a layered cache (In-memory -> Raw Disk Info -> yfinance).
    
    The function returns the calculated *derived* metrics.
    """
    global GLOBAL_FUNDAMENTAL_DATA
    
    # Initialize result dictionary for derived metrics
    derived_metrics = {
        'BookToPrice': None, 
        'EarningsYield': None, 
        'SalesToPrice': None
    }
    
    # 1. Check in-memory cache for DERIVED metrics
    if symbol in GLOBAL_FUNDAMENTAL_DATA:
        #debug_print(f"{symbol}: Derived fundamental data loaded from In-Memory Cache.")
        return GLOBAL_FUNDAMENTAL_DATA[symbol]

    # --- RAW INFO Data Retrieval (Disk or Fetch) ---
    raw_info: Optional[Dict[str, Any]] = None

    # 2. Check Disk Cache for RAW info
    if is_fundamental_cache_valid(symbol):
        raw_info = load_fundamental_data_from_cache(symbol)

    # 3. Fetch data from yfinance if raw info is missing or invalid
    if raw_info is None:
        print(f"  -> Fetching RAW yfinance info for {symbol}...")
        try:
            ticker = yf.Ticker(symbol)
            # Fetch the info dictionary
            raw_info = ticker.info 
            
            if raw_info and len(raw_info) > 10: # Simple check for valid info dict
                # Save the complete RAW info dictionary to disk cache
                save_fundamental_data_to_cache(symbol, raw_info)
            else:
                 raw_info = {} # Treat as empty/invalid
                 
        except Exception as e:
            debug_print(f"Failed to fetch RAW fundamental info for {symbol}: {e}")
            raw_info = {}
            
    # --- Process RAW info to get DERIVED metrics ---
    
    # Use raw_info (from cache or download) to calculate derived metrics
    if raw_info:
        # Note: yfinance uses 'priceToBook', 'trailingPE', and 'priceToSales'
        pb_ratio = raw_info.get('priceToBook') 
        pe_ratio = raw_info.get('trailingPE')
        ps_ratio = raw_info.get('priceToSales') 

        # --- Calculate Inverse Metrics (Value Factors) ---
        
        # Helper to convert to float and check for validity (None, 0, inf, nan)
        def safe_inverse(ratio: Any) -> Optional[float]:
            """
            Calculates the safe inverse (1/ratio) after ensuring the ratio is a 
            valid, non-zero, non-inf, non-nan float, handling non-numeric types gracefully.
            """
            if ratio is None:
                return None
            
            try:
                # CRITICAL FIX: Convert to float first. This resolves the TypeError 
                # by ensuring np.isinf/isnan is only called on a numeric type.
                float_ratio = float(ratio)
            except (ValueError, TypeError):
                # Handles cases where ratio is a non-numeric string (e.g., 'N/A')
                return None
                
            # Check for 0, inf, and nan on the guaranteed float value
            if float_ratio == 0.0 or np.isinf(float_ratio) or np.isnan(float_ratio):
                 return None
            
            # The value is a valid, non-zero number. Calculate the inverse.
            return 1.0 / float_ratio
        
        derived_metrics['BookToPrice'] = safe_inverse(pb_ratio) 
        derived_metrics['EarningsYield'] = safe_inverse(pe_ratio)
        derived_metrics['SalesToPrice'] = safe_inverse(ps_ratio)
        
    # 4. Save DERIVED metrics to In-memory cache and return
    GLOBAL_FUNDAMENTAL_DATA[symbol] = derived_metrics
        
    return derived_metrics

def calculate_raw_value_score(fundamentals: Dict[str, Optional[float]]) -> Optional[float]:
    """
    Calculates the raw composite Value Score (V-Score components).
    Metrics: Book-to-Price (Inverse P/B), Earnings Yield (Inverse P/E), Sales-to-Price (Inverse P/S).
    """
    if not fundamentals: return np.nan
    
    metrics = {
        'BookToPrice': fundamentals.get('BookToPrice'), 
        'EarningsYield': fundamentals.get('EarningsYield'), 
        'SalesToPrice': fundamentals.get('SalesToPrice')
    }
    
    score = 0
    valid_components = 0
    
    for val in metrics.values():
        # Check for None, 0, or explicit NaN
        if val is not None and not np.isnan(val):
            score += val
            valid_components += 1
            
    return float(score / valid_components) if valid_components > 0 else np.nan


def calculate_raw_price_momentum_score(df: pd.DataFrame) -> Optional[float]:
    """
    Calculates the raw composite Price Momentum Score (P-Score components).
    Metrics: 12M, 6M ROC, Distance from 52W High.
    """
    if df.empty or 'close' not in df.columns: return np.nan
    
    try:
        latest_close = df['close'].iloc[-1].item()
    except:
        return np.nan
    
    # 1. 12-Month Momentum (252-day ROC)
    roc_12m = df['close'].pct_change(252).iloc[-1].item() if len(df) > 252 else np.nan
    #roc_12m = (Current_Price/ Price_252_days_ago) - 1
    
    # 2. 6-Month Rate of Change (126-day ROC)
    roc_6m = df['close'].pct_change(126).iloc[-1].item() if len(df) > 126 else np.nan
    
    # 3. 6-Month Rate of Change (63-day ROC)
    roc_3m = df['close'].pct_change(63).iloc[-1].item() if len(df) > 63 else np.nan
    
    # 4. Distance from 52-Week High (Current Price relative to 52W High)
    high_52w = df['high'].tail(252).max() if len(df) > 252 else np.nan
    
    if hasattr(high_52w, 'item'):
        high_52w = high_52w.item() 
            
    distance_from_high = (latest_close / high_52w) - 1 if not np.isnan(high_52w) and high_52w > 0 else np.nan
    
    raw_score = 0
    valid_weights = 0
    
    # Weights for this composite P-Score:
    if not np.isnan(roc_12m):
        raw_score += roc_12m * 1.0 
        valid_weights += 1.0
    if not np.isnan(roc_6m):
        raw_score += roc_6m * 2.0
        valid_weights += 2.0
    if not np.isnan(roc_3m):
        raw_score += roc_3m * 2.0
        valid_weights += 2.0
    if not np.isnan(distance_from_high):
        raw_score += distance_from_high * 0.5 # Lower weight for distance
        valid_weights += 0.5 
    
    return (raw_score / valid_weights) * 100 if valid_weights > 0 else np.nan


def calculate_weighted_momentum_score(df: pd.DataFrame) -> Optional[float]:
    """
    Calculates the ROC Composite Score for the Final WMS. 
    Periods: 60, 40, 20 days, with higher weight on shorter duration, as requested.
    """
    if df.empty or 'close' not in df.columns: return np.nan
    
    config = CONFIG["MOMENTUM_CONFIG"]
    periods = config["WMS_ROC_PERIODS"]
    weights = config["WMS_ROC_WEIGHTS"]
    
    if len(periods) != len(weights):
        print("[ERROR] WMS_ROC_PERIODS and WMS_ROC_WEIGHTS must have the same length.")
        return np.nan

    weighted_roc_sum = 0
    total_valid_weight = 0

    for period, weight in zip(periods, weights):
        if len(df) > period:
            try:
                roc = df['close'].pct_change(period).iloc[-1].item()
                # from ta.momentum import RSIIndicator, ROCIndicator
                # roc_sr = ROCIndicator(df["close"], window=period).roc()
                # roc = roc_sr.iloc[-1].item()
                
                if not np.isnan(roc):
                    weighted_roc_sum += roc * weight
                    total_valid_weight += weight
            except:
                pass # Continue if ROC calculation fails for this period
                
    # Normalize the score by the total valid weight
    return weighted_roc_sum / total_valid_weight if total_valid_weight > 0 else np.nan

def calculate_rs_ratio(stock_df: pd.DataFrame, benchmark_ticker: str, target_date: datetime) -> Optional[float]:
    """
    Calculates the Relative Strength (RS-55) ratio: Stock Return / Benchmark Return.
    Uses the 55-day lookback period.
    Calculates RS-55:
    RS = Stock Close / Benchmark Close
    RS-55 = 55-period moving average of RS (Relative Strength line)
    RS-55-Vivek-Bajaj = (Price_today/Price_55_days_back)/(Benchmark_today/Benchmark_55_days_back) - 1    
    """
    if not CONFIG: load_config()

    if stock_df.empty or 'close' not in stock_df.columns: return np.nan
    benchmark_df = get_data_for_benchmark_backtest(benchmark_ticker)
    
    if benchmark_df is None or benchmark_df.empty or 'close' not in benchmark_df.columns: return np.nan
    
    rs_lookback = CONFIG["MOMENTUM_CONFIG"]["RS_LOOKBACK_DAYS"]
    
    # Check if we have enough data (plus one day for the initial price)
    if len(stock_df) <= rs_lookback or len(benchmark_df) <= rs_lookback: return np.nan
    
    try:
        # Get the lookback period slice ending on the target date
        stock_period = stock_df.loc[:target_date].tail(rs_lookback + 1)
        benchmark_period = benchmark_df.loc[:target_date].tail(rs_lookback + 1)
        
        if len(stock_period) < rs_lookback + 1 or len(benchmark_period) < rs_lookback + 1:
            return np.nan
        
        # --- Stock Return ---
        stock_close_prices = stock_period['close']
        # stock_return = (stock_close_prices.iloc[-1] / stock_close_prices.iloc[0]) - 1.0
        
        stock_return = (stock_close_prices.iloc[-1] / stock_close_prices.iloc[0])
        
        # --- Benchmark Return ---
        bench_close_prices = benchmark_period['close']
        # benchmark_return = (bench_close_prices.iloc[-1] / bench_close_prices.iloc[0]) - 1.0
        benchmark_return = (bench_close_prices.iloc[-1] / bench_close_prices.iloc[0])
        
        if benchmark_return == 0.0: 
            return np.nan # Avoid division by zero, treat zero benchmark return as no reference
            
        # rs_ratio = (stock_return / benchmark_return)
        rs_ratio = (stock_return / benchmark_return) - 1.0
        
        # # --- Stock Return --- OLD IMPLEMENTATION
        # stock_close_prices = stock_period['close']
        # stock_return = (stock_close_prices.iloc[-1] / stock_close_prices.iloc[0]) - 1.0
        
        # # --- Benchmark Return ---
        # bench_close_prices = benchmark_period['close']
        # benchmark_return = (bench_close_prices.iloc[-1] / bench_close_prices.iloc[0]) - 1.0
        # if benchmark_return == 0.0: 
        #     return np.nan # Avoid division by zero, treat zero benchmark return as no reference
            
        # # rs_ratio = (stock_return / benchmark_return)
        # rs_ratio = (stock_return / benchmark_return)
        
        return rs_ratio
    except Exception:
        return np.nan

# ============================================================
# FILTERING LOGIC (STAGES 2 & 3)
# ============================================================

def check_consistency(df: pd.DataFrame, target_date: datetime, ma200_check: bool = True, rsi_check: bool = True) -> Dict[str, Any]:
    """
    Checks historical filter consistency over a lookback period based on MA200 and RSI.
    """
    if not CONFIG: load_config()
    c_config = CONFIG["FILTER_CONFIG"]["CONSISTENCY_CHECK"]
    check_days = c_config["CHECK_DAYS"]
    recent_window = c_config["RECENT_WINDOW"]
    
    consistency_ok = False
    fail_reason = "N/A"
    
    if not c_config["ENABLE"]:
        return {"ConsistencyOK": True, "Details": "Disabled"}

    # Slice data up to the target date
    df_upto_date = df.loc[:target_date]
    if len(df_upto_date) < check_days + 200: # Need enough data for MA200 and the check window
        return {"ConsistencyOK": False, "Details": f"Insufficient data (needed > {check_days + 200} days, found {len(df_upto_date)})"}

    df_check = df_upto_date.tail(check_days)
    
    if df_check.empty:
        return {"ConsistencyOK": False, "Details": "Check window is empty."}
        
    # 1. Calculate Daily Pass/Fail for MA200 and RSI
    
    # MA200 Check (Price > MA200)
    if ma200_check:
        df_upto_date.loc[:, 'MA200'] = df_upto_date['close'].rolling(window=200).mean()
        # Create a boolean Series: True if Price > MA200
        pass_ma200_daily = (df_upto_date['close'] > df_upto_date['MA200']).loc[df_check.index]
        pass_ma200_daily = pass_ma200_daily.fillna(False)
    else:
        pass_ma200_daily = pd.Series(True, index=df_check.index) # Always pass if disabled
        
    # RSI Check (RSI > 50)
    if rsi_check:
        # Calculate daily RSI for the entire data set, then slice the check period
        gain = (df_upto_date['close'].diff().where(df_upto_date['close'].diff() > 0, 0)).rolling(window=14).mean()
        loss = (-df_upto_date['close'].diff().where(df_upto_date['close'].diff() < 0, 0)).rolling(window=14).mean()
        loss_safe = loss.replace(0, np.finfo(float).eps) 
        rsi = 100 - (100 / (1 + (gain / loss_safe)))
        
        # Create a boolean Series: True if RSI > 50
        pass_rsi_daily = (rsi > 50).loc[df_check.index]
        pass_rsi_daily = pass_rsi_daily.fillna(False)
    else:
        pass_rsi_daily = pd.Series(True, index=df_check.index) # Always pass if disabled
        
    # 2. Combine and Check Conditions
    
    # Total Consistency: Pass if BOTH MA200 and RSI pass on that day
    daily_pass = pass_ma200_daily & pass_rsi_daily
    total_passed = daily_pass.sum()
    
    # Recent Consistency: Check the last 10 days
    recent_pass = daily_pass.tail(recent_window)
    recent_passed_count = recent_pass.sum()
    
    # Check 1: Min Total Days Passed
    check_1_ok = total_passed >= c_config["MIN_TOTAL_DAYS_PASS"]
    
    # Check 2: Min Recent Days Passed
    check_2_ok = recent_passed_count >= c_config["MIN_RECENT_DAYS_PASS"]
    
    consistency_ok = check_1_ok or check_2_ok
    
    # Determine fail reason
    if not consistency_ok:
        if not check_1_ok and not check_2_ok:
            fail_reason = f"Total Days Passed ({total_passed}/{c_config['MIN_TOTAL_DAYS_PASS']}) AND Recent Days Passed ({recent_passed_count}/{c_config['MIN_RECENT_DAYS_PASS']}) failed."
        elif not check_1_ok:
             fail_reason = f"Total Days Passed ({total_passed}/{c_config['MIN_TOTAL_DAYS_PASS']}) failed."
        elif not check_2_ok:
             fail_reason = f"Recent Days Passed ({recent_passed_count}/{c_config['MIN_RECENT_DAYS_PASS']}) failed."
             
    return {
        "ConsistencyOK": consistency_ok, 
        "Details": fail_reason,
        "TotalPassed": int(total_passed),
        "RecentPassed": int(recent_passed_count),
    }


def apply_technical_indicators_filters(df: pd.DataFrame, target_date: datetime) -> Tuple[bool, str, Dict[str, Any], Dict[str, Any]]:
    """
    Applies mandatory technical filters (Price, Volume, Consistency, MA200/MA50 position) 
    and calculates the raw WMS-contributing scores (RSI, MFI, CCI).
    
    Returns: (passed_filters, filter_reason, filter_results, consistency_stats)
    """
    if not CONFIG: load_config()
    filter_results = {}
    df_upto_date = df.loc[:target_date]
    
    if df_upto_date.empty:
        return False, "No data available up to target date.", filter_results, {"ConsistencyOK": False, "Details": "No data"}
        
    latest_row = df_upto_date.iloc[-1]

    # F6: Minimum Price & Volume (Mandatory Base Filters)
    min_price = CONFIG["FILTER_CONFIG"].get("MIN_PRICE", 1.0)
    min_volume_avg = CONFIG["FILTER_CONFIG"].get("MIN_VOLUME_AVG", 100000)

    # --- Raw Score Calculations (For WMS) ---    
    # R1: RSI (Raw Score for WMS)
    rsi_raw = calculate_rsi(df_upto_date, period=14)
    filter_results['RSI_Raw'] = rsi_raw
    
    # R2: CCI (Raw Score for WMS)
    cci_raw = calculate_cci(df_upto_date, period=20)
    filter_results['CCI_Raw'] = cci_raw
    
    # R3: MFI (Raw Score for WMS)
    mfi_raw = calculate_mfi(df_upto_date, period=14)
    filter_results['MFI_Raw'] = mfi_raw

    # Price Check
    price_ok = False
    try:
        current_price = latest_row['close'].item()
        price_ok = bool(current_price >= min_price)
    except:
        current_price = np.nan
        price_ok = False
        
    filter_results['F6_MinPrice_OK'] = price_ok

    # Volume Check (20-day average)
    volume_ok = False
    volume_avg = np.nan
    try:
        volume_avg = df_upto_date['volume'].tail(20).mean()
        volume_ok = bool(volume_avg >= min_volume_avg)
    except:
        volume_ok = False
        
    filter_results['F6_MinVolume_OK'] = volume_ok

    if not price_ok:
        return False, f"Failed Min Price Filter (Price: {current_price:.2f} < {min_price:.2f})", filter_results, {"ConsistencyOK": False, "Details": "Min Price Fail"}
    if not volume_ok:
        return False, f"Failed Min Volume Filter (Avg Volume: {volume_avg:,.0f} < {min_volume_avg:,.0f})", filter_results, {"ConsistencyOK": False, "Details": "Min Volume Fail"}

    # Final check: Must have at least one WMS factor calculated (ROC, RSI, MFI, CCI)
    if np.isnan(filter_results.get('WMS_ROC_Raw', np.nan)) and \
       np.isnan(rsi_raw) and np.isnan(cci_raw) and np.isnan(mfi_raw):
        return False, "Failed: No WMS core factors (ROC/RSI/MFI/CCI) could be calculated.", filter_results, {"ConsistencyOK": False, "Details": "No WMS core factors (ROC/RSI/MFI/CCI) could be calculated"}

    # F1/F2/F3: Bullish EMA Alignment (EMA21 > EMA50 > EMA200)
    try:
        # ema_21 = df_upto_date['close'].ewm(span=21, adjust=False).mean().iloc[-1]
        # ema_50 = df_upto_date['close'].ewm(span=50, adjust=False).mean().iloc[-1]
        # ema_200 = df_upto_date['close'].ewm(span=200, adjust=False).mean().iloc[-1]
        sma_200 = df_upto_date['close'].rolling(window=200).mean().iloc[-1].item()
        sma_50 = df_upto_date['close'].rolling(window=50).mean().iloc[-1].item()

        if np.isnan(sma_50) or np.isnan(sma_200):
            return False, "SMA values not available", filter_results, {"ConsistencyOK": False, "Details": "One or more EMA values are NaN"}

        if not (current_price > sma_50 > sma_200):
            return False, (f"Failed EMA Alignment (current_price: {current_price:.2f}, sma_50: {sma_50:.2f}, sma_200: {sma_200:.2f})"), filter_results, {"ConsistencyOK": False,"Details": "current_price <= EMA50 or EMA50 <= EMA200"}

    except Exception as e:
        return False, "EMA calculation error", filter_results, {"ConsistencyOK": False,"Details": str(e)}
        
    # F5: Consistency Check (Mandatory Filter)
    consistency_stats = check_consistency(df, target_date)
    if not consistency_stats["ConsistencyOK"]:
         return False, f"Failed Consistency Check: {consistency_stats['Details']}", filter_results, consistency_stats     
     
    # All mandatory filters passed
    return True, "Passed all mandatory filters.", filter_results, consistency_stats


def rank_and_apply_relative_filters(raw_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Ranks the raw scores (WMS components, P-Mom, Value, RS-55), imputes missing WMS components, 
    calculates the Final Weighted Score (WMS), and applies the Relative P/V Filter (Stage 2 - Primary Filter).
    """
    if not CONFIG: load_config()

    # 1. Convert to DataFrame and identify raw score columns
    scores_df = pd.DataFrame(raw_results).set_index('Symbol')
    
    # Raw scores that contribute to the Final Weighted Score (WMS)
    wms_raw_cols = ['WMS_ROC_Raw', 'RSI_Raw', 'MFI_Raw', 'CCI_Raw'] 
    
    # Other raw scores used for filtering
    filter_raw_cols = ['P_Mom_Raw', 'Value_Raw']
    
    # Combine all columns that need to be ranked (WMS components + P/V)
    all_raw_cols = wms_raw_cols + filter_raw_cols + ['RS_Raw']

    # Calculate Percentile Ranks (0-100)
    for col in all_raw_cols:
        # rank(pct=True) is robust to NaNs: non-NaNs get a rank among other non-NaNs
        scores_df[f'{col}_Pct'] = scores_df[col].rank(pct=True, ascending=True) * 100
        
    # 
    merged_df = scores_df.copy()

    # 2. Imputation Loop for WMS Components (v10.7 logic)
    # Only iterate over stocks that passed the initial filters (PassedFilters=True)
    for index, row in merged_df[merged_df['PassedFilters'] == True].iterrows():
        
        # Select the calculated percentile ranks for non-missing WMS factors
        valid_wms_factors_pct = [f'{col}_Pct' for col in wms_raw_cols if not pd.isna(row[col])]
        valid_percentiles = row[valid_wms_factors_pct]

        # Calculate the average percentile of the WMS factors that *did* calculate
        imputed_value = valid_percentiles.mean() if not valid_percentiles.empty else 0.0

        # Apply imputation to missing WMS percentile ranks
        for raw_col in wms_raw_cols:
            pct_col = f'{raw_col}_Pct'
            # If the percentile is missing (NaN), replace it with the imputed average
            if pd.isna(row[pct_col]):
                merged_df.loc[index, pct_col] = imputed_value
    
    # 3. Calculate Final Weighted Score (WMS)
    scoring_weights = CONFIG["SCORING_WEIGHTS"]
    total_score_series = pd.Series(0.0, index=merged_df.index)
    
    # Map raw columns to their specific weights in the final WMS composite
    weight_map = {
        'WMS_ROC_Raw': scoring_weights["WMS_ROC_Composite"],
        'RSI_Raw': scoring_weights["RSI_Score"],
        'MFI_Raw': scoring_weights["MFI_Score"],
        'CCI_Raw': scoring_weights["CCI_Score"]
    }
    
    for raw_col, weight in weight_map.items():
        pct_col = f'{raw_col}_Pct'
        # Multiply the percentile rank (imputed or not) by its weight
        total_score_series += merged_df[pct_col] * weight
        
    merged_df['FinalWeightedScore'] = total_score_series.round(2)

    # 4. Apply Relative P/V Screen (Stage 2 - Primary Filter)
    final_results = []
    min_p_pct = CONFIG["FILTER_CONFIG"]["MIN_P_SCORE_PCT"]
    min_v_pct = CONFIG["FILTER_CONFIG"]["MIN_V_SCORE_PCT"]

    for symbol, s_row in merged_df.iterrows():
        r = s_row.to_dict()
        r['Symbol'] = symbol
        
        # If it failed any initial/technical filters, it's already excluded
        if not r['PassedFilters']:
            # r['FinalWeightedScore'] = 0.0 # Assign 0 score to ensure it sinks in the final sort
            final_results.append(r)
            continue
            
        p_score_pct = r.get('P_Mom_Raw_Pct', np.nan)
        v_score_pct = r.get('Value_Raw_Pct', np.nan)
        
        is_p_ranked = not np.isnan(p_score_pct)
        is_v_ranked = not np.isnan(v_score_pct)
        
        # Check the primary relative filter
        p_fail = is_p_ranked and (p_score_pct < min_p_pct)
        v_fail = is_v_ranked and (v_score_pct < min_v_pct)
        
        pv_screen_fail = p_fail or v_fail
        
        if pv_screen_fail:
            r['PassedFilters'] = False
            r['FilterReason'] = "Failed Relative P/V Screen (Stage 2 Primary Filter)"
            
            p_status = f"P-Pct {p_score_pct:.1f}" if is_p_ranked else "P-Score Missing"
            v_status = f"V-Pct {v_score_pct:.1f}" if is_v_ranked else "V-Score Missing"
            r['FilterReason'] += f" | Status: (P-Min: {min_p_pct}%, V-Min: {min_v_pct}%) | Stock: ({p_status}, {v_status})"
            #r['FinalWeightedScore'] = 0.0
            
        # Add Code to RS-Filtering also if rs_55 < 0
        rs_55_score = r.get('RS_Raw', np.nan)
        is_rs_55_scored = not np.isnan(rs_55_score)
        rs_55_fail = is_rs_55_scored and (rs_55_score < 0)
        if rs_55_fail:
            r['PassedFilters'] = False
            r['FilterReason'] = "Failed RS_55 [Nifty50] > 0 Screen (Stage 2 Primary Filter)"
            
            rs_55_status = f"RS-55 Score {rs_55_score:.1f}" if is_rs_55_scored else "RS-55 Missing"
            r['FilterReason'] += f" | Status: (RS-55-Min: 0) | Stock: ({rs_55_status})"
            #r['FinalWeightedScore'] = 0.0
            
        # Add Code to RS-Filtering also if rs_55 < 0
        rsi_score = r.get('RSI_Raw', np.nan)
        is_rsi_scored = not np.isnan(rsi_score)
        rsi_fail = is_rsi_scored and (rsi_score < 50)
        if rsi_fail:
            r['PassedFilters'] = False
            r['FilterReason'] = "Failed RSI > 50 Screen (Stage 2 Primary Filter)"
            
            rsi_status = f"RSI Score {rsi_score:.1f}" if is_rsi_scored else "RSI Missing"
            r['FilterReason'] += f" | Status: (RSI > 50) | Stock: ({rsi_status})"
            #r['FinalWeightedScore'] = 0.0        
            
        final_results.append(r)

    return final_results


def get_momentum_scores_for_stocks(symbols: List[str], target_date: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """
    Calculates the detailed multi-factor raw scores and filter status for a list of symbols.
    """
    if not CONFIG: load_config()
    if target_date is None:
        target_date = datetime.now()
        
    benchmark_ticker = CONFIG["DATA_CONFIG"]["INDEX_BENCHMARK"]
    print(f"\nCalculating momentum scores and applying filters for {len(symbols)} stocks against benchmark {benchmark_ticker} \n")
    raw_results = []
    total_symbols = len(symbols)

    # 1. Calculate Raw Scores and Apply Technical Filters (Stage 2 - Mandatory/Secondary)
    for i, symbol in enumerate(symbols):
        sys.stdout.write(f"  -> Calculating scores and filters for {symbol} ({i + 1}/{total_symbols})... \r")
        sys.stdout.flush()
        
        df = get_data_for_symbol_backtest(symbol)
        
        if df is None or df.empty:
            raw_results.append({
                'Symbol': symbol,
                'PassedFilters': False,
                'FilterReason': "Insufficient/Missing Stock Price Data",
                'ConsistencyOK': False,
                'Details': "No Data"
            })
            continue

        # 1.1 Apply Technical/Consistency Filters
        passed_filters, filter_reason, tech_details, consistency_stats = apply_technical_indicators_filters(df, target_date)
        
        # 1.2 Calculate Raw Scores (for P/V and WMS ROC)
        df_upto_date = df.loc[:target_date]
        
        rs_55_ratio = calculate_rs_ratio(df, benchmark_ticker, target_date)
        wms_roc_raw = calculate_weighted_momentum_score(df_upto_date)
        
        # Price and Value Raw Scores (for P/V Relative Filter)
        p_mom_raw = calculate_raw_price_momentum_score(df_upto_date)
        
        # --- Value Raw Score (Uses real data with persistent cache) ---
        v_fundamentals = get_fundamental_data(symbol) 
        value_raw = calculate_raw_value_score(v_fundamentals)
        # -------------------------------------------------------------

        # 1.3 Compile Raw Result
        result = {
            'Symbol': symbol,
            'PassedFilters': passed_filters,
            'FilterReason': filter_reason,
            'RS_Raw': rs_55_ratio,
            'WMS_ROC_Raw': wms_roc_raw,
            'P_Mom_Raw': p_mom_raw,
            'Value_Raw': value_raw,
            'ConsistencyOK': consistency_stats.get('ConsistencyOK'),
            'Details': consistency_stats.get('Details'),
            'TotalPassed': consistency_stats.get('TotalPassed'),
            'RecentPassed': consistency_stats.get('RecentPassed'),
            'RSI_Raw': tech_details.get('RSI_Raw'),
            'MFI_Raw': tech_details.get('MFI_Raw'),
            'CCI_Raw': tech_details.get('CCI_Raw'),
        }
        raw_results.append(result)

    sys.stdout.write("                                                                                                      \r")
    sys.stdout.flush()
    
    # 2. Rank Scores, Impute missing WMS factors, Apply P/V Filter, and Calculate Final WMS
    if not raw_results:
        return []
        
    final_ranked_results = rank_and_apply_relative_filters(raw_results)

    return final_ranked_results


# ============================================================
# INTERACTIVE & BACKTEST HISTORY & EXPORT
# ============================================================

def export_dataframe_to_file(df: pd.DataFrame, base_output_dir: str, base_filename: str):
    """Saves a DataFrame to CSV and Excel with a timestamped filename."""
    # Ensure the output directory exists
    OUTPUT_DIR = Path('.') / base_output_dir
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Clean the filename (e.g., replace spaces/slashes)
    safe_filename = base_filename.replace(' ', '_').replace('/', '-').replace('\\', '-')
    
    # csv_path = OUTPUT_DIR / f"{safe_filename}_{timestamp}.csv"
    excel_path = OUTPUT_DIR / f"{safe_filename}_{timestamp}.xlsx"

    print(f"\nAttempting to export data to output/{safe_filename}_{timestamp}.*")

    '''
    # Save to CSV
    try:
        df.to_csv(csv_path)
        print(f"✅ Data successfully exported to CSV: {csv_path}")
    except Exception as e:
        print(f"[EXPORT ERROR] Failed to save to CSV: {e}")
    '''
    # Save to Excel
    try:
        df.to_excel(excel_path)
        print(f"✅ Data successfully exported to Excel: {excel_path}")
    except Exception as e:
        print(f"[EXPORT ERROR] Failed to save to Excel: {e}")


def get_first_trading_day(benchmark_ticker: str, target_date: datetime) -> Optional[Tuple[datetime, datetime]]:
    """ Finds the first actual trading day on or after the target_date. """
    benchmark_df = get_data_for_benchmark_backtest(benchmark_ticker)
    if benchmark_df is None or benchmark_df.empty: 
        return None
    
    # Ensure target_date is a timestamp for consistent comparison
    ts_target = pd.Timestamp(target_date)
    
    # Find dates >= target_date
    valid_dates = benchmark_df.index[benchmark_df.index >= ts_target].sort_values()
    
    if not valid_dates.empty:
        return (target_date, valid_dates[0].to_pydatetime())
    
    # Fallback: Check if the very last date in the index matches the date part of target_date
    last_date = benchmark_df.index.max()
    if last_date.date() >= target_date.date():
        return (target_date, last_date.to_pydatetime())
        
    return None

def get_last_trading_day(benchmark_ticker: str, target_date: datetime) -> Optional[Tuple[datetime, datetime]]:
    """
    Finds the last actual trading day on or before target_date.
    Returns (input_target_date, effective_last_trading_datetime).
    """
    benchmark_df = get_data_for_benchmark_backtest(benchmark_ticker)
    if benchmark_df is None:
        return None

    # Ensure index is datetime
    index_dates = benchmark_df.index.sort_values()

    # Filter dates <= target_date
    valid_dates = index_dates[index_dates <= target_date]

    if valid_dates.empty:
        # No date <= target_date → return earliest available if desired
        if index_dates.min() <= target_date:
            return (target_date, index_dates.min().to_pydatetime())
        return None

    # Last trading day before or on target_date
    last_day = valid_dates[-1].to_pydatetime()

    return (target_date, last_day)

# ============================================================
# DATE AND TIME UTILITIES
# ============================================================

def get_calendar_rebalance_start_dates(start_date: datetime, end_date: datetime, frequency: str) -> List[datetime]:
    """
    Generates a list of calendar rebalance dates (start of period) based on the frequency.
    Ensures the start_date is included.
    """
    start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = end_date.replace(hour=0, minute=0, second=0, microsecond=0)
    
    freq_map = {
        'W': 'W',  # Weekly
        'M': 'MS', # Monthly Start
        'Q': 'QS', # Quarterly Start
        'A': 'AS'  # Annual Start
    }
    
    pd_frequency = freq_map.get(frequency.upper(), 'MS')
    
    # Generate the date range using pandas
    date_range = pd.date_range(start=start_date, end=end_date, freq=pd_frequency).to_list()
    
    rebalance_start_dates = date_range.copy()
    
    # CRITICAL FIX (Line 1548): Replaced .normalize() which is not always available on datetime objects
    # Compare only the date component of the start_date against the date range
    if start_date.date() not in [d.date() for d in date_range]:
        # If the start date is not already in the generated date range, add it.
        rebalance_start_dates.insert(0, start_date) # start_date is already normalized to midnight above

    # Filter dates to ensure they fall within the start_date and end_date range (inclusive)
    # The date_range generation is usually sufficient, but this adds safety.
    rebalance_start_dates = [d for d in rebalance_start_dates if d.date() >= start_date.date() and d.date() <= end_date.date()]
    
    # Ensure all are standard Python datetime objects and sort them
    return sorted(list(set(rebalance_start_dates)))

def get_benchmark_returns(category, effective_start_date, effective_end_date):
    """ Get benchmark returns for effective start aand end date. """
    benchmark_ticker=CONFIG["DATA_CONFIG"]["INDICES"][category]
    benchmark_df = GLOBAL_BENCHMARK_DATA.get(benchmark_ticker)
    if benchmark_df is None:
        print(f"Error: Benchmark data for {benchmark_ticker} is not available. Using INDEX_BENCHMARK {CONFIG["DATA_CONFIG"]["INDEX_BENCHMARK"]}.")
        benchmark_ticker=CONFIG["DATA_CONFIG"]["INDEX_BENCHMARK"]
        benchmark_df = GLOBAL_BENCHMARK_DATA.get(benchmark_ticker)
        if benchmark_df is None:
            print(f"Error: Benchmark data for {benchmark_ticker} is not available. can not backtest.")
            return
    
    ser = benchmark_df.loc[effective_start_date:effective_end_date, "close"]
    df_benchmarks = ser.to_frame(name="close").reset_index()
    df_benchmarks.rename(columns={"index": "date"}, inplace=True)  # if index is unnamed
    return df_benchmarks

def get_all_stock_data_for_date(tickers: List[str], target_date: datetime) -> pd.DataFrame:
    """ Retrieves the close price for all specified tickers on or nearest to the target_date (no lookahead). """
    
    data_points = []
    
    # Iterate over all holdings/candidates to get their price data
    for ticker in tickers:
        df = get_data_for_symbol_backtest(ticker)
        if df is None or df.empty:
            continue
            
        # Select the latest data point up to and including the target date
        try:
            # .iloc[-1] will be the most recent date <= target_date
            row = df.loc[:target_date].iloc[-1]
            data_points.append({'Ticker': ticker, 'Date': row.name, 'close': row['close'], 'open': row.get('open', np.nan), 'volume': row.get('volume', np.nan)})
        except IndexError:
            # No data found up to that date
            continue
            
    df_data = pd.DataFrame(data_points).set_index('Ticker')
    return df_data

def normalize_columns(df):
    # lowercase all names and strip spaces
    # small normalization step that lowercases and standardizes column names
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    return df

def export_backtest_data_default_excel(category, df_rebalance, df_equity, df_transactions, df_benchmarks, base_file_name_excel):
    """
    Exports backtest results (rebalance, equity, transactions, benchmark)
    and saves a comparison chart of normalized equity vs normalized benchmark.
    """

    # 0) Normalize column names for consistency
    df_equity = normalize_columns(df_equity)
    df_benchmarks = normalize_columns(df_benchmarks)
    df_rebalance = normalize_columns(df_rebalance)
    df_transactions = normalize_columns(df_transactions)

    # De-dup and sort by date
    if "date" in df_equity.columns:
        df_equity["date"] = pd.to_datetime(df_equity["date"])
        df_equity = df_equity.sort_values("date")
        df_equity = df_equity.drop_duplicates(subset=["date"], keep="first")

    if "date" in df_benchmarks.columns:
        df_benchmarks["date"] = pd.to_datetime(df_benchmarks["date"])
        df_benchmarks = df_benchmarks.sort_values("date")
        df_benchmarks = df_benchmarks.drop_duplicates(subset=["date"], keep="first")

    # 1) Folder name: Backtest_Results/{category}_{timestamp}
    base_folder = "Backtest_Results"
    run_folder = os.path.join(base_folder, f"compare")
    #run_folder = base_folder
    os.makedirs(run_folder, exist_ok=True)

    # 2) File name: <timestamp>.xlsx or <timestamp>.csv (user chooses extension)    
    user_name = f"{base_file_name_excel}.xlsx"
    file_path = os.path.join(run_folder, user_name)

    try:
        # 3) Export to Excel with 4 sheets
        if file_path.lower().endswith((".xlsx", ".xls")):
            with pd.ExcelWriter(file_path, engine="xlsxwriter") as writer:
                df_rebalance.to_excel(writer, sheet_name="Rebalance_Summary", index=False)
                df_equity.to_excel(writer, sheet_name="Equity_Curve", index=False)
                df_transactions.to_excel(writer, sheet_name="Transaction_Log", index=False)
                df_benchmarks.to_excel(writer, sheet_name="Benchmark", index=False)
            print(f"✅ Exported backtest results to Excel: {file_path} (4 sheets).")

        # 3) Or export to CSVs
        elif file_path.lower().endswith(".csv"):
            base_no_ext = file_path[:-4]
            df_rebalance.to_csv(f"{base_no_ext}_Summary.csv", index=False)
            df_equity.to_csv(f"{base_no_ext}_Equity.csv", index=False)
            df_transactions.to_csv(f"{base_no_ext}_Transactions.csv", index=False)
            df_benchmarks.to_csv(f"{base_no_ext}_Benchmark.csv", index=False)
            print("✅ Exported backtest results to CSV files "
                  "(Summary, Equity, Transactions, Benchmark).")

        else:
            print("❌ Export cancelled. Use a file name ending in .xlsx, .xls, or .csv.")
            return

        # 4) Create comparison chart: normalized equity vs normalized benchmark
        fig, ax = plt.subplots(figsize=(10, 6))

        # Equity: expects columns 'date' and 'equity'
        equity_series = df_equity.set_index("date")["equity"]

        # Benchmark: expects columns 'date' and 'close'
        bench_series = df_benchmarks.set_index("date")["close"]

        # Align on common dates
        equity_series, bench_series = equity_series.align(bench_series, join="inner")

        if len(equity_series) == 0 or len(bench_series) == 0:
            print("⚠️ Not enough overlapping dates to plot equity vs benchmark.")
        else:
            # Normalize both curves to same starting equity
            start_equity = float(equity_series.iloc[0])
            equity_norm = equity_series / equity_series.iloc[0] * start_equity
            bench_norm = bench_series / bench_series.iloc[0] * start_equity

            ax.plot(
                equity_norm.index,
                equity_norm.values,
                label="Strategy Equity",
                color="tab:blue",
                linewidth=1.8,
            )
            ax.plot(
                bench_norm.index,
                bench_norm.values,
                label="Benchmark (scaled)",
                color="tab:orange",
                linewidth=1.8,
            )

            ax.set_title(f"Strategy vs Benchmark (normalized) - {category}")
            ax.set_xlabel("Date")
            ax.set_ylabel(f"Portfolio value (start = {start_equity:,.0f})")
            ax.grid(True, alpha=0.3)
            ax.legend()

            chart_path = os.path.join(run_folder, f"{base_file_name_excel}_equity_vs_benchmark.png")
            plt.tight_layout()
            plt.savefig(chart_path, dpi=150)
            plt.close(fig)

            print(f"📈 Saved comparison chart: {chart_path}")

    except Exception as e:
        print(f"❌ ERROR during export: {e}")

def plot_multi_category_equity_curves(all_equity_curves: dict):
    """
    Plot normalized equity curves for all (category, FY) labels
    on a single figure for visual comparison.
    """
    if not all_equity_curves:
        print("No equity curves to plot.")
        return

    plt.figure(figsize=(12, 7))

    for label, ser in all_equity_curves.items():
        ser = ser.dropna()
        if ser.empty:
            continue
        base = float(ser.iloc[0])
        norm = ser / base  # start at 1.0
        plt.plot(norm.index, norm.values, label=label, linewidth=1.5)

    plt.title("Normalized Equity Curves by Category / FY")
    plt.xlabel("Date")
    plt.ylabel("Normalized Equity (start = 1.0)")
    plt.grid(True, alpha=0.3)
    plt.legend(fontsize=8)
    plt.tight_layout()

    base_folder = "Backtest_Results"
    os.makedirs(base_folder, exist_ok=True)
    chart_path = os.path.join(base_folder, "multi_category_equity_comparison.png")
    plt.savefig(chart_path, dpi=150)
    plt.close()

    print(f"📈 Saved multi-category comparison chart: {chart_path}")


def plot_multi_category_equity_by_fy(curves_by_fy: dict, base_folder: str):
    """
    For each FY (year key), create one PNG in base_folder:
      - all category strategy curves, normalized to each strategy's start equity
      - each category's benchmark curve, normalized to the *same* start equity
        as that category's strategy (so values are directly comparable).
    """
    if not curves_by_fy:
        print("No curves to plot.")
        return

    os.makedirs(base_folder, exist_ok=True)

    for fy_year, data in sorted(curves_by_fy.items()):
        strat_curves = data.get("strategy", {})
        bench_curves = data.get("benchmark", {})

        if not strat_curves:
            continue

        plt.figure(figsize=(12, 7))

        for category, eq_ser in strat_curves.items():
            eq_ser = eq_ser.dropna()
            if eq_ser.empty:
                continue

            # Strategy start equity
            start_equity = float(eq_ser.iloc[0])
            equity_norm = eq_ser / eq_ser.iloc[0] * start_equity

            plt.plot(
                equity_norm.index,
                equity_norm.values,
                label=f"{category} (strategy)",
                linewidth=1.8,
            )

            # If a benchmark exists for this category, normalize it to same start_equity
            b_ser = bench_curves.get(category)
            if b_ser is not None:
                b_ser = b_ser.dropna()
                if not b_ser.empty:
                    # Align dates before normalizing
                    eq_aligned, b_aligned = equity_norm.align(b_ser, join="inner")
                    if len(eq_aligned) > 0 and len(b_aligned) > 0:
                        bench_norm = b_aligned / b_aligned.iloc[0] * start_equity
                        plt.plot(
                            bench_norm.index,
                            bench_norm.values,
                            linestyle="--",
                            linewidth=1.5,
                            label=f"{category.lower()} benchmark",
                        )

        plt.title(f"Strategy vs Benchmark (normalized to strategy start) - FY ending {fy_year}-03-31")
        plt.xlabel("Date")
        plt.ylabel("Portfolio value (start = strategy start equity)")
        plt.grid(True, alpha=0.3)
        plt.legend(fontsize=8)
        plt.tight_layout()

        chart_path = os.path.join(base_folder, f"equity_vs_benchmark_FY{fy_year}.png")
        plt.savefig(chart_path, dpi=150)
        plt.close()

        print(f"📈 Saved FY plot with categories + benchmarks: {chart_path}")


def export_backtest_data(category, df_rebalance, df_equity, df_transactions, df_benchmarks):
    """
    Exports backtest results (rebalance, equity, transactions, benchmark)
    and saves a comparison chart of normalized equity vs normalized benchmark.
    """

    # 0) Normalize column names for consistency
    df_equity = normalize_columns(df_equity)
    df_benchmarks = normalize_columns(df_benchmarks)
    df_rebalance = normalize_columns(df_rebalance)
    df_transactions = normalize_columns(df_transactions)

    # De-dup and sort by date
    if "date" in df_equity.columns:
        df_equity["date"] = pd.to_datetime(df_equity["date"])
        df_equity = df_equity.sort_values("date")
        df_equity = df_equity.drop_duplicates(subset=["date"], keep="first")

    if "date" in df_benchmarks.columns:
        df_benchmarks["date"] = pd.to_datetime(df_benchmarks["date"])
        df_benchmarks = df_benchmarks.sort_values("date")
        df_benchmarks = df_benchmarks.drop_duplicates(subset=["date"], keep="first")

    # 1) Folder name: Backtest_Results/{category}_{timestamp}
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_folder = "Backtest_Results"
    run_folder = os.path.join(base_folder, f"{category}_{timestamp}")
    os.makedirs(run_folder, exist_ok=True)

    # 2) File name: <timestamp>.xlsx or <timestamp>.csv (user chooses extension)
    default_filename = f"{timestamp}.xlsx"
    print("\n" + "=" * 70)
    print("BACKTEST EXPORT")
    print("=" * 70)

    user_name = input(
        f"Enter file name for export (e.g., results.xlsx or results.csv, "
        f"default: {default_filename}): "
    ).strip()

    if not user_name:
        user_name = default_filename

    file_path = os.path.join(run_folder, user_name)

    try:
        # 3) Export to Excel with 4 sheets
        if file_path.lower().endswith((".xlsx", ".xls")):
            with pd.ExcelWriter(file_path, engine="xlsxwriter") as writer:
                df_rebalance.to_excel(writer, sheet_name="Rebalance_Summary", index=False)
                df_equity.to_excel(writer, sheet_name="Equity_Curve", index=False)
                df_transactions.to_excel(writer, sheet_name="Transaction_Log", index=False)
                df_benchmarks.to_excel(writer, sheet_name="Benchmark", index=False)
            print(f"✅ Exported backtest results to Excel: {file_path} (4 sheets).")

        # 3) Or export to CSVs
        elif file_path.lower().endswith(".csv"):
            base_no_ext = file_path[:-4]
            df_rebalance.to_csv(f"{base_no_ext}_Summary.csv", index=False)
            df_equity.to_csv(f"{base_no_ext}_Equity.csv", index=False)
            df_transactions.to_csv(f"{base_no_ext}_Transactions.csv", index=False)
            df_benchmarks.to_csv(f"{base_no_ext}_Benchmark.csv", index=False)
            print("✅ Exported backtest results to CSV files "
                  "(Summary, Equity, Transactions, Benchmark).")

        else:
            print("❌ Export cancelled. Use a file name ending in .xlsx, .xls, or .csv.")
            return

        # 4) Create comparison chart: normalized equity vs normalized benchmark
        fig, ax = plt.subplots(figsize=(10, 6))

        # Equity: expects columns 'date' and 'equity'
        equity_series = df_equity.set_index("date")["equity"]

        # Benchmark: expects columns 'date' and 'close'
        bench_series = df_benchmarks.set_index("date")["close"]

        # Align on common dates
        equity_series, bench_series = equity_series.align(bench_series, join="inner")

        if len(equity_series) == 0 or len(bench_series) == 0:
            print("⚠️ Not enough overlapping dates to plot equity vs benchmark.")
        else:
            # Normalize both curves to same starting equity
            start_equity = float(equity_series.iloc[0])
            equity_norm = equity_series / equity_series.iloc[0] * start_equity
            bench_norm = bench_series / bench_series.iloc[0] * start_equity

            ax.plot(
                equity_norm.index,
                equity_norm.values,
                label="Strategy Equity",
                color="tab:blue",
                linewidth=1.8,
            )
            ax.plot(
                bench_norm.index,
                bench_norm.values,
                label="Benchmark (scaled)",
                color="tab:orange",
                linewidth=1.8,
            )

            ax.set_title(f"Strategy vs Benchmark (normalized) - {category}")
            ax.set_xlabel("Date")
            ax.set_ylabel(f"Portfolio value (start = {start_equity:,.0f})")
            ax.grid(True, alpha=0.3)
            ax.legend()

            chart_path = os.path.join(run_folder, f"{timestamp}_equity_vs_benchmark.png")
            plt.tight_layout()
            plt.savefig(chart_path, dpi=150)
            plt.close(fig)

            print(f"📈 Saved comparison chart: {chart_path}")

    except Exception as e:
        print(f"❌ ERROR during export: {e}")


# ============================================================
# INTERACTIVE FUNCTIONS
# ============================================================
# ============================================================
# BACKTESTING LOGIC (CORE FUNCTION)
# ============================================================
def run_full_backtest(category: str, start_date: datetime, end_date: datetime, top_n: int, rebalance_freq: str, transaction_cost: float):
    """
    Runs a backtest simulation over the specified period, using a smart rebalance logic.
    """
    if not CONFIG: load_config()
    b_config = CONFIG.get("BACKTEST_CONFIG", {})

    print("\n" + "="*70)
    print(f"STARTING BACKTEST for {category} ({start_date.date()} to {end_date.date()})")
    print("="*70)

    # 1. Initialization and Data Prep
    symbols = load_symbols(category)
    if not symbols:
        print(f"Error: Could not load symbols for category '{category}'. Aborting.")
        return

    all_symbols = symbols.copy()
    
    # Ensure all required data (stocks and benchmark) is precached/updated
    update_global_data(all_symbols)
    
    benchmark_ticker=CONFIG["DATA_CONFIG"]["INDICES"][category]
    benchmark_df = GLOBAL_BENCHMARK_DATA.get(benchmark_ticker)
    if benchmark_df is None:
        print(f"Error: Benchmark data for {benchmark_ticker} is not available. Using INDEX_BENCHMARK {CONFIG["DATA_CONFIG"]["INDEX_BENCHMARK"]}.")
        benchmark_ticker=CONFIG["DATA_CONFIG"]["INDEX_BENCHMARK"]
        benchmark_df = GLOBAL_BENCHMARK_DATA.get(benchmark_ticker)
        if benchmark_df is None:
            print(f"Error: Benchmark data for {benchmark_ticker} is not available. can not backtest.")
            return

    # 2. Get Rebalance Dates
    rebalance_dates = get_calendar_rebalance_start_dates(start_date, end_date, rebalance_freq)
    if len(rebalance_dates) < 2:
        print(f"Error: Found only {len(rebalance_dates)} rebalance points. Need at least 2. Aborting.")
        return

    # Adjust start date to the first valid trading day on or after the first calendar date
    trading_day_details = get_first_trading_day(benchmark_ticker, rebalance_dates[0])
    if trading_day_details is None:
        print(f"[ERROR] Could not find a valid trading day for backtest start: {rebalance_dates[0].date()}. Aborting.")
        return

    # The actual start date of the backtest
    effective_start_date = trading_day_details[1]
    print(f"Effective Start date for backtesting {effective_start_date}") 

    # Re-align rebalance dates to trading days starting from the effective_start_date
    new_rebalance_dates = []
    # Ensure the first rebalance point is the effective start date
    new_rebalance_dates.append(effective_start_date) 
    for cal_date in rebalance_dates[1:]:
        trade_date_details = get_first_trading_day(benchmark_ticker, cal_date)
        if trade_date_details:
            new_rebalance_dates.append(trade_date_details[1])
    rebalance_dates = sorted(list(set(new_rebalance_dates)))
    

    # Adjust start date to the first valid trading day on or after the first calendar date
    trading_day_details = get_last_trading_day(benchmark_ticker, end_date)
    if trading_day_details is None:
        print(f"[ERROR] Could not find a valid End trading day")
    
    # The actual End date of the backtest
    effective_end_date = trading_day_details[1]       

    print(f"Backtest period: {effective_start_date.date()} to {effective_end_date.date()}")
    print(f"Rebalance frequency: {rebalance_freq}")
    print(f"Trading on {len(rebalance_dates) - 1} rebalance periods.")


    # 3. Core Backtest Loop Variables
    initial_capital = 1000000.0 # $1M starting capital
    total_capital = initial_capital
    
    # MODIFICATION (Point 3): Updated current_holdings structure to store WMS
    # {ticker: {'shares': int, 'wms': float}} 
    current_holdings: Dict[str, Dict[str, Union[int, float]]] = {} 
    
    equity_curve_data = [] # For daily tracking
    transaction_log = []   # For detailed transaction history
    rebalance_results = [] # For periodic performance summary
    
    # Transaction counters
    total_fees = 0.0
    total_trades = 0
    total_buy_trades = 0

    # Get config parameters for smart rebalancing
    TRANSACTION_COST = transaction_cost    
    STOCK_SCALING_FACTOR = b_config.get("STOCK_SCALING_FACTOR", 2)
    MOMENTUM_DROP_THRESHOLD_PCT = b_config.get("MOMENTUM_DROP_THRESHOLD_PCT", 50.0)
    NEW_STOCK_ADDITION_LIMIT = b_config.get("NEW_STOCK_ADDITION_LIMIT", 10) # Point 5 limit
    ANNUAL_CASH_RETURN_RATE = 0.04 # 4% fixed annual return for cash (Point 7)

    # 4. Backtest Loop
    for i in range(len(rebalance_dates) - 1):
        current_date = rebalance_dates[i]
        next_date = rebalance_dates[i+1]
        
        # Calculate days in the current period for interest calculation (Point 7)
        period_days = (next_date - current_date).days

        print("\n" + "-"*70)
        print(f"PERIOD {i+1}: {current_date.date()} to {next_date.date()}")
        print("-" * 70)

        # Apply interest to cash held from the *previous* period (Point 7)
        if i > 0:
            interest_start_date = rebalance_dates[i-1] # Start of previous period
            interest_days = (current_date - interest_start_date).days
            
            # Apply interest to capital carried over from the start of this period
            total_capital = apply_interest_to_cash(total_capital, interest_days, ANNUAL_CASH_RETURN_RATE)
            debug_print(f"Cash interest applied for {interest_days} days at {ANNUAL_CASH_RETURN_RATE*100}% p.a. New Cash: ${total_capital:,.2f}")


        # A. Prepare Data & Calculate Initial Value
        update_global_data(list(current_holdings.keys()))
        trade_day_data = get_all_stock_data_for_date(all_symbols, current_date)
        
        # Calculate start value
        start_value_period = total_capital
        
        # UPDATED: Accessing shares via holding_info['shares']
        for ticker, holding_info in current_holdings.items():
            shares = holding_info['shares']
            try:
                # Use the price on the rebalance day to calculate current value
                price = trade_day_data.loc[ticker, 'open'] 
                start_value_period += shares * price
            except KeyError:
                debug_print(f"[WARNING] Missing price for {ticker} on {current_date.date()}. Ignoring in starting value calculation.")
                # We do NOT sell the stock here; we assume it's still held.

        print(f"Starting Portfolio Value: ${start_value_period:,.2f} (Cash: ${total_capital:,.2f}) | Holdings: {len(current_holdings)}")
        
        if trade_day_data.empty:
            print("[WARNING] No trading prices available for the rebalance day. Skipping rebalance.")
            # Log zero return for the period
            rebalance_results.append({
                'Start_Date': current_date.date(), 'End_Date': next_date.date(),
                'Start_Value': round(start_value_period, 2), 'End_Value': round(start_value_period, 2),
                'Return': 0.0, 'Benchmark_Return': np.nan, 'Holdings_Count': len(current_holdings),
                'Total_Fees': 0.0, 'Trades': 0
            })
            continue

        # --- B. Find Rebalance Candidates (Scoring on current_date) ---
        print("1. Identifying candidates...")
        
        # Get scores for all available symbols up to the current date
        rebalance_candidates_list = get_momentum_scores_for_stocks(all_symbols, target_date=current_date)
        rebalance_candidates_df = pd.DataFrame(rebalance_candidates_list)
        
        # Filter to only stocks that passed all filters and have WMS > 0
        rebalance_candidates_df = rebalance_candidates_df[
            (rebalance_candidates_df['PassedFilters'] == True) & 
            (rebalance_candidates_df['FinalWeightedScore'] > 0.0)
        ].sort_values(by='FinalWeightedScore', ascending=False).reset_index(drop=True)
        
        # If no stocks passed the filter, skip rebalancing
        if rebalance_candidates_df.empty:
            print("[WARNING] No stocks passed all filters and screens. Maintaining current holdings.")
            continue
        
        print(f"2. Found {len(rebalance_candidates_df)} fully qualified candidates.")

        # --- C. Smart Rebalance Logic (SELL/HOLD Phase) ---
        print("3. Applying Smart Rebalance Logic (Sell/Hold)...")

        # Point 1: Get the expanded pool of 'safe-to-hold' stocks (e.g., Top 20)
        target_pool_size = top_n * STOCK_SCALING_FACTOR
        top_recommended_symbols = set(rebalance_candidates_df['Symbol'].head(target_pool_size))
        
        symbols_to_sell = set()
        symbols_to_hold = set()
        
        # 3.1 SELL/HOLD Phase (Determining which existing holdings to sell/keep)
        current_holdings_to_remove = set()
        
        for symbol, holding_info in current_holdings.items():
            
            latest_score_row = rebalance_candidates_df[rebalance_candidates_df['Symbol'] == symbol]
            
            # If stock is no longer in the qualified candidates universe (e.g., failed filters or delisted)
            if latest_score_row.empty:
                symbols_to_sell.add(symbol)
                debug_print(f"   {symbol} -> FORCED SELL (No longer in qualified universe).")
                continue
            
            latest_wms = latest_score_row['FinalWeightedScore'].iloc[0]
            previous_wms = holding_info.get('wms', 0.0) # Point 3: Get previous WMS
            
            # Point 4: Momentum Drop Sell Rule
            force_sell = False
            if previous_wms > 0 and latest_wms < previous_wms:
                roc = ((previous_wms - latest_wms) / previous_wms) * 100
                
                if roc >= MOMENTUM_DROP_THRESHOLD_PCT:
                    symbols_to_sell.add(symbol)
                    force_sell = True
                    debug_print(f"   {symbol} -> FORCED SELL (WMS dropped from {previous_wms:.2f} to {latest_wms:.2f} | ROC: {roc:.2f}%)")
                    continue
                    
            # Point 2: Hold Check (If not force sold and is in the expanded pool)
            if not force_sell and symbol in top_recommended_symbols:
                symbols_to_hold.add(symbol)
                # No change to shares (Point 3)
                # Update WMS for next period's check
                current_holdings[symbol]['wms'] = latest_wms
                debug_print(f"   {symbol} -> HOLD (Ranked high in expanded pool, WMS updated to {latest_wms:.2f}).")

            else:
                # Sell if it's not in the Top N*Factor pool
                symbols_to_sell.add(symbol)
                debug_print(f"   {symbol} -> SELL (Ranked too low for holding pool).")
                
        # Execute Sell orders (Full liquidation of stocks_to_sell)
        total_sale_value = 0.0
        total_sale_fees = 0.0

        for ticker in symbols_to_sell:
            shares = current_holdings[ticker]['shares'] # UPDATED access
            try: 
                sell_price = trade_day_data.loc[ticker, 'open']
                transaction_value = shares * sell_price
                
                fee = transaction_value * TRANSACTION_COST
                total_fees += fee
                total_capital += transaction_value - fee
                
                total_sale_value += transaction_value
                total_sale_fees += fee
                
                total_trades += 1
                transaction_log.append({
                    'Date': current_date.date(), 'Type': 'SELL', 'Symbol': ticker, 'Shares': shares,
                    'Price': sell_price, 'Value': round(transaction_value, 2), 'Fee': round(fee, 2), 
                    'Net_Capital': round(total_capital, 2)
                })
                current_holdings_to_remove.add(ticker)
                
            except KeyError:
                print(f"[WARNING] Cannot find opening price for {ticker} on {current_date.date()}. Liquidation failed.")
                current_holdings_to_remove.add(ticker) 

        # Remove sold items from current_holdings after iterating
        for ticker in current_holdings_to_remove:
            if ticker in current_holdings:
                 del current_holdings[ticker]

        print(f"   Stocks Sold (Full Liquidation): {len(symbols_to_sell)} | Sale Proceeds: ${total_sale_value:,.2f} | Fees: ${total_sale_fees:,.2f}")
        print(f"   Stocks Held (No Adjustment): {len(symbols_to_hold)}")
        print(f"   Cash Available After Sales: ${total_capital:,.2f}")


        # --- D. Buy Phase (New Stock Additions) ---
        print("4. Applying Buy Logic (New Additions Only)...")
        
        # 4.1 Determine Available Slots and Candidates
        current_slots_occupied = len(symbols_to_hold)
        slots_to_fill = top_n - current_slots_occupied
        
        if slots_to_fill <= 0:
            print("   Portfolio is full with held stocks. No new purchases required.")
            print(f"   Unused Cash Left in Purse: ${total_capital:,.2f}")
            continue

        # Point 5: Identify the maximum number of stocks we need to buy
        max_stocks_to_buy = slots_to_fill
        
        # Point 5 & 6: Find eligible new candidates from the Top N limit
        new_candidates = []
        
        # Use only candidates that passed all filters, sorted by WMS
        qualified_candidates_df = rebalance_candidates_df
        
        for index, row in qualified_candidates_df.head(NEW_STOCK_ADDITION_LIMIT).iterrows():
            symbol = row['Symbol']
            if symbol not in symbols_to_hold and symbol not in current_holdings:
                # Also check if we have a trade price for the day
                if symbol in trade_day_data.index:
                    new_candidates.append(row)
                    debug_print(f"   {symbol} added as New Buy Candidate (Rank: {index+1}).")
                else:
                    debug_print(f"   {symbol} excluded (Missing trade price on {current_date.date()}).")

        # Point 6: The actual number of stocks to buy is the MIN of slots available and candidates found
        stocks_to_buy_count = min(max_stocks_to_buy, len(new_candidates))
        stocks_to_buy = new_candidates[:stocks_to_buy_count]

        print(f"   Slots to Fill: {max_stocks_to_buy} | Candidates Found (Top {NEW_STOCK_ADDITION_LIMIT}): {len(new_candidates)} | Actual Purchases: {stocks_to_buy_count}")

        if stocks_to_buy_count == 0:
            print(f"   No suitable new stocks to purchase. Unused Cash Left in Purse: ${total_capital:,.2f}")
            continue

        # 4.2 Allocation and Purchase (Points 4 & 5)
        
        # Point 5: Remaining cash is divided into parts equal to stocks_to_buy_count
        cash_per_stock = (total_capital * 0.99)/ stocks_to_buy_count
        
        total_cash_spent = 0.0
        total_buy_fees = 0.0
        
        for candidate in stocks_to_buy:
            ticker = candidate['Symbol']
            wms_for_holding = candidate['FinalWeightedScore'] # WMS for Point 3 update
            
            try:
                buy_price = trade_day_data.loc[ticker, 'open']
                
                # Calculate shares based on cash_per_stock
                target_shares_float = cash_per_stock / buy_price
                shares_to_buy = np.floor(target_shares_float).astype(int) 
                
                if shares_to_buy > 0: 
                    buy_value = shares_to_buy * buy_price
                    fee = buy_value * TRANSACTION_COST
                    
                    if total_capital >= (buy_value + fee):
                        
                        total_capital -= (buy_value + fee)
                        total_fees += fee
                        total_cash_spent += buy_value
                        total_buy_fees += fee
                        total_buy_trades += 1
                        total_trades += 1
                        
                        # Add holding structure (Point 3)
                        current_holdings[ticker] = {
                            'shares': shares_to_buy, 
                            'wms': wms_for_holding
                        }
                        
                        transaction_log.append({
                            'Date': current_date.date(), 'Type': 'BUY', 'Symbol': ticker, 'Shares': shares_to_buy,
                            'Price': buy_price, 'Value': round(buy_value, 2), 'Fee': round(fee, 2), 
                            'Net_Capital': round(total_capital, 2)
                        })
                        debug_print(f"   BUY {ticker}: {shares_to_buy} shares @ ${buy_price:.2f} (Cost: ${buy_value+fee:,.2f})")
                        
                    else:
                        debug_print(f"   {ticker} BUY FAILED: Insufficient remaining cash for value + fee.")
                else:
                    debug_print(f"   {ticker} BUY SKIPPED: Calculated shares to buy is 0.")
                    
            except KeyError:
                # This should be caught earlier, but kept for robustness
                debug_print(f"[WARNING] Cannot find opening price for {ticker}. Skipping buy.")


        print(f"5. Purchase complete. New stocks added: {len(current_holdings) - current_slots_occupied}. Total cash spent: ${total_cash_spent:,.2f} | Buy Fees: ${total_buy_fees:,.2f}")
        print(f" Final Holdings: {len(current_holdings)} stocks. Unused Cash Left in Purse: ${total_capital:,.2f}")


        # --- E. Daily Equity Tracking (from rebalance to next rebalance) ---
        # Get all trading days in the period
        period_days = benchmark_df.loc[current_date:next_date].index.to_list()
        
        # Ensure daily data for all holdings is available
        tickers_to_track = list(current_holdings.keys())
        update_global_data(tickers_to_track)
        
        for daily_date in period_days:
            daily_data = get_all_stock_data_for_date(tickers_to_track, daily_date)
            
            if daily_data.empty:
                continue
                
            current_equity = total_capital # Start with cash
            # UPDATED: Accessing shares via holding_info['shares']
            for ticker, holding_info in current_holdings.items():
                shares = holding_info['shares']
                try:
                    price = daily_data.loc[ticker, 'close']
                    current_equity += shares * price
                except KeyError:
                    # Skip if price is missing on the end date
                    pass
            
            equity_curve_data.append({
                'Date': daily_date.date(),
                'Equity': round(current_equity, 2)
            })
            
        # --- F. End of Period Valuation and Logging ---
        
        # Calculate end value based on closing price (using CLOSE price from next_date)
        end_value_period = total_capital 
        
        # Get price data for next_date (start of next rebalance/end of this one)
        next_date_data = get_all_stock_data_for_date(list(current_holdings.keys()), next_date)
        
        if next_date_data.empty:
            # Fallback to the last logged equity for performance calculation
            if equity_curve_data:
                end_value_period = equity_curve_data[-1]['Equity']
            else:
                end_value_period = total_capital
        else:
            # UPDATED: Accessing shares via holding_info['shares']
            for ticker, holding_info in current_holdings.items():
                shares = holding_info['shares']
                try:
                    price = next_date_data.loc[ticker, 'close']
                    end_value_period += shares * price
                except KeyError:
                    # Skip if price is missing on the end date
                    pass
        
        period_return = (end_value_period / start_value_period) - 1.0 if start_value_period > 0 else np.nan

        # Feature 1: Benchmark Return Calculation (v10.17.14)
        benchmark_return = np.nan
        
        if benchmark_df is not None:
            try:
                # Get start price (closest to current_date)
                start_price_series = benchmark_df.loc[:current_date]['close'].iloc[-1:]
                # Get end price (closest to next_date)
                end_price_series = benchmark_df.loc[next_date:]['close'].iloc[:1]

                if not start_price_series.empty and not end_price_series.empty:
                    start_close = start_price_series.iloc[0]
                    end_close = end_price_series.iloc[0]
                    if start_close > 0:
                        benchmark_return = (end_close / start_close) - 1.0
            except (IndexError, KeyError):
                pass
        
        # 6. Log Results
        rebalance_results.append({
            'Start_Date': current_date.date(), 'End_Date': next_date.date(),
            'Start_Value': round(start_value_period, 2), 'End_Value': round(end_value_period, 2),
            'Return': round(period_return * 100, 2), 
            'Benchmark_Return': round(benchmark_return * 100, 2) if not np.isnan(benchmark_return) else np.nan,
            'Holdings_Count': len(current_holdings),
            'Total_Fees': round(total_fees, 2), 
            'Trades': total_trades
        })
        total_fees = 0
        
        print(f"End Value: ${end_value_period:,.2f} | Period Return: {period_return*100:.2f}% (Benchmark: {benchmark_return*100:.2f}%)")
        
    # ... [Final Liquidation and Reporting remains the same]
    # ------------------------------------------------
    # 5. Final Liquidation at End Date
    # ------------------------------------------------

    final_sale_date = effective_end_date.date()
    total_final_sale_fees = 0.0
    
    print("\n" + "="*70)
    print(f"FINAL LIQUIDATION ON {final_sale_date}")
    print("="*70)

    # Get closing price data for the final day
    update_global_data(list(current_holdings.keys()))
    final_day_data = get_all_stock_data_for_date(list(current_holdings.keys()), effective_end_date)
    
    # Sell all remaining holdings
    holdings_to_sell = list(current_holdings.keys())
    
    for ticker in holdings_to_sell:
        if ticker not in current_holdings: continue
        
        shares_to_sell = current_holdings[ticker]['shares'] # UPDATED access
        
        try:
            # Use final day closing price for liquidation
            sell_price = final_day_data.loc[ticker, 'close'] 
            transaction_value = shares_to_sell * sell_price
            
            # Deduct transaction fee based on the transaction value
            fee = transaction_value * TRANSACTION_COST
            total_final_sale_fees += fee
            
            # Add net proceeds to capital (Value - Fee)
            total_capital += transaction_value - fee
            
            # Remove from holdings (liquidate)
            current_holdings.pop(ticker)
            
            # Log the transaction
            total_trades += 1
            transaction_log.append({
                'Date': final_sale_date, 'Type': 'FINAL_SELL', 'Symbol': ticker, 'Shares': shares_to_sell,
                'Price': sell_price, 'Value': round(transaction_value, 2), 'Fee': round(fee, 2), 
                'Net_Capital': round(total_capital, 2)
            })
            
        except KeyError:
             print(f"[WARNING] No closing price available for final sale of {ticker} on {final_sale_date}. Shares were not sold.")
             
    final_value = total_capital
    print(f"\n[FINAL LIQUIDATION] Final cash: ${final_value:,.2f} | Final sale fees: ${total_final_sale_fees:,.2f} | Total trades: {total_trades}")

    # ------------------------------------------------
    # 5. Final Reporting
    # ------------------------------------------------

    # Calculate annualized return    
    total_return = (final_value / initial_capital) - 1.0
    total_fees_charged = sum(r['Total_Fees'] for r in rebalance_results) + total_final_sale_fees # Re-calculate for accuracy    

    days = (effective_end_date - effective_start_date).days
    annualized_return = (1 + total_return) ** (365.25 / days) - 1.0 if days > 0 else 0.0

    # Calculate total benchmark return over the entire period (start_date to end_date)
    print(f"BACKTEST RESULTS Calcuating Benchmark Return for category {category} between start date {effective_start_date} and end date {effective_end_date}")
    benchmark_period_return = np.nan
    try:
        # Safer indexing: Find the last available closing price on or before the start date
        start_data = benchmark_df.loc[:effective_start_date]['close'].iloc[-1:]
        if start_data.empty:
            raise ValueError("Benchmark data not available for start date.")
            
        # Safer indexing: Find the first available closing price on or after the end date
        end_data = benchmark_df.loc[effective_end_date:]['close'].iloc[:1]
        if end_data.empty:
            raise ValueError("Benchmark data not available for End date.")
        
        if not start_data.empty and not end_data.empty:
            benchmark_start_price = start_data.iloc[0].item()
            benchmark_end_price = end_data.iloc[0].item()
            
            if benchmark_start_price > 0:
                benchmark_period_return = (benchmark_end_price / benchmark_start_price) - 1.0
        else:
                # This captures cases where one of the data series is empty
            raise ValueError("Benchmark data not available for start or end date.")
    except Exception as e:
        print(f"ERROR BACKTEST Not able to calculate Return for category {category} with Error {e}")
        pass # Benchmark period return remains NaN
    
    benchmark_annualized_return = np.nan
    if not np.isnan(benchmark_period_return) and days > 0:
        benchmark_annualized_return = (1 + benchmark_period_return) ** (365.25 / days) - 1.0

    print("\n" + "="*70)
    print(f"BACKTEST RESULTS SUMMARY ({category})")
    print("="*70)
    print(f"Initial Capital: ${initial_capital:,.2f}")
    print(f"Final Value:     ${final_value:,.2f}")
    print(f"Total Return:    {total_return*100:.2f}%")
    print(f"Annualized Ret:  {annualized_return*100:.2f}%")
    print("-" * 30)
    print(f"Benchmark Total Ret: {benchmark_period_return*100:.2f}%")
    print(f"Benchmark Ann Ret:   {benchmark_annualized_return*100:.2f}%")
    print("-" * 30)
    print(f"Total Trades: {total_trades}")
    print(f"Total Fees:   ${total_fees_charged:,.2f}")
    print("="*70)

    # Convert results to DataFrame for export/display
    df_rebalance = pd.DataFrame(rebalance_results)
    df_equity = pd.DataFrame(equity_curve_data)
    df_equity = df_equity.sort_values("Date")
    df_equity = df_equity.drop_duplicates(subset=["Date"], keep="first")
    df_transactions = pd.DataFrame(transaction_log)
    df_benchmarks = get_benchmark_returns(category, effective_start_date, effective_end_date)
    
    if not df_equity.empty:
        # Final formatting for the curve
        df_equity['Date'] = pd.to_datetime(df_equity['Date'])
        # Ensure we capture the start value even if no trades occurred on day 1
        if df_equity.iloc[0]['Date'].date() != effective_start_date.date():
            df_equity.loc[-1] = {'Date': effective_start_date.date(), 'Equity': initial_capital}
            df_equity.index = df_equity.index + 1
            df_equity = df_equity.sort_index().reset_index(drop=True)
            
    #print("\nEQUITY CURVE CHART:")
    #print(df_equity.to_markdown(index=False))
    # 

    #[Image of Equity Curve Chart]
    #(Assuming your environment renders this)

    #print("\nREBALANCE PERIOD SUMMARY:")
    #print(df_rebalance.to_markdown(index=False))

    #print("\nTRANSACTION LOG (First 10 entries):")
    #print(df_transactions.head(10).to_markdown(index=False))

    return df_rebalance, df_equity, df_transactions, df_benchmarks

# ============================================================
# NEW/RESTORED INTERACTIVE FEATURES
# ============================================================

def select_category_interactively(prompt_message: str) -> Optional[str]:
    """Allows the user to select an index category by number."""
    if not CONFIG: load_config()
    categories = list(CONFIG["DATA_CONFIG"]["SYMBOL_FILE_MAP"].keys())
    
    if not categories:
        print("\n**ERROR: No index categories are configured in the system.**")
        print("Please use Option [5] to add a category or [7] to load a config file.")
        return None

    print("\n--- Available Index Categories ---")
    for i, category in enumerate(categories):
        file_name = CONFIG["DATA_CONFIG"]["SYMBOL_FILE_MAP"][category]
        print(f"[{i + 1}]. {category} (File: {file_name})")
    print("-" * 30)
    
    while True:
        choice = input(f"{prompt_message} [1-{len(categories)}]: ").strip()
        if choice.isdigit():
            choice_index = int(choice) - 1
            if 0 <= choice_index < len(categories):
                return categories[choice_index]
            else:
                print("Invalid choice number.")
        else:
            print("Invalid input.")

def run_quick_backtest():
    """Runs a backtest using default parameters for a user-selected category."""
    if not GLOBAL_STOCK_DATA:
        print("Initial stock price data download failed. Cannot run quick backtest. Run Option [9] first.")
        return
        
    category = select_category_interactively("Select category for QUICK backtest: ")
    if not category:
        return

    b_config = CONFIG.get("BACKTEST_CONFIG", {})
    top_n = b_config.get('TOP_N', 10)
    rebalance_freq = b_config.get('REBALANCE_FREQUENCY', 'Q')
    transaction_cost = b_config.get('TRANSACTION_COST', 0.001)

    # Use default dates (last 5 years)
    end_date_str = datetime.now().strftime("%Y-%m-%d")
    start_date_str = (datetime.now() - timedelta(days=5*365.25)).strftime("%Y-%m-%d")

    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
    except ValueError:
        print("Error in default date calculation. Aborting.")
        return

    run_full_backtest(category, start_date, end_date, top_n, rebalance_freq, transaction_cost)

def run_quick_backtest_multiple_catagory_for_multiple_years(years_list: list, categories :list):
    """Runs a backtest using default parameters for a user-selected category."""
    if not GLOBAL_STOCK_DATA:
        print("Initial stock price data download failed. Cannot run quick backtest. Run Option [9] first.")
        return
    
    if not categories:
        return

    b_config = CONFIG.get("BACKTEST_CONFIG", {})
    top_n = b_config.get('TOP_N', 10)
    rebalance_freq = b_config.get('REBALANCE_FREQUENCY', 'Q')
    transaction_cost = b_config.get('TRANSACTION_COST', 0.001)
   
    for years_n in years_list:
        end_date_str = datetime.now().strftime("%Y-%m-%d")
        start_date_str = (datetime.now() - timedelta(days=int(float(years_n))*365.25)).strftime("%Y-%m-%d")

        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
        except ValueError:
            print("Error in default date calculation. Aborting.")
            return
        
        for category in categories:
            df_rebalance, df_equity, df_transactions, df_benchmarks = run_full_backtest(category, start_date, end_date, top_n, rebalance_freq, transaction_cost)
            
            if not df_equity.empty:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                excel_file_name = f"{category}_yr_count_{years_n}_{timestamp}"
                export_backtest_data_default_excel(category, df_rebalance, df_equity, df_transactions, df_benchmarks, excel_file_name)


def run_quick_backtest_multiple_category_different_financial_years(start_yr_for_backtrack: int, years_n: int, categories :list):
    """Run backtests for all configured categories over multiple FY windows,
    aggregate results (strategy + benchmark), export one Excel summary,
    and create 1 comparison plot per FY with all categories + benchmarks.
    """
    if not GLOBAL_STOCK_DATA:
        print("Initial stock price data download failed. Cannot run quick backtest. Run Option [9] first.")
        return

    if not CONFIG:
        load_config()

    if not categories:
        return

    b_config = CONFIG.get("BACKTEST_CONFIG", {})
    top_n = b_config.get("TOP_N", 10)
    rebalance_freq = b_config.get("REBALANCE_FREQUENCY", "Q")
    transaction_cost = b_config.get("TRANSACTION_COST", 0.001)

    years_number_list = range(start_yr_for_backtrack, (datetime.now().year) + 1)

    # --- aggregation containers ---
    summary_rows = []  # rows for summary DataFrame
    # curves_by_fy[fy_year] = {"strategy": {category: Series}, "benchmark": {category: Series}}
    curves_by_fy = {}

    for year in years_number_list:
        fy_end = date(year, 3, 31)
        end_date_str = fy_end.strftime("%Y-%m-%d")
        start_date_str = (fy_end - timedelta(days=int(float(years_n) * 365.25))).strftime("%Y-%m-%d")

        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
        except ValueError:
            print("Error in default date calculation. Aborting.")
            return

        print(f"\n=== Running backtests for FY ending {end_date_str}, lookback {years_n} years ===")

        for category in categories:
            print(f" -> Category: {category}")

            df_rebalance, df_equity, df_transactions, df_benchmarks = run_full_backtest(
                category, start_date, end_date, top_n, rebalance_freq, transaction_cost
            )

            if df_equity is None or df_equity.empty:
                print(f"   Skipping {category} for FY {year}: empty equity.")
                continue

            # Normalize columns
            df_equity = normalize_columns(df_equity)
            df_benchmarks = normalize_columns(df_benchmarks)

            # Clean dates
            if "date" in df_equity.columns:
                df_equity["date"] = pd.to_datetime(df_equity["date"])
                df_equity = df_equity.sort_values("date").drop_duplicates(subset=["date"], keep="first")

            if "date" in df_benchmarks.columns:
                df_benchmarks["date"] = pd.to_datetime(df_benchmarks["date"])
                df_benchmarks = df_benchmarks.sort_values("date").drop_duplicates(subset=["date"], keep="first")

            if "equity" not in df_equity.columns:
                print(f"   Skipping {category} for FY {year}: 'equity' column missing.")
                continue

            eq_ser = df_equity.set_index("date")["equity"]
            if len(eq_ser) < 2:
                print(f"   Skipping {category} for FY {year}: not enough equity points.")
                continue

            # Align benchmark if available
            bench_ser = None
            if df_benchmarks is not None and not df_benchmarks.empty and "close" in df_benchmarks.columns:
                bench_ser = df_benchmarks.set_index("date")["close"]
                eq_ser, bench_ser = eq_ser.align(bench_ser, join="inner")
                if len(eq_ser) < 2 or len(bench_ser) < 2:
                    bench_ser = None

            # Strategy performance
            eq_start = float(eq_ser.iloc[0])
            eq_end = float(eq_ser.iloc[-1])
            eq_total_ret = eq_end / eq_start - 1.0
            eq_ann_ret = (1.0 + eq_total_ret) ** (1.0 / years_n) - 1.0

            # Benchmark performance
            bench_total_ret = None
            bench_ann_ret = None
            bench_name = None

            if bench_ser is not None:
                b_start = float(bench_ser.iloc[0])
                b_end = float(bench_ser.iloc[-1])
                bench_total_ret = b_end / b_start - 1.0
                bench_ann_ret = (1.0 + bench_total_ret) ** (1.0 / years_n) - 1.0
                # simple label: "nifty50 benchmark" for "Nifty50" etc.
                bench_name = category.lower()

            summary_rows.append(
                {
                    "Category": category,
                    "Benchmark_Name": bench_name,
                    "FY_End": end_date_str,
                    "Lookback_Years": years_n,
                    "Start_Date": eq_ser.index[0].strftime("%Y-%m-%d"),
                    "End_Date": eq_ser.index[-1].strftime("%Y-%m-%d"),
                    "Start_Equity": eq_start,
                    "End_Equity": eq_end,
                    "Strategy_Total_Return_%": eq_total_ret * 100.0,
                    "Strategy_CAGR_%": eq_ann_ret * 100.0,
                    "Benchmark_Total_Return_%": None if bench_total_ret is None else bench_total_ret * 100.0,
                    "Benchmark_CAGR_%": None if bench_ann_ret is None else bench_ann_ret * 100.0,
                }
            )

            # Store curves grouped by FY
            fy_dict = curves_by_fy.setdefault(year, {"strategy": {}, "benchmark": {}})
            fy_dict["strategy"][category] = eq_ser
            if bench_ser is not None:
                fy_dict["benchmark"][category] = bench_ser

    if not summary_rows:
        print("No successful backtests to summarize.")
        return

    df_summary = pd.DataFrame(summary_rows)
    print("\n=== Summary of all backtests ===")
    print(df_summary)

    # --- export to single Excel ---
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    root_base_folder = "Backtest_Results"
    base_folder = os.path.join(root_base_folder, f"{timestamp}")
    os.makedirs(base_folder, exist_ok=True)
    excel_path = os.path.join(base_folder, f"multi_category_backtests_{timestamp}.xlsx")

    with pd.ExcelWriter(excel_path, engine="xlsxwriter") as writer:
        # 1) Summary sheet (strategy + benchmark stats)
        df_summary.to_excel(writer, sheet_name="Summary", index=False)

        # flatten curves_by_fy => long table
        # 2) Long-format strategy equity curves
        strat_rows = []
        bench_rows = []
        for fy_year, data in curves_by_fy.items():
            # strategies
            for category, ser in data.get("strategy", {}).items():
                for dt, val in ser.items():
                    strat_rows.append(
                        {
                            "FY_Year": fy_year,
                            "Category": category,
                            "Date": dt,
                            "Equity": float(val),
                        }
                    )            
            # benchmarks
            for category, b_ser in data.get("benchmark", {}).items():
                for dt, val in b_ser.items():
                    bench_rows.append(
                        {
                            "FY_Year": fy_year,
                            "Category": category,
                            "Date": dt,
                            "Benchmark_Value": float(val),
                        }
                    )

        if strat_rows:
            df_all_eq = pd.DataFrame(strat_rows)
            df_all_eq.to_excel(writer, sheet_name="All_Equity_Curves", index=False)

        if bench_rows:
            df_all_bench = pd.DataFrame(bench_rows)
            df_all_bench.to_excel(writer, sheet_name="All_Benchmark_Curves", index=False)

    print(f"\n✅ Exported multi-category backtest results to: {excel_path}")

    # --- create 1 plot per FY with all category + benchmark curves ---
    plot_multi_category_equity_by_fy(curves_by_fy, base_folder)

def run_full_backtest_interactive():
    """Allows running a backtest with custom parameters."""
    if not GLOBAL_STOCK_DATA:
        print("Initial stock price data download failed. Cannot run full backtest. Run Option [9] first.")
        return
        
    category = select_category_interactively("Select category for FULL backtest: ")
    if not category:
        return

    b_config = CONFIG.get("BACKTEST_CONFIG", {})
    
    # Prompt for custom parameters
    print("\n--- Configure Full Backtest ---")
    start_date_str = input(f"Enter Start Date (YYYY-MM-DD, Default: {(datetime.now() - timedelta(days=5*365.25)).strftime('%Y-%m-%d')}): ").strip() or (datetime.now() - timedelta(days=5*365.25)).strftime("%Y-%m-%d")
    end_date_str = input(f"Enter End Date (YYYY-MM-DD, Default: {datetime.now().strftime('%Y-%m-%d')}): ").strip() or datetime.now().strftime("%Y-%m-%d")
    top_n_str = input(f"Enter Top N stocks to select (Default: {b_config.get('TOP_N', 10)}): ").strip() or str(b_config.get('TOP_N', 10))
    rebalance_freq = input(f"Enter Rebalance Frequency (M/Q/A, Default: {b_config.get('REBALANCE_FREQUENCY', 'Q')}): ").strip().upper() or b_config.get('REBALANCE_FREQUENCY', 'Q')
    transaction_cost_str = input(f"Enter Transaction Cost (e.g., 0.001 for 0.1%, Default: {b_config.get('TRANSACTION_COST', 0.001)}): ").strip() or str(b_config.get('TRANSACTION_COST', 0.001))

    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
        top_n = int(top_n_str)
        transaction_cost = float(transaction_cost_str)
    except ValueError:
        print("Invalid date/number format entered. Aborting.")
        return
        
    if rebalance_freq not in ['M', 'Q', 'A']:
        print("Invalid rebalance frequency. Aborting.")
        return

    #run_full_backtest(category, start_date, end_date, top_n, rebalance_freq, transaction_cost)
    # --- Run the Backtest ---
    try:
        # The run_full_backtest function returns the results DataFrames
        df_rebalance, df_equity, df_transactions, df_benchmarks = run_full_backtest(
            category, start_date, end_date, top_n, rebalance_freq, transaction_cost
        )
        
        # --- NEW EXPORT LOGIC ---
        if not df_equity.empty:
            export_choice = input("\nDo you want to export the backtest results? (y/n): ").strip().lower()
            if export_choice == 'y':
                export_backtest_data(category, df_rebalance, df_equity, df_transactions, df_benchmarks)
        
    except Exception as e:
        print(f"\nCRITICAL ERROR during backtest execution: {e}")
        import traceback
        traceback.print_exc()


def get_momentum_recommendations_interactive(top_n: int):
    """ 
    Handles the interactive process for selecting an index and generating today's top 
    momentum recommendations, including export functionality (Feature 2). 
    """
    if not GLOBAL_STOCK_DATA:
        print("Initial stock price data download failed. Cannot run recommendations. Run Option [9] first.")
        return

    # 1. Ask the user to select an index category
    category_name = select_category_interactively("Select category for today's recommendations: ")
    if not category_name:
        return
        
    symbols = load_symbols(category_name)
    if not symbols:
        print(f"Error: Could not load symbols for category '{category_name}'. Aborting.")
        return

    print(f"\nCalculating recommendations for {category_name} with {len(symbols)} stocks...")
    
    # Ensure data is up to date (updates all stocks and benchmark)
    update_global_data(symbols)
    
    # Use today's date for scoring
    today = datetime.now()
    
    # 2. Call the core logic to get filtered and ranked stocks
    # This also applies the P/V filter and final WMS calculation
    filtered_and_sorted = get_momentum_scores_for_stocks(symbols, target_date=today)
    
    # Filter to only stocks that passed all filters and have WMS > 0
    final_recommendations = [ 
        s for s in filtered_and_sorted 
        if s['PassedFilters'] == True and s['FinalWeightedScore'] > 0 
    ]

    if not final_recommendations:
        print(f"\n[ERROR] No stocks passed all filters for the {category_name} category.")
        return

    # Convert list of dicts to DataFrame for clean display and export
    export_df = pd.DataFrame(final_recommendations)
    
    # Rename for readability
    export_df = export_df.rename(columns={
        'FinalWeightedScore': 'WMS',
        'P_Mom_Raw_Pct': 'P_Pct',
        'Value_Raw_Pct': 'V_Pct',
        'ConsistencyOK': 'Consistency',
        'Details': 'FilterDetails'
    })

    # Display Top N recommendations
    display_df = export_df.sort_values(by='WMS', ascending=False).head(top_n)
    
    print(f"\n--- Top {min(top_n, len(final_recommendations))} Momentum Recommendations ({category_name}) ---")
    
    # Columns for display: WMS, P_Pct, V_Pct, RS_Raw
    display_cols = ['Symbol', 'WMS', 'P_Pct', 'V_Pct', 'RS_Raw']
    
    # Final cleanup before display/export
    for col in display_cols:
        if col in display_df.columns:
            # Round numerical columns for display
            if display_df[col].dtype in ['float64', 'float32']:
                display_df[col] = display_df[col].round(2)
        else:
             # Drop if missing (should not happen with current logic, but safe)
             display_cols.remove(col) 
             
    display_df = display_df[display_cols].reset_index(drop=True)
    display_df.index = display_df.index + 1
    display_df.index.name = 'Rank'
    
    print(display_df.to_markdown(index=True, numalign="left", stralign="left"))

    # 3. Export the full filtered set (not just top N)
    base_filename = f"{category_name}_Top_Recommendations"
    
    # export_cols_all = [
    #     'Symbol', 'WMS', 'P_Pct', 'V_Pct', 'RS_Raw', 'WMS_ROC_Raw', 'RSI_Raw', 'MFI_Raw', 'CCI_Raw', 
    #     'PassedFilters', 'FilterReason', 'Consistency', 'FilterDetails'
    # ]
    # Standardize column order (all calculated columns)
    export_cols_all = [
        'Symbol', 'WMS', 'P_Pct', 'V_Pct', 'WMS_ROC_Raw_Pct', 'RSI_Raw_Pct', 'MFI_Raw_Pct', 'CCI_Raw_Pct', 'RS_Raw_Pct',
        'P_Mom_Raw', 'Value_Raw', 'WMS_ROC_Raw', 'RSI_Raw', 'MFI_Raw', 'CCI_Raw', 'RS_Raw',
        'PassedFilters', 'FilterReason', 'Consistency', 'FilterDetails', 'TotalPassed', 'RecentPassed',
    ]
    
    export_df = export_df[[col for col in export_cols_all if col in export_df.columns]].sort_values(by='WMS', ascending=False).reset_index(drop=True)
    export_df.index = export_df.index + 1
    export_df.index.name = 'Rank'
    
    export_dataframe_to_file(export_df, 'Stock_Recommendations', base_filename)
    
    # # Convert list of dicts to DataFrame for clean display and export
    # export_df = pd.DataFrame(filtered_and_sorted)
    # # Rename for readability
    # export_df = export_df.rename(columns={
    #     'FinalWeightedScore': 'WMS',
    #     'P_Mom_Raw_Pct': 'P_Pct',
    #     'Value_Raw_Pct': 'V_Pct',
    #     'ConsistencyOK': 'Consistency',
    #     'Details': 'FilterDetails'
    # })   
    
    # export_df = export_df[[col for col in export_cols_all if col in export_df.columns]].sort_values(by='WMS', ascending=False).reset_index(drop=True)
    # export_df.index = export_df.index + 1
    # export_df.index.name = 'Rank'
    
    # # 3. Export the full filtered set (not just top N)
    # base_filename = f"{category_name}_full_Recommendations"
    # export_dataframe_to_file(export_df, 'Stock_Recommendations', base_filename)
    
    print("\n--- Recommendations process complete. ---")

# --- NEW FUNCTION TO EXPORT ALL SCORES ---
def export_full_universe_scores(category_name: str):
    """ 
    Handles the interactive process for selecting an index and exporting the 
    full set of raw and final scores for ALL stocks in the selected category. 
    (New Feature - Option 4)
    """
    symbols = load_symbols(category_name)
    if not symbols:
        print(f"Error: Could not load symbols for category '{category_name}'. Aborting.")
        return
        
    print(f"\nCalculating scores for ALL {len(symbols)} stocks in {category_name}...")
    
    # Ensure data is up to date (updates all stocks and benchmark)
    update_global_data(symbols)
    
    # Use today's date for scoring
    today = datetime.now()
    
    # 2. Call the core logic to get filtered and ranked stocks
    # This returns ALL stocks processed, including those that failed filters.
    full_scored_results = get_momentum_scores_for_stocks(symbols, target_date=today)
    
    if not full_scored_results:
        print(f"\n[INFO] No data could be processed for the {category_name} category.")
        return
        
    # Convert list of dicts to DataFrame for clean display and export
    export_df = pd.DataFrame(full_scored_results)
    
    # Rename for readability
    export_df = export_df.rename(columns={
        'FinalWeightedScore': 'WMS',
        'P_Mom_Raw_Pct': 'P_Pct',
        'Value_Raw_Pct': 'V_Pct',
        'ConsistencyOK': 'Consistency',
        'Details': 'FilterDetails'
    })
    
    # # Standardize column order (all calculated columns)
    # export_cols_all = [
    #     'Symbol', 'WMS', 'P_Pct', 'V_Pct', 'RS_Raw', 'WMS_ROC_Raw', 'RSI_Raw', 'MFI_Raw', 'CCI_Raw', 
    #     'PassedFilters', 'FilterReason', 'Consistency', 'FilterDetails', 'TotalPassed', 'RecentPassed'
    # ]
    # Standardize column order (all calculated columns)
    export_cols_all = [
        'Symbol', 'WMS', 'P_Pct', 'V_Pct', 'WMS_ROC_Raw_Pct', 'RSI_Raw_Pct', 'MFI_Raw_Pct', 'CCI_Raw_Pct', 'RS_Raw_Pct',
        'P_Mom_Raw', 'Value_Raw', 'WMS_ROC_Raw', 'RSI_Raw', 'MFI_Raw', 'CCI_Raw', 'RS_Raw',
        'PassedFilters', 'FilterReason', 'Consistency', 'FilterDetails', 'TotalPassed', 'RecentPassed',
    ]
    
    # Ensure required columns are present and select them in order
    final_cols = [col for col in export_cols_all if col in export_df.columns]
    
    # Sort by WMS descending, reset index, and add 'Rank'
    export_df = export_df[final_cols].sort_values(by=['PassedFilters', 'WMS', 'P_Pct', 'V_Pct'], ascending=[False, False, False, False]).reset_index(drop=True)
    export_df.index = export_df.index + 1
    export_df.index.name = 'Rank'
    
    # 3. Export the file
    base_filename = f"{category_name}_FULL_SCORES"
    export_dataframe_to_file(export_df, "Scored_Custom", base_filename)
    
    print("\n--- Full Score Export process complete. ---")
# --- END NEW FUNCTION ---

def add_new_category_to_config():
    """Allows interactive addition of a new index category and symbol file map."""
    global CONFIG
    print("\n--- Add New Index Category ---")
    
    new_category_name = input("Enter new category NAME (e.g., 'Sensex30'): ").strip()
    if not new_category_name:
        print("Category name cannot be empty. Cancelled.")
        return
        
    if new_category_name in CONFIG["DATA_CONFIG"]["SYMBOL_FILE_MAP"]:
        print(f"Category '{new_category_name}' already exists. Use Option [6] to edit or [0] to cancel.")
        return

    file_name = input("Enter symbol list CSV FILE NAME (e.g., 'ind_sensex30list.csv'): ").strip()
    if not file_name:
        print("File name cannot be empty. Cancelled.")
        return

    file_path = Path(file_name)
    if not file_path.exists():
        print(f"**Warning: File '{file_name}' not found at current location. Ensure the file is placed in the correct directory.**")
        
    CONFIG["DATA_CONFIG"]["SYMBOL_FILE_MAP"][new_category_name] = file_name
    print(f"Category '{new_category_name}' added to configuration (File: {file_name}). Remember to save configuration.")


def edit_config_menu():
    """Allows interactive editing of configuration settings."""
    if not CONFIG: load_config()

    sections = {
        '1': "SYSTEM_CONFIG",
        '2': "DATA_CONFIG",
        '3': "MOMENTUM_CONFIG",
        '4': "FILTER_CONFIG",
        '5': "SCORING_WEIGHTS",
        '6': "BACKTEST_CONFIG"
    }
    
    while True:
        print("\n--- Edit Configuration Settings ---")
        for k, v in sections.items():
            print(f"[{k}]. {v}")
        print("[0]. Back to Section Menu")
        print("-" * 30)

        section_choice = input("Select section to edit: ").strip()
        if section_choice == '0':
            break

        section_name = sections.get(section_choice)
        if not section_name:
            print("Invalid section choice.")
            continue

        section_data = CONFIG.get(section_name, {})
        print(f"\n--- Editing {section_name} ---")
        
        parameters = list(section_data.keys())
        if not parameters:
             print(f"No editable parameters found in {section_name}.")
             continue
             
        for i, param in enumerate(parameters):
            print(f"[{i + 1}]. {param}: {section_data[param]}")
        print("[0]. Back to Section Menu")
        print("-" * 30)

        param_choice = input("Select parameter number to change: ").strip()
        if param_choice == '0':
            continue

        try:
            param_index = int(param_choice) - 1
            if 0 <= param_index < len(parameters):
                selected_param = parameters[param_index]
                current_value = section_data[selected_param]
                
                print(f"\nCurrent value for '{selected_param}': {current_value}")
                new_value_str = input("Enter new value: ").strip()
                
                if not new_value_str:
                    print("No change made.")
                    continue

                new_value: Any = new_value_str
                
                # Attempt to convert to the original type
                if isinstance(current_value, int):
                    new_value = int(new_value_str)
                elif isinstance(current_value, float):
                    new_value = float(new_value_str)
                elif isinstance(current_value, bool):
                    if new_value_str.lower() in ('true', 't', '1'):
                        new_value = True
                    elif new_value_str.lower() in ('false', 'f', '0'):
                        new_value = False
                    else:
                        raise ValueError("Invalid boolean input.")
                elif isinstance(current_value, list):
                    # Simple list of numbers assumption
                    try:
                        new_value = [float(x.strip()) for x in new_value_str.split(',') if x.strip()]
                    except ValueError:
                        raise ValueError("Invalid list format. Expecting comma-separated numbers.")
                elif isinstance(current_value, dict):
                    print("Cannot edit dictionaries directly. Please edit config file manually or clear cache to reset.")
                    continue
                else:
                    # Default to string
                    new_value = new_value_str

                CONFIG[section_name][selected_param] = new_value
                print(f"Successfully updated '{selected_param}' to {new_value}.")
                
            else:
                print("Invalid parameter choice.")
        except ValueError:
            print("Invalid value entered for the required data type. Update failed.")
        except Exception as e:
            print(f"An unexpected error occurred: {e}. Update failed.")

def run_quick_backtest_interactively_with_default_config():
    """Allows interactive editing of configuration settings."""
    if not CONFIG: load_config()
    categories = list(CONFIG["DATA_CONFIG"]["SYMBOL_FILE_MAP"].keys())
    print(f"categories : {categories} ")            
    
    if not categories:
        print("\n**ERROR: No index categories are configured in the system.**")
        print("Please use Option [5] to add a category or [7] to load a config file.")
        return None    

    sections = {
        '1': "Quick Backtest for 5 Years",
        '2': "Quick Backtest for single period [ year Duration ] for all categories",
        '3': "Quick Backtest for multiple period for Category",
        '4': "Quick Backtest for multiple period for multiple categories",
        '5': "Quick Backtest for multiple FY for Category",
        '6': "Quick Backtest for multiple FY for multiple categories",
        '7': "Quick Backtest for multiple FY for multiple years [ 1-5] in multiple categories",
    }
    
    while True:
        print("\n--- Run Quick Backtest Choices ---")
        for k, v in sections.items():
            print(f"[{k}]. {v}")
        print("[0]. Back to Section Menu")
        print("-" * 30)

        choice = input("SEnter choice: ").strip()
        if choice == '0':
            break

        section_name = sections.get(choice)
        if not section_name:
            print("Invalid section choice.")
            continue
        
        if choice == '1':
            run_quick_backtest()
        elif choice == '2':
            years_n_str = input("Enter number of years to back track from FY-end (Default: 3): ").strip() or "3"
            years_n=int(years_n_str)
            run_quick_backtest_multiple_catagory_for_multiple_years([years_n], categories)
        elif choice == '3':
            yr_list=[1,2,3,4,5]
            category = select_category_interactively("Select category for FULL backtest: ")
            if not category:
                return
            run_quick_backtest_multiple_catagory_for_multiple_years(yr_list, [category])
        elif choice == '4':
            years_n_str = input("Enter number of years to back track from FY-end (Default: 3): ").strip() or "3"
            years_n=int(years_n_str)
            run_quick_backtest_multiple_catagory_for_multiple_years([years_n], categories)
        elif choice == '5':
            start_yr_for_backtrack_str = input("Enter year to start back track (Default: 2020): ").strip() or "2020"
            years_n_str = input("Enter number of years to back track from FY-end (Default: 3): ").strip() or "3"

            years_n = int(years_n_str)
            start_yr_for_backtrack = int(start_yr_for_backtrack_str)
            category = select_category_interactively("Select category for FULL backtest: ")
            if not category:
                return
            run_quick_backtest_multiple_category_different_financial_years(start_yr_for_backtrack, years_n, [category] )
        elif choice == '6':            
            start_yr_for_backtrack_str = input("Enter year to start back track (Default: 2020): ").strip() or "2020"
            years_n_str = input("Enter number of years to back track from FY-end (Default: 3): ").strip() or "3"

            years_n = int(years_n_str)
            start_yr_for_backtrack = int(start_yr_for_backtrack_str)
            run_quick_backtest_multiple_category_different_financial_years(start_yr_for_backtrack, years_n, categories )
            
        elif choice == '7':            
            start_yr_for_backtrack_str = input("Enter year to start back track (Default: 2020): ").strip() or "2020"            
            start_yr_for_backtrack = int(start_yr_for_backtrack_str)
            yr_list=[1,2,3,4,5]
            for years_n in yr_list:
                run_quick_backtest_multiple_category_different_financial_years(start_yr_for_backtrack, years_n, categories )

def score_custom_universe_from_excel():
    """Allows scoring multiple custom stock universes defined in a single Excel file."""
    if not CONFIG: load_config()
    
    # 1. Ask for Excel File Name
    file_name = input("Enter the Excel file name (e.g., custom_universe.xlsx): ").strip()
    if not file_name:
        print("Operation cancelled.")
        return

    file_path = Path(file_name)
    if not file_path.exists():
        print(f"Error: File not found at '{file_path}'.")
        return

    print(f"Loading workbook: {file_name}")

    try:
        xls = pd.ExcelFile(file_path)
        sheet_names = xls.sheet_names
        
        if not sheet_names:
            print("Error: Excel file contains no sheets.")
            return

    except Exception as e:
        print(f"Error reading Excel file: {e}")
        return

    all_results_by_sheet = {}
    
    for sheet_name in sheet_names:
        print(f"\n--- Processing Sheet: '{sheet_name}' ---")
        
        try:
            df_original = xls.parse(sheet_name)
            if df_original.empty:
                print(f" [INFO] Sheet '{sheet_name}' is empty. Skipping.")
                continue
        except Exception as e:
            print(f"Error parsing sheet '{sheet_name}': {e}. Skipping.")
            continue
            
        # --- A. Get Score Date (UPDATED for Date Range Parsing) ---
        try:
            # Look for a cell in the first row containing 'Date' or 'Score Date'
            date_col_match = df_original.columns[df_original.columns.str.contains('Date', case=False, na=False)].tolist()
            score_date = None
            raw_date_value = None

            if date_col_match:
                # Assuming the date is in the first non-NaN cell of the matched column
                raw_date_series = df_original[date_col_match[0]].dropna()
                if not raw_date_series.empty:
                    raw_date_value = raw_date_series.iloc[0]
            
            if raw_date_value is not None:
                
                # 1. Handle date range string (e.g., "2025-11-03 to 2025-11-09")
                if isinstance(raw_date_value, str) and 'to' in raw_date_value.lower():
                    # Extract the first date string, which is the start date
                    date_string = raw_date_value.split('to')[0].strip()
                    score_date = pd.to_datetime(date_string, errors='coerce').date()
                
                # 2. Handle datetime objects (from Excel direct read)
                elif isinstance(raw_date_value, datetime):
                    score_date = raw_date_value.date()
                
                # 3. Handle single date string/number
                else:
                    score_date = pd.to_datetime(str(raw_date_value), errors='coerce').date()
            
            # If date not found or parsing failed, default to today
            if score_date is None or score_date is pd.NaT.date():
                score_date = date.today()
                print(f" [INFO] Score date not found or invalid. Defaulting to today's date: {score_date}")
            else:
                 print(f" -> Score Date derived from sheet: {score_date}")

        except Exception as e:
             # Default to today if date parsing fails entirely
             score_date = date.today()
             print(f" [INFO] Error determining score date ({e}). Defaulting to today's date: {score_date}")

        # --- B. Get Tickers (UPDATED for YF format) ---
        # Find column containing 'Symbol' or 'Ticker', case-insensitive
        ticker_col = df_original.columns[df_original.columns.str.contains('Symbol|Ticker', case=False, na=False)].tolist()
        if not ticker_col:
            # If no obvious ticker column, assume the first column is the ticker column
            ticker_col = [df_original.columns[0]] 

        # Clean and deduplicate tickers, and EXPLICITLY filter out 'NA'
        all_raw_tickers = df_original[ticker_col[0]].dropna().tolist()
        tickers = []
        na_count = 0
        for t in all_raw_tickers:
            ticker_str = str(t).strip().upper()
            if ticker_str and ticker_str != 'NA':
                # FIX: Check if market suffix is present and append '.NS' if missing for YF format.
                if "." not in ticker_str:
                    ticker_str += ".NS"
                tickers.append(ticker_str)
            elif ticker_str == 'NA':
                na_count += 1

        if not tickers:
            print(f" [INFO] No valid tickers found (or only 'NA's) in sheet '{sheet_name}'. Skipping.")
            continue 
        print(f" -> Found {len(tickers)} tickers for scoring (filtered {na_count} 'NA' entries).")
        
        # --- C. Calculate Scores ---
        full_scored_results = get_momentum_scores_for_stocks(tickers, target_date=score_date)
        
        # --- FIX for AttributeError: 'list' object has no attribute 'empty' ---
        # Convert list of dicts to DataFrame immediately if necessary
        if isinstance(full_scored_results, list):
            full_scored_results = pd.DataFrame(full_scored_results)
            
        # Robust check for None or empty DataFrame
        if full_scored_results is None or full_scored_results.empty:
            print(f" [ERROR] Could not generate scores for any stocks in sheet '{sheet_name}'. Skipping export.")
            continue
            
        # --- FIX for KeyError: 'Ticker_YF' ---
        # Rename 'Symbol' column to 'Ticker_YF' to match the merge key
        if 'Symbol' in full_scored_results.columns:
            full_scored_results = full_scored_results.rename(columns={'Symbol': 'Ticker_YF'})
        # Note: If 'Symbol' is not present, this suggests an issue in get_momentum_scores_for_stocks, 
        # but the merge will proceed, potentially failing on the key if it's missing.

        # --- D. Merge with Original Data and Export ---
        
        # 1. Clean the ticker column in the original DataFrame for merging
        def clean_and_format_ticker(raw_t):
            ticker_str = str(raw_t).strip().upper()
            if ticker_str and ticker_str != 'NA':
                 if "." not in ticker_str:
                    return ticker_str + ".NS"
            return None 
            
        df_original['Merge_Key'] = df_original[ticker_col[0]].apply(clean_and_format_ticker)
        
        # 2. Merge the scored results with the original data
        # 'Ticker_YF' is now ensured to be present (via the renaming logic above)
        scored_results_export = pd.merge(
            df_original, 
            full_scored_results, 
            left_on='Merge_Key', 
            right_on='Ticker_YF', 
            how='left'
        )
        
        # Drop temporary columns and reorder (optional, but good practice)
        scored_results_export = scored_results_export.drop(columns=['Merge_Key', 'Ticker_YF'], errors='ignore')
        
        # 3. Apply ranking and filtering (if enabled)
        
        # --- E. Apply Ranking and Filters (Optional) ---
        
        # Rank the scores
        if 'WMS_Composite_Score' in scored_results_export.columns:
            scored_results_export['Rank'] = scored_results_export['WMS_Composite_Score'].rank(ascending=False, method='min')
            
        # Apply standard filtering if configured
        if CONFIG["FILTER_CONFIG"].get("ENABLE_FILTERS", True):
            # Apply technical filters if columns exist
            min_price = CONFIG["FILTER_CONFIG"].get("MIN_PRICE", 0)
            min_volume = CONFIG["FILTER_CONFIG"].get("MIN_VOLUME_AVG", 0)
            
            # 1. Filter by Price and Volume Average (if calculated/present)
            pre_filter_count = len(scored_results_export)
            if 'Last_Price' in scored_results_export.columns and min_price > 0:
                scored_results_export = scored_results_export[scored_results_export['Last_Price'] >= min_price]
            
            if 'Volume_Avg_30D' in scored_results_export.columns and min_volume > 0:
                scored_results_export = scored_results_export[scored_results_export['Volume_Avg_30D'] >= min_volume]
                
            post_filter_count = len(scored_results_export)
            if pre_filter_count != post_filter_count:
                print(f" -> Applied filters: {pre_filter_count - post_filter_count} stocks filtered out.")

        # Final sort by Rank/Score
        if 'Rank' in scored_results_export.columns:
             scored_results_export = scored_results_export.sort_values(by='Rank')
        
        # Store result
        all_results_by_sheet[sheet_name] = scored_results_export
        print(f" -> Successfully scored and prepared {len(scored_results_export)} stocks.")

    # --- F. Export Results ---
    if not all_results_by_sheet:
        print("\nNo sheets were successfully scored. Export skipped.")
        return
    
    OUTPUT_DIR = Path('.') / 'Scored_Custom'
    OUTPUT_DIR.mkdir(exist_ok=True)    
    path_object = Path(file_path)

    # file_name_with_extension = path_object.name
    # print(f"File name with extension: {file_name_with_extension}")

    base_filename = path_object.stem
    print(f"File name without extension: {base_filename}")
    
    # Clean the filename (e.g., replace spaces/slashes)
    safe_filename = base_filename.replace(' ', '_').replace('/', '-').replace('\\', '-')
    
    #csv_path = OUTPUT_DIR / f"{safe_filename}_{timestamp}.csv"
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file_name = OUTPUT_DIR / f"{safe_filename}_{timestamp}.xlsx"

    #output_file_name = f"Scored_Custom_Universe_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    print(f"\n--- Exporting all sheet results to: {output_file_name} ---")
    
    try:
        with pd.ExcelWriter(output_file_name, engine='xlsxwriter') as writer:
            for sheet_name, df_result in all_results_by_sheet.items():
                # Clean sheet name for Excel if needed
                safe_sheet_name = sheet_name[:31] 
                # Re-run rank if filtering was done
                if 'WMS_Composite_Score' in df_result.columns:
                    df_result['Rank'] = df_result['WMS_Composite_Score'].rank(ascending=False, method='min').astype(int)
                    df_result = df_result.sort_values(by='Rank')
                    
                df_result.to_excel(writer, sheet_name=safe_sheet_name, index=False)
                
        print(f"\nSuccessfully exported all scored results to {output_file_name}")
        
    except Exception as e:
        print(f"FATAL EXPORT ERROR: {e}")        
        
def generate_rebalance_recommendations():
    """
    NEW FUNCTION: Reads a previous recommendation file, calculates current scores,
    and identifies BUY/SELL/HOLD actions based on backtest rebalancing logic.
    """
    print("\n" + "="*60)
    print("PORTFOLIO REBALANCE ASSISTANT (Buffer Logic: Top 20 Buy / Top 40 Hold)")
    print("="*60)
    file_path = input("Enter the path to your LAST_Recommendation (Excel or CSV): ").strip()
    os.makedirs("Rebalance_history", exist_ok=True)
    
    try:
        # 1. Load the previous portfolio
        if file_path.endswith('.csv'):
            old_df = pd.read_csv(file_path)
        else:
            old_df = pd.read_excel(file_path)
        
        if 'Symbol' not in old_df.columns:
            print("Error: The file must contain a 'Symbol' column.")
            return

        current_holdings = old_df['Symbol'].unique().tolist()
        print(f"Current Holdings: Loaded {len(current_holdings)} stocks")

        # 2. Select Category (Universe) for comparison
        print("\nSelect Universe to compare against:")
        category = select_category_interactively("Select category for comparison: ")
        if not category: return        

        # 3. Calculate fresh scores for the whole universe
        print(f"Fetching current market data for {category}...")
        universe_symbols = load_symbols(category)
        # Ensure current holdings are included in the calculation even if they moved out of the index
        total_symbols_to_check = list(set(universe_symbols + current_holdings))
        
        # This returns ALL stocks processed, including those that failed filters.
        scores_list = get_momentum_scores_for_stocks(total_symbols_to_check, target_date=datetime.now())
        scores_df = pd.DataFrame(scores_list)        
        if scores_df.empty:
            print("Failed to calculate scores.")
            return

        # Rename for readability
        scores_df = scores_df.rename(columns={
            'FinalWeightedScore': 'WMS',
            'P_Mom_Raw_Pct': 'P_Pct',
            'Value_Raw_Pct': 'V_Pct',
            'ConsistencyOK': 'Consistency',
            'Details': 'FilterDetails'
        })
        
        # 3. Identify Thresholds
        # Filter only stocks that passed fundamental criteria
        filtered_df = scores_df[scores_df['PassedFilters'] == True].sort_values(by='WMS', ascending=False).copy()

        target_size = CONFIG["BACKTEST_CONFIG"]["TOP_N"]
        scaling_factor = CONFIG["BACKTEST_CONFIG"]["STOCK_SCALING_FACTOR"]
        top_n=target_size*scaling_factor
        
        top_20_symbols = filtered_df.head(target_size)['Symbol'].tolist()
        top_40_symbols = filtered_df.head(target_size*scaling_factor)['Symbol'].tolist()
        
        # 4. Apply Backtracking Logic
        rebalance_results = []
        hold_list = []
        
        # Step A: Evaluate current holdings (HOLD if in Top 40, else SELL)
        for symbol in current_holdings:
            stock_row = scores_df[scores_df['Symbol'] == symbol]
            if stock_row.empty:
                action = "SELL (Data Missing/Delisted)"
            elif symbol in top_40_symbols:
                action = "HOLD"
                hold_list.append(symbol)
            else:
                action = "SELL"
            
            if not stock_row.empty:
                res_row = stock_row.iloc[0].to_dict()
                res_row['Action'] = action
                rebalance_results.append(res_row)
            else:
                rebalance_results.append({'Symbol': symbol, 'Action': action})

        # Step B: Fill the gap with BUYS (Check Top 20 only)
        num_needed = max(0, target_size - len(hold_list))
        buy_list = []
        
        if num_needed > 0:
            # Candidates must be in Top 20 and NOT already in our hold_list
            candidates = [s for s in top_20_symbols if s not in hold_list]
            buy_list = candidates[:num_needed]
            
            for symbol in buy_list:
                stock_row = scores_df[scores_df['Symbol'] == symbol].iloc[0].to_dict()
                stock_row['Action'] = "BUY"
                rebalance_results.append(stock_row)

        # 5. Export Report
        report_df = pd.DataFrame(rebalance_results)
        # # Sort for readability: Buys first, then Holds, then Sells
        # action_order = {"BUY": 0, "HOLD": 1, "SELL": 2}
        # report_df['Order'] = report_df['Action'].map(lambda x: action_order.get(x, 3))
        # report_df = report_df.sort_values('Order').drop(columns=['Order'])        

        export_cols_all = [
            'Symbol', 'WMS', 'P_Pct', 'V_Pct', 'WMS_ROC_Raw_Pct', 'RSI_Raw_Pct', 'MFI_Raw_Pct', 'CCI_Raw_Pct', 'RS_Raw_Pct',
            'P_Mom_Raw', 'Value_Raw', 'WMS_ROC_Raw', 'RSI_Raw', 'MFI_Raw', 'CCI_Raw', 'RS_Raw',
            'PassedFilters', 'FilterReason', 'Consistency', 'FilterDetails', 'TotalPassed', 'RecentPassed','Action',
        ]
        
        # Ensure required columns are present and select them in order
        final_cols = [col for col in export_cols_all if col in report_df.columns]
        
        # Sorting for the Excel sheet: BUY -> HOLD -> SELL
        action_order = {"BUY": 1, "HOLD": 2, "SELL": 3, "SELL (Data Missing/Delisted)": 4}
        report_df['ActionSort'] = report_df['Action'].map(action_order)
        report_df = report_df.sort_values(by=['ActionSort', 'WMS', 'P_Pct', 'V_Pct'], ascending=[True, False, False, False])
        
        # Final Cleanup
        report_df = report_df[final_cols].reset_index(drop=True)
        report_df.index = report_df.index + 1
        report_df.index.name = 'Rank'

        # 7. Export
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"Rebalance_history/Rebalance_Action_{timestamp}.xlsx"
        report_df.to_excel(filename, index=False)
        
        print(f"\n--- Rebalance Summary ---")
        print(f"HOLDING (Top 40): {len(hold_list)}")
        print(f"SELLING:          {len([r for r in rebalance_results if 'SELL' in r['Action']])}")
        print(f"NEW BUYS:         {len(buy_list)}")
        print(f"Final Count:      {len(hold_list) + len(buy_list)}")
        print(f"Report saved to:  {filename}")

    except Exception as e:
        print(f"Error during rebalance: {e}")
        
def main_menu():
    """Main application menu."""
    global current_config_file
    load_config()
    
    # Check if 'VERSION' exists in config, if not, use a default fallback
    version_str = CONFIG.get('VERSION', 'Unknown Version') 

    while True:
        print("\n" + "="*70)
        print(f"Momentum Portfolio System ({version_str}) - Main Menu")
        print("="*70)
        print("[1]. Run Quick Backtest wuth various configuration for comparision")
        print("[2]. Run Full Backtest (Custom Config)")
        print("[3]. Get Today's Top Recommendations (Filtered & Ranked, exports top N)")
        print("[4]. Export Full Universe Scores (All Symbols, All Scores)")
        print("[5]. SCORE CUSTOM UNIVERSE from Excel")
        #print("[5]. Add New Index Category")
        print("[6]. Edit Configuration Settings")
        print("-" * 70)
        print("[7]. Load Configuration File")
        print("[8]. Save Current Configuration")
        print("[9]. Force Initial Data Pre-cache / Update All")
        print("[10]. Clear Cache & Reset Data")
        print(f"[11]. Toggle Debug Mode (Current: {CONFIG['SYSTEM_CONFIG']['DEBUG_MODE']})")
        print("[12] Portfolio Rebalance Assistant (Compare with Last Run)")
        print("[0]. Exit")
        print("-" * 70)
        
        c = input("Enter choice: ").strip()

        if c == '1':
            run_quick_backtest_interactively_with_default_config()
        elif c == '2':
            run_full_backtest_interactive()
        elif c == '3':
            top_n = CONFIG.get("BACKTEST_CONFIG", {}).get("TOP_N", 10)
            get_momentum_recommendations_interactive(top_n * 2)
        
        elif c == '4':
            if not GLOBAL_STOCK_DATA:
                print("Initial stock price data download failed. Cannot run recommendations. Run Option [9] first.")
            # 1. Ask the user to select an index category
            # category_name = select_category_interactively("Select category to export ALL scores for: ")
            # if category_name:
                # export_full_universe_scores(category_name)
                
            categories = list(CONFIG["DATA_CONFIG"]["SYMBOL_FILE_MAP"].keys())
            #print(f"categories : {categories} ")
            for category_name in categories:
                export_full_universe_scores(category_name)
            
        elif c == '5':
            score_custom_universe_from_excel() 
            #add_new_category_to_config()
        elif c == '6':
            edit_config_menu()
                
        elif c == '7':
            new_file = input(f"Enter file name to LOAD (current: {current_config_file}): ").strip()
            if new_file:
                load_config(new_file)
            else:
                print("Load cancelled.")
                
        elif c == '8':
            new_file = input(f"Enter file name to SAVE CURRENT config as (current: {current_config_file}): ").strip()
            if new_file:
                save_config(new_file, get_current_global_config_data())
                current_config_file = new_file 
            else:
                print("Save cancelled.")
                
        elif c == '9':
            initial_data_precache()
                
        elif c == '10':
            if os.path.exists(CACHE_DIR):
                try:
                    shutil.rmtree(CACHE_DIR)
                    CACHE_DIR.mkdir(exist_ok=True) 
                    GLOBAL_STOCK_DATA.clear()
                    GLOBAL_BENCHMARK_DATA.clear()
                    # Also clear the new fundamental data cache
                    GLOBAL_FUNDAMENTAL_DATA.clear()
                    print("Cache cleared and in-memory data reset.")
                    # --- NEW LOGIC: Ask for years and update config ---
                    try:
                        current_years = CONFIG["DATA_CONFIG"].get("DOWNLOAD_HISTORY_YEARS", 5)
                        years = input(f"Enter number of years to download for subsequent runs (current: {current_years}, press Enter to keep): ").strip()
                        if years:
                            years_int = int(years)
                            if years_int > 0:
                                CONFIG["DATA_CONFIG"]["DOWNLOAD_HISTORY_YEARS"] = years_int
                                save_config(current_config_file, CONFIG) 
                                print(f"Set DOWNLOAD_HISTORY_YEARS to {years_int}.")                                
                            else:
                                print(f"Invalid number of years. Keeping previous setting ({current_years}).")
                            if(years_int > current_years):
                                print(f"Downloading Data :  [ Requested Cache : {years_int} years ] > [Cache history {current_years} years].")
                                initial_data_precache() 
                            
                        else:
                            print(f"Keeping current DOWNLOAD_HISTORY_YEARS setting ({current_years}).")
                        
                        
                    except ValueError:
                        print("Invalid input. Keeping previous setting.")
                    # --- END NEW LOGIC ---
                except Exception as e:
                    print(f"Error clearing cache: {e}")
            else:
                print("Cache directory not found. Creating it.")
                CACHE_DIR.mkdir(exist_ok=True)
                
        elif c == '11': # New Debug Option
            toggle_debug_mode()
            
        elif c == '12': # New Debug Option
            generate_rebalance_recommendations()
                
        elif c == '0': break
        else:
            print("Invalid choice. Please try again.")


if __name__ == "__main__":
    main_menu()
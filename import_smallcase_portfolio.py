import os
import sys
import csv
import sqlite3
import django

# Set up Django environment
sys.path.append(r'c:\Users\gopal\GOPAL-SHARE\Stock-market-Project\Momentum-Tracker')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'momentum_project.settings')
django.setup()

from core.db_config import DBConfig
from core import get_db

db = get_db()
user_id = 3

print("Using database type:", DBConfig.DB_TYPE)

# Read open and closed files
open_positions_file = 'open_positions_simulation.csv'
closed_trades_file = 'closed_trades_simulation.csv'

if not os.path.exists(open_positions_file) or not os.path.exists(closed_trades_file):
    print("Error: simulation CSV files not found. Run generate_review_files.py first.")
    sys.exit(1)

# Establish connection based on DB_TYPE
if DBConfig.DB_TYPE == 'postgresql':
    import psycopg2
    conn = psycopg2.connect(**DBConfig.pg_connect_kwargs())
    # PostgreSQL uses %s placeholders
    param_style = '%s'
else:
    # default to sqlite
    conn = sqlite3.connect(DBConfig.SQLITE_PATH)
    # SQLite uses ? placeholders
    param_style = '?'

cursor = conn.cursor()

try:
    print(f"\nCleaning up existing data for User ID {user_id}...")
    
    # Delete from portfolio
    q_del_portfolio = f"DELETE FROM portfolio WHERE user_id = {param_style}"
    cursor.execute(q_del_portfolio, (user_id,))
    print(f"Deleted portfolio rows: {cursor.rowcount}")
    
    # Delete from performance
    q_del_perf = f"DELETE FROM performance WHERE user_id = {param_style}"
    cursor.execute(q_del_perf, (user_id,))
    print(f"Deleted performance rows: {cursor.rowcount}")
    
    # Delete from alerts
    q_del_alerts = f"DELETE FROM alerts WHERE user_id = {param_style}"
    cursor.execute(q_del_alerts, (user_id,))
    print(f"Deleted alerts rows: {cursor.rowcount}")
    
    print("\nInserting open positions...")
    open_count = 0
    with open(open_positions_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbol = row['Symbol']
            buy_price = float(row['Buy Price'])
            qty = int(row['Qty'])
            added_at = row['Added At']
            
            q_ins_portfolio = f"INSERT INTO portfolio (user_id, symbol, buy_price, qty, added_at, status) VALUES ({param_style}, {param_style}, {param_style}, {param_style}, {param_style}, 'OPEN')"
            cursor.execute(q_ins_portfolio, (user_id, symbol, buy_price, qty, added_at))
            open_count += 1
            
    print(f"Inserted {open_count} open positions.")
    
    print("\nInserting closed trades...")
    closed_count = 0
    closed_tickers = set()
    latest_closed = {}
    
    with open(closed_trades_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbol = row['Symbol']
            buy_price = float(row['Buy Price'])
            sell_price = float(row['Sell Price'])
            qty = int(row['Qty'])
            pnl = float(row['PnL'])
            pnl_pct = float(row['PnL Pct'])
            hold_days = int(row['Hold Days'])
            opened_at = row['Opened At']
            closed_at = row['Closed At']
            exit_reason = row['Exit Reason']
            
            q_ins_perf = (
                f"INSERT INTO performance (user_id, symbol, buy_price, sell_price, qty, pnl, pnl_pct, hold_days, opened_at, closed_at, exit_reason) "
                f"VALUES ({param_style}, {param_style}, {param_style}, {param_style}, {param_style}, {param_style}, {param_style}, {param_style}, {param_style}, {param_style}, {param_style})"
            )
            cursor.execute(q_ins_perf, (user_id, symbol, buy_price, sell_price, qty, pnl, pnl_pct, hold_days, opened_at, closed_at, exit_reason))
            closed_count += 1
            closed_tickers.add(symbol)
            
            # Keep track of the latest closed trade details for the portfolio table placeholder
            latest_closed[symbol] = {
                'price': sell_price,
                'closed_at': closed_at
            }
            
    print(f"Inserted {closed_count} closed trades.")
    
    print("\nInserting closed placeholders in portfolio table...")
    placeholder_count = 0
    
    # Read open tickers to avoid overwriting currently open positions
    open_tickers = set()
    with open(open_positions_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            open_tickers.add(row['Symbol'])
            
    for symbol in closed_tickers:
        if symbol not in open_tickers:
            info = latest_closed[symbol]
            q_ins_closed_portfolio = (
                f"INSERT INTO portfolio (user_id, symbol, buy_price, qty, added_at, status) "
                f"VALUES ({param_style}, {param_style}, {param_style}, 0, {param_style}, 'CLOSED') "
                f"ON CONFLICT(user_id, symbol) DO UPDATE SET status = 'CLOSED', qty = 0"
            )
            cursor.execute(q_ins_closed_portfolio, (user_id, symbol, info['price'], info['closed_at']))
            placeholder_count += 1
            
    print(f"Inserted/updated {placeholder_count} closed position placeholders in portfolio.")
    
    conn.commit()
    print("\nIMPORT COMPLETED SUCCESSFULLY!")
    
except Exception as e:
    conn.rollback()
    print("\nError during import, rolling back changes:", e)
    raise e
finally:
    conn.close()

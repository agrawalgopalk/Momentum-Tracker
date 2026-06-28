from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional
import pandas as pd
import numpy as np

from utils import normalize_symbol


class PortfolioService:
    """
    Unified domain service for portfolio management.
    Acts as the single source of truth for portfolio modifications and calculations.
    """

    def __init__(self, db_interface, db_manager=None) -> None:
        self.db = db_interface
        self.dm = db_manager

    def get_holdings(self, user_id: int = 3) -> Dict[str, Dict[str, Any]]:
        """
        Load open positions for user and format as legacy JSON dict structure:
        {symbol: {"shares": int, "avg_cost": float, "date_added": str}}
        This preserves compatibility with existing CLI strategy and report modules.
        """
        held = self.db.held_positions(user_id=user_id)
        holdings = {}
        for pos in held:
            holdings[pos["symbol"]] = {
                "shares": pos["qty"],
                "avg_cost": pos["buy_price"],
                "date_added": pos["added_at"][:10] if pos.get("added_at") else datetime.now().strftime("%Y-%m-%d")
            }
        return holdings

    def add_holding(
        self, symbol: str, shares: int, avg_cost: float, date_added: Optional[str] = None, user_id: int = 3
    ) -> None:
        """Add or update an open position for a user."""
        normalized_sym = normalize_symbol(symbol)
        if not normalized_sym:
            raise ValueError("Symbol cannot be empty.")
            
        added_at = date_added or datetime.now().strftime("%Y-%m-%d")
        if "T" not in added_at:
            added_at = f"{added_at}T10:00:00"

        # Direct database write via abstraction
        self.db.add_position(normalized_sym, avg_cost, shares, user_id=user_id, added_at=added_at)

    def remove_holding(self, symbol: str, sell_price: float = 0.0, user_id: int = 3) -> None:
        """Close an open position for a user."""
        normalized_sym = normalize_symbol(symbol)
        if not normalized_sym:
            raise ValueError("Symbol cannot be empty.")
            
        self.db.close_position(normalized_sym, sell_price, exit_reason="MANUAL", user_id=user_id)

    def get_portfolio_valuation(self, user_id: int = 3) -> pd.DataFrame:
        """
        Calculate current market valuation, unrealized P&L, and returns across holdings.
        """
        held = self.db.held_positions(user_id=user_id)
        rows = []
        for pos in held:
            symbol = pos["symbol"]
            current_price = np.nan
            
            # Fetch price from DatabaseManager cache if available
            if self.dm:
                df = self.dm.get_price(symbol)
                if df is not None and not df.empty:
                    current_price = float(df["close"].iloc[-1])

            shares = pos["qty"]
            avg_cost = pos["buy_price"]
            
            # Calculations
            mkt_value = shares * current_price if not np.isnan(current_price) else np.nan
            pnl = mkt_value - (shares * avg_cost) if not np.isnan(mkt_value) else np.nan
            pnl_pct = (pnl / (shares * avg_cost) * 100) if (avg_cost > 0 and not np.isnan(pnl)) else np.nan

            rows.append({
                "Symbol": symbol,
                "Shares": shares,
                "Avg_Cost": round(avg_cost, 2),
                "Current_Price": round(current_price, 2) if not np.isnan(current_price) else None,
                "Market_Value": round(mkt_value, 2) if not np.isnan(mkt_value) else None,
                "Unrealised_PnL": round(pnl, 2) if not np.isnan(pnl) else None,
                "PnL_%": round(pnl_pct, 2) if not np.isnan(pnl_pct) else None,
            })

        df_out = pd.DataFrame(rows)
        return df_out

    def upload_transactions(
        self,
        file_path_or_buf: Any,
        file_type: str = "csv",
        user_id: int = 3
    ) -> Dict[str, Any]:
        """
        Parse and execute transactions from a CSV or Excel file.
        Expects columns: Date,Batch Type,Symbol,Price,Qty,Action
        Supports auto-detection of single-column SmallCase Excel formats.
        """
        # Read the file
        if file_type == "csv":
            df = pd.read_csv(file_path_or_buf)
        else:
            df = pd.read_excel(file_path_or_buf)

        # Detect if it's a SmallCase single-column layout
        is_smallcase = False
        if df.shape[1] == 1:
            col_name = str(df.columns[0])
            if any(term in col_name for term in ["Batch", "Placed on", "Status", "Filled"]):
                is_smallcase = True

        if is_smallcase:
            vals = df.iloc[:, 0].tolist()
            # Clean values of non-breaking spaces and whitespace
            cleaned_vals = [v.replace('\xa0', ' ').strip() if isinstance(v, str) else v for v in vals]
            
            # Find the header element 'Stock' in the first few elements to start block parsing
            header_idx = -1
            for i, val in enumerate(cleaned_vals[:15]):
                if isinstance(val, str) and val.lower() == 'stock':
                    header_idx = i
                    break
                    
            start_idx = header_idx + 5 if header_idx != -1 else 5
            
            txs = []
            for i in range(start_idx, len(cleaned_vals) - 1, 4):
                if i + 3 >= len(cleaned_vals):
                    break
                stock = cleaned_vals[i]
                price_val = cleaned_vals[i+1]
                qty_val = cleaned_vals[i+2]
                order_type = cleaned_vals[i+3]
                
                # Basic validation to filter footer text or invalid rows
                if not isinstance(stock, str) or not isinstance(price_val, (int, float)):
                    continue
                if not isinstance(order_type, str) or order_type.upper() not in ('BUY', 'SELL'):
                    continue
                    
                try:
                    qty_str = str(qty_val)
                    if '/' in qty_str:
                        qty = int(qty_str.split('/')[0].strip())
                    else:
                        qty = int(float(qty_str))
                except Exception:
                    continue
                    
                txs.append({
                    'Symbol': stock.upper(),
                    'Price': float(price_val),
                    'Qty': qty,
                    'Action': order_type.upper()
                })
            # Convert to standard layout
            df = pd.DataFrame(txs)
        else:
            # Clean column names for standard format
            df.columns = [c.strip() for c in df.columns]
        
        # Verify required columns
        required = {"Symbol", "Price", "Qty", "Action"}
        if not required.issubset(df.columns):
            missing = required - set(df.columns)
            raise ValueError(f"Missing required columns in transaction report: {missing}")
            
        # Sort by Date if present, so we apply them chronologically
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"])
            df = df.sort_values("Date").reset_index(drop=True)
            
        success_count = 0
        skipped_count = 0
        details = []
        
        for idx, row in df.iterrows():
            symbol = str(row["Symbol"]).strip().upper()
            price = float(row["Price"])
            qty = int(row["Qty"])
            action = str(row["Action"]).strip().upper()
            date_str = str(row["Date"])[:10] if "Date" in row and pd.notna(row["Date"]) else None
            
            # Normalize symbol
            normalized_sym = normalize_symbol(symbol)
            if not normalized_sym:
                continue
                
            # Get current holdings to manage weighted averages or partial sells
            holdings = self.get_holdings(user_id=user_id)
            
            if action == "BUY":
                if normalized_sym in holdings:
                    # Incremental buy
                    current_qty = holdings[normalized_sym]["shares"]
                    current_cost = holdings[normalized_sym]["avg_cost"]
                    new_qty = current_qty + qty
                    new_cost = ((current_qty * current_cost) + (qty * price)) / new_qty
                    self.add_holding(normalized_sym, new_qty, new_cost, date_added=date_str, user_id=user_id)
                    details.append(f"Incremented {normalized_sym}: new qty {new_qty}, new avg_cost {new_cost:.2f}")
                else:
                    # Fresh buy
                    self.add_holding(normalized_sym, qty, price, date_added=date_str, user_id=user_id)
                    details.append(f"Bought new position {normalized_sym}: {qty} shares @ {price:.2f}")
                success_count += 1
            elif action == "SELL":
                if normalized_sym in holdings:
                    current_qty = holdings[normalized_sym]["shares"]
                    if qty >= current_qty:
                        # Full sell
                        self.remove_holding(normalized_sym, sell_price=price, user_id=user_id)
                        details.append(f"Closed position {normalized_sym}: sold {qty} shares @ {price:.2f}")
                    else:
                        # Partial sell
                        current_cost = holdings[normalized_sym]["avg_cost"]
                        # Write closed trade to performance
                        self.db.add_closed_performance_record(
                            symbol=normalized_sym,
                            buy_price=current_cost,
                            sell_price=price,
                            qty=qty,
                            opened_at=holdings[normalized_sym]["date_added"],
                            user_id=user_id
                        )
                        # Update remaining holding
                        remaining_qty = current_qty - qty
                        self.add_holding(normalized_sym, remaining_qty, current_cost, date_added=holdings[normalized_sym]["date_added"], user_id=user_id)
                        details.append(f"Partially sold {normalized_sym}: remaining qty {remaining_qty}")
                    success_count += 1
                else:
                    skipped_count += 1
                    details.append(f"Skipped SELL for {normalized_sym} (not in holdings)")
            else:
                skipped_count += 1
                details.append(f"Skipped unknown action '{action}' for {normalized_sym}")
                
        return {
            "success_count": success_count,
            "skipped_count": skipped_count,
            "details": details
        }


"""
institutional_flow_tool.py – CrewAI tool that checks FII/DII institutional flows from the local database.
Integrates live stock-level and sector-level fetchers from momentum_tracker/src/fii_dii_provider.py.
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field
import pandas as pd

_root = Path(__file__).resolve().parent.parent   # Momentum-Tracker/

class InstitutionalFlowInput(BaseModel):
    ticker: str = Field(
        default="", 
        description="Optional stock ticker (e.g. 'INFY') to query. If empty, checks for sector instead."
    )
    sector: str = Field(
        default="",
        description="Optional sector name (e.g. 'IT', 'BANK', 'AUTO') to check average sector holdings."
    )

class InstitutionalFlowTool(BaseTool):
    name: str = "Institutional Flow Tool"
    description: str = (
        "Queries FII/DII institutional flows. "
        "If a ticker is provided, returns stock holdings and FII/DII percentages. "
        "If a sector is provided, returns average sector holdings and top stocks. "
        "If both are empty, returns the latest daily market-wide aggregate flows."
    )
    args_schema: Type[BaseModel] = InstitutionalFlowInput

    def _run(self, ticker: str = "", sector: str = "") -> str:
        ticker = ticker.strip().upper()
        sector = sector.strip().upper()

        try:
            # Setup path so we can import fii_dii_provider from momentum_tracker/src/
            import sys
            _src = _root / "momentum_tracker" / "src"
            if str(_src) not in sys.path:
                sys.path.insert(0, str(_src))
                
            from data import fii_dii_provider

            report_parts = []

            # 1. Check latest aggregate provisional flows
            agg_df = fii_dii_provider.query_aggregate("daily")
            if not agg_df.empty:
                report_parts.append(
                    "=== LATEST MARKET-WIDE PROVISIONAL FII/DII FLOWS (₹ Crores) ===\n"
                    + agg_df.head(4).to_string(index=False)
                    + "\n============================================================\n"
                )
            else:
                report_parts.append("No market-wide provisional FII/DII flows found in the database.\n")

            # 2. Check stock level flows
            if ticker:
                # Remove suffix like .NS if present
                clean_ticker = ticker.split(".")[0]
                stock_data = fii_dii_provider.get_stock_fii_dii(clean_ticker)
                
                stock_report = (
                    f"\n=== STOCK LEVEL INSTITUTIONAL DETAILS: {clean_ticker} ===\n"
                    f"Quarter Analyzed: {stock_data.get('quarter', 'N/A')}\n"
                    f"Promoter Holding: {stock_data.get('promoter', 0.0):.2f}%\n"
                    f"FII/FPI Holding:  {stock_data.get('fii', 0.0):.2f}%\n"
                    f"DII Holding:      {stock_data.get('dii', 0.0):.2f}%\n"
                    f"Public/Others:    {stock_data.get('public', 0.0):.2f}%\n"
                    "-------------------------------------------------\n"
                )
                report_parts.append(stock_report)

            # 3. Check sector level flows
            if sector:
                sector_data = fii_dii_provider.get_sector_fii_dii(sector)
                
                if "error" in sector_data:
                    report_parts.append(f"\nSector Query Error: {sector_data['error']}\n")
                else:
                    top_holdings_str = ""
                    for rank, hold in enumerate(sector_data.get("top_fii_holdings", []), 1):
                        top_holdings_str += f"  {rank}. {hold['symbol']} (FII: {hold['fii']:.2f}%, DII: {hold['dii']:.2f}%, Q: {hold['quarter']})\n"
                        
                    sector_report = (
                        f"\n=== SECTOR LEVEL INSTITUTIONAL DETAILS: {sector_data.get('sector', sector)} ===\n"
                        f"Constituents Analyzed:    {sector_data.get('constituents_analyzed', 0)}\n"
                        f"Average Promoter Holding: {sector_data.get('average_promoter_pct', 0.0):.2f}%\n"
                        f"Average FII/FPI Holding:  {sector_data.get('average_fii_pct', 0.0):.2f}%\n"
                        f"Average DII Holding:      {sector_data.get('average_dii_pct', 0.0):.2f}%\n"
                        f"Top FII/FPI Holdings in Sector:\n{top_holdings_str}"
                        "------------------------------------------------------\n"
                    )
                    report_parts.append(sector_report)

            return "".join(report_parts)

        except Exception as exc:
            return f"Error executing Institutional Flow Tool: {exc}\n{traceback.format_exc()}"

"""
dashboard.py  –  Streamlit dashboard for the Momentum Portfolio System.

Run with:
  streamlit run dashboard.py

Pages
─────
  Overview   – open positions + latest alert status at a glance
  - Overview is the one you'll look at every morning. 
  It shows your open positions in cards, with the latest alert badge (RED/YELLOW/GREEN) prominently displayed. 
  RED positions expand automatically so you can't miss them. 
  Each position card also shows the last 5 analyst calls for that stock 
  — so you can see if it's been consistently BUY or if the conviction has been drifting.
  
  Scan history – ranked WMS tables from past runs with analyst picks
  - Scan history shows the latest WMS ranked table with the analyst classification overlaid as a colour-coded column. 
  The bar chart makes sector concentration immediately visible — if 8 of 20 bars are the same colour cluster, 
  that's a risk you need to see visually, not read in a wall of text.
  
  Alerts     – full alert log, filterable by level / ticker
  - Alert log is your audit trail. Every RED/YELLOW/GREEN ever generated, filterable by ticker or level.
  This is how you catch the pattern of "ADANIENT has had 3 YELLOWs in 10 days" — a slow deterioration that no single alert would tell you about.
  
  Performance – closed-trade P&L stats and win-rate by classification
  - Performance is the most important page for improving your decision-making over time.
  The "win rate by classification" table tells you something brutally honest 
  — if your BUY calls have a 40% win rate and your HOLD calls have a 55% win rate, 
  your classifier is miscalibrated and the LLM prompts need adjustment. 
  You cannot see this without the closed-trade P&L data that persistence.py is collecting.  

Install:
  pip install streamlit plotly
"""

import json
from datetime import datetime

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from persistence import DB

import logging
from pathlib import Path

# _LOG_FILE = Path(__file__).parent / "momentum_tracker" / "mps_cache" / "dashboard.log"
# _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s  %(levelname)-8s  %(message)s",
#     datefmt="%Y-%m-%d %H:%M:%S",
#     handlers=[
#         logging.FileHandler(_LOG_FILE, encoding="utf-8"),   # saves to file
#         # logging.StreamHandler(),                             # also prints to terminal
#         logging.StreamHandler(open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False)),
#     ],
# )
# dash_log = logging.getLogger("dashboard")
from logger import get_logger, get_log_file
dash_log = get_logger("dashboard")

# ─────────────────────────────────────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Momentum Portfolio System",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Constants — single source of truth for categories (mirrors config.py INDICES)
# ─────────────────────────────────────────────────────────────────────────────

_ALL_SCAN_CATEGORIES = [
    "Nifty50", "Nifty100", "Midcap150", "Smallcap250",
    "NiftyLargeMidcap250", "NiftyNext50", "Nifty500", "NiftyMicrocap250",
]
_REPORT_CATEGORIES = _ALL_SCAN_CATEGORIES + ["Monitor"]

# ─────────────────────────────────────────────────────────────────────────────
# Sidebar navigation
# ─────────────────────────────────────────────────────────────────────────────

st.sidebar.title("Momentum Portfolio")
page = st.sidebar.radio(
    "Navigate",
    ["Portfolio Overview", "Add/Remove Stocks", "Run Momentum Scan", "Scan history", "Scan reports", "Alert log", "Performance", "Settings"],
    index=0,
)

st.sidebar.divider()
st.sidebar.subheader("Quick actions")

# Category picker for the sidebar quick-scan
_sidebar_category = st.sidebar.selectbox(
    "Scan category",
    _ALL_SCAN_CATEGORIES,
    index=_ALL_SCAN_CATEGORIES.index("Nifty100"),
    key="sidebar_scan_category",
)

if st.sidebar.button("▶ Run momentum scan", use_container_width=True):
    with st.spinner(f"Scanning {_sidebar_category} — 3–10 mins..."):
        try:
            dash_log.info("Dashboard triggered: momentum scan [%s]", _sidebar_category)
            from scheduler import job_scan_and_classify
            job_scan_and_classify(category=_sidebar_category)
            dash_log.info("Dashboard scan completed [%s]", _sidebar_category)
            st.sidebar.success(f"✅ {_sidebar_category} scan done")
        except Exception as e:
            dash_log.exception("Dashboard scan failed: %s", e)
            st.sidebar.error(f"Scan failed: {e}")

# CHANGE the monitor button block
if st.sidebar.button("Run portfolio monitor now"):
    with st.spinner("Scanning your positions for alerts..."):
        try:
            dash_log.info("Dashboard triggered: portfolio monitor")
            from scheduler import job_monitor
            job_monitor()
            dash_log.info("Dashboard monitor completed successfully")
            st.sidebar.success("Monitor complete — check Alert log")
        except Exception as e:
            dash_log.exception("Dashboard monitor failed: %s", e)
            st.sidebar.error(f"Monitor failed: {e}")            
# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

ALERT_COLORS = {"RED": "🔴", "YELLOW": "🟡", "GREEN": "🟢"}
PICK_COLORS  = {"BUY": "🟢", "HOLD": "🟡", "AVOID": "🔴"}


def _alert_badge(level: str) -> str:
    return f"{ALERT_COLORS.get(level, '⚪')} {level}"


def _pick_badge(cls: str) -> str:
    return f"{PICK_COLORS.get(cls, '⚪')} {cls}"


# ─────────────────────────────────────────────────────────────────────────────
# Page: Overview
# ─────────────────────────────────────────────────────────────────────────────

if page == "Portfolio Overview":
    st.title("Portfolio overview")
    
    # --- ADD THIS BLOCK ---
    with st.expander("Controls"):
        if st.button("Run portfolio monitor now", type="primary"):
            with st.spinner("Monitoring your positions..."):
                from scheduler import job_monitor
                job_monitor()
                st.success("Monitor run complete!")
                st.rerun()  # Refresh the dashboard to display new alerts
    # ----------------------

    held   = DB.held_positions()
    alerts = DB.alert_history(n=200)
    alert_map = {}   # symbol → latest alert level
    for a in alerts:
        if a["symbol"] not in alert_map:
            alert_map[a["symbol"]] = a["alert_level"]

    if not held:
        st.info("No open positions. Add one in the sidebar.")
    else:
        # Summary KPIs
        red_count    = sum(1 for h in held if alert_map.get(h["symbol"]) == "RED")
        yellow_count = sum(1 for h in held if alert_map.get(h["symbol"]) == "YELLOW")
        green_count  = sum(1 for h in held if alert_map.get(h["symbol"]) == "GREEN")

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Open positions", len(held))
        k2.metric("🔴 RED alerts",    red_count)
        k3.metric("🟡 YELLOW alerts", yellow_count)
        k4.metric("🟢 GREEN",         green_count)

        st.divider()
        st.subheader("Positions")

        for pos in held:
            sym   = pos["symbol"]
            level = alert_map.get(sym, "–")
            badge = _alert_badge(level) if level != "–" else "⚪ No alert yet"

            with st.expander(f"{sym}  ·  {badge}", expanded=(level == "RED")):
                c1, c2, c3 = st.columns(3)
                c1.metric("Buy price", f"₹{pos['buy_price']:.2f}")
                c2.metric("Qty", pos["qty"])
                c3.metric("Added", pos["added_at"][:10])

                # Latest picks history
                picks = DB.recent_picks(sym, n=5)
                if picks:
                    st.caption("Last 5 analyst calls")
                    for p in picks:
                        st.write(
                            f"**{p['picked_at'][:10]}**  "
                            f"{_pick_badge(p['classification'])}  "
                            f"Conf {p['confidence']}/5  ·  {p['rationale'] or '–'}"
                        )
                # ADD THIS BLOCK — full analyst report for this stock
                st.divider()
                st.caption("Latest analyst report")
                analyst_report = DB.get_stock_analyst_report(sym)
                if analyst_report:
                    # Parse into labelled fields for clean display
                    field_colors = {
                        "CLASSIFICATION": {"BUY": "green", "HOLD": "orange", "AVOID": "red"},
                    }
                    for line in analyst_report.splitlines():
                        if not line.strip():
                            continue
                        if ":" in line:
                            label, _, value = line.partition(":")
                            label = label.strip()
                            value = value.strip()
                            if label == "CLASSIFICATION":
                                color = field_colors["CLASSIFICATION"].get(value, "gray")
                                st.markdown(f"**{label}:** :{color}[**{value}**]")
                            elif label == "SYMBOL":
                                pass   # already shown in expander header
                            elif label in ("CONFIDENCE", "MOMENTUM QUALITY",
                                        "RISK FLAGS", "ONE-LINE RATIONALE"):
                                st.markdown(f"**{label}:** {value}")
                            else:
                                # Multi-line fields — show as caption
                                st.markdown(f"**{label}:**")
                                st.caption(value)
                        else:
                            st.caption(line)
                else:
                    st.caption("No analyst report found — run a scan first.")
                    
                # ADD after the analyst report block
                st.divider()
                st.caption("Latest monitor alert")
                monitor_report = DB.get_stock_monitor_report(sym)
                if monitor_report:
                    for line in monitor_report.splitlines():
                        line = line.strip()
                        if not line or line.startswith("═"):
                            continue
                        if line.startswith("ALERT"):
                            level_val = line.split(":", 1)[1].strip()
                            if "RED"    in level_val: st.error(f"🔴 {level_val}")
                            elif "YELLOW" in level_val: st.warning(f"🟡 {level_val}")
                            elif "GREEN"  in level_val: st.success(f"🟢 {level_val}")
                        elif line.startswith("TRIGGER SUMMARY"):
                            st.markdown(f"**Trigger:**")
                        elif line.startswith("RECOMMENDED ACTION"):
                            st.markdown(f"**Action:**")
                        elif line.startswith("NEWS STORIES"):
                            st.markdown(f"**News considered:**")
                        elif line.startswith("RISK FLAGS"):
                            val = line.split(":", 1)[1].strip()
                            st.markdown(f"**Risk flags:** {val}")
                        elif line.startswith("CONFIDENCE"):
                            val = line.split(":", 1)[1].strip()
                            st.markdown(f"**Confidence:** {val}")
                        elif line.startswith("TICKER") or line.startswith("═"):
                            pass
                        else:
                            st.caption(line)
                else:
                    st.caption("No monitor report yet — run portfolio monitor first.")
                    
                st.divider()
                # Close button
                sell_col, btn_col = st.columns([3, 1])
                sell_price = sell_col.number_input(
                    "Sell price (₹)", min_value=0.01, step=0.5,
                    key=f"sell_{sym}"
                )
                if btn_col.button("Close position", key=f"btn_{sym}"):
                    try:
                        DB.close_position(sym, sell_price, exit_reason="MANUAL")
                        st.success(f"Closed {sym}")
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))

# ─────────────────────────────────────────────────────────────────────────────
# Page: Portfolio  (add / close / review positions)
# ─────────────────────────────────────────────────────────────────────────────
 
elif page == "Add/Remove Stocks":
    import pandas as pd
    st.title("Execute Trades")
 
    # ── Add new position ──────────────────────────────────────────────────────
    st.subheader("➕ Add position")
    with st.form("add_position_form", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
        new_ticker     = c1.text_input("Ticker", placeholder="e.g. RELIANCE.NS")
        new_buy_price  = c2.number_input("Buy price (₹)", min_value=0.01, step=0.5)
        new_qty        = c3.number_input("Qty", min_value=1, step=1)
        new_trade_date = c4.date_input("Trade date", value=datetime.now().date())
        add_submitted  = st.form_submit_button("Add position", type="primary", use_container_width=True)
 
    if add_submitted:
        if not new_ticker.strip():
            st.error("Ticker cannot be empty.")
        else:
            DB.add_position(new_ticker.upper().strip(), new_buy_price, int(new_qty))
            st.success(f"✅ Added **{new_ticker.upper().strip()}** — {int(new_qty)} shares @ ₹{new_buy_price:.2f} on {new_trade_date}")
            st.rerun()
 
    st.divider()
 
    # ── Open positions table ──────────────────────────────────────────────────
    st.subheader("📂 Open positions")
    held = DB.held_positions()
 
    if not held:
        st.info("No open positions yet. Add one above.")
    else:
        # Fetch latest alert level per symbol for quick status view
        alert_map = {}
        for a in DB.alert_history(n=500):
            if a["symbol"] not in alert_map:
                alert_map[a["symbol"]] = a["alert_level"]
 
        df_held = pd.DataFrame(held)
        df_held["alert"] = df_held["symbol"].map(lambda s: _alert_badge(alert_map.get(s, "–")))
        df_held["added_at"] = df_held["added_at"].str[:10]
 
        st.dataframe(
            df_held[["symbol", "buy_price", "qty", "added_at", "alert"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "symbol":    st.column_config.TextColumn("Symbol",     width=150),
                "buy_price": st.column_config.NumberColumn("Buy price (₹)", format="%.2f", width=130),
                "qty":       st.column_config.NumberColumn("Qty",       width=80),
                "added_at":  st.column_config.TextColumn("Added",      width=110),
                "alert":     st.column_config.TextColumn("Last alert", width=130),
            },
        )
 
        st.divider()
 
        # ── Close a position ──────────────────────────────────────────────────
        st.subheader("❌ Close position")
        symbols = [p["symbol"] for p in held]
 
        with st.form("close_position_form", clear_on_submit=True):
            cl1, cl2, cl3 = st.columns([3, 2, 2])
            close_sym      = cl1.selectbox("Select position to close", symbols)
            close_price    = cl2.number_input("Sell price (₹)", min_value=0.01, step=0.5)
            close_reason   = cl3.selectbox(
                "Exit reason",
                ["MANUAL", "RED_ALERT", "TARGET_HIT", "STOP_LOSS"],
            )
            close_submitted = st.form_submit_button("Close position", type="primary", use_container_width=True)
 
        if close_submitted:
            try:
                # Show P&L preview before closing
                pos = next(p for p in held if p["symbol"] == close_sym)
                pnl     = (close_price - pos["buy_price"]) * pos["qty"]
                pnl_pct = (close_price / pos["buy_price"] - 1) * 100
                DB.close_position(close_sym, close_price, exit_reason=close_reason)
                pnl_color = "🟢" if pnl >= 0 else "🔴"
                st.success(
                    f"{pnl_color} Closed **{close_sym}** @ ₹{close_price:.2f}  ·  "
                    f"P&L: ₹{pnl:,.0f} ({pnl_pct:+.1f}%)  ·  Reason: {close_reason}"
                )
                st.rerun()
            except ValueError as e:
                st.error(str(e))
 
    st.divider()
 
    # ── Closed positions history ──────────────────────────────────────────────
    st.subheader("🗂️ Closed positions history")
    from persistence import _conn
    with _conn() as con:
        closed_rows = con.execute(
            "SELECT symbol, buy_price, sell_price, qty, pnl, pnl_pct, "
            "       hold_days, opened_at, closed_at, pick_classification, exit_reason "
            "FROM performance ORDER BY closed_at DESC"
        ).fetchall()
 
    if not closed_rows:
        st.info("No closed trades yet.")
    else:
        df_closed = pd.DataFrame([dict(r) for r in closed_rows])
        df_closed["opened_at"]  = df_closed["opened_at"].str[:10]
        df_closed["closed_at"]  = df_closed["closed_at"].str[:10]
        df_closed["pnl_pct"]    = df_closed["pnl_pct"].round(2)
        df_closed["pnl"]        = df_closed["pnl"].round(2)
 
        st.dataframe(
            df_closed,
            use_container_width=True,
            hide_index=True,
            column_config={
                "symbol":             st.column_config.TextColumn("Symbol",       width=130),
                "buy_price":          st.column_config.NumberColumn("Buy (₹)",    format="%.2f", width=100),
                "sell_price":         st.column_config.NumberColumn("Sell (₹)",   format="%.2f", width=100),
                "qty":                st.column_config.NumberColumn("Qty",         width=70),
                "pnl":                st.column_config.NumberColumn("P&L (₹)",    format="%.2f", width=110),
                "pnl_pct":            st.column_config.NumberColumn("P&L %",      format="%.2f", width=90),
                "hold_days":          st.column_config.NumberColumn("Days held",   width=90),
                "opened_at":          st.column_config.TextColumn("Opened",        width=100),
                "closed_at":          st.column_config.TextColumn("Closed",        width=100),
                "pick_classification":st.column_config.TextColumn("Pick",          width=80),
                "exit_reason":        st.column_config.TextColumn("Exit reason",   width=110),
            },
        )
 

# ─────────────────────────────────────────────────────────────────────────────
# Page: Run Momentun Scan (Trigger a new scan from the dashboard)
# ─────────────────────────────────────────────────────────────────────────────

# 2. Implement the "Run Momentum Scan" page logic
elif page == "Run Momentum Scan":
    st.title("Run momentum scan")
    
    selected_category = st.selectbox(
        "Select Index Category",
        _ALL_SCAN_CATEGORIES,
        index=_ALL_SCAN_CATEGORIES.index("Nifty100"),
        help="All 8 NSE index universes available. Larger indices (Nifty500, NiftyMicrocap250) take longer.",
    )
    
    if st.button("Start Scan", type="primary"):
        with st.spinner(f"Running scan for {selected_category}... This takes 3-10 minutes. Please wait."):
            try:
                from scheduler import job_scan_and_classify
                job_scan_and_classify(category=selected_category)
                st.success(f"✅ Scan for {selected_category} completed successfully.")
                st.balloons()
            except Exception as e:
                st.error(f"Scan failed: {e}")
                dash_log.exception("Dashboard scan failed: %s", e)
 
# ─────────────────────────────────────────────────────────────────────────────
# Page: Scan history
# ─────────────────────────────────────────────────────────────────────────────

elif page == "Scan history":
    st.title("Scan history")

    category = st.selectbox("Category", _ALL_SCAN_CATEGORIES)

    rows = DB.latest_scan(category)
    if not rows:
        st.info(f"No scan data for {category} yet. Run `python scheduler.py --once` to generate.")
    else:
        st.caption(f"Showing latest scan – {len(rows)} stocks")

        # Colour-code classification column
        import pandas as pd
        df = pd.DataFrame(rows)
        if "classification" in df.columns:
            df["pick"] = df["classification"].apply(
                lambda c: _pick_badge(c) if c else "–"
            )
        # REPLACE the existing st.dataframe call with this
        st.dataframe(
            df[["rank", "symbol", "wms", "rsi", "mfi", "cci", "pick", "confidence"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "rank":       st.column_config.NumberColumn("Rank",           width=40),
                "symbol":     st.column_config.TextColumn("Symbol",           width=140),
                "wms":        st.column_config.NumberColumn("WMS",            width=50,  format="%.2f"),
                "rsi":        st.column_config.NumberColumn("RSI",            width=50,  format="%.1f"),
                "mfi":        st.column_config.NumberColumn("MFI",            width=50,  format="%.1f"),
                "cci":        st.column_config.NumberColumn("CCI",            width=50,  format="%.1f"),
                "pick":       st.column_config.TextColumn("Classification",   width=130),
                "confidence": st.column_config.NumberColumn("Confidence",           width=60),
            }
        )

        # WMS bar chart
        fig = px.bar(
            df, x="symbol", y="wms",
            color="classification",
            color_discrete_map={"BUY": "#3B6D11", "HOLD": "#BA7517", "AVOID": "#A32D2D"},
            title="WMS score by stock",
            labels={"symbol": "Stock", "wms": "WMS score"},
            height=350,
        )
        fig.update_layout(showlegend=True, xaxis_tickangle=-45)
        st.plotly_chart(fig, use_container_width=True)

        if st.button("Export to CSV"):
            path = DB.export_picks_csv()
            st.success(f"Exported to {path}")


# ─────────────────────────────────────────────────────────────────────────────
# Page: Alert log
# ─────────────────────────────────────────────────────────────────────────────

elif page == "Alert log":
    st.title("Alert log")

    col1, col2 = st.columns(2)
    filter_sym   = col1.text_input("Filter by ticker")
    filter_level = col2.selectbox("Filter by level", ["All", "RED", "YELLOW", "GREEN"])

    alerts = DB.alert_history(
        symbol=filter_sym.upper().strip() or None,
        level=filter_level if filter_level != "All" else None,
        n=200,
    )

    if not alerts:
        st.info("No alerts found.")
    else:
        for a in alerts:
            level = a["alert_level"]
            color = {"RED": "red", "YELLOW": "orange", "GREEN": "green"}.get(level, "gray")
            with st.container():
                st.markdown(
                    f":{color}[**{ALERT_COLORS.get(level, '')} {level}**]  "
                    f"**{a['symbol']}**  ·  {a['alerted_at'][:16]}"
                )
                if a.get("trigger"):
                    st.caption(a["trigger"])
                if a.get("action"):
                    st.write(f"Action: {a['action']}")
                st.divider()


# ─────────────────────────────────────────────────────────────────────────────
# Page: Performance
# ─────────────────────────────────────────────────────────────────────────────

elif page == "Performance":
    st.title("Performance tracker")

    summary = DB.performance_summary()

    if not summary:
        st.info("No closed trades yet. Close a position from the Overview page.")
    else:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Total trades",  summary["total_trades"])
        k2.metric("Win rate",      f"{summary['win_rate_pct']}%")
        k3.metric("Total P&L",     f"₹{summary['total_pnl']:,.0f}")
        k4.metric("Avg P&L %",     f"{summary['avg_pnl_pct']:.1f}%")

        st.divider()

        # By classification breakdown
        if summary.get("by_classification"):
            st.subheader("Win rate by analyst classification")
            cls_data = [
                {
                    "Classification": k,
                    "Trades": v["trades"],
                    "Wins":   v["wins"],
                    "Win rate": round(v["wins"] / v["trades"] * 100, 1) if v["trades"] else 0,
                    "Total P&L": round(v["pnl"], 2),
                }
                for k, v in summary["by_classification"].items()
            ]
            import pandas as pd
            st.dataframe(pd.DataFrame(cls_data), use_container_width=True, hide_index=True)

            fig2 = px.bar(
                cls_data, x="Classification", y="Win rate",
                color="Classification",
                color_discrete_map={"BUY": "#3B6D11", "HOLD": "#BA7517",
                                    "AVOID": "#A32D2D", "UNKNOWN": "#888780"},
                title="Win rate by pick classification",
                height=300,
            )
            st.plotly_chart(fig2, use_container_width=True)

        # Best and worst
        col1, col2 = st.columns(2)
        best  = summary.get("best_trade", {})
        worst = summary.get("worst_trade", {})

        if best:
            col1.subheader("Best trade")
            col1.metric(best["symbol"], f"+{best['pnl_pct']:.1f}%",
                        f"₹{best['pnl']:,.0f}")
        if worst:
            col2.subheader("Worst trade")
            col2.metric(worst["symbol"], f"{worst['pnl_pct']:.1f}%",
                        f"₹{worst['pnl']:,.0f}", delta_color="inverse")

        if summary.get("avg_hold_days"):
            st.metric("Avg hold period", f"{summary['avg_hold_days']} days")
            
# ─────────────────────────────────────────────────────────────────────────────
# Page: Scan Reports
# ─────────────────────────────────────────────────────────────────────────────
            
# elif page == "Scan reports":
#     st.title("Scan reports")
#     st.caption("Full analyst output from each run. Delete reports that are identical to the previous run.")

#     category = st.selectbox("Category", ["Nifty50", "Nifty100", "Midcap150", "Smallcap250", "Nifty500", "Monitor"])
#     n        = st.slider("Show last N reports", min_value=3, max_value=20, value=10)

#     reports = DB.get_scan_reports(category=category, n=n)
#     if not reports:
#         st.info("No reports saved yet. Run a scan first.")
#     else:
#         for r in reports:
#             col1, col2 = st.columns([5, 1])
#             with col1:
#                 with st.expander(f"Report {r['id']}  ·  {r['created_at'][:16]}  ·  run_id={r['run_id']}"):
#                     detail = DB.get_scan_report_detail(r["id"])
#                     if detail:
#                         if detail["category"] == "Monitor":
#                             st.text(detail["analyst_raw"])
#                         else:
#                             tab1, tab2 = st.tabs(["Analyst output", "WMS table"])
#                             with tab1:
#                                 st.text(detail["analyst_raw"])
#                             with tab2:
#                                 st.text(detail["scout_raw"])                            
#             with col2:
#                 st.write("")   # vertical spacing
#                 if st.button("Delete", key=f"del_{r['id']}"):
#                     DB.delete_scan_report(r["id"])
#                     st.success(f"Deleted report {r['id']}")
#                     st.rerun()     


elif page == "Scan reports":
    st.title("Scan reports")
    
    # 1. Selection Filters
    category = st.selectbox("Category", _REPORT_CATEGORIES)
    n = st.slider("Show last N reports", min_value=3, max_value=20, value=10)

    reports = DB.get_scan_reports(category=category, n=n)
    
    if not reports:
        st.info(f"No reports saved for {category}. Run a scan first.")
    else:
        # Create a dictionary to map labels to report IDs
        report_options = {
            f"{r['report_type']} - {r['created_at'][:16]} (ID: {r['id']})": r['id'] 
            for r in reports
        }
        selected_label = st.selectbox("Select Report Run", options=list(report_options.keys()))
        selected_report_id = report_options[selected_label]

        st.divider()

        # 2. Fetch full detail
        detail = DB.get_scan_report_detail(selected_report_id)
        
        if detail:
            import pandas as pd
            import io
            import re

            # --- ROBUST TABLE PARSING ---
            scout_text = detail["scout_raw"]
            table_lines = []
            
            # Use Regex to find lines starting with a Rank (number)
            # This ignores headers, separators, and free-text notes
            for line in scout_text.splitlines():
                clean_line = line.strip()
                # Matches: digits, space, then at least one alphanumeric char (Symbol)
                if re.match(r'^\d+\s+[A-Z0-9]', clean_line): 
                    table_lines.append(clean_line)
            
            if table_lines:
                # Use Fixed Width format to prevent spaces in names from breaking columns
                df = pd.read_fwf(
                    io.StringIO("\n".join(table_lines)), 
                    names=["Rank", "Symbol", "WMS", "RS", "RSI", "MFI", "CCI"],
                    header=None
                )
            else:
                df = pd.DataFrame()

            # 3. Main UI Layout: Left (Table) | Right (Analyst View)
            col_left, col_right = st.columns([1, 1.8])

            with col_left:
                st.subheader("WMS Rankings")
                if not df.empty:
                    # Interactive dataframe
                    event = st.dataframe(
                        df,
                        height=500,  # <--- Set this to your preferred height in pixels (e.g., 500, 600, 800)
                        use_container_width=True,
                        hide_index=True,
                        on_select="rerun",
                        selection_mode="single-row",
                        column_config={
                            "Symbol": st.column_config.TextColumn("Symbol (Select row to view)")
                        }
                    )
                    
                    # Logic to capture selected stock from click
                    selected_stock = None
                    if event.selection.rows:
                        selected_stock = df.iloc[event.selection.rows[0]]["Symbol"]
                else:
                    st.warning("Could not extract a structured table from this report.")
                    st.text(detail["scout_raw"][:500] + "...")

            with col_right:
                st.subheader("Analyst Detailed View")
                if selected_stock:
                    st.markdown(f"### Report for: `{selected_stock}`")
                    
                    # Fetch raw text
                    stock_report = DB.get_stock_analyst_report(selected_stock, category=category)
                    
                    if stock_report:
                        # --- FORMATTING LOGIC ---
                        # Inject newlines before known keys to ensure clear vertical display
                        formatted_report = stock_report
                        keys = [
                            "SYMBOL", "CLASSIFICATION", "CONFIDENCE", "SECTOR BACKDROP", 
                            "FUNDAMENTAL HEALTH", "NEWS CATALYSTS", "MOMENTUM QUALITY", 
                            "RISK FLAGS", "MEMORY NOTE", "ONE-LINE RATIONALE"
                        ]
                        
                        for key in keys:
                            formatted_report = formatted_report.replace(f"{key}:", f"\n\n**{key}:**")
                        
                        st.markdown(formatted_report)
                    else:
                        st.warning(f"No specific section found for {selected_stock} in category {category}.")
                else:
                    st.info("👈 **Click a row in the table** to see the Analyst's deep-dive.")

            # 4. Global Raw View (Backup)
            # with st.expander("View Full Raw Analyst Report"):
            #     st.markdown(detail["analyst_raw"])
            
            if st.button("Delete this report", type="secondary"):
                DB.delete_scan_report(selected_report_id)
                st.success("Report deleted.")
                st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Page: Setting Page
# ─────────────────────────────────────────────────────────────────────────────

elif page == "Settings":
    st.title("Data management")

    # ── Table stats ───────────────────────────────────────────────────
    st.subheader("Database summary")
    from persistence import _conn
    stats = {}
    with _conn() as con:
        for table in ["scan_runs", "scans", "picks", "alerts",
                      "portfolio", "performance", "scan_reports"]:
            stats[table] = con.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]

    import pandas as pd
    st.dataframe(
        pd.DataFrame(stats.items(), columns=["Table", "Rows"]),
        use_container_width=True,
        hide_index=True,
    )

    st.divider()

    # ── Clear specific data ───────────────────────────────────────────
    st.subheader("Cleanup actions")
    st.warning("Portfolio positions are never deleted by any action below.")

    col1, col2, col3 = st.columns(3)

    if col1.button("Clear all alerts"):
        with _conn() as con:
            con.execute("DELETE FROM alerts")
        st.success("All alerts cleared.")
        st.rerun()

    if col2.button("Clear all scan reports"):
        with _conn() as con:
            con.execute("DELETE FROM scan_reports")
        st.success("All scan reports cleared.")
        st.rerun()

    if col3.button("Clear performance history"):
        with _conn() as con:
            con.execute("DELETE FROM performance")
        st.success("Performance history cleared.")
        st.rerun()

    st.divider()
    st.subheader("Clear scans before date")
    cutoff = st.date_input("Delete all scan runs before", value=None)
    if st.button("Clear old scans") and cutoff:
        cutoff_str = str(cutoff)
        with _conn() as con:
            con.execute(
                "DELETE FROM scans WHERE run_id IN "
                "(SELECT id FROM scan_runs WHERE run_at < ?)", (cutoff_str,)
            )
            con.execute(
                "DELETE FROM picks WHERE run_id IN "
                "(SELECT id FROM scan_runs WHERE run_at < ?)", (cutoff_str,)
            )
            con.execute(
                "DELETE FROM scan_reports WHERE run_id IN "
                "(SELECT id FROM scan_runs WHERE run_at < ?)", (cutoff_str,)
            )
            con.execute("DELETE FROM scan_runs WHERE run_at < ?", (cutoff_str,))
        st.success(f"Cleared all scan data before {cutoff_str}.")
        st.rerun()

    st.divider()
    st.subheader("Nuclear option")
    confirm = st.text_input("Type YES to clear ALL data except portfolio positions")
    if st.button("Clear everything", type="primary") and confirm == "YES":
        with _conn() as con:
            for table in ["scan_reports", "picks", "scans",
                          "alerts", "scan_runs", "performance"]:
                con.execute(f"DELETE FROM {table}")
        st.success("All data cleared. Portfolio positions preserved.")
        st.rerun()
        
    # ADD at the bottom of the Settings page block
    st.divider()
    st.subheader("Logs")
    log_choice = st.radio("View log", ["dashboard.log", "scheduler.log"], horizontal=True)
    # log_path = Path(__file__).parent / "momentum_tracker" / "mps_cache" / log_choice
    # In the log viewer in Settings page
    log_path = get_log_file()
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8").splitlines()
        n_lines = st.slider("Last N lines", 20, 200, 50)
        st.code("\n".join(lines[-n_lines:]), language=None)
    else:
        st.info(f"{log_choice} not found yet.")        

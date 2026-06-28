import os
import re
import sys
import threading
import markdown
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.conf import settings

# Inject the 'streamlite_app' and 'momentum_tracker/src' directories into sys.path to ensure compatibility
sys.path.insert(0, str(settings.BASE_DIR / 'streamlite_app'))
sys.path.insert(0, str(settings.BASE_DIR / 'momentum_tracker' / 'src'))

from database import get_db
from utils import get_log_file
from config import Config
from reporting.report_exporter import ReportExporter

from datetime import timedelta
import time

from scheduler import RateLimitScanError

# Initialize DB singleton
DB = get_db()

# Global state for scanning tracking
SCAN_LOCK = threading.Lock()
SCAN_RUNNING = False
SCAN_CATEGORY = None
SCAN_LOGS = []
SCAN_ERROR = None
SCAN_SUCCESS = False
SCAN_REPORT = ""

# Rate Limit Queue State
QUEUE_LOCK = threading.Lock()
RATE_LIMIT_QUEUE = []

def parse_retry_delay(error_msg: str) -> float:
    match = re.search(r'(?:retry|try again) in ([\d\.]+)\s*(?:s|second)', error_msg, re.IGNORECASE)
    if match:
        return float(match.group(1))
    match2 = re.search(r'([\d\.]+)\s*(?:s|second|min|minute)', error_msg, re.IGNORECASE)
    if match2:
        val = float(match2.group(1))
        if 'min' in error_msg.lower():
            val *= 60
        return val
    return 60.0

def queue_rate_limited_task(task_type, category=None, run_id=None, tickers=None, scout_raw="", accumulated_text="", user_id=None, delay=60.0, retries=0):
    if retries >= 5:
        print(f"[ERROR] Task {task_type} reached maximum retries (5) and was discarded.")
        return
        
    retry_after = datetime.now() + timedelta(seconds=delay)
    task_item = {
        "type": task_type,
        "category": category,
        "run_id": run_id,
        "tickers": tickers,
        "scout_raw": scout_raw,
        "accumulated_text": accumulated_text,
        "user_id": user_id,
        "retry_after": retry_after,
        "retries": retries + 1
    }
    with QUEUE_LOCK:
        RATE_LIMIT_QUEUE.append(task_item)
    print(f"[INFO] Queued rate-limited task: {task_type} (retry {retries+1}/5) to run at {retry_after.strftime('%H:%M:%S')}")

def run_queued_task(item):
    task_type = item["type"]
    if task_type == "scan" or task_type == "scan_remaining":
        category = item["category"]
        global SCAN_RUNNING, SCAN_CATEGORY, SCAN_ERROR, SCAN_SUCCESS
        with SCAN_LOCK:
            SCAN_RUNNING = True
            SCAN_CATEGORY = category
            SCAN_ERROR = None
            SCAN_SUCCESS = False
            
        try:
            from scheduler import job_scan_and_classify_remaining
            if task_type == "scan_remaining":
                # Only execute remaining tickers
                job_scan_and_classify_remaining(
                    run_id=item["run_id"],
                    category=category,
                    tickers=item["tickers"],
                    scout_raw=item["scout_raw"],
                    accumulated_text=item["accumulated_text"]
                )
            else:
                from scheduler import job_scan_and_classify
                job_scan_and_classify(category=category)
                
            with SCAN_LOCK:
                SCAN_RUNNING = False
                SCAN_CATEGORY = None
                SCAN_ERROR = None
                SCAN_SUCCESS = True
        except RateLimitScanError as rle:
            # Queue remaining portion
            queue_rate_limited_task(
                "scan_remaining",
                category=category,
                run_id=rle.run_id,
                tickers=rle.tickers,
                scout_raw=rle.scout_raw,
                accumulated_text=rle.accumulated_text,
                delay=parse_retry_delay(str(rle)),
                retries=item["retries"]
            )
            with SCAN_LOCK:
                SCAN_RUNNING = False
                SCAN_ERROR = f"Rate limit hit. Queued for retry in {parse_retry_delay(str(rle)):.1f}s (Attempt {item['retries']}/5)."
                SCAN_SUCCESS = False
        except Exception as e:
            error_msg = str(e)
            if "RESOURCE_EXHAUSTED" in error_msg or "rate_limit" in error_msg.lower() or "429" in error_msg:
                delay = parse_retry_delay(error_msg)
                queue_rate_limited_task(
                    task_type,
                    category=category,
                    run_id=item.get("run_id"),
                    tickers=item.get("tickers"),
                    scout_raw=item.get("scout_raw"),
                    accumulated_text=item.get("accumulated_text"),
                    delay=delay,
                    retries=item["retries"]
                )
                with SCAN_LOCK:
                    SCAN_RUNNING = False
                    SCAN_ERROR = f"Rate limit hit. Queued for retry in {delay:.1f}s (Attempt {item['retries']}/5)."
                    SCAN_SUCCESS = False
            else:
                with SCAN_LOCK:
                    SCAN_RUNNING = False
                    SCAN_CATEGORY = None
                    SCAN_ERROR = error_msg
                    SCAN_SUCCESS = False
                    
    elif task_type == "monitor":
        user_id = item["user_id"]
        try:
            from scheduler import job_monitor
            job_monitor(user_id=user_id)
        except Exception as e:
            error_msg = str(e)
            if "RESOURCE_EXHAUSTED" in error_msg or "rate_limit" in error_msg.lower() or "429" in error_msg:
                delay = parse_retry_delay(error_msg)
                queue_rate_limited_task("monitor", user_id=user_id, delay=delay, retries=item["retries"])
            else:
                print(f"[ERROR] Queued monitor job failed: {e}")

def start_queue_worker():
    def worker():
        while True:
            time.sleep(5)
            now = datetime.now()
            to_execute = []
            
            with QUEUE_LOCK:
                still_pending = []
                for item in RATE_LIMIT_QUEUE:
                    if now >= item["retry_after"]:
                        to_execute.append(item)
                    else:
                        still_pending.append(item)
                RATE_LIMIT_QUEUE[:] = still_pending
                
            for item in to_execute:
                threading.Thread(target=run_queued_task, args=(item,), daemon=True).start()
                
    threading.Thread(target=worker, daemon=True, name="RateLimitQueueWorker").start()

# Start background queue worker
start_queue_worker()

def update_env_vars(updates: dict[str, str]) -> bool:
    from dotenv import load_dotenv, find_dotenv
    env_path = find_dotenv()
    if not env_path:
        return False
        
    with open(env_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    for key, value in updates.items():
        found = False
        for i, line in enumerate(lines):
            if line.strip().startswith(f"{key}="):
                lines[i] = f"{key}={value}\n"
                found = True
                break
        if not found:
            lines.append(f"{key}={value}\n")
            
    with open(env_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
        
    load_dotenv(env_path, override=True)
    return True

# ─────────────────────────────────────────────────────────────────────────────
# Authentication Views
# ─────────────────────────────────────────────────────────────────────────────

def login_view(request):
    if request.user.is_authenticated:
        return redirect('overview')
        
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, f"Welcome back, {username}!")
            return redirect('overview')
        else:
            messages.error(request, "Invalid username or password.")
            
    return render(request, 'dashboard/login.html')


def signup_view(request):
    if request.user.is_authenticated:
        return redirect('overview')
        
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')
        
        if not username or not password:
            messages.error(request, "Username and password are required.")
        elif password != confirm_password:
            messages.error(request, "Passwords do not match.")
        elif User.objects.filter(username=username).exists():
            messages.error(request, "Username is already taken.")
        else:
            # Create user
            user = User.objects.create_user(username=username, email=email, password=password)
            messages.success(request, "Account created successfully! You can now log in.")
            return redirect('login')
            
    return render(request, 'dashboard/signup.html')


def logout_view(request):
    logout(request)
    messages.success(request, "Logged out successfully.")
    return redirect('login')

# ─────────────────────────────────────────────────────────────────────────────
# Dashboard Views
# ─────────────────────────────────────────────────────────────────────────────

def overview_redirect(request):
    return redirect('overview')


@login_required
def overview_view(request):
    # Quick action 1: Run Portfolio Monitor
    if request.method == 'POST' and 'run_monitor' in request.POST:
        # We can run the monitor inside a thread to prevent freezing the page.
        # Pass the user_id context to restrict scan to this user's positions
        def monitor_thread(user_id):
            try:
                from scheduler import job_monitor
                job_monitor(user_id=user_id)
            except Exception as e:
                error_msg = str(e)
                if "RESOURCE_EXHAUSTED" in error_msg or "rate_limit" in error_msg.lower() or "429" in error_msg:
                    delay = parse_retry_delay(error_msg)
                    queue_rate_limited_task("monitor", user_id=user_id, delay=delay)
                else:
                    print(f"Background monitor run failed: {e}")
                
        threading.Thread(target=monitor_thread, args=(request.user.id,), daemon=True).start()
        messages.info(request, "Portfolio monitor triggered in background. Check the Alert Log in a minute.")
        return redirect('overview')


    held = DB.held_positions(user_id=request.user.id)
    alerts = DB.alert_history(n=200, user_id=request.user.id)
    
    # Map symbol -> latest alert level
    alert_map = {}
    for a in alerts:
        if a["symbol"] not in alert_map:
            alert_map[a["symbol"]] = a["alert_level"]

    # Calculate KPIs
    red_count = sum(1 for h in held if alert_map.get(h["symbol"]) == "RED")
    yellow_count = sum(1 for h in held if alert_map.get(h["symbol"]) == "YELLOW")
    green_count = sum(1 for h in held if alert_map.get(h["symbol"]) == "GREEN")

    # Structure position details
    positions_data = []
    for pos in held:
        sym = pos["symbol"]
        level = alert_map.get(sym, "–")
        
        # Get alert history for this specific position
        history_list = DB.alert_history(symbol=sym, n=10, user_id=request.user.id)
        
        # Get latest alert details
        latest_alerts = DB.alert_history(symbol=sym, n=1, user_id=request.user.id)
        latest_alert = latest_alerts[0] if latest_alerts else None
        
        positions_data.append({
            'symbol': sym,
            'buy_price': pos['buy_price'],
            'qty': pos['qty'],
            'added_at': pos['added_at'][:10],
            'alert_level': level,
            'latest_alert': latest_alert,
            'history': history_list
        })

    context = {
        'positions': positions_data,
        'open_count': len(held),
        'red_count': red_count,
        'yellow_count': yellow_count,
        'green_count': green_count,
    }
    return render(request, 'dashboard/overview.html', context)


@login_required
def trade_view(request):
    from utils import normalize_symbol
    if request.method == 'POST':
        # Add new position
        if 'add_position' in request.POST:
            symbol = normalize_symbol(request.POST.get('symbol', ''))
            try:
                buy_price = float(request.POST.get('buy_price', 0))
                qty = int(request.POST.get('qty', 0))
                if not symbol:
                    messages.error(request, "Ticker symbol cannot be empty.")
                elif buy_price <= 0 or qty <= 0:
                    messages.error(request, "Price and Quantity must be positive values.")
                else:
                    DB.add_position(symbol, buy_price, qty, user_id=request.user.id)
                    messages.success(request, f"Added position: {qty} shares of {symbol} @ ₹{buy_price:.2f}.")
            except ValueError:
                messages.error(request, "Invalid input for price or quantity.")
                
        # Close position
        elif 'close_position' in request.POST:
            symbol = normalize_symbol(request.POST.get('symbol', ''))
            try:
                sell_price = float(request.POST.get('sell_price', 0))
                exit_reason = request.POST.get('exit_reason', 'MANUAL')
                
                # Fetch position details to calculate preview metrics
                held = DB.held_positions(user_id=request.user.id)
                pos = next((p for p in held if p["symbol"] == symbol), None)
                if pos:
                    pnl = (sell_price - pos["buy_price"]) * pos["qty"]
                    pnl_pct = (sell_price / pos["buy_price"] - 1) * 100
                    pnl_sign = "+" if pnl >= 0 else ""
                    
                    DB.close_position(symbol, sell_price, exit_reason=exit_reason, user_id=request.user.id)
                    messages.success(
                        request, 
                        f"Closed {symbol} @ ₹{sell_price:.2f}. "
                        f"P&L: ₹{pnl:,.2f} ({pnl_sign}{pnl_pct:.2f}%) | Reason: {exit_reason}"
                    )
                else:
                    messages.error(request, f"No open position found for {symbol}.")
            except ValueError as e:
                messages.error(request, f"Error closing position: {e}")
                
        return redirect('trade')

    held = DB.held_positions(user_id=request.user.id)
    closed = DB.closed_positions(user_id=request.user.id)
    
    # Enrich held positions with their latest alert badge
    alert_map = {}
    for a in DB.alert_history(n=200, user_id=request.user.id):
        if a["symbol"] not in alert_map:
            alert_map[a["symbol"]] = a["alert_level"]
            
    for h in held:
        h['alert_level'] = alert_map.get(h['symbol'], '–')
        h['added_at'] = h['added_at'][:10]

    for c in closed:
        c['opened_at'] = c['opened_at'][:10] if c.get('opened_at') else '–'
        c['closed_at'] = c['closed_at'][:10]

    context = {
        'held_positions': held,
        'closed_positions': closed,
    }
    return render(request, 'dashboard/trade.html', context)


# Async execution worker function for Scanning
def _async_scan_task(category):
    global SCAN_RUNNING, SCAN_CATEGORY, SCAN_ERROR, SCAN_SUCCESS
    try:
        from scheduler import job_scan_and_classify
        job_scan_and_classify(category=category)
        with SCAN_LOCK:
            SCAN_RUNNING = False
            SCAN_CATEGORY = None
            SCAN_ERROR = None
            SCAN_SUCCESS = True
    except RateLimitScanError as rle:
        delay = parse_retry_delay(str(rle))
        queue_rate_limited_task(
            "scan_remaining",
            category=category,
            run_id=rle.run_id,
            tickers=rle.tickers,
            scout_raw=rle.scout_raw,
            accumulated_text=rle.accumulated_text,
            delay=delay
        )
        with SCAN_LOCK:
            SCAN_RUNNING = False
            SCAN_ERROR = f"Rate limit hit. Queued remaining {len(rle.tickers)} stocks for retry in {delay:.1f}s."
            SCAN_SUCCESS = False
    except Exception as e:
        error_msg = str(e)
        if "RESOURCE_EXHAUSTED" in error_msg or "rate_limit" in error_msg.lower() or "429" in error_msg:
            delay = parse_retry_delay(error_msg)
            queue_rate_limited_task("scan", category=category, delay=delay)
            with SCAN_LOCK:
                SCAN_RUNNING = False
                SCAN_ERROR = f"Rate limit hit. Queued for retry in {delay:.1f}s."
                SCAN_SUCCESS = False
        else:
            with SCAN_LOCK:
                SCAN_RUNNING = False
                SCAN_CATEGORY = None
                SCAN_ERROR = error_msg
                SCAN_SUCCESS = False


# Async execution worker function for deep Multi-Agent analysis on selected tickers
def _async_analysis_task(category, tickers, run_technical=True, run_fii_dii=True):
    global SCAN_RUNNING, SCAN_CATEGORY, SCAN_ERROR, SCAN_SUCCESS, SCAN_REPORT
    SCAN_REPORT = ""
    try:
        from crew.stock_discovery_agents import process_tickers_batch
        from scheduler import _parse_picks
        
        # Run Multi-Agent Crew
        report_text = process_tickers_batch(tickers, run_technical=run_technical, run_fii_dii=run_fii_dii)
        
        # Save picks to DB
        picks = _parse_picks(report_text)
        if picks:
            results_list = [{"Symbol": p["symbol"]} for p in picks]
            run_id = DB.save_scan(category=category, results=results_list, top_n=len(picks))
            DB.save_picks(run_id, picks)
            
        # Convert report markdown to HTML for rendering
        import markdown
        SCAN_REPORT = markdown.markdown(report_text)
        
        with SCAN_LOCK:
            SCAN_RUNNING = False
            SCAN_CATEGORY = None
            SCAN_ERROR = None
            SCAN_SUCCESS = True
    except Exception as e:
        with SCAN_LOCK:
            SCAN_RUNNING = False
            SCAN_CATEGORY = None
            SCAN_ERROR = str(e)
            SCAN_SUCCESS = False


@login_required
def scan_view(request):
    global SCAN_RUNNING, SCAN_CATEGORY, SCAN_ERROR, SCAN_SUCCESS, SCAN_REPORT
    
    categories = [
        "Nifty50", "Nifty100", "Midcap150", "Smallcap250",
        "NiftyLargeMidcap250", "NiftyNext50", "Nifty500", "NiftyMicrocap250",
    ]
    
    scan_results = None
    selected_category = 'Nifty100'
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'fetch_ranks':
            category = request.POST.get('category', 'Nifty100')
            selected_category = category
            
            try:
                from crew.momentum_tool import MomentumBackboneTool
                from scheduler import _parse_scan_rows
                
                tool = MomentumBackboneTool()
                scout_text = tool._run(category=category, top_n=20)
                scan_results = _parse_scan_rows(scout_text)
                
                # Store in session
                request.session['scan_results'] = scan_results
                request.session['selected_category'] = category
            except Exception as e:
                messages.error(request, f"Failed to retrieve momentum ranks: {e}")
                
        elif action == 'run_analysis':
            selected_stocks = request.POST.getlist('selected_stocks')
            category = request.session.get('selected_category', 'Nifty100')
            selected_category = category
            
            if not selected_stocks:
                messages.error(request, "Please select at least one stock to analyze.")
                scan_results = request.session.get('scan_results')
            else:
                run_technical = request.POST.get('run_technical') == 'yes'
                run_fii_dii = request.POST.get('run_fii_dii') == 'yes'
                
                with SCAN_LOCK:
                    if SCAN_RUNNING:
                        messages.error(request, "A scan/analysis is already running.")
                        return redirect('scan')
                        
                    SCAN_RUNNING = True
                    SCAN_CATEGORY = f"{category} (Selected Stocks)"
                    SCAN_ERROR = None
                    SCAN_SUCCESS = False
                    SCAN_REPORT = ""
                    
                t = threading.Thread(
                    target=_async_analysis_task, 
                    args=(category, selected_stocks, run_technical, run_fii_dii), 
                    daemon=True
                )
                t.start()
                messages.success(request, f"Multi-Agent deep analysis started in background for {len(selected_stocks)} selected stocks.")
                return redirect('scan')
                
    else:
        # GET request: clear session scan cache to start fresh
        if 'scan_results' in request.session:
            del request.session['scan_results']
            
    context = {
        'categories': categories,
        'scan_running': SCAN_RUNNING,
        'scan_category': SCAN_CATEGORY,
        'scan_error': SCAN_ERROR,
        'scan_success': SCAN_SUCCESS,
        'scan_results': scan_results,
        'selected_category': selected_category,
    }
    return render(request, 'dashboard/scan.html', context)


@login_required
def scan_status(request):
    global SCAN_RUNNING, SCAN_CATEGORY, SCAN_ERROR, SCAN_SUCCESS, SCAN_REPORT
    return JsonResponse({
        'running': SCAN_RUNNING,
        'category': SCAN_CATEGORY,
        'error': SCAN_ERROR,
        'success': SCAN_SUCCESS,
        'report': SCAN_REPORT
    })


@login_required
def history_view(request):
    categories = [
        "Nifty50", "Nifty100", "Midcap150", "Smallcap250",
        "NiftyLargeMidcap250", "NiftyNext50", "Nifty500", "NiftyMicrocap250", "Monitor"
    ]
    
    selected_category = request.GET.get('category', 'Nifty100')
    limit = int(request.GET.get('limit', 15))
    selected_report_id = request.GET.get('report_id')
    selected_stock = request.GET.get('symbol')
    view_type = request.GET.get('view_type', 'index') # 'index' or 'portfolio'
    search_query = request.GET.get('search_query', '').strip().upper()

    if search_query:
        selected_stock = search_query
        view_type = 'search'

    # Handle deletion
    if request.method == 'POST' and 'delete_report' in request.POST:
        rep_id = request.POST.get('report_id')
        if rep_id:
            DB.delete_scan_report(int(rep_id))
            messages.success(request, f"Deleted report ID {rep_id}.")
        return redirect(f'/history/?view_type={view_type}&category={selected_category}&limit={limit}')

    # Handle on-demand analysis trigger
    if request.method == 'POST' and request.POST.get('action') == 'run_on_demand':
        symbol = request.POST.get('symbol', '').strip().upper()
        if symbol:
            if '.' not in symbol:
                symbol = f"{symbol}.NS"
            
            # Start background thread to run process_tickers_batch for this symbol
            t = threading.Thread(target=_async_analysis_task, args=('On-Demand', [symbol]), daemon=True)
            t.start()
            messages.success(request, f"On-demand background scan started for {symbol}. Refresh in a minute.")
            return redirect(f'/history/?view_type=search&category={selected_category}&symbol={symbol}')

    reports = DB.get_scan_reports(category=selected_category, n=limit)
    
    # Default to first report if none selected and in index view
    if not selected_report_id and reports and view_type == 'index':
        selected_report_id = str(reports[0]['id'])
        
    detail = None
    rankings = []
    analyst_report_html = None
    symbols = []
    wms_scores = []
    classifications = []
    
    # Export CSV action (from history_view)
    if request.method == 'POST' and 'export_csv' in request.POST:
        rep_id = request.POST.get('report_id') or selected_report_id
        if rep_id:
            detail = DB.get_scan_report_detail(int(rep_id))
            if detail:
                scout_text = detail.get("scout_raw", "") or ""
                parsed_rows = []
                for line in scout_text.splitlines():
                    clean_line = line.strip()
                    if re.match(r'^\d+\s+[A-Z0-9]', clean_line):
                        parts = clean_line.split()
                        if len(parts) >= 7:
                            parsed_rows.append({
                                'Rank': parts[0],
                                'Symbol': parts[1],
                                'WMS': parts[2],
                                'RS_Raw': parts[3],
                                'RSI_Raw': parts[4],
                                'MFI_Raw': parts[5],
                                'CCI_Raw': parts[6]
                            })
                if parsed_rows:
                    import csv
                    from io import StringIO
                    f = StringIO()
                    writer = csv.DictWriter(f, fieldnames=['Rank', 'Symbol', 'WMS', 'RS_Raw', 'RSI_Raw', 'MFI_Raw', 'CCI_Raw'])
                    writer.writeheader()
                    writer.writerows(parsed_rows)
                    response = HttpResponse(f.getvalue(), content_type='text/csv')
                    response['Content-Disposition'] = f'attachment; filename="scan_export_{selected_category}_{rep_id}.csv"'
                    return response
        messages.error(request, "No data found to export.")
        return redirect(f'/history/?view_type={view_type}&category={selected_category}&limit={limit}&report_id={selected_report_id}')

    # 1. Load Data depending on view_type
    if view_type == 'portfolio':
        # Load portfolio positions
        portfolio_positions = DB.get_portfolio_positions_with_reports(request.user.id)
        # Format keys for layout compatibility
        for p in portfolio_positions:
            p['symbol'] = p['symbol']
            p['wms'] = p['wms'] or 0.0
            p['rank'] = '–'
        rankings = portfolio_positions
        if not selected_stock and rankings:
            selected_stock = rankings[0]['symbol']
    elif view_type == 'index':
        # Load index progressions
        progressions = DB.get_category_stock_progressions(selected_category, limit=30)
        # Format keys for layout compatibility
        for p in progressions:
            p['wms'] = p['latest_wms'] or 0.0
            p['rank'] = p['latest_rank'] or '–'
        rankings = progressions
        if not selected_stock and rankings:
            selected_stock = rankings[0]['symbol']
    elif view_type == 'search':
        # Single stock view
        rankings = []
        if not selected_stock and search_query:
            selected_stock = search_query

    # 2. Get detailed report for selected stock
    if selected_stock:
        # Resolve suffix if missing
        stock_sym = selected_stock if '.' in selected_stock else f"{selected_stock}.NS"
        # Attempt to load latest pick record directly
        with DB._conn() as con:
            pick_row = con.execute(
                "SELECT classification, confidence, momentum_quality, sector_backdrop, fundamental, news_catalysts, risk_flags, rationale, picked_at "
                "FROM picks WHERE symbol=? ORDER BY picked_at DESC LIMIT 1",
                (stock_sym,)
            ).fetchone()
            
            if pick_row:
                formatted_report = f"""
SYMBOL: {selected_stock}
CLASSIFICATION: {pick_row['classification']}
CONFIDENCE: {pick_row['confidence']}/5
SECTOR BACKDROP: {pick_row['sector_backdrop']}
FUNDAMENTAL HEALTH: {pick_row['fundamental']}
NEWS CATALYSTS: {pick_row['news_catalysts']}
MOMENTUM QUALITY: {pick_row['momentum_quality']}
RISK FLAGS: {pick_row['risk_flags']}
ONE-LINE RATIONALE: {pick_row['rationale']}
"""
                for key in ["SYMBOL", "CLASSIFICATION", "CONFIDENCE", "SECTOR BACKDROP", 
                            "FUNDAMENTAL HEALTH", "NEWS CATALYSTS", "MOMENTUM QUALITY", 
                            "RISK FLAGS", "ONE-LINE RATIONALE"]:
                    formatted_report = formatted_report.replace(f"{key}:", f"\n\n**{key}:**")
                
                analyst_report_html = markdown.markdown(formatted_report)
                
                class DummyDetail:
                    def __init__(self, date):
                        self.created_at = date
                    def get(self, key, default=None):
                        if key == 'created_at': return self.created_at
                        return default
                detail = DummyDetail(pick_row['picked_at'])
            else:
                # Attempt to extract from raw scout report if pick row is not present
                stock_report = DB.get_stock_analyst_report(stock_sym, category=selected_category)
                if stock_report:
                    formatted_report = stock_report
                    keys = [
                        "SYMBOL", "CLASSIFICATION", "CONFIDENCE", "SECTOR BACKDROP", 
                        "FUNDAMENTAL HEALTH", "NEWS CATALYSTS", "MOMENTUM QUALITY", 
                        "RISK FLAGS", "MEMORY NOTE", "ONE-LINE RATIONALE"
                    ]
                    for key in keys:
                        formatted_report = formatted_report.replace(f"{key}:", f"\n\n**{key}:**")
                    analyst_report_html = markdown.markdown(formatted_report)

        # 3. Load WMS score history trend data for Plotly chart (last 30 scans)
        with DB._conn() as con:
            hist_rows = con.execute(
                "SELECT s.wms, r.run_at FROM scans s "
                "INNER JOIN scan_runs r ON s.run_id = r.id "
                "WHERE s.symbol = ? ORDER BY r.run_at ASC LIMIT 30",
                (stock_sym,)
            ).fetchall()
            symbols = [h['run_at'][:10] for h in hist_rows]
            wms_scores = [h['wms'] for h in hist_rows]
            classifications = [pick_row['classification'] if pick_row else 'UNKNOWN'] * len(hist_rows)

    context = {
        'categories': categories,
        'selected_category': selected_category,
        'limit': limit,
        'reports': reports,
        'selected_report_id': int(selected_report_id) if selected_report_id and selected_report_id.isdigit() else None,
        'rows': rankings,
        'selected_stock': selected_stock,
        'detail': detail,
        'symbols': symbols,
        'wms_scores': wms_scores,
        'classifications': classifications,
        'analyst_report_html': analyst_report_html,
        'view_type': view_type,
        'search_query': search_query,
    }
    return render(request, 'dashboard/history.html', context)


@login_required
def reports_view(request):
    return redirect('history')


@login_required
def alerts_view(request):
    filter_sym = request.GET.get('symbol', '').strip().upper()
    filter_level = request.GET.get('level', 'All')
    
    alerts = DB.alert_history(
        symbol=filter_sym or None,
        level=filter_level if filter_level != 'All' else None,
        n=200,
        user_id=request.user.id
    )
    
    context = {
        'alerts': alerts,
        'filter_symbol': filter_sym,
        'filter_level': filter_level,
    }
    return render(request, 'dashboard/alerts.html', context)


@login_required
def performance_view(request):
    summary = DB.performance_summary(user_id=request.user.id)
    
    # Process classification chart data
    cls_labels = []
    cls_win_rates = []
    cls_trades = []
    cls_pnl = []
    
    if summary and summary.get("by_classification"):
        for k, v in summary["by_classification"].items():
            cls_labels.append(k)
            cls_trades.append(v["trades"])
            rate = round(v["wins"] / v["trades"] * 100, 1) if v["trades"] else 0
            cls_win_rates.append(rate)
            cls_pnl.append(round(v["pnl"], 2))
            
    context = {
        'summary': summary,
        'cls_labels': cls_labels,
        'cls_win_rates': cls_win_rates,
        'cls_trades': cls_trades,
        'cls_pnl': cls_pnl,
    }
    return render(request, 'dashboard/performance.html', context)


@login_required
def settings_view(request):
    if not request.user.is_superuser:
        messages.error(request, "Access denied. Only administrators can access settings.")
        return redirect('overview')

    config_path = str(Path(settings.BASE_DIR) / 'momentum_tracker' / 'config.json')
    config = Config(config_path)

    # Handle cleanups & config updates
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'clear_alerts':
            DB.clear_alerts(user_id=request.user.id)
            messages.success(request, "Successfully cleared your alerts.")
        elif action == 'clear_reports':
            DB.clear_reports()
            messages.success(request, "Successfully cleared all scan reports.")
        elif action == 'clear_performance':
            DB.clear_stock_performance_history(user_id=request.user.id)
            messages.success(request, "Successfully cleared your performance history.")
        elif action == 'clear_old_scans':
            cutoff = request.POST.get('cutoff_date')
            if cutoff:
                DB.clear_runs_before(cutoff)
                messages.success(request, f"Successfully cleared scans before {cutoff}.")
            else:
                messages.error(request, "Please provide a valid cutoff date.")
        elif action == 'nuclear_option':
            confirm = request.POST.get('confirm_text', '')
            if confirm.strip().upper() == 'YES':
                DB.clear_all()
                messages.success(request, "Nuclear cleanup complete! Portfolio positions preserved.")
            else:
                messages.error(request, "Nuclear action aborted. You must type 'YES' exactly.")
        elif action == 'update_strategy_config':
            try:
                config["FILTER_CONFIG"]["MIN_PRICE"] = float(request.POST.get('min_price', 1.0))
                config["FILTER_CONFIG"]["MIN_VOLUME_AVG"] = int(request.POST.get('min_volume_avg', 10000))
                config["FILTER_CONFIG"]["ENABLE_FILTERS"] = request.POST.get('enable_filters') == 'true'
                config["FILTER_CONFIG"]["ENABLE_EMA_FILTER"] = request.POST.get('enable_ema_filter') == 'true'
                config["DATA_CONFIG"]["MAX_CACHE_DAYS"] = int(request.POST.get('max_cache_days', 3))
                config["DATA_CONFIG"]["DOWNLOAD_HISTORY_YEARS"] = int(request.POST.get('download_history_years', 5))
                config["MOMENTUM_CONFIG"]["RS_LOOKBACK_DAYS"] = int(request.POST.get('rs_lookback_days', 55))
                config["BACKTEST_CONFIG"]["TOP_N"] = int(request.POST.get('top_n', 20))
                config["BACKTEST_CONFIG"]["MOMENTUM_DROP_THRESHOLD_PCT"] = float(request.POST.get('momentum_drop_threshold_pct', 50.0))
                
                config.save(minimal=False)
                messages.success(request, "Strategy configuration updated successfully.")
            except Exception as e:
                messages.error(request, f"Failed to save strategy configuration: {e}")
        elif action == 'update_llm_provider':
            provider = request.POST.get('provider')
            gemini_model = request.POST.get('gemini_model', '').strip()
            groq_model = request.POST.get('groq_model', '').strip()
            gemini_api_key = request.POST.get('gemini_api_key', '').strip()
            groq_api_key = request.POST.get('groq_api_key', '').strip()
            
            updates = {}
            if provider in ['gemini', 'groq']:
                updates['LLM_PROVIDER'] = provider
            if gemini_model:
                updates['GEMINI_MODEL'] = gemini_model
            if groq_model:
                updates['GROQ_MODEL'] = groq_model
            if gemini_api_key and not gemini_api_key.startswith('****') and '...' not in gemini_api_key:
                updates['GEMINI_API_KEY'] = gemini_api_key
            if groq_api_key and not groq_api_key.startswith('****') and '...' not in groq_api_key:
                updates['GROQ_API_KEY'] = groq_api_key
                
            if updates:
                if update_env_vars(updates):
                    messages.success(request, "LLM Configuration successfully updated.")
                else:
                    messages.error(request, "Could not find .env file to update.")
            else:
                messages.error(request, "No updates provided.")
                
        return redirect('settings')

    from dotenv import load_dotenv, find_dotenv
    load_dotenv(find_dotenv(), override=True)
    current_provider = os.getenv("LLM_PROVIDER", "gemini")
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    
    raw_gemini_key = os.getenv("GEMINI_API_KEY", "")
    raw_groq_key = os.getenv("GROQ_API_KEY", "")
    
    def mask_key(k):
        if not k:
            return ""
        if len(k) <= 8:
            return "****"
        return f"{k[:4]}...{k[-4:]}"
        
    gemini_api_key_masked = mask_key(raw_gemini_key)
    groq_api_key_masked = mask_key(raw_groq_key)

    stats = DB.table_row_counts()
    
    # Process stats for template
    stats_data = [{'table': k, 'rows': v} for k, v in stats.items()]
    
    # Fetch logs
    log_type = request.GET.get('log_type', 'dashboard')
    
    # Resolve log path based on the parent directory of get_log_file()
    log_path = get_log_file().parent / ('scheduler.log' if log_type == 'scheduler' else 'momentum_dashboard.log')
        
    lines_count = int(request.GET.get('lines', 50))
    log_content = ""
    
    if log_path.exists():
        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                log_content = "".join(lines[-lines_count:])
        except Exception as e:
            log_content = f"Error reading log file: {e}"
    else:
        log_content = f"Log file not found at: {log_path}"

    strategy_config = {
        "min_price": config["FILTER_CONFIG"].get("MIN_PRICE", 1.0),
        "min_volume_avg": config["FILTER_CONFIG"].get("MIN_VOLUME_AVG", 10000),
        "enable_filters": config["FILTER_CONFIG"].get("ENABLE_FILTERS", True),
        "enable_ema_filter": config["FILTER_CONFIG"].get("ENABLE_EMA_FILTER", True),
        "max_cache_days": config["DATA_CONFIG"].get("MAX_CACHE_DAYS", 3),
        "download_history_years": config["DATA_CONFIG"].get("DOWNLOAD_HISTORY_YEARS", 5),
        "rs_lookback_days": config["MOMENTUM_CONFIG"].get("RS_LOOKBACK_DAYS", 55),
        "top_n": config["BACKTEST_CONFIG"].get("TOP_N", 20),
        "momentum_drop_threshold_pct": config["BACKTEST_CONFIG"].get("MOMENTUM_DROP_THRESHOLD_PCT", 50.0),
    }

    context = {
        'stats': stats_data,
        'log_type': log_type,
        'log_content': log_content,
        'lines': lines_count,
        'current_provider': current_provider,
        'gemini_model': gemini_model,
        'groq_model': groq_model,
        'gemini_api_key_masked': gemini_api_key_masked,
        'groq_api_key_masked': groq_api_key_masked,
        'strategy_config': strategy_config,
    }
    return render(request, 'dashboard/settings.html', context)


@login_required
def download_report_excel(request, report_id):
    detail = DB.get_scan_report_detail(int(report_id))
    if not detail:
        messages.error(request, "Report not found.")
        return redirect('history')
        
    scout_text = detail.get("scout_raw", "") or ""
    rankings = []
    
    # Parse table lines matching layout rules
    for line in scout_text.splitlines():
        clean_line = line.strip()
        if re.match(r'^\d+\s+[A-Z0-9]', clean_line):
            parts = clean_line.split()
            if len(parts) >= 7:
                try:
                    rankings.append({
                        'Rank': int(parts[0]),
                        'Symbol': parts[1],
                        'WMS': float(parts[2]),
                        'RS_Raw': float(parts[3]),
                        'RSI_Raw': float(parts[4]),
                        'MFI_Raw': float(parts[5]),
                        'CCI_Raw': float(parts[6])
                    })
                except (ValueError, IndexError):
                    pass
                
    if not rankings:
        messages.error(request, "Could not extract quantitative table from report to export.")
        return redirect('reports')
        
    import pandas as pd
    df = pd.DataFrame(rankings)
    df.set_index('Rank', inplace=True)
    
    # Reorder columns nicely
    cols_order = ['Symbol', 'WMS', 'RS_Raw', 'RSI_Raw', 'MFI_Raw', 'CCI_Raw']
    df = df[[c for c in cols_order if c in df.columns]]
    
    exporter = ReportExporter()
    xlsx_path = exporter.export_scores(df, base_dir="data_cache", filename=f"scan_report_{detail.get('category')}_{report_id}")
    
    if xlsx_path.exists():
        with open(xlsx_path, 'rb') as f:
            response = HttpResponse(f.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            response['Content-Disposition'] = f'attachment; filename="{xlsx_path.name}"'
            return response
            
    messages.error(request, "Failed to generate Excel file.")
    return redirect('reports')


@login_required
def momentum_view(request):
    """
    Historical Momentum Score Tracker view.
    Displays momentum score (WMS) history for portfolio stocks, the benchmark, and sectors.
    """
    from momentum_tracker.api import MomentumTrackerAPI
    api = MomentumTrackerAPI(user_id=request.user.id)
    
    # Calculate 30-day history with exception handling
    try:
        history = api.get_portfolio_momentum_history(days=30)
    except Exception as e:
        messages.error(request, f"Error loading momentum tracker history (check database cache or connection): {e}")
        history = None

    
    # Check if portfolio has no stocks or history is empty
    if not history or not history.get("dates") or not history.get("portfolio"):
        context = {
            "no_holdings": True,
            "dates_json": "[]",
            "portfolio_json": "{}",
            "sectors_json": "{}",
            "index_json": "[]",
            "grid_data": [],
        }
        return render(request, "dashboard/momentum.html", context)

    # Format JSON strings for template Chart.js consumption
    import json
    dates_json = json.dumps(history["dates"])
    portfolio_json = json.dumps(history["portfolio"])
    sectors_json = json.dumps(history["sectors"])
    index_json = json.dumps(history["index"])

    # Prepare table grid with latest score, changes, and alerts
    grid_data = []
    dates = history["dates"]
    portfolio = history["portfolio"]
    sectors = history["sectors"]
    index = history["index"]
    sector_map = history["sector_map"]

    for sym, scores in portfolio.items():
        if not scores:
            continue
        
        latest_score = scores[-1]
        score_7d_ago = scores[-6] if len(scores) >= 6 else scores[0]
        score_30d_ago = scores[-30] if len(scores) >= 30 else scores[0]
        change_7d = round(latest_score - score_7d_ago, 2)
        change_30d = round(latest_score - score_30d_ago, 2)
        
        # Determine status warning: if WMS is low or has dropped significantly
        status = "Healthy"
        status_color = "green"
        if change_7d <= -15.0 or change_30d <= -25.0:
            status = "Fading Momentum"
            status_color = "red"
        elif change_7d <= -5.0 or change_30d <= -10.0:
            status = "Slight Loss"
            status_color = "yellow"

        # Corresponding sector & its scores
        sec = sector_map.get(sym, "N/A")
        sec_scores = sectors.get(sec, [])
        sec_latest = sec_scores[-1] if sec_scores else 0.0

        grid_data.append({
            "symbol": sym,
            "sector": sec,
            "latest_score": latest_score,
            "change_7d": change_7d,
            "change_30d": change_30d,
            "status": status,
            "status_color": status_color,
            "sector_score": sec_latest,
        })

    context = {
        "no_holdings": False,
        "dates_json": dates_json,
        "portfolio_json": portfolio_json,
        "sectors_json": sectors_json,
        "index_json": index_json,
        "grid_data": grid_data,
        "latest_index_score": index[-1] if index else 0.0,
    }
    return render(request, "dashboard/momentum.html", context)


@login_required
def rebalance_view(request):
    """
    Portfolio Rebalance Assistant view (Option 12).
    Compares the current portfolio against the latest recommendations,
    or generates a direct rebalance report from live DB holdings, saving it to database.
    """
    from momentum_tracker.api import MomentumTrackerAPI
    api = MomentumTrackerAPI(user_id=request.user.id)

    report_data = None
    download_url = None
    
    # Load categories from config for universe selection
    categories = list(api.config["DATA_CONFIG"].get("INDICES", {}).keys())
    selected_category = request.POST.get("category") or api.config["DATA_CONFIG"].get("DEFAULT_CATEGORY", "Nifty100")
    target_size = int(request.POST.get("target_size") or api.config["BACKTEST_CONFIG"].get("TOP_N", 20))

    if request.method == "POST":
        use_db = request.POST.get("use_db") == "on"
        portfolio_file = request.FILES.get("portfolio_file")
        reco_file = request.FILES.get("reco_file")
        
        # Validation
        if not use_db and not portfolio_file:
            messages.error(request, "Please either select 'Use Database Holdings' or upload a portfolio file.")
            return redirect("rebalance")
        
        # Create temp dir in project root
        temp_dir = settings.BASE_DIR / "temp"
        temp_dir.mkdir(exist_ok=True)
        
        import uuid
        uid = uuid.uuid4().hex
        
        # Save uploaded reco file if present
        reco_path = None
        if reco_file:
            reco_path = temp_dir / f"reco_{uid}_{reco_file.name}"
            with open(reco_path, "wb") as f:
                for chunk in reco_file.chunks():
                    f.write(chunk)
                    
        # Save or build portfolio file if using file mode
        port_path = None
        if not use_db and portfolio_file:
            port_path = temp_dir / f"port_{uid}_{portfolio_file.name}"
            with open(port_path, "wb") as f:
                for chunk in portfolio_file.chunks():
                    f.write(chunk)
        
        try:
            report_df = pd.DataFrame()
            
            if use_db:
                # Mode A: Use DB Holdings
                universe = api.loader.load(selected_category)
                if not universe:
                    universe = api.loader.all_symbols()
                
                # Check if we are doing comparison or simple rebalance
                if reco_path:
                    # Compare DB portfolio with uploaded last recommendation file
                    report_df = api.portfolio.compare_with_last_recommendation_file(
                        universe_symbols=universe,
                        last_file_path=str(reco_path),
                        target_size=target_size
                    )
                else:
                    # Pure rebalance check of live DB portfolio vs latest scores
                    report_df = api.portfolio.generate_rebalance_report(
                        universe_symbols=universe,
                        target_size=target_size
                    )
            else:
                # Mode B: File-based holdings vs recommendation file comparison
                if not reco_path:
                    messages.error(request, "Please upload the last recommendation file for comparison.")
                else:
                    report_df = api.portfolio.compare_and_rebalance(
                        portfolio_file=str(port_path),
                        last_reco_file=str(reco_path)
                    )
            
            if report_df is not None and not report_df.empty:
                # Convert DataFrame to records for Django template rendering
                report_data = report_df.to_dict(orient="records")
                
                # Save the run to the database rebalance_history table
                run_id = DB.save_rebalance_run(request.user.id, report_data)
                download_url = f"/rebalance/download/{run_id}/"
                
                messages.success(request, "Rebalancing action report generated and logged successfully!")
            else:
                messages.error(request, "Failed to generate action report.")
        except Exception as e:
            messages.error(request, f"Error during rebalancing calculation: {e}")
        finally:
            # Cleanup temp files
            if port_path and port_path.exists():
                port_path.unlink()
            if reco_path and reco_path.exists():
                reco_path.unlink()

    # If run_id is passed as GET param, display that historical run
    run_id_param = request.GET.get("run_id")
    if run_id_param and run_id_param.isdigit():
        run_detail = DB.get_rebalance_run_detail(int(run_id_param))
        if run_detail and run_detail["user_id"] == request.user.id:
            report_data = run_detail["report_data"]
            download_url = f"/rebalance/download/{run_detail['id']}/"
            messages.info(request, f"Loaded historical rebalance report from {run_detail['run_at']}.")

    # Load history for the list
    history = DB.get_rebalance_runs(request.user.id, n=15)

    context = {
        "report_data": report_data,
        "download_url": download_url,
        "categories": categories,
        "selected_category": selected_category,
        "target_size": target_size,
        "history": history,
    }
    return render(request, "dashboard/rebalance.html", context)


@login_required
def rebalance_download(request):
    """Serve a generated rebalance action report for download (from disk path)."""
    from momentum_tracker.api import MomentumTrackerAPI
    api = MomentumTrackerAPI(user_id=request.user.id)
    file_name = request.GET.get("file")
    if not file_name:
        return HttpResponse("File parameter missing", status=400)
        
    rebalance_dir = Path(api.config.get("SYSTEM_CONFIG", {}).get("REBALANCE_HISTORY_DIR", "Rebalance_history"))
    if not rebalance_dir.is_absolute():
        rebalance_dir = settings.BASE_DIR / rebalance_dir
        
    file_path = rebalance_dir / file_name
    if not file_path.exists() or ".." in file_name or "/" in file_name or "\\" in file_name:
        return HttpResponse("File not found or invalid path", status=404)
        
    with open(file_path, "rb") as f:
        response = HttpResponse(
            f.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f"attachment; filename={file_name}"
        return response


@login_required
def rebalance_download_view(request, run_id):
    """Dynamically serve saved rebalance action report as Excel from DB."""
    run = DB.get_rebalance_run_detail(run_id)
    if not run or run["user_id"] != request.user.id:
        return HttpResponse("Run not found or unauthorized", status=404)
        
    df = pd.DataFrame(run["report_data"])
    
    import io
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name="Rebalance_Actions", index=False)
        
    output.seek(0)
    
    # Format filename safely
    formatted_date = run["run_at"].replace(":", "-").replace("T", "_")
    filename = f"Rebalance_Action_{formatted_date}.xlsx"
    
    response = HttpResponse(
        output.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f"attachment; filename={filename}"
    return response


@login_required
def portfolio_upload_transactions(request):
    """Parse and apply bulk transactions from an uploaded Excel or CSV file."""
    if request.method == 'POST':
        tx_file = request.FILES.get('tx_file')
        if not tx_file:
            messages.error(request, "Please select a transaction report CSV or Excel file to upload.")
            return redirect('trade')
            
        try:
            from core.portfolio_service import PortfolioService
            from momentum_tracker.api import MomentumTrackerAPI
            api = MomentumTrackerAPI(user_id=request.user.id)
            
            # Instantiate service with active db backend and db manager cache
            service = PortfolioService(DB, api.db)
            
            # Read suffix to determine type
            suffix = Path(tx_file.name).suffix.lower()
            file_type = "excel" if suffix in (".xlsx", ".xls") else "csv"
            
            # Save upload to a temp buffer and parse
            import io
            if file_type == "csv":
                file_buf = io.StringIO(tx_file.read().decode('utf-8', errors='ignore'))
            else:
                file_buf = io.BytesIO(tx_file.read())
                
            res = service.upload_transactions(file_buf, file_type=file_type, user_id=request.user.id)
            
            msg = f"Successfully processed transaction report! Applied {res['success_count']} transactions. "
            if res['skipped_count'] > 0:
                msg += f"Skipped {res['skipped_count']} rows."
            messages.success(request, msg)
            
            # Log details in console for visibility
            for detail in res['details']:
                print(f"[TX Uploader] {detail}")
                
        except Exception as e:
            messages.error(request, f"Error processing transaction file: {e}")
            
    return redirect('trade')


@login_required
def add_transaction_view(request):
    """View to handle bulk transaction uploads via Excel or CSV, supporting SmallCase formats."""
    results = None
    if request.method == 'POST':
        tx_file = request.FILES.get('tx_file')
        if not tx_file:
            messages.error(request, "Please select a transaction report CSV or Excel file to upload.")
            return render(request, 'dashboard/add_transaction.html')
            
        try:
            from core.portfolio_service import PortfolioService
            from momentum_tracker.api import MomentumTrackerAPI
            from pathlib import Path
            import io
            
            api = MomentumTrackerAPI(user_id=request.user.id)
            service = PortfolioService(DB, api.db)
            
            # Read suffix to determine type
            suffix = Path(tx_file.name).suffix.lower()
            file_type = "excel" if suffix in (".xlsx", ".xls") else "csv"
            
            if file_type == "csv":
                file_buf = io.StringIO(tx_file.read().decode('utf-8', errors='ignore'))
            else:
                file_buf = io.BytesIO(tx_file.read())
                
            res = service.upload_transactions(file_buf, file_type=file_type, user_id=request.user.id)
            
            msg = f"Successfully processed transaction report! Applied {res['success_count']} transactions. "
            if res['skipped_count'] > 0:
                msg += f"Skipped {res['skipped_count']} rows."
            messages.success(request, msg)
            
            results = res
            
            # Log details in console
            for detail in res['details']:
                print(f"[TX Uploader] {detail}")
                
        except Exception as e:
            messages.error(request, f"Error processing transaction file: {e}")
            
    return render(request, 'dashboard/add_transaction.html', {'results': results})



# ─────────────────────────────────────────────────────────────────────────────
# Backtesting views (CLI Options [1] & [2])
# ─────────────────────────────────────────────────────────────────────────────

# Global state for backtesting tracking
BACKTEST_LOCK = threading.Lock()
BACKTEST_RUNNING = False
BACKTEST_ERROR = None
BACKTEST_SUCCESS = False
BACKTEST_RESULTS_DATA = None
BACKTEST_EXPORT_PATH = None

def _async_backtest_task(category, start_date, end_date, top_n, rebalance_freq, transaction_cost, initial_capital, user_id):
    global BACKTEST_RUNNING, BACKTEST_ERROR, BACKTEST_SUCCESS, BACKTEST_RESULTS_DATA, BACKTEST_EXPORT_PATH
    try:
        from momentum_tracker.api import MomentumTrackerAPI
        api = MomentumTrackerAPI(user_id=user_id)
        
        # Override initial capital in backtest configuration temporarily
        api.config["BACKTEST_CONFIG"]["INITIAL_CAPITAL"] = initial_capital
        
        # Run single category backtest
        df_r, df_e, df_t, df_b = api.runner.run_single(
            category=category,
            start_date=start_date,
            end_date=end_date,
            top_n=top_n,
            rebalance_freq=rebalance_freq,
            transaction_cost=transaction_cost,
            export=True
        )
        
        if df_e.empty:
            raise ValueError("Backtest executed but returned empty equity curve. Verify date range and data cache.")

        # Save output path details
        results_dir = Path(api.config.get("SYSTEM_CONFIG", {}).get("BACKTEST_RESULTS_DIR", "Backtest_Results"))
        if not results_dir.is_absolute():
            results_dir = settings.BASE_DIR / results_dir
        folder = results_dir / "single_runs"
        
        files = list(folder.glob(f"{category}_*.xlsx"))
        latest_file = None
        if files:
            latest_file = max(files, key=lambda p: p.stat().st_mtime)
            BACKTEST_EXPORT_PATH = str(latest_file)
            
        # Calculate summary statistics
        eq_start = float(df_e["equity"].iloc[0])
        eq_end = float(df_e["equity"].iloc[-1])
        total_return = (eq_end / eq_start - 1.0) * 100
        
        years = (end_date - start_date).days / 365.25
        cagr = (((eq_end / eq_start) ** (1 / max(years, 0.01))) - 1.0) * 100
        
        bm_start = float(df_b["close"].iloc[0]) if not df_b.empty else 1.0
        bm_end = float(df_b["close"].iloc[-1]) if not df_b.empty else 1.0
        bm_return = (bm_end / bm_start - 1.0) * 100
        bm_cagr = (((bm_end / bm_start) ** (1 / max(years, 0.01))) - 1.0) * 100
        
        total_trades = len(df_t)
        wins = len(df_t[df_t["pnl"] > 0]) if "pnl" in df_t.columns else 0
        win_rate = (wins / total_trades * 100) if total_trades else 0.0
        max_dd = float(df_e["drawdown"].max() * 100) if "drawdown" in df_e.columns else 0.0
        
        transactions = []
        if not df_t.empty:
            df_t_sorted = df_t.sort_values(by="date", ascending=False).head(100)
            for idx, r in df_t_sorted.iterrows():
                transactions.append({
                    "date": str(r.get("date"))[:10],
                    "type": str(r.get("type", "TRADE")).upper(),
                    "symbol": str(r.get("symbol")),
                    "qty": int(r.get("qty", 0)),
                    "price": float(r.get("price", 0.0)),
                    "value": float(r.get("value", 0.0)),
                    "pnl": float(r.get("pnl", 0.0)) if "pnl" in r else 0.0,
                    "pnl_pct": float(r.get("pnl_pct", 0.0)) if "pnl_pct" in r else 0.0,
                })

        step = max(1, len(df_e) // 300)
        df_e_sampled = df_e.iloc[::step]
        dates_list = [str(d)[:10] for d in df_e_sampled["date"]]
        equity_list = [round(float(v), 2) for v in df_e_sampled["equity"]]
        
        benchmark_list = []
        if not df_b.empty:
            df_b_idx = df_b.set_index("date")
            for d in df_e_sampled["date"]:
                closest_date = df_b_idx.index[df_b_idx.index.get_indexer([d], method="nearest")[0]]
                val = df_b_idx.loc[closest_date]["close"]
                benchmark_list.append(round(float(val), 2))
                
        if benchmark_list and equity_list:
            bm_init = benchmark_list[0]
            benchmark_scaled = [round((v / bm_init) * eq_start, 2) for v in benchmark_list]
        else:
            benchmark_scaled = []

        with BACKTEST_LOCK:
            BACKTEST_RUNNING = False
            BACKTEST_ERROR = None
            BACKTEST_SUCCESS = True
            BACKTEST_RESULTS_DATA = {
                "category": category,
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
                "total_return": round(total_return, 2),
                "cagr": round(cagr, 2),
                "bm_return": round(bm_return, 2),
                "bm_cagr": round(bm_cagr, 2),
                "win_rate": round(win_rate, 2),
                "total_trades": total_trades,
                "max_drawdown": round(max_dd, 2),
                "dates": dates_list,
                "equity": equity_list,
                "benchmark": benchmark_scaled,
                "transactions": transactions,
                "file_name": latest_file.name if latest_file else ""
            }
            
    except Exception as e:
        print(f"[ERROR] Async backtest failed: {e}")
        with BACKTEST_LOCK:
            BACKTEST_RUNNING = False
            BACKTEST_ERROR = str(e)
            BACKTEST_SUCCESS = False
            BACKTEST_RESULTS_DATA = None


@login_required
def backtest_view(request):
    global BACKTEST_RUNNING, BACKTEST_ERROR, BACKTEST_SUCCESS, BACKTEST_RESULTS_DATA
    
    from momentum_tracker.api import MomentumTrackerAPI
    api = MomentumTrackerAPI(user_id=request.user.id)
    categories = api.loader.available_categories()
    
    if request.method == 'POST':
        with BACKTEST_LOCK:
            if BACKTEST_RUNNING:
                messages.error(request, "A backtest simulation is already running.")
                return redirect('backtest')
                
            BACKTEST_RUNNING = True
            BACKTEST_ERROR = None
            BACKTEST_SUCCESS = False
            BACKTEST_RESULTS_DATA = None
            
        category = request.POST.get('category', 'Nifty100')
        start_str = request.POST.get('start_date')
        end_str = request.POST.get('end_date')
        capital_str = request.POST.get('capital', '1000000')
        top_n_str = request.POST.get('top_n', '20')
        freq = request.POST.get('rebalance_freq', 'M')
        cost_str = request.POST.get('transaction_cost', '0.001')
        
        try:
            start_date = datetime.strptime(start_str, "%Y-%m-%d")
            end_date = datetime.strptime(end_str, "%Y-%m-%d")
            initial_capital = float(capital_str)
            top_n = int(top_n_str)
            cost = float(cost_str)
        except (ValueError, TypeError) as e:
            with BACKTEST_LOCK:
                BACKTEST_RUNNING = False
                BACKTEST_ERROR = f"Invalid form inputs: {e}"
            messages.error(request, f"Input validation failed: {e}")
            return redirect('backtest')
            
        t = threading.Thread(
            target=_async_backtest_task,
            args=(category, start_date, end_date, top_n, freq, cost, initial_capital, request.user.id),
            daemon=True
        )
        t.start()
        messages.success(request, f"Backtest started in background for {category}.")
        return redirect('backtest')
        
    context = {
        'categories': categories,
        'backtest_running': BACKTEST_RUNNING,
        'backtest_error': BACKTEST_ERROR,
        'backtest_success': BACKTEST_SUCCESS,
        'results': BACKTEST_RESULTS_DATA,
    }
    return render(request, 'dashboard/backtest.html', context)


@login_required
def backtest_status(request):
    global BACKTEST_RUNNING, BACKTEST_ERROR, BACKTEST_SUCCESS, BACKTEST_RESULTS_DATA
    return JsonResponse({
        'running': BACKTEST_RUNNING,
        'error': BACKTEST_ERROR,
        'success': BACKTEST_SUCCESS,
        'results': BACKTEST_RESULTS_DATA
    })


@login_required
def backtest_download_report(request):
    global BACKTEST_EXPORT_PATH
    if not BACKTEST_EXPORT_PATH or not os.path.exists(BACKTEST_EXPORT_PATH):
        return HttpResponse("Report file not found. Run a backtest first.", status=404)
        
    path = Path(BACKTEST_EXPORT_PATH)
    with open(path, "rb") as f:
        response = HttpResponse(
            f.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = f"attachment; filename={path.name}"
        return response


# ─────────────────────────────────────────────────────────────────────────────
# Custom Ticker Scorer View (CLI Option [5])
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def scan_custom_view(request):
    results = None
    if request.method == 'POST' and request.FILES.get('custom_file'):
        uploaded_file = request.FILES['custom_file']
        
        temp_dir = settings.BASE_DIR / 'temp'
        temp_dir.mkdir(exist_ok=True)
        import uuid
        uid = uuid.uuid4().hex
        temp_path = temp_dir / f"custom_{uid}_{uploaded_file.name}"
        
        with open(temp_path, 'wb') as f:
            for chunk in uploaded_file.chunks():
                f.write(chunk)
                
        try:
            import pandas as pd
            if temp_path.suffix.lower() == '.csv':
                df = pd.read_csv(temp_path)
            else:
                df = pd.read_excel(temp_path)
                
            col = (
                "Symbol" if "Symbol" in df.columns
                else "symbol" if "symbol" in df.columns
                else df.columns[0]
            )
            
            tickers = []
            for ticker in df[col].dropna().unique():
                if not isinstance(ticker, str):
                    ticker = str(ticker)
                ticker = ticker.strip().upper()
                if not ticker:
                    continue
                if not ticker.endswith('.NS') and not ticker.startswith('^'):
                    ticker = f"{ticker}.NS"
                tickers.append(ticker)
                
            if not tickers:
                raise ValueError("No valid tickers found in the uploaded file.")
                
            from momentum_tracker.api import MomentumTrackerAPI
            api = MomentumTrackerAPI(user_id=request.user.id)
            
            # Cache missing symbols dynamically
            bench_tickers = [api.config["DATA_CONFIG"]["INDEX_BENCHMARK"]]
            api.db.bulk_precache(tickers, bench_tickers)
            
            # Run multi-factor momentum recommendations
            df_scores = api.strategy.top_n_recommendations(tickers, len(tickers))
            
            if df_scores is not None and not df_scores.empty:
                results = []
                for idx, r in df_scores.iterrows():
                    results.append({
                        "symbol": r.get("Symbol", idx),
                        "wms": round(float(r.get("FinalWeightedScore", 0.0)), 2),
                        "rs": round(float(r.get("RS_Raw", 0.0)), 3) if "RS_Raw" in r else "–",
                        "rsi": round(float(r.get("RSI_Raw", 0.0)), 1) if "RSI_Raw" in r else "–",
                        "mfi": round(float(r.get("MFI_Raw", 0.0)), 1) if "MFI_Raw" in r else "–",
                        "cci": round(float(r.get("CCI_Raw", 0.0)), 1) if "CCI_Raw" in r else "–",
                    })
                messages.success(request, f"Successfully scored {len(results)} tickers from your uploaded file!")
            else:
                messages.error(request, "Failed to score tickers or universe is empty.")
                
        except Exception as e:
            messages.error(request, f"Error processing file: {e}")
        finally:
            if temp_path.exists():
                temp_path.unlink()
                
    return render(request, 'dashboard/scan_custom.html', {'results': results})


# ─────────────────────────────────────────────────────────────────────────────
# Cache operations & Category creation views (CLI Options [10], [11] & [13])
# ─────────────────────────────────────────────────────────────────────────────

PRECACHE_LOCK = threading.Lock()
PRECACHE_RUNNING = False
PRECACHE_TOTAL = 0
PRECACHE_CURRENT = 0
PRECACHE_STATUS_MSG = ""
PRECACHE_ERROR = None
PRECACHE_SUCCESS = False

def _async_precache_task(user_id):
    global PRECACHE_RUNNING, PRECACHE_TOTAL, PRECACHE_CURRENT, PRECACHE_STATUS_MSG, PRECACHE_ERROR, PRECACHE_SUCCESS
    try:
        from momentum_tracker.api import MomentumTrackerAPI
        api = MomentumTrackerAPI(user_id=user_id)
        
        stock_tickers = api.loader.all_symbols()
        bench_tickers = api.loader.all_benchmark_tickers()
        
        all_tickers = list(dict.fromkeys(bench_tickers + stock_tickers))
        total_tickers = len(all_tickers)
        total_funds = len(stock_tickers)
        
        with PRECACHE_LOCK:
            PRECACHE_TOTAL = total_tickers + total_funds
            PRECACHE_CURRENT = 0
            PRECACHE_STATUS_MSG = "Starting bulk cache operations..."
            PRECACHE_ERROR = None
            PRECACHE_SUCCESS = False
            
        success_count = 0
        bench_set = set(bench_tickers)
        
        for idx, ticker in enumerate(all_tickers, 1):
            with PRECACHE_LOCK:
                PRECACHE_CURRENT = idx
                PRECACHE_STATUS_MSG = f"Downloading price data for {ticker} ({idx}/{total_tickers})"
                
            ok = api.db.ensure_price(ticker, is_benchmark=(ticker in bench_set))
            if ok:
                success_count += 1
                
        for idx, ticker in enumerate(stock_tickers, 1):
            curr_idx = total_tickers + idx
            with PRECACHE_LOCK:
                PRECACHE_CURRENT = curr_idx
                PRECACHE_STATUS_MSG = f"Downloading fundamental data for {ticker} ({idx}/{total_funds})"
                
            api.db.get_fundamental(ticker)
            
        with PRECACHE_LOCK:
            PRECACHE_RUNNING = False
            PRECACHE_STATUS_MSG = f"Caching finished! Price success: {success_count}/{total_tickers}."
            PRECACHE_SUCCESS = True
            
    except Exception as e:
        print(f"[ERROR] Precache task failed: {e}")
        with PRECACHE_LOCK:
            PRECACHE_RUNNING = False
            PRECACHE_ERROR = str(e)
            PRECACHE_SUCCESS = False


@login_required
def settings_precache(request):
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
        
    global PRECACHE_RUNNING, PRECACHE_TOTAL, PRECACHE_CURRENT, PRECACHE_STATUS_MSG, PRECACHE_ERROR, PRECACHE_SUCCESS
    
    if request.method == 'POST':
        with PRECACHE_LOCK:
            if PRECACHE_RUNNING:
                return JsonResponse({'error': 'Caching is already in progress.'}, status=400)
            PRECACHE_RUNNING = True
            PRECACHE_ERROR = None
            PRECACHE_SUCCESS = False
            PRECACHE_STATUS_MSG = "Initializing database..."
            
        t = threading.Thread(target=_async_precache_task, args=(request.user.id,), daemon=True)
        t.start()
        return JsonResponse({'success': True})
        
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required
def settings_precache_status(request):
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
        
    global PRECACHE_RUNNING, PRECACHE_TOTAL, PRECACHE_CURRENT, PRECACHE_STATUS_MSG, PRECACHE_ERROR, PRECACHE_SUCCESS
    return JsonResponse({
        'running': PRECACHE_RUNNING,
        'total': PRECACHE_TOTAL,
        'current': PRECACHE_CURRENT,
        'status_msg': PRECACHE_STATUS_MSG,
        'error': PRECACHE_ERROR,
        'success': PRECACHE_SUCCESS
    })


@login_required
def settings_clear_cache(request):
    if not request.user.is_superuser:
        messages.error(request, "Access denied.")
        return redirect('settings')
        
    if request.method == 'POST':
        try:
            from momentum_tracker.api import MomentumTrackerAPI
            api = MomentumTrackerAPI(user_id=request.user.id)
            
            years_str = request.POST.get('download_history_years', '')
            if years_str.isdigit():
                api.config["DATA_CONFIG"]["DOWNLOAD_HISTORY_YEARS"] = int(years_str)
                api.config.save(minimal=False)
                
            api.db.clear_cache()
            messages.success(request, "Database price and fundamental cache cleared successfully.")
        except Exception as e:
            messages.error(request, f"Error clearing cache: {e}")
            
    return redirect('settings')


@login_required
def settings_add_category(request):
    if not request.user.is_superuser:
        messages.error(request, "Access denied.")
        return redirect('settings')
        
    if request.method == 'POST':
        category_name = request.POST.get('category_name', '').strip()
        benchmark_ticker = request.POST.get('benchmark_ticker', '').strip()
        symbols_file = request.FILES.get('symbols_file')
        
        if not category_name or not symbols_file:
            messages.error(request, "Category Name and Tickers CSV file are required.")
            return redirect('settings')
            
        try:
            from momentum_tracker.api import MomentumTrackerAPI
            api = MomentumTrackerAPI(user_id=request.user.id)
            
            symbols_dir = Path(api.config["DATA_CONFIG"].get("SYMBOLS_DIR", "data/symbols"))
            if not symbols_dir.is_absolute():
                symbols_dir = settings.BASE_DIR / symbols_dir
            symbols_dir.mkdir(parents=True, exist_ok=True)
            
            file_name = f"ind_{category_name.lower()}list.csv"
            file_path = symbols_dir / file_name
            
            with open(file_path, 'wb') as f:
                for chunk in symbols_file.chunks():
                    f.write(chunk)
                    
            ok = api.loader.add_category(
                category_name=category_name,
                file_name=file_name,
                benchmark_ticker=benchmark_ticker or None
            )
            
            if ok:
                messages.success(request, f"Successfully created index category '{category_name}' with symbols file '{file_name}'!")
            else:
                messages.error(request, "Could not save category configuration overrides.")
                if file_path.exists():
                    file_path.unlink()
        except Exception as e:
            messages.error(request, f"Error creating category: {e}")
            
    return redirect('settings')



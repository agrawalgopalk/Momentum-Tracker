from django.apps import AppConfig
import sys
import os
import threading
import time

class DashboardConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'dashboard'

    def ready(self):
        # Prevent starting the background worker when running inside a pytest session or during commands other than runserver/gunicorn
        import sys
        if 'pytest' in sys.modules or 'pytest' in sys.argv[0] or any('pytest' in arg for arg in sys.argv):
            return

        no_worker_commands = {'test', 'migrate', 'makemigrations', 'collectstatic', 'shell'}
        if any(cmd in sys.argv for cmd in no_worker_commands):
            return
            
        # Ensure we don't start multiple threads when using development reload server
        # (reloader starts parent, then runs ready() again in the child with RUN_MAIN=true)
        if 'runserver' in sys.argv and os.environ.get('RUN_MAIN') != 'true':
            return
            
        # Start background worker thread
        t = threading.Thread(target=self.background_caching_loop, name="BackgroundPrecacheWorker", daemon=True)
        t.start()

    def background_caching_loop(self):
        from utils import get_logger
        logger = get_logger("dashboard.apps")
        logger.info("[BackgroundPrecacheWorker] Worker started. Waiting 10 seconds for boot up sequence...")
        time.sleep(10)
        
        while True:
            try:
                logger.info("[BackgroundPrecacheWorker] Starting scheduled 24h pre-cache cycle...")
                from momentum_tracker.api import MomentumTrackerAPI
                api = MomentumTrackerAPI(user_id=3)
                
                stock_tickers = api.loader.all_symbols()
                bench_tickers = api.loader.all_benchmark_tickers()
                
                if stock_tickers:
                    logger.info(f"[BackgroundPrecacheWorker] Precaching price data for {len(stock_tickers)} stocks...")
                    api.db.bulk_precache(stock_tickers, bench_tickers)
                    
                    logger.info(f"[BackgroundPrecacheWorker] Precaching fundamentals for {len(stock_tickers)} stocks...")
                    api.db.bulk_precache_fundamentals(stock_tickers)
                    
                    logger.info("[BackgroundPrecacheWorker] Warming up portfolio momentum history cache...")
                    try:
                        api.get_portfolio_momentum_history(days=30)
                        logger.info("[BackgroundPrecacheWorker] Portfolio momentum history cache successfully warmed up.")
                    except Exception as he:
                        logger.error(f"[BackgroundPrecacheWorker] Portfolio momentum history warmup failed: {he}")

                    # Catch-up daily portfolio scan if not already run today
                    try:
                        from database import get_db
                        db = get_db()
                        with db._conn() as con:
                            row = con.execute(
                                "SELECT max(run_at) as last_run FROM scan_runs WHERE category='Portfolio'"
                            ).fetchone()
                            last_run = row['last_run'] if row else None
                        
                        today_str = time.strftime("%Y-%m-%d")
                        if not last_run or last_run[:10] != today_str:
                            logger.info(f"[BackgroundPrecacheWorker] Today's portfolio scan has not run (last run: {last_run}). Running catch-up scan now...")
                            from streamlite_app.scheduler import job_portfolio_daily_scan
                            job_portfolio_daily_scan()
                            logger.info("[BackgroundPrecacheWorker] Catch-up portfolio scan completed successfully.")
                        else:
                            logger.info(f"[BackgroundPrecacheWorker] Today's portfolio scan already completed on {last_run}. Skipping catch-up.")
                    except Exception as se:
                        logger.error(f"[BackgroundPrecacheWorker] Today's portfolio scan startup check failed: {se}")
                    
                    logger.info("[BackgroundPrecacheWorker] Pre-cache run successfully finished.")
                else:
                    logger.warning("[BackgroundPrecacheWorker] No stock symbols to cache.")
                
                # Sleep for 24 hours
                time.sleep(24 * 3600)
            except Exception as e:
                logger.error(f"[BackgroundPrecacheWorker] Automatic pre-caching failed with error: {e}. Retrying in 1 hour.")
                time.sleep(3600)


"""
cleanup.py  –  Command line data cleanup utility.

Usage
─────
  python cleanup.py --help
  python cleanup.py --show-tables
  python cleanup.py --clear-alerts
  python cleanup.py --clear-reports
  python cleanup.py --clear-all
  python cleanup.py --clear-runs-before 2026-04-01
"""

import argparse
from persistence import DB, _conn


def show_tables():
    with _conn() as con:
        for table in ["scan_runs", "scans", "picks", "alerts",
                      "portfolio", "performance", "scan_reports"]:
            count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table:<20} {count:>6} rows")


def clear_alerts():
    with _conn() as con:
        con.execute("DELETE FROM alerts")
    print("Cleared all alerts.")


def clear_reports():
    with _conn() as con:
        con.execute("DELETE FROM scan_reports")
    print("Cleared all scan reports.")


def clear_runs_before(date_str: str):
    with _conn() as con:
        con.execute(
            "DELETE FROM scans WHERE run_id IN "
            "(SELECT id FROM scan_runs WHERE run_at < ?)", (date_str,)
        )
        con.execute(
            "DELETE FROM picks WHERE run_id IN "
            "(SELECT id FROM scan_runs WHERE run_at < ?)", (date_str,)
        )
        con.execute(
            "DELETE FROM scan_reports WHERE run_id IN "
            "(SELECT id FROM scan_runs WHERE run_at < ?)", (date_str,)
        )
        con.execute("DELETE FROM scan_runs WHERE run_at < ?", (date_str,))
    print(f"Cleared all scan data before {date_str}.")


def clear_all():
    with _conn() as con:
        for table in ["scan_reports", "picks", "scans",
                      "alerts", "scan_runs", "performance"]:
            con.execute(f"DELETE FROM {table}")
        # Keep portfolio — user positions must not be deleted accidentally
    print("Cleared all scan/alert/performance data. Portfolio positions preserved.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Momentum system data cleanup")
    parser.add_argument("--show-tables",        action="store_true")
    parser.add_argument("--clear-alerts",       action="store_true")
    parser.add_argument("--clear-reports",      action="store_true")
    parser.add_argument("--clear-all",          action="store_true")
    parser.add_argument("--clear-runs-before",  metavar="YYYY-MM-DD")
    args = parser.parse_args()

    if args.show_tables:
        show_tables()
    elif args.clear_alerts:
        clear_alerts()
    elif args.clear_reports:
        clear_reports()
    elif args.clear_all:
        confirm = input("This deletes ALL data except portfolio positions. Type YES to confirm: ")
        if confirm == "YES":
            clear_all()
        else:
            print("Cancelled.")
    elif args.clear_runs_before:
        clear_runs_before(args.clear_runs_before)
    else:
        parser.print_help()
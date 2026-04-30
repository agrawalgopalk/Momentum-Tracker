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
from core import get_db

from utils import get_logger, get_log_file
log = get_logger(__name__)

DB = get_db()


def show_tables():
    for table, count in DB.table_row_counts().items():
        print(f"  {table:<20} {count:>6} rows")


def clear_alerts():
    DB.clear_alerts()


def clear_reports():
    DB.clear_reports()

def clear_runs_before(date_str: str):
    DB.clear_runs_before(date_str)
    print(f"Cleared all scan data before {date_str}.")


def clear_all():
    DB.clear_all()


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
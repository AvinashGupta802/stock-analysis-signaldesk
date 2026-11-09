"""Import NSE sessions and run the saved EOD strategy after validation."""

import argparse
import sqlite3
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "stock_analysis_exchange.sqlite3"


def previous_weekday(today):
    candidate = today - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def weekdays(start_date, end_date):
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            yield current
        current += timedelta(days=1)


def dataset_counts(db_path, trade_date):
    with sqlite3.connect(db_path) as conn:
        price_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM daily_prices AS prices
            JOIN instruments AS instruments ON instruments.id = prices.instrument_id
            WHERE instruments.exchange = 'NSE' AND prices.trade_date = ?
            """,
            (trade_date,),
        ).fetchone()[0]
        delivery_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM daily_delivery AS delivery
            JOIN instruments AS instruments ON instruments.id = delivery.instrument_id
            WHERE instruments.exchange = 'NSE' AND delivery.trade_date = ?
            """,
            (trade_date,),
        ).fetchone()[0]
    return price_count, delivery_count


def latest_complete_date(db_path):
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT MAX(prices.trade_date)
            FROM daily_prices AS prices
            JOIN instruments AS instruments ON instruments.id = prices.instrument_id
            WHERE instruments.exchange = 'NSE'
              AND EXISTS (
                SELECT 1
                FROM daily_delivery AS delivery
                WHERE delivery.trade_date = prices.trade_date
              )
            """
        ).fetchone()
    return date.fromisoformat(row[0]) if row and row[0] else None


def analysis_result_count(db_path, trade_date):
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM rule_daily_results WHERE trade_date = ?",
            (trade_date,),
        ).fetchone()[0]


def run(command):
    print(f"\n> {' '.join(str(part) for part in command)}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(
        description="Import missing NSE prices and delivery data, validate them, and run EOD analysis."
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--date",
        help="Trading date in YYYY-MM-DD. Defaults to the previous weekday.",
    )
    selection.add_argument(
        "--catch-up",
        action="store_true",
        help="Process weekdays after the latest complete NSE date through the previous weekday.",
    )
    selection.add_argument("--start-date", help="First date in a catch-up range (YYYY-MM-DD).")
    parser.add_argument("--end-date", help="Last range date; defaults to the previous weekday.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path.")
    args = parser.parse_args()

    try:
        default_end = previous_weekday(date.today())
        end_date = date.fromisoformat(args.end_date) if args.end_date else default_end
        if args.date:
            targets = [date.fromisoformat(args.date)]
        elif args.catch_up:
            latest = latest_complete_date(Path(args.db).resolve())
            if not latest:
                raise SystemExit("No complete NSE date found; provide --start-date.")
            targets = list(weekdays(latest + timedelta(days=1), end_date))
        elif args.start_date:
            targets = list(weekdays(date.fromisoformat(args.start_date), end_date))
        else:
            targets = [default_end]
    except ValueError as exc:
        raise SystemExit("Dates must use YYYY-MM-DD format") from exc

    if args.end_date and not (args.catch_up or args.start_date):
        raise SystemExit("--end-date requires --catch-up or --start-date.")
    if args.date and targets[0].weekday() >= 5:
        raise SystemExit(f"{targets[0]:%Y-%m-%d} is a weekend; choose an NSE trading date.")

    db_path = Path(args.db).resolve()
    if db_path != DEFAULT_DB.resolve():
        raise SystemExit(
            "The daily pipeline currently uses the application database only: "
            f"{DEFAULT_DB}"
        )

    if not targets:
        print(f"NSE data is already caught up through {end_date:%Y-%m-%d}.")
        return

    imported_dates = []
    analyzed_dates = []
    unavailable_dates = []
    for target in targets:
        trade_date = target.isoformat()
        price_count, delivery_count = dataset_counts(db_path, trade_date)
        was_complete = bool(price_count and delivery_count)
        if not was_complete:
            run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "import_exchange_bhavcopy.py"),
                    "--exchange",
                    "NSE",
                    "--dataset",
                    "both",
                    "--date",
                    trade_date,
                    "--db",
                    str(db_path),
                ]
            )
            price_count, delivery_count = dataset_counts(db_path, trade_date)

        print(
            f"\nValidated {trade_date}: {price_count:,} price rows, "
            f"{delivery_count:,} delivery rows",
            flush=True,
        )
        if not price_count or not delivery_count:
            unavailable_dates.append(trade_date)
            print("Skipping EOD analysis because one or both NSE reports are unavailable.")
            continue

        if not was_complete:
            imported_dates.append(trade_date)
        if not was_complete or not analysis_result_count(db_path, trade_date):
            run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_eod_analysis.py"),
                    "--date",
                    trade_date,
                ]
            )
            analyzed_dates.append(trade_date)
        else:
            print("Data and EOD results already exist; skipping this date.")

    print("\nDaily NSE pipeline complete")
    print(f"Imported complete dates: {len(imported_dates)}")
    print(f"EOD dates analyzed: {len(analyzed_dates)}")
    if unavailable_dates:
        print(f"Unavailable dates (holidays or unpublished reports): {', '.join(unavailable_dates)}")


if __name__ == "__main__":
    main()

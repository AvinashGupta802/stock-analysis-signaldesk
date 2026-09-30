"""Import one NSE session and run the saved EOD strategy after validation."""

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


def run(command):
    print(f"\n> {' '.join(str(part) for part in command)}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(
        description="Import NSE prices and delivery data, validate them, and run EOD analysis."
    )
    parser.add_argument(
        "--date",
        help="Trading date in YYYY-MM-DD. Defaults to the previous weekday.",
    )
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path.")
    args = parser.parse_args()

    try:
        target = date.fromisoformat(args.date) if args.date else previous_weekday(date.today())
    except ValueError as exc:
        raise SystemExit("--date must use YYYY-MM-DD format") from exc

    if target.weekday() >= 5:
        raise SystemExit(f"{target:%Y-%m-%d} is a weekend; choose an NSE trading date.")

    trade_date = target.isoformat()
    db_path = Path(args.db).resolve()
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
        raise SystemExit(
            "EOD analysis was not run because the NSE price or delivery report is unavailable. "
            "Retry after both reports are published."
        )

    if db_path != DEFAULT_DB.resolve():
        raise SystemExit(
            "Import completed, but EOD analysis currently uses the application database only: "
            f"{DEFAULT_DB}"
        )

    run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_eod_analysis.py"),
            "--date",
            trade_date,
        ]
    )
    print(f"\nDaily NSE pipeline complete for {trade_date}")


if __name__ == "__main__":
    main()

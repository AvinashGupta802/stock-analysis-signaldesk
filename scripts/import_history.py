import argparse
import csv
import sqlite3
from datetime import datetime
from pathlib import Path


SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS stocks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL UNIQUE,
  exchange TEXT,
  source_file TEXT,
  first_trade_date TEXT,
  last_trade_date TEXT,
  row_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS daily_prices (
  stock_id INTEGER NOT NULL,
  trade_date TEXT NOT NULL,
  open REAL NOT NULL,
  high REAL NOT NULL,
  low REAL NOT NULL,
  close REAL NOT NULL,
  volume INTEGER NOT NULL DEFAULT 0,
  dividends REAL,
  stock_splits REAL,
  source_file TEXT,
  PRIMARY KEY (stock_id, trade_date),
  FOREIGN KEY (stock_id) REFERENCES stocks(id)
);

CREATE INDEX IF NOT EXISTS idx_daily_prices_date ON daily_prices(trade_date);
CREATE INDEX IF NOT EXISTS idx_daily_prices_stock_date ON daily_prices(stock_id, trade_date);
"""


def main():
    parser = argparse.ArgumentParser(description="Import per-stock EOD CSV files into SQLite.")
    parser.add_argument("--source", required=True, help="Folder containing historical CSV files")
    parser.add_argument("--db", default="data/stock_analysis.sqlite3", help="SQLite database path")
    parser.add_argument("--limit", type=int, default=0, help="Optional max number of files to import")
    args = parser.parse_args()

    source_dir = Path(args.source)
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    files = sorted(source_dir.glob("*.csv"))
    if args.limit:
        files = files[: args.limit]

    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)

    total_rows = 0
    imported_files = 0
    failed = []

    for index, file_path in enumerate(files, start=1):
        try:
            rows = list(read_price_rows(file_path))
            if not rows:
                continue
            symbol, exchange = symbol_from_filename(file_path.name)
            stock_id = upsert_stock(conn, symbol, exchange, file_path.name, rows)
            conn.executemany(
                """
                INSERT INTO daily_prices (
                  stock_id, trade_date, open, high, low, close, volume,
                  dividends, stock_splits, source_file
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(stock_id, trade_date) DO UPDATE SET
                  open = excluded.open,
                  high = excluded.high,
                  low = excluded.low,
                  close = excluded.close,
                  volume = excluded.volume,
                  dividends = excluded.dividends,
                  stock_splits = excluded.stock_splits,
                  source_file = excluded.source_file
                """,
                [
                    (
                        stock_id,
                        row["trade_date"],
                        row["open"],
                        row["high"],
                        row["low"],
                        row["close"],
                        row["volume"],
                        row["dividends"],
                        row["stock_splits"],
                        file_path.name,
                    )
                    for row in rows
                ],
            )
            total_rows += len(rows)
            imported_files += 1
            if index % 100 == 0:
                conn.commit()
                print(f"Imported {index}/{len(files)} files, {total_rows:,} rows")
        except Exception as exc:
            failed.append((file_path.name, str(exc)))

    conn.commit()
    stats = conn.execute(
        """
        SELECT COUNT(DISTINCT stock_id), COUNT(*), MIN(trade_date), MAX(trade_date)
        FROM daily_prices
        """
    ).fetchone()
    conn.close()

    print("Import complete")
    print(f"Files imported: {imported_files:,}/{len(files):,}")
    print(f"Rows imported: {stats[1]:,}")
    print(f"Stocks: {stats[0]:,}")
    print(f"Date range: {stats[2]} to {stats[3]}")
    if failed:
        print(f"Failures: {len(failed):,}")
        for name, reason in failed[:10]:
            print(f"- {name}: {reason}")


def read_price_rows(file_path):
    with file_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            trade_date = parse_trade_date(row.get("Date"))
            if not trade_date:
                continue
            open_price = to_float(row.get("Open"))
            high = to_float(row.get("High"))
            low = to_float(row.get("Low"))
            close = to_float(row.get("Close"))
            if None in (open_price, high, low, close):
                continue
            yield {
                "trade_date": trade_date,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": int(to_float(row.get("Volume")) or 0),
                "dividends": to_float(row.get("Dividends")),
                "stock_splits": to_float(row.get("Stock Splits")),
            }


def upsert_stock(conn, symbol, exchange, source_file, rows):
    first_date = rows[0]["trade_date"]
    last_date = rows[-1]["trade_date"]
    conn.execute(
        """
        INSERT INTO stocks (symbol, exchange, source_file, first_trade_date, last_trade_date, row_count)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol) DO UPDATE SET
          exchange = excluded.exchange,
          source_file = excluded.source_file,
          first_trade_date = excluded.first_trade_date,
          last_trade_date = excluded.last_trade_date,
          row_count = excluded.row_count
        """,
        (symbol, exchange, source_file, first_date, last_date, len(rows)),
    )
    return conn.execute("SELECT id FROM stocks WHERE symbol = ?", (symbol,)).fetchone()[0]


def symbol_from_filename(filename):
    stem = Path(filename).stem.upper()
    if "." in stem:
        symbol, exchange = stem.rsplit(".", 1)
        return symbol.replace("-", ""), exchange
    return stem.split("_")[0].replace("-", ""), None


def parse_trade_date(value):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.split(" ")[0]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def to_float(value):
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if not text or text.lower() in {"nan", "null", "none"}:
        return None
    return float(text)


if __name__ == "__main__":
    main()

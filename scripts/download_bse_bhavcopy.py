import argparse
import csv
import io
import sqlite3
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "stock_analysis.sqlite3"
DEFAULT_RAW_DIR = ROOT / "data" / "raw" / "bse_bhavcopy"

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS stocks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL UNIQUE,
  name TEXT,
  exchange TEXT,
  bse_code TEXT,
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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/csv,application/zip,application/octet-stream,*/*",
    "Referer": "https://www.bseindia.com/markets/MarketInfo/BhavCopy.aspx",
}


def main():
    parser = argparse.ArgumentParser(description="Download BSE equity bhavcopy and import into SQLite.")
    parser.add_argument("--date", help="Single date in YYYY-MM-DD format")
    parser.add_argument("--start-date", help="Start date in YYYY-MM-DD format")
    parser.add_argument("--end-date", help="End date in YYYY-MM-DD format")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--raw-dir", default=str(DEFAULT_RAW_DIR))
    parser.add_argument("--sleep", type=float, default=1.5)
    parser.add_argument("--no-download", action="store_true", help="Import already downloaded raw files only")
    args = parser.parse_args()

    dates = requested_dates(args)
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(args.db)
    conn.executescript(SCHEMA)
    ensure_stock_columns(conn)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_stocks_bse_code ON stocks(bse_code)")

    imported = 0
    skipped = 0
    failed = []

    for trade_date in dates:
        if trade_date.weekday() >= 5:
            skipped += 1
            continue
        try:
            csv_path = existing_csv(raw_dir, trade_date)
            if not csv_path and not args.no_download:
                csv_path = download_for_date(raw_dir, trade_date)
                time.sleep(args.sleep)
            if not csv_path:
                skipped += 1
                print(f"No BSE bhavcopy for {trade_date:%Y-%m-%d}")
                continue
            count = import_bhavcopy(conn, csv_path, trade_date)
            conn.commit()
            imported += 1
            print(f"Imported {trade_date:%Y-%m-%d}: {count:,} rows from {csv_path.name}")
        except Exception as exc:
            failed.append((trade_date.date().isoformat(), str(exc)))
            print(f"Failed {trade_date:%Y-%m-%d}: {exc}")

    stats = conn.execute(
        "SELECT COUNT(*), (SELECT COUNT(*) FROM daily_prices), MIN(first_trade_date), MAX(last_trade_date) FROM stocks"
    ).fetchone()
    conn.close()

    print("BSE bhavcopy run complete")
    print(f"Imported dates: {imported}")
    print(f"Skipped dates: {skipped}")
    print(f"Stocks: {stats[0]:,}")
    print(f"Daily rows: {stats[1]:,}")
    print(f"Date range: {stats[2]} to {stats[3]}")
    if failed:
        print(f"Failures: {len(failed)}")
        for date, reason in failed[:10]:
            print(f"- {date}: {reason}")


def requested_dates(args):
    if args.date:
        return [datetime.strptime(args.date, "%Y-%m-%d")]
    if not args.start_date or not args.end_date:
        raise SystemExit("Provide --date or both --start-date and --end-date")
    start = datetime.strptime(args.start_date, "%Y-%m-%d")
    end = datetime.strptime(args.end_date, "%Y-%m-%d")
    dates = []
    current = start
    while current <= end:
        dates.append(current)
        current += timedelta(days=1)
    return dates


def download_for_date(raw_dir, trade_date):
    urls = [
        f"https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{trade_date:%Y%m%d}_F_0000.CSV",
        f"https://www.bseindia.com/download/BhavCopy/Equity/EQ{trade_date:%d%m%y}_CSV.ZIP",
    ]
    for url in urls:
        try:
            data = fetch(url)
            if url.lower().endswith(".zip"):
                return extract_old_zip(raw_dir, trade_date, data)
            path = raw_dir / f"BhavCopy_BSE_CM_0_0_0_{trade_date:%Y%m%d}_F_0000.CSV"
            path.write_bytes(data)
            return path
        except HTTPError as exc:
            if exc.code in {403, 404}:
                continue
            raise
        except zipfile.BadZipFile:
            continue
    return None


def fetch(url):
    request = Request(url, headers=HEADERS)
    with urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise HTTPError(url, response.status, response.reason, response.headers, None)
        return response.read()


def extract_old_zip(raw_dir, trade_date, data):
    expected = f"EQ{trade_date:%d%m%y}.CSV"
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        member = expected if expected in archive.namelist() else archive.namelist()[0]
        path = raw_dir / Path(member).name
        path.write_bytes(archive.read(member))
        return path


def existing_csv(raw_dir, trade_date):
    candidates = [
        raw_dir / f"BhavCopy_BSE_CM_0_0_0_{trade_date:%Y%m%d}_F_0000.CSV",
        raw_dir / f"EQ{trade_date:%d%m%y}.CSV",
    ]
    return next((path for path in candidates if path.exists()), None)


def import_bhavcopy(conn, csv_path, trade_date):
    count = 0
    with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            parsed = parse_bse_row(row, csv_path.name, trade_date)
            if not parsed:
                continue
            stock_id = upsert_stock(conn, parsed)
            conn.execute(
                """
                INSERT INTO daily_prices (stock_id, trade_date, open, high, low, close, volume, source_file)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(stock_id, trade_date) DO UPDATE SET
                  open = excluded.open,
                  high = excluded.high,
                  low = excluded.low,
                  close = excluded.close,
                  volume = excluded.volume,
                  source_file = excluded.source_file
                """,
                (
                    stock_id,
                    parsed["trade_date"],
                    parsed["open"],
                    parsed["high"],
                    parsed["low"],
                    parsed["close"],
                    parsed["volume"],
                    parsed["source_file"],
                ),
            )
            count += 1
    return count


def parse_bse_row(row, source_file, trade_date):
    normalized = {clean_key(key): value for key, value in row.items()}
    instrument_type = pick(normalized, "FININSTRMTP", "SCTYPE")
    if instrument_type and instrument_type not in {"STK", "Q"}:
        return None
    bse_code = pick(normalized, "SCCODE", "SCRIPCD", "SCRIPCODE", "FININSTRMID")
    ticker = pick(normalized, "TCKRSYMB", "SYMBOL")
    name = pick(normalized, "SCNAME", "SCRIPNAME", "SECURITYNAME", "SECURITY", "FININSTRMNM", "TCKRSYMB")
    open_price = to_float(pick(normalized, "OPEN", "OPENPRICE", "OPENPRIC", "OPNPRIC"))
    high = to_float(pick(normalized, "HIGH", "HIGHPRICE", "HIGHPRIC", "HGHPRIC"))
    low = to_float(pick(normalized, "LOW", "LOWPRICE", "LOWPRIC", "LWPRIC"))
    close = to_float(pick(normalized, "CLOSE", "CLOSEPRICE", "CLOSPRIC", "CLSPRIC"))
    volume = int(to_float(pick(normalized, "NOOFSHRS", "NOOFSHARES", "TTLTRDQNTY", "TTLTRADGVOL", "VOLUME", "NOOFSHARE")) or 0)
    if None in (open_price, high, low, close) or not bse_code:
        return None
    symbol = clean_symbol(ticker) or clean_symbol(name) or str(bse_code).strip()
    return {
        "symbol": symbol,
        "name": clean_name(name) or symbol,
        "bse_code": str(bse_code).strip(),
        "exchange": "BSE",
        "trade_date": trade_date.date().isoformat(),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "source_file": source_file,
    }


def upsert_stock(conn, parsed):
    conn.execute(
        """
        INSERT INTO stocks (symbol, name, exchange, bse_code, source_file, first_trade_date, last_trade_date, row_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(symbol) DO UPDATE SET
          name = excluded.name,
          exchange = excluded.exchange,
          bse_code = COALESCE(stocks.bse_code, excluded.bse_code),
          source_file = excluded.source_file,
          first_trade_date = CASE
            WHEN stocks.first_trade_date IS NULL OR excluded.first_trade_date < stocks.first_trade_date THEN excluded.first_trade_date
            ELSE stocks.first_trade_date
          END,
          last_trade_date = CASE
            WHEN stocks.last_trade_date IS NULL OR excluded.last_trade_date > stocks.last_trade_date THEN excluded.last_trade_date
            ELSE stocks.last_trade_date
          END
        """,
        (
            parsed["symbol"],
            parsed["name"],
            parsed["exchange"],
            parsed["bse_code"],
            parsed["source_file"],
            parsed["trade_date"],
            parsed["trade_date"],
        ),
    )
    return conn.execute("SELECT id FROM stocks WHERE symbol = ?", (parsed["symbol"],)).fetchone()[0]


def ensure_stock_columns(conn):
    columns = {row[1] for row in conn.execute("PRAGMA table_info(stocks)")}
    if "name" not in columns:
        conn.execute("ALTER TABLE stocks ADD COLUMN name TEXT")
        conn.execute("UPDATE stocks SET name = symbol WHERE name IS NULL")
    if "bse_code" not in columns:
        conn.execute("ALTER TABLE stocks ADD COLUMN bse_code TEXT")


def clean_key(value):
    return "".join(char for char in str(value or "").upper() if char.isalnum())

def clean_symbol(value):
    text = clean_name(value).upper()
    return "".join(char for char in text if char.isalnum())[:32]


def clean_name(value):
    return str(value or "").strip()


def pick(row, *keys):
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return value
    return ""


def to_float(value):
    text = str(value or "").replace(",", "").strip()
    if not text:
        return None
    return float(text)


if __name__ == "__main__":
    main()




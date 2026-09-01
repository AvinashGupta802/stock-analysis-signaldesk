import argparse
import csv
import io
import sqlite3
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "stock_analysis_exchange.sqlite3"
DEFAULT_RAW_DIR = ROOT / "data" / "raw" / "exchange_bhavcopy"

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS instruments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  exchange TEXT NOT NULL,
  symbol TEXT NOT NULL,
  name TEXT,
  isin TEXT,
  exchange_code TEXT,
  series TEXT,
  instrument_type TEXT,
  source_file TEXT,
  first_trade_date TEXT,
  last_trade_date TEXT,
  row_count INTEGER NOT NULL DEFAULT 0,
  UNIQUE(exchange, symbol)
);

CREATE TABLE IF NOT EXISTS daily_prices (
  instrument_id INTEGER NOT NULL,
  trade_date TEXT NOT NULL,
  open REAL NOT NULL,
  high REAL NOT NULL,
  low REAL NOT NULL,
  close REAL NOT NULL,
  volume INTEGER NOT NULL DEFAULT 0,
  turnover REAL,
  trades INTEGER,
  source_file TEXT,
  PRIMARY KEY (instrument_id, trade_date),
  FOREIGN KEY (instrument_id) REFERENCES instruments(id)
);

CREATE INDEX IF NOT EXISTS idx_instruments_symbol ON instruments(symbol);
CREATE INDEX IF NOT EXISTS idx_instruments_isin ON instruments(isin);
CREATE INDEX IF NOT EXISTS idx_daily_prices_date ON daily_prices(trade_date);
CREATE INDEX IF NOT EXISTS idx_daily_prices_instrument_date ON daily_prices(instrument_id, trade_date);
"""

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/csv,application/zip,application/octet-stream,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def main():
    parser = argparse.ArgumentParser(description="Download NSE/BSE UDiFF bhavcopy and import into clean SQLite DB.")
    parser.add_argument("--exchange", choices=["NSE", "BSE", "both"], default="both")
    parser.add_argument("--date", help="Single date in YYYY-MM-DD")
    parser.add_argument("--start-date", help="Start date in YYYY-MM-DD")
    parser.add_argument("--end-date", help="End date in YYYY-MM-DD")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--raw-dir", default=str(DEFAULT_RAW_DIR))
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--no-download", action="store_true")
    args = parser.parse_args()

    dates = requested_dates(args)
    exchanges = ["NSE", "BSE"] if args.exchange == "both" else [args.exchange]
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(args.db)
    conn.executescript(SCHEMA)

    imported = 0
    skipped = 0
    failed = []

    for trade_date in dates:
        if trade_date.weekday() >= 5:
            skipped += len(exchanges)
            continue
        for exchange in exchanges:
            try:
                csv_path = existing_csv(raw_dir, exchange, trade_date)
                if not csv_path and not args.no_download:
                    csv_path = download_for_date(raw_dir, exchange, trade_date)
                    time.sleep(args.sleep)
                if not csv_path:
                    skipped += 1
                    print(f"No {exchange} bhavcopy for {trade_date:%Y-%m-%d}")
                    continue
                rows = import_file(conn, csv_path, exchange, trade_date)
                conn.commit()
                imported += 1
                print(f"Imported {exchange} {trade_date:%Y-%m-%d}: {rows:,} rows from {csv_path.name}")
            except Exception as exc:
                failed.append((exchange, trade_date.date().isoformat(), str(exc)))
                print(f"Failed {exchange} {trade_date:%Y-%m-%d}: {exc}")

    stats = conn.execute(
        """
        SELECT
          COUNT(*) AS instruments,
          (SELECT COUNT(*) FROM daily_prices) AS rows,
          (SELECT MIN(trade_date) FROM daily_prices) AS first_date,
          (SELECT MAX(trade_date) FROM daily_prices) AS last_date
        FROM instruments
        """
    ).fetchone()
    conn.close()

    print("Exchange import complete")
    print(f"Imported files: {imported}")
    print(f"Skipped files: {skipped}")
    print(f"Instruments: {stats[0]:,}")
    print(f"Daily rows: {stats[1]:,}")
    print(f"Date range: {stats[2]} to {stats[3]}")
    if failed:
        print(f"Failures: {len(failed)}")
        for exchange, date, reason in failed[:20]:
            print(f"- {exchange} {date}: {reason}")


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


def download_for_date(raw_dir, exchange, trade_date):
    exchange_dir = raw_dir / exchange
    exchange_dir.mkdir(parents=True, exist_ok=True)
    urls = urls_for(exchange, trade_date)
    for url in urls:
        try:
            data = fetch(url, exchange)
            if url.lower().endswith(".zip"):
                return extract_zip(exchange_dir, data)
            path = exchange_dir / filename_for(exchange, trade_date)
            path.write_bytes(data)
            return path
        except HTTPError as exc:
            if exc.code in {403, 404}:
                continue
            raise
        except (zipfile.BadZipFile, URLError):
            continue
    return None


def urls_for(exchange, trade_date):
    if exchange == "NSE":
        name = f"BhavCopy_NSE_CM_0_0_0_{trade_date:%Y%m%d}_F_0000.csv.zip"
        return [f"https://nsearchives.nseindia.com/content/cm/{name}"]
    name = f"BhavCopy_BSE_CM_0_0_0_{trade_date:%Y%m%d}_F_0000.CSV"
    old = f"EQ{trade_date:%d%m%y}_CSV.ZIP"
    return [
        f"https://www.bseindia.com/download/BhavCopy/Equity/{name}",
        f"https://www.bseindia.com/download/BhavCopy/Equity/{old}",
    ]


def filename_for(exchange, trade_date):
    return f"BhavCopy_{exchange}_CM_0_0_0_{trade_date:%Y%m%d}_F_0000.CSV"


def fetch(url, exchange):
    headers = dict(HEADERS)
    if exchange == "BSE":
        headers["Referer"] = "https://www.bseindia.com/markets/MarketInfo/BhavCopy.aspx"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise HTTPError(url, response.status, response.reason, response.headers, None)
        return response.read()


def extract_zip(output_dir, data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        member = next(name for name in archive.namelist() if name.lower().endswith(".csv"))
        path = output_dir / Path(member).name
        path.write_bytes(archive.read(member))
        return path


def existing_csv(raw_dir, exchange, trade_date):
    exchange_dir = raw_dir / exchange
    candidates = [exchange_dir / filename_for(exchange, trade_date)]
    if exchange == "NSE":
        candidates.append(exchange_dir / f"BhavCopy_NSE_CM_0_0_0_{trade_date:%Y%m%d}_F_0000.csv")
    else:
        candidates.append(exchange_dir / f"EQ{trade_date:%d%m%y}.CSV")
    return next((path for path in candidates if path.exists() and path.stat().st_size > 0), None)


def import_file(conn, csv_path, exchange, trade_date):
    count = 0
    with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            parsed = parse_udiff_row(row, exchange, csv_path.name, trade_date)
            if not parsed:
                continue
            instrument_id = upsert_instrument(conn, parsed)
            conn.execute(
                """
                INSERT INTO daily_prices (
                  instrument_id, trade_date, open, high, low, close, volume,
                  turnover, trades, source_file
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(instrument_id, trade_date) DO UPDATE SET
                  open = excluded.open,
                  high = excluded.high,
                  low = excluded.low,
                  close = excluded.close,
                  volume = excluded.volume,
                  turnover = excluded.turnover,
                  trades = excluded.trades,
                  source_file = excluded.source_file
                """,
                (
                    instrument_id,
                    parsed["trade_date"],
                    parsed["open"],
                    parsed["high"],
                    parsed["low"],
                    parsed["close"],
                    parsed["volume"],
                    parsed["turnover"],
                    parsed["trades"],
                    parsed["source_file"],
                ),
            )
            count += 1
    return count


def parse_udiff_row(row, exchange, source_file, fallback_date):
    normalized = {clean_key(key): value for key, value in row.items()}
    instrument_type = pick(normalized, "FININSTRMTP", "SCTYPE")
    if instrument_type and instrument_type != "STK":
        return None
    symbol = clean_symbol(pick(normalized, "TCKRSYMB", "SYMBOL"))
    exchange_code = pick(normalized, "FININSTRMID", "SCCODE", "SCRIPCD")
    name = clean_name(pick(normalized, "FININSTRMNM", "SCNAME", "SCRIPNAME", "SECURITYNAME", "TCKRSYMB"))
    isin = clean_name(pick(normalized, "ISIN"))
    series = clean_name(pick(normalized, "SCTYSRS", "SERIES"))
    open_price = to_float(pick(normalized, "OPNPRIC", "OPEN", "OPENPRICE"))
    high = to_float(pick(normalized, "HGHPRIC", "HIGH", "HIGHPRICE"))
    low = to_float(pick(normalized, "LWPRIC", "LOW", "LOWPRICE"))
    close = to_float(pick(normalized, "CLSPRIC", "CLOSE", "CLOSEPRICE"))
    volume = int(to_float(pick(normalized, "TTLTRADGVOL", "TTLTRDQNTY", "NOOFSHRS", "VOLUME")) or 0)
    turnover = to_float(pick(normalized, "TTLTRFVAL", "TTLTRDVAL", "TURNOVER"))
    trades = int(to_float(pick(normalized, "TTLNBOFTXSEXCTD", "TOTALTRADES", "NOOFTRADES")) or 0)
    trade_date = parse_date(pick(normalized, "TRADDT", "BIZDT")) or fallback_date.date().isoformat()
    if not symbol or None in (open_price, high, low, close):
        return None
    return {
        "exchange": exchange,
        "symbol": symbol,
        "name": name or symbol,
        "isin": isin,
        "exchange_code": clean_name(exchange_code),
        "series": series,
        "instrument_type": instrument_type or "STK",
        "trade_date": trade_date,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "turnover": turnover,
        "trades": trades,
        "source_file": source_file,
    }


def upsert_instrument(conn, parsed):
    conn.execute(
        """
        INSERT INTO instruments (
          exchange, symbol, name, isin, exchange_code, series, instrument_type,
          source_file, first_trade_date, last_trade_date, row_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(exchange, symbol) DO UPDATE SET
          name = excluded.name,
          isin = COALESCE(NULLIF(excluded.isin, ''), instruments.isin),
          exchange_code = COALESCE(NULLIF(excluded.exchange_code, ''), instruments.exchange_code),
          series = excluded.series,
          instrument_type = excluded.instrument_type,
          source_file = excluded.source_file,
          first_trade_date = CASE
            WHEN instruments.first_trade_date IS NULL OR excluded.first_trade_date < instruments.first_trade_date THEN excluded.first_trade_date
            ELSE instruments.first_trade_date
          END,
          last_trade_date = CASE
            WHEN instruments.last_trade_date IS NULL OR excluded.last_trade_date > instruments.last_trade_date THEN excluded.last_trade_date
            ELSE instruments.last_trade_date
          END,
          row_count = instruments.row_count + 1
        """,
        (
            parsed["exchange"],
            parsed["symbol"],
            parsed["name"],
            parsed["isin"],
            parsed["exchange_code"],
            parsed["series"],
            parsed["instrument_type"],
            parsed["source_file"],
            parsed["trade_date"],
            parsed["trade_date"],
        ),
    )
    return conn.execute(
        "SELECT id FROM instruments WHERE exchange = ? AND symbol = ?",
        (parsed["exchange"], parsed["symbol"]),
    ).fetchone()[0]


def parse_date(value):
    text = clean_name(value)
    if not text:
        return None
    return datetime.strptime(text[:10], "%Y-%m-%d").date().isoformat()


def clean_key(value):
    return "".join(char for char in str(value or "").upper() if char.isalnum())


def clean_symbol(value):
    return "".join(char for char in clean_name(value).upper() if char.isalnum())[:32]


def clean_name(value):
    return str(value or "").strip()


def pick(row, *keys):
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return value
    return ""


def to_float(value):
    text = clean_name(value).replace(",", "")
    if not text:
        return None
    return float(text)


if __name__ == "__main__":
    main()

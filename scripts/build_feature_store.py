"""Build a point-in-time NSE feature store from the application SQLite database.

Features contain only information available on each trading date. Forward-looking
outcomes are stored in a separate table to reduce accidental look-ahead leakage.
"""

import argparse
import math
import sqlite3
from datetime import datetime
from pathlib import Path

try:
    import duckdb
except ImportError as exc:
    raise SystemExit(
        "DuckDB is required. Install it with: D:\\Python311\\python.exe -m pip install duckdb"
    ) from exc


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "data" / "stock_analysis_exchange.sqlite3"
DEFAULT_STORE = ROOT / "data" / "stock_feature_store.duckdb"
DEFAULT_PARQUET = ROOT / "data" / "feature_store_parquet"

RETURN_WINDOWS = [1, 2, 3, 5, 7, 10, 15, 20, 30, 50, 60, 100, 126, 200, 252]
SMA_WINDOWS = [5, 7, 10, 15, 20, 30, 50, 60, 100, 200]
VOLUME_WINDOWS = [5, 7, 10, 15, 20, 30, 50, 60, 100, 200]
DELIVERY_WINDOWS = [5, 10, 15, 20, 30, 50, 60]
VOLATILITY_WINDOWS = [5, 10, 15, 20, 30, 50, 60, 100]
RANGE_WINDOWS = [5, 10, 15, 20, 30, 50, 60, 100]
OUTCOME_WINDOWS = [2, 5, 10, 15, 20, 30]
FEATURE_VERSION = 1


def main():
    parser = argparse.ArgumentParser(description="Build the SignalDesk research feature store.")
    parser.add_argument("--source-db", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--store-db", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--from-date", default="2024-07-08")
    parser.add_argument("--to-date", default="", help="Inclusive date; defaults to latest source date")
    parser.add_argument("--symbols", default="", help="Comma-separated symbols for a test or partial run")
    parser.add_argument("--incremental", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--export-parquet", action="store_true")
    parser.add_argument("--parquet-dir", type=Path, default=DEFAULT_PARQUET)
    parser.add_argument("--batch-size", type=int, default=2_000)
    args = parser.parse_args()

    if not args.source_db.exists():
        raise SystemExit(f"Source database not found: {args.source_db}")
    args.store_db.parent.mkdir(parents=True, exist_ok=True)
    if args.rebuild and args.store_db.exists():
        args.store_db.unlink()

    definitions = feature_definitions()
    source = sqlite3.connect(args.source_db)
    source.row_factory = sqlite3.Row
    store = duckdb.connect(str(args.store_db))
    try:
        ensure_schema(store, definitions)
        register_catalog(store, definitions)
        to_date = args.to_date or source.execute("SELECT MAX(trade_date) FROM daily_prices").fetchone()[0]
        from_date = incremental_start(store, args.from_date) if args.incremental else args.from_date
        symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
        instruments = load_instruments(source, symbols)
        print(
            f"Feature store: {args.store_db}\nMode: {'incremental' if args.incremental else 'backfill'}\n"
            f"Date range to write: {from_date} to {to_date}\nInstruments: {len(instruments):,}\n"
            f"Feature metrics: {len(definitions):,}; outcome labels: {len(OUTCOME_WINDOWS) * 3:,}",
            flush=True,
        )

        feature_columns = [item["metric_id"] for item in definitions]
        feature_sql = insert_sql("feature_values", ["instrument_id", "symbol", "trade_date", "feature_version", *feature_columns])
        outcome_columns = outcome_column_names()
        outcome_sql = insert_sql("outcome_labels", ["instrument_id", "symbol", "trade_date", *outcome_columns])
        feature_batch = []
        outcome_batch = []
        feature_count = 0
        outcome_count = 0

        for number, instrument in enumerate(instruments, 1):
            rows = load_history(source, instrument["id"], to_date)
            if not rows:
                continue
            feature_rows, outcome_rows = calculate_instrument(
                instrument, rows, from_date, to_date, feature_columns
            )
            feature_batch.extend(feature_rows)
            outcome_batch.extend(outcome_rows)
            if len(feature_batch) >= args.batch_size:
                store.executemany(feature_sql, feature_batch)
                feature_count += len(feature_batch)
                feature_batch.clear()
            if len(outcome_batch) >= args.batch_size:
                store.executemany(outcome_sql, outcome_batch)
                outcome_count += len(outcome_batch)
                outcome_batch.clear()
            if number % 100 == 0 or number == len(instruments):
                print(f"Processed {number:,}/{len(instruments):,} instruments", flush=True)

        if feature_batch:
            store.executemany(feature_sql, feature_batch)
            feature_count += len(feature_batch)
        if outcome_batch:
            store.executemany(outcome_sql, outcome_batch)
            outcome_count += len(outcome_batch)
        record_run(store, args, from_date, to_date, feature_count, outcome_count)
        print(f"Feature rows written: {feature_count:,}\nOutcome rows written: {outcome_count:,}", flush=True)

        if args.export_parquet:
            export_parquet(store, args.parquet_dir)
            print(f"Parquet export: {args.parquet_dir}", flush=True)
        print("Feature-store build complete", flush=True)
    finally:
        store.close()
        source.close()


def feature_definitions():
    items = []

    def add(metric_id, name, category, description, minimum_history=1, source="price"):
        items.append({
            "metric_id": metric_id, "name": name, "category": category,
            "description": description, "minimum_history": minimum_history,
            "source": source, "feature_version": FEATURE_VERSION,
        })

    for metric_id, name, category in [
        ("open_price", "Open price", "Price"), ("high_price", "High price", "Price"),
        ("low_price", "Low price", "Price"), ("close_price", "Close price", "Price"),
        ("volume", "Traded volume", "Volume"), ("turnover", "Turnover", "Liquidity"),
        ("gap_open_pct", "Opening gap %", "Price Action"),
        ("intraday_return_pct", "Open-to-close return %", "Price Action"),
        ("intraday_range_pct", "Daily high-low range %", "Volatility"),
        ("close_position_day_pct", "Close position in daily range %", "Price Action"),
        ("delivery_pct", "Delivery percentage", "Delivery"),
        ("deliverable_qty", "Delivered quantity", "Delivery"),
    ]:
        add(metric_id, name, category, f"Point-in-time {name.lower()}.", source="delivery" if "delivery" in metric_id else "price")
    for window in RETURN_WINDOWS:
        add(f"return_{window}d_pct", f"{window}D return %", "Momentum", f"Close return over {window} trading sessions.", window + 1)
    for window in SMA_WINDOWS:
        add(f"sma_{window}", f"SMA {window}", "Moving Average", f"Simple average close over {window} sessions.", window)
        add(f"close_vs_sma_{window}_pct", f"Close vs SMA{window} %", "Moving Average", f"Close distance from SMA{window}.", window)
        add(f"sma_{window}_slope_3d_pct", f"SMA{window} 3D slope %", "Moving Average", f"Percentage change in SMA{window} over three sessions.", window + 3)
    for window in VOLUME_WINDOWS:
        add(f"avg_volume_{window}d", f"Average volume {window}D", "Volume", f"Average traded volume over preceding {window} sessions.", window + 1)
        add(f"volume_ratio_{window}d", f"Volume / {window}D average", "Volume", f"Current volume divided by preceding {window}D average.", window + 1)
    for window in DELIVERY_WINDOWS:
        add(f"avg_delivery_qty_{window}d", f"Average delivery quantity {window}D", "Delivery", f"Average available delivered quantity over preceding {window} sessions.", window + 1, "delivery")
        add(f"delivery_qty_ratio_{window}d", f"Delivery quantity / {window}D average", "Delivery", f"Current delivered quantity divided by preceding {window}D average.", window + 1, "delivery")
    for window in VOLATILITY_WINDOWS:
        add(f"return_volatility_{window}d_pct", f"Return volatility {window}D %", "Volatility", f"Population standard deviation of daily returns over {window} sessions.", window + 1)
    for window in RANGE_WINDOWS:
        add(f"distance_from_high_{window}d_pct", f"Distance from {window}D high %", "Range", f"Percentage below the highest high over {window} sessions.", window)
        add(f"distance_from_low_{window}d_pct", f"Distance from {window}D low %", "Range", f"Percentage above the lowest low over {window} sessions.", window)
        add(f"range_position_{window}d_pct", f"Position in {window}D range %", "Range", f"Close position between the {window}D low and high.", window)
    return items


def ensure_schema(store, definitions):
    store.execute("""
        CREATE TABLE IF NOT EXISTS metric_catalog (
          metric_id VARCHAR PRIMARY KEY, name VARCHAR, category VARCHAR, description VARCHAR,
          minimum_history INTEGER, source VARCHAR, feature_version INTEGER, enabled BOOLEAN
        )
    """)
    feature_columns = ",\n".join(f'"{item["metric_id"]}" DOUBLE' for item in definitions)
    store.execute(f"""
        CREATE TABLE IF NOT EXISTS feature_values (
          instrument_id BIGINT, symbol VARCHAR, trade_date DATE, feature_version INTEGER,
          {feature_columns}, PRIMARY KEY (instrument_id, trade_date)
        )
    """)
    outcome_columns = ",\n".join(f'"{name}" DOUBLE' for name in outcome_column_names())
    store.execute(f"""
        CREATE TABLE IF NOT EXISTS outcome_labels (
          instrument_id BIGINT, symbol VARCHAR, trade_date DATE,
          {outcome_columns}, PRIMARY KEY (instrument_id, trade_date)
        )
    """)
    store.execute("""
        CREATE TABLE IF NOT EXISTS feature_build_runs (
          run_at TIMESTAMP, feature_version INTEGER, mode VARCHAR, from_date DATE, to_date DATE,
          feature_rows BIGINT, outcome_rows BIGINT, source_db VARCHAR
        )
    """)


def register_catalog(store, definitions):
    store.executemany(
        "INSERT OR REPLACE INTO metric_catalog VALUES (?, ?, ?, ?, ?, ?, ?, TRUE)",
        [[item[key] for key in ("metric_id", "name", "category", "description", "minimum_history", "source", "feature_version")] for item in definitions],
    )


def load_instruments(source, symbols):
    sql = """
        SELECT id, symbol, name FROM instruments
        WHERE exchange = 'NSE' AND series = 'EQ' AND isin LIKE 'INE%'
    """
    params = []
    if symbols:
        sql += f" AND symbol IN ({','.join('?' for _ in symbols)})"
        params.extend(symbols)
    sql += " ORDER BY symbol"
    return source.execute(sql, params).fetchall()


def load_history(source, instrument_id, to_date):
    return source.execute("""
        SELECT p.trade_date, p.open, p.high, p.low, p.close, p.volume, p.turnover,
               d.deliverable_qty, d.delivery_pct
        FROM daily_prices p
        LEFT JOIN daily_delivery d
          ON d.instrument_id = p.instrument_id AND d.trade_date = p.trade_date
        WHERE p.instrument_id = ? AND p.trade_date <= ?
        ORDER BY p.trade_date
    """, (instrument_id, to_date)).fetchall()


def calculate_instrument(instrument, rows, from_date, to_date, feature_columns):
    closes = [float(row["close"]) for row in rows]
    highs = [float(row["high"]) for row in rows]
    lows = [float(row["low"]) for row in rows]
    volumes = [float(row["volume"] or 0) for row in rows]
    deliveries = [optional_float(row["deliverable_qty"]) for row in rows]
    daily_returns = [None] + [percent(closes[index], closes[index - 1]) for index in range(1, len(rows))]
    close_prefix = prefix_sum(closes)
    volume_prefix = prefix_sum(volumes)
    delivery_prefix, delivery_count = optional_prefix(deliveries)
    features = []
    outcomes = []

    for index, row in enumerate(rows):
        trade_date = row["trade_date"]
        if trade_date < from_date or trade_date > to_date:
            continue
        values = base_features(rows, index)
        for window in RETURN_WINDOWS:
            values[f"return_{window}d_pct"] = percent(closes[index], closes[index - window]) if index >= window else None
        for window in SMA_WINDOWS:
            sma = rolling_average(close_prefix, index, window, include_current=True)
            previous_sma = rolling_average(close_prefix, index - 3, window, include_current=True)
            values[f"sma_{window}"] = sma
            values[f"close_vs_sma_{window}_pct"] = percent(closes[index], sma)
            values[f"sma_{window}_slope_3d_pct"] = percent(sma, previous_sma)
        for window in VOLUME_WINDOWS:
            average_volume = rolling_average(volume_prefix, index, window, include_current=False)
            values[f"avg_volume_{window}d"] = average_volume
            values[f"volume_ratio_{window}d"] = divide(volumes[index], average_volume)
        for window in DELIVERY_WINDOWS:
            average_delivery = rolling_optional_average(delivery_prefix, delivery_count, index, window)
            values[f"avg_delivery_qty_{window}d"] = average_delivery
            values[f"delivery_qty_ratio_{window}d"] = divide(deliveries[index], average_delivery)
        for window in VOLATILITY_WINDOWS:
            sample = [value for value in daily_returns[max(1, index - window + 1):index + 1] if value is not None]
            values[f"return_volatility_{window}d_pct"] = population_std(sample) if len(sample) >= window else None
        for window in RANGE_WINDOWS:
            if index + 1 < window:
                high = low = None
            else:
                high = max(highs[index - window + 1:index + 1])
                low = min(lows[index - window + 1:index + 1])
            values[f"distance_from_high_{window}d_pct"] = percent(closes[index], high)
            values[f"distance_from_low_{window}d_pct"] = percent(closes[index], low)
            values[f"range_position_{window}d_pct"] = range_position(closes[index], low, high)
        features.append((instrument["id"], instrument["symbol"], trade_date, FEATURE_VERSION, *[values.get(column) for column in feature_columns]))

        labels = outcome_values(rows, index)
        if any(value is not None for value in labels):
            outcomes.append((instrument["id"], instrument["symbol"], trade_date, *labels))
    return features, outcomes


def base_features(rows, index):
    row = rows[index]
    previous_close = float(rows[index - 1]["close"]) if index else None
    low = float(row["low"])
    high = float(row["high"])
    return {
        "open_price": row["open"], "high_price": row["high"], "low_price": row["low"],
        "close_price": row["close"], "volume": row["volume"], "turnover": row["turnover"],
        "gap_open_pct": percent(float(row["open"]), previous_close),
        "intraday_return_pct": percent(float(row["close"]), float(row["open"])),
        "intraday_range_pct": percent(high, low),
        "close_position_day_pct": range_position(float(row["close"]), low, high),
        "delivery_pct": row["delivery_pct"], "deliverable_qty": row["deliverable_qty"],
    }


def outcome_column_names():
    return [name for window in OUTCOME_WINDOWS for name in (
        f"forward_return_{window}d_pct", f"mfe_{window}d_pct", f"mae_{window}d_pct"
    )]


def outcome_values(rows, index):
    close = float(rows[index]["close"])
    values = []
    for window in OUTCOME_WINDOWS:
        if index + window >= len(rows):
            values.extend([None, None, None])
            continue
        future = rows[index + 1:index + window + 1]
        values.extend([
            percent(float(rows[index + window]["close"]), close),
            percent(max(float(row["high"]) for row in future), close),
            percent(min(float(row["low"]) for row in future), close),
        ])
    return values


def incremental_start(store, fallback):
    dates = store.execute(
        "SELECT DISTINCT trade_date FROM feature_values ORDER BY trade_date DESC LIMIT ?",
        [max(OUTCOME_WINDOWS) + 1],
    ).fetchall()
    if not dates:
        return fallback
    return min(row[0] for row in dates).isoformat()


def insert_sql(table, columns):
    names = ", ".join(f'"{column}"' for column in columns)
    placeholders = ", ".join("?" for _ in columns)
    return f"INSERT OR REPLACE INTO {table} ({names}) VALUES ({placeholders})"


def record_run(store, args, from_date, to_date, feature_rows, outcome_rows):
    store.execute(
        "INSERT INTO feature_build_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [datetime.now(), FEATURE_VERSION, "incremental" if args.incremental else "backfill",
         from_date, to_date, feature_rows, outcome_rows, str(args.source_db)],
    )


def export_parquet(store, directory):
    directory.mkdir(parents=True, exist_ok=True)
    feature_path = str(directory / "features.parquet").replace("'", "''")
    outcome_path = str(directory / "outcomes.parquet").replace("'", "''")
    catalog_path = str(directory / "metric_catalog.parquet").replace("'", "''")
    store.execute(f"COPY feature_values TO '{feature_path}' (FORMAT PARQUET, COMPRESSION ZSTD, OVERWRITE TRUE)")
    store.execute(f"COPY outcome_labels TO '{outcome_path}' (FORMAT PARQUET, COMPRESSION ZSTD, OVERWRITE TRUE)")
    store.execute(f"COPY metric_catalog TO '{catalog_path}' (FORMAT PARQUET, COMPRESSION ZSTD, OVERWRITE TRUE)")


def prefix_sum(values):
    output = [0.0]
    for value in values:
        output.append(output[-1] + float(value or 0))
    return output


def optional_prefix(values):
    totals = [0.0]
    counts = [0]
    for value in values:
        totals.append(totals[-1] + (value or 0))
        counts.append(counts[-1] + (1 if value is not None else 0))
    return totals, counts


def rolling_average(prefix, index, window, include_current):
    end = index + 1 if include_current else index
    start = end - window
    return (prefix[end] - prefix[start]) / window if start >= 0 else None


def rolling_optional_average(totals, counts, index, window):
    end = index
    start = end - window
    if start < 0:
        return None
    count = counts[end] - counts[start]
    return (totals[end] - totals[start]) / count if count else None


def optional_float(value):
    return float(value) if value is not None else None


def percent(value, baseline):
    if value is None or baseline in (None, 0):
        return None
    return ((value / baseline) - 1) * 100


def divide(value, baseline):
    if value is None or baseline in (None, 0):
        return None
    return value / baseline


def range_position(value, low, high):
    if value is None or low is None or high is None or high == low:
        return None
    return ((value - low) / (high - low)) * 100


def population_std(values):
    if not values:
        return None
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


if __name__ == "__main__":
    main()

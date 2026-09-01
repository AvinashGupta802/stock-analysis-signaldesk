import argparse
import csv
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from backtest_exchange_eod import avg, ema_series, load_instruments, load_rows, pct, rsi_series


def main():
    parser = argparse.ArgumentParser(description="Mine common pre-move factors before NSE 5-day shoot-up events.")
    parser.add_argument("--db", default="data/stock_analysis_exchange.sqlite3")
    parser.add_argument("--from-date", default="2024-08-15")
    parser.add_argument("--to-date", default="2026-08-24")
    parser.add_argument("--future-gain", type=float, default=15)
    parser.add_argument("--max-future-gain", type=float, default=80)
    parser.add_argument("--min-price", type=float, default=100)
    parser.add_argument("--max-price", type=float, default=1000)
    parser.add_argument("--min-rupee-volume-cr", type=float, default=5)
    parser.add_argument("--max-events", type=int, default=2500)
    parser.add_argument("--focus-symbol", default="ARIES")
    parser.add_argument("--output", default="outputs/breakout_factor_events.csv")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    instruments = load_instruments(conn, "NSE")

    all_events = []
    focus_events = []
    processed = 0
    for instrument in instruments:
        rows = [dict(row) for row in load_rows(conn, instrument["id"])]
        if len(rows) < 80:
            continue
        events = find_events(instrument, rows, args)
        all_events.extend(events)
        if instrument["symbol"].upper() == args.focus_symbol.upper():
            focus_events = events
        processed += 1
        if processed % 500 == 0:
            print(f"Scanned {processed:,} NSE instruments, found {len(all_events):,} events")
    conn.close()

    all_events = sorted(all_events, key=lambda row: (row["future_gain_5d"], row["rel_volume"]), reverse=True)[:args.max_events]
    write_events(Path(args.output), all_events)
    print_report(processed, all_events, focus_events, args)
    print(f"CSV: {args.output}")


def find_events(instrument, rows, args):
    closes = [row["close"] for row in rows]
    highs = [row["high"] for row in rows]
    lows = [row["low"] for row in rows]
    volumes = [row["volume"] for row in rows]
    ema9 = ema_series(closes, 9)
    ema20 = ema_series(closes, 20)
    rsi14 = rsi_series(closes, 14)
    events = []

    for i in range(60, len(rows) - 5):
        row = rows[i]
        if row["trade_date"] < args.from_date or row["trade_date"] > args.to_date:
            continue
        future_high = max(item["high"] for item in rows[i + 1:i + 6])
        future_gain = pct(future_high, row["close"])
        if future_gain < args.future_gain or future_gain > args.max_future_gain:
            continue
        avg_volume20 = avg(volumes[i - 20:i])
        rupee_volume_cr = (row["close"] * avg_volume20) / 10_000_000
        if row["close"] < args.min_price or row["close"] > args.max_price:
            continue
        if rupee_volume_cr < args.min_rupee_volume_cr:
            continue
        day_range = max(row["high"] - row["low"], 0.01)
        high20 = max(highs[i - 19:i + 1])
        low20 = min(lows[i - 19:i + 1])
        high60_prior = max(highs[i - 60:i])
        volume5 = avg(volumes[i - 5:i])
        features = {
            "symbol": instrument["symbol"],
            "name": instrument["name"],
            "setup_date": row["trade_date"],
            "close": row["close"],
            "future_gain_5d": future_gain,
            "future_close_return_5d": pct(rows[i + 5]["close"], row["close"]),
            "change_1d": pct(row["close"], closes[i - 1]),
            "change_3d": pct(row["close"], closes[i - 3]),
            "change_5d": pct(row["close"], closes[i - 5]),
            "rel_volume": volumes[i] / avg_volume20 if avg_volume20 else 0,
            "vol5_vs_vol20": volume5 / avg_volume20 if avg_volume20 else 0,
            "rsi14": rsi14[i],
            "above_ema9": row["close"] > ema9[i],
            "above_ema20": row["close"] > ema20[i],
            "ema9_above_ema20": ema9[i] > ema20[i],
            "dist_ema9": pct(row["close"], ema9[i]),
            "dist_ema20": pct(row["close"], ema20[i]),
            "near_20d_high": pct(row["close"], high20),
            "above_60d_high": row["close"] >= high60_prior,
            "close_position": (row["close"] - row["low"]) / day_range,
            "range_pct": ((row["high"] - row["low"]) / row["close"]) * 100 if row["close"] else 0,
            "from_20d_low": pct(row["close"], low20),
            "rupee_volume_cr": rupee_volume_cr,
        }
        features.update(flag_features(features))
        events.append(features)
    return events


def flag_features(row):
    return {
        "flag_price_100_500": 100 <= row["close"] <= 500,
        "flag_adv_liquid": row["rupee_volume_cr"] >= 20,
        "flag_rel_volume_1_2": row["rel_volume"] >= 1.2,
        "flag_rel_volume_1_5": row["rel_volume"] >= 1.5,
        "flag_rsi_50_68": 50 <= row["rsi14"] <= 68,
        "flag_rsi_50_72": 50 <= row["rsi14"] <= 72,
        "flag_roc3_1_5": row["change_3d"] >= 1.5,
        "flag_roc3_3": row["change_3d"] >= 3,
        "flag_roc3_4": row["change_3d"] >= 4,
        "flag_above_ema_stack": row["above_ema9"] and row["above_ema20"] and row["ema9_above_ema20"],
        "flag_near_20d_high": row["near_20d_high"] >= -2,
        "flag_close_upper_half": row["close_position"] >= 0.5,
        "flag_close_top_quarter": row["close_position"] >= 0.75,
        "flag_not_extended_ema9": row["dist_ema9"] <= 5,
    }


def write_events(path, events):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not events:
        return
    fieldnames = list(events[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for event in events:
            writer.writerow({key: round(value, 4) if isinstance(value, float) else value for key, value in event.items()})


def print_report(processed, events, focus_events, args):
    print("Breakout factor mining complete")
    print(f"Exchange: NSE")
    print(f"Instruments processed: {processed:,}")
    print(f"Future gain threshold: >= {args.future_gain:g}% high within next 5 trading days")
    print(f"Filters: price {args.min_price:g}-{args.max_price:g}, rupee liquidity >= {args.min_rupee_volume_cr:g}cr, max future gain <= {args.max_future_gain:g}%")
    print(f"Events analysed: {len(events):,}")
    if not events:
        return
    print_summary(events)
    print_flags(events)
    print_top_examples(events[:20])
    print_focus(args.focus_symbol, focus_events)


def print_summary(events):
    print("Averages before shoot-up:")
    for key, label in [
        ("future_gain_5d", "Future 5D high gain"),
        ("future_close_return_5d", "Future 5D close return"),
        ("change_1d", "1D change"),
        ("change_3d", "3D change"),
        ("change_5d", "5D change"),
        ("rel_volume", "Relative volume"),
        ("vol5_vs_vol20", "5D volume / 20D volume"),
        ("rsi14", "RSI 14"),
        ("dist_ema9", "Distance from EMA9"),
        ("dist_ema20", "Distance from EMA20"),
        ("near_20d_high", "Close vs 20D high"),
        ("close_position", "Close position"),
        ("rupee_volume_cr", "Rupee liquidity cr"),
    ]:
        print(f"  {label}: {avg([row[key] for row in events]):+.2f}")


def print_flags(events):
    flags = [key for key in events[0] if key.startswith("flag_")]
    rates = sorted(
        [(flag, avg([1 if row[flag] else 0 for row in events]) * 100) for flag in flags],
        key=lambda item: item[1],
        reverse=True,
    )
    print("Common factor hit rates:")
    for flag, rate in rates:
        print(f"  {flag}: {rate:.2f}%")


def print_top_examples(events):
    print("Top examples:")
    for row in events[:20]:
        print(
            f"  {row['setup_date']} {row['symbol']}: future_high={row['future_gain_5d']:+.2f}%, "
            f"roc3={row['change_3d']:+.2f}%, rvol={row['rel_volume']:.2f}, rsi={row['rsi14']:.2f}, "
            f"ema9dist={row['dist_ema9']:+.2f}%"
        )


def print_focus(symbol, events):
    print(f"{symbol.upper()} events:")
    if not events:
        print("  No matching events found for this threshold/date range.")
        return
    for row in sorted(events, key=lambda item: item["setup_date"])[-12:]:
        print(
            f"  {row['setup_date']}: close={row['close']:.2f}, future_high={row['future_gain_5d']:+.2f}%, "
            f"roc3={row['change_3d']:+.2f}%, rvol={row['rel_volume']:.2f}, rsi={row['rsi14']:.2f}, "
            f"near20h={row['near_20d_high']:+.2f}%, closepos={row['close_position']:.2f}"
        )


if __name__ == "__main__":
    main()

import argparse
import csv
import sqlite3
from collections import defaultdict
from itertools import product
from pathlib import Path

from backtest_exchange_eod import atr_series, avg, ema_series, load_instruments, load_rows, pct, rsi_series


def main():
    parser = argparse.ArgumentParser(description="Sweep short-term long-entry thresholds against EOD exchange data.")
    parser.add_argument("--db", default="data/stock_analysis_exchange.sqlite3")
    parser.add_argument("--exchange", choices=["NSE", "BSE", "all"], default="NSE")
    parser.add_argument("--from-date", default="2024-08-15")
    parser.add_argument("--to-date", default="2026-08-24")
    parser.add_argument("--min-price", type=float, default=100)
    parser.add_argument("--max-price", type=float, default=500)
    parser.add_argument("--min-adv20", type=float, default=1_000_000)
    parser.add_argument("--min-trades", type=int, default=100)
    parser.add_argument("--output", default="outputs/velocity_long_sweep.csv")
    args = parser.parse_args()

    combos = build_combos()
    stats = {combo_key(combo): new_stat(combo) for combo in combos}

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    instruments = load_instruments(conn, args.exchange)

    processed = 0
    candidate_days = 0
    for instrument in instruments:
        rows = load_rows(conn, instrument["id"])
        if len(rows) < 60:
            continue
        candidate_days += sweep_instrument(rows, args, combos, stats)
        processed += 1
        if processed % 500 == 0:
            print(f"Swept {processed:,} instruments, {candidate_days:,} base candidate days")

    conn.close()
    ranked = rank_stats(stats.values(), args.min_trades)
    write_output(Path(args.output), ranked)
    print("Sweep complete")
    print(f"Exchange: {args.exchange}")
    print(f"Instruments processed: {processed:,}")
    print(f"Base candidate days: {candidate_days:,}")
    print(f"Combinations tested: {len(combos):,}")
    print(f"Combinations with >= {args.min_trades:,} trades: {len(ranked):,}")
    print_top(ranked[:15])
    print(f"CSV: {args.output}")


def build_combos():
    grid = {
        "roc3_min": [1.5, 2.0, 3.0, 4.0],
        "rel_volume_min": [1.2, 1.5, 2.0],
        "rsi_max": [68, 72, 78],
        "rupee_volume_cr": [20, 50],
        "ema9_dist_max": [5, 8],
        "close_position_min": [0.5, 0.6],
    }
    keys = list(grid)
    return [dict(zip(keys, values)) for values in product(*(grid[key] for key in keys))]


def sweep_instrument(rows, args, combos, stats):
    closes = [r["close"] for r in rows]
    volumes = [r["volume"] for r in rows]
    ema9 = ema_series(closes, 9)
    ema20 = ema_series(closes, 20)
    rsi14 = rsi_series(closes, 14)
    atr14 = atr_series(rows, 14)
    candidate_days = 0

    for i in range(50, len(rows) - 5):
        row = rows[i]
        close = row["close"]
        if row["trade_date"] < args.from_date or row["trade_date"] > args.to_date:
            continue
        if close < args.min_price or (args.max_price and close > args.max_price):
            continue

        avg_volume20 = avg(volumes[i - 20:i])
        if avg_volume20 < args.min_adv20:
            continue

        rel_volume = volumes[i] / avg_volume20 if avg_volume20 else 0
        rupee_volume_cr = (close * avg_volume20) / 10_000_000
        roc3 = pct(close, closes[i - 3])
        sma50 = avg(closes[i - 50:i])
        dist_ema9 = pct(close, ema9[i])
        dist_ema20 = pct(close, ema20[i])
        day_range = max(row["high"] - row["low"], 0.01)
        close_position = (close - row["low"]) / day_range

        if not (close > ema9[i] and close > ema20[i] and ema20[i] > sma50):
            continue
        if not (dist_ema20 <= 12 and 45 <= rsi14[i] <= 82 and roc3 > 0 and rel_volume >= 1.0):
            continue

        candidate_days += 1
        metrics = {
            "roc3": roc3,
            "rel_volume": rel_volume,
            "rsi": rsi14[i],
            "rupee_volume_cr": rupee_volume_cr,
            "dist_ema9": dist_ema9,
            "close_position": close_position,
            "ret_2d": pct(rows[i + 2]["close"], close),
            "ret_3d": pct(rows[i + 3]["close"], close),
            "ret_5d": pct(rows[i + 5]["close"], close),
            "max_upside_5d": pct(max(r["high"] for r in rows[i + 1:i + 6]), close),
            "max_drawdown_5d": pct(min(r["low"] for r in rows[i + 1:i + 6]), close),
            "atr_stop_pct": ((2 * atr14[i]) / close) * 100 if close and atr14[i] else 0,
        }
        for combo in combos:
            if passes_combo(metrics, combo):
                update_stat(stats[combo_key(combo)], metrics)

    return candidate_days


def passes_combo(metrics, combo):
    return (
        metrics["roc3"] >= combo["roc3_min"]
        and metrics["roc3"] <= 12
        and metrics["rel_volume"] >= combo["rel_volume_min"]
        and metrics["rsi"] < combo["rsi_max"]
        and metrics["rupee_volume_cr"] >= combo["rupee_volume_cr"]
        and metrics["dist_ema9"] <= combo["ema9_dist_max"]
        and metrics["close_position"] >= combo["close_position_min"]
    )


def new_stat(combo):
    row = dict(combo)
    row.update({
        "signals": 0,
        "sum_2d": 0,
        "hit_2d": 0,
        "sum_3d": 0,
        "hit_3d": 0,
        "sum_5d": 0,
        "hit_5d": 0,
        "sum_upside_5d": 0,
        "sum_drawdown_5d": 0,
        "sum_atr_stop_pct": 0,
    })
    return row


def update_stat(stat, metrics):
    stat["signals"] += 1
    for horizon in ["2d", "3d", "5d"]:
        value = metrics[f"ret_{horizon}"]
        stat[f"sum_{horizon}"] += value
        stat[f"hit_{horizon}"] += 1 if value > 0 else 0
    stat["sum_upside_5d"] += metrics["max_upside_5d"]
    stat["sum_drawdown_5d"] += metrics["max_drawdown_5d"]
    stat["sum_atr_stop_pct"] += metrics["atr_stop_pct"]


def rank_stats(rows, min_trades):
    out = []
    for row in rows:
        signals = row["signals"]
        if signals < min_trades:
            continue
        result = {key: row[key] for key in [
            "roc3_min", "rel_volume_min", "rsi_max", "rupee_volume_cr", "ema9_dist_max", "close_position_min", "signals"
        ]}
        for horizon in ["2d", "3d", "5d"]:
            result[f"avg_{horizon}"] = row[f"sum_{horizon}"] / signals
            result[f"hit_{horizon}"] = row[f"hit_{horizon}"] / signals
        result["avg_upside_5d"] = row["sum_upside_5d"] / signals
        result["avg_drawdown_5d"] = row["sum_drawdown_5d"] / signals
        result["avg_atr_stop_pct"] = row["sum_atr_stop_pct"] / signals
        result["quality_score"] = result["avg_5d"] + (result["hit_5d"] - 0.5) + (signals ** 0.5 / 100)
        out.append(result)
    return sorted(out, key=lambda r: (r["quality_score"], r["avg_5d"], r["signals"]), reverse=True)


def write_output(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "roc3_min", "rel_volume_min", "rsi_max", "rupee_volume_cr", "ema9_dist_max", "close_position_min",
        "signals", "avg_2d", "hit_2d", "avg_3d", "hit_3d", "avg_5d", "hit_5d",
        "avg_upside_5d", "avg_drawdown_5d", "avg_atr_stop_pct", "quality_score",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: round(row[key], 4) if isinstance(row[key], float) else row[key] for key in fieldnames})


def print_top(rows):
    for index, row in enumerate(rows, start=1):
        print(
            f"{index:02d}. signals={row['signals']:,}, avg5={row['avg_5d']:+.2f}%, hit5={row['hit_5d'] * 100:.2f}%, "
            f"roc3>={row['roc3_min']}, rvol>={row['rel_volume_min']}, rsi<{row['rsi_max']}, "
            f"rupee>={row['rupee_volume_cr']}cr, ema9dist<={row['ema9_dist_max']}, closepos>={row['close_position_min']}"
        )


def combo_key(combo):
    return tuple((key, combo[key]) for key in sorted(combo))


if __name__ == "__main__":
    main()

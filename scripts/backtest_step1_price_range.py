import argparse
import csv
import sqlite3
from collections import defaultdict
from pathlib import Path

from backtest_exchange_eod import avg, load_instruments, load_rows, pct


def main():
    parser = argparse.ArgumentParser(description="Step 1 baseline backtest: NSE price range filter only.")
    parser.add_argument("--db", default="data/stock_analysis_exchange.sqlite3")
    parser.add_argument("--from-date", default="2024-08-15")
    parser.add_argument("--to-date", default="2026-08-24")
    parser.add_argument("--min-price", type=float, default=100)
    parser.add_argument("--max-price", type=float, default=500)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--capital-per-stock", type=float, default=10_000)
    parser.add_argument("--targets", default="5,10")
    parser.add_argument("--stops", default="5,10")
    parser.add_argument("--max-hold-days", type=int, default=5)
    parser.add_argument("--output", default="outputs/step1_price_range_backtest.csv")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    instruments = load_instruments(conn, "NSE")

    picks_by_date = defaultdict(list)
    price_rows = {}
    processed = 0
    for instrument in instruments:
        rows = [dict(row) for row in load_rows(conn, instrument["id"])]
        if len(rows) < args.max_hold_days + 2:
            continue
        price_rows[instrument["symbol"]] = rows
        collect_price_range_picks(instrument, rows, args, picks_by_date)
        processed += 1
        if processed % 500 == 0:
            print(f"Scanned {processed:,} NSE instruments")
    conn.close()

    picks = [pick for rows in picks_by_date.values() for pick in rows]
    print("Step 1 price range filter")
    print(f"NSE instruments processed: {processed:,}")
    print(f"Price range: Rs. {args.min_price:g}-{args.max_price:g}")
    print(f"Eligible stock-days: {len(picks):,}")
    print(f"Avg next-day return for all eligible stock-days: {avg([pick['next_day_return'] for pick in picks]):+.2f}%")
    print(f"Next-day positive rate: {avg([1 if pick['next_day_return'] > 0 else 0 for pick in picks]) * 100:.2f}%")

    targets = [float(value.strip()) for value in args.targets.split(",") if value.strip()]
    stops = [float(value.strip()) for value in args.stops.split(",") if value.strip()]
    summaries = []
    for target in targets:
        for stop in stops:
            trades = simulate(picks_by_date, price_rows, args, target, stop)
            summaries.append(summarize(f"target{target:g}_stop{stop:g}", target, stop, trades, args))

    write_summary(Path(args.output), summaries)
    print_report(summaries, args)
    print(f"CSV: {args.output}")


def collect_price_range_picks(instrument, rows, args, picks_by_date):
    for i in range(0, len(rows) - args.max_hold_days - 1):
        row = rows[i]
        if row["trade_date"] < args.from_date or row["trade_date"] > args.to_date:
            continue
        if not (args.min_price <= row["close"] <= args.max_price):
            continue
        next_row = rows[i + 1]
        picks_by_date[row["trade_date"]].append({
            "symbol": instrument["symbol"],
            "index": i,
            "close": row["close"],
            "volume": row["volume"],
            "next_day_return": pct(next_row["close"], row["close"]),
        })


def simulate(picks_by_date, price_rows, args, target_pct, stop_pct):
    trades = []
    for signal_date in sorted(picks_by_date):
        picks = sorted(picks_by_date[signal_date], key=lambda row: (row["volume"], row["symbol"]), reverse=True)[:args.top_n]
        for pick in picks:
            rows = price_rows[pick["symbol"]]
            entry_index = pick["index"] + 1
            if entry_index >= len(rows):
                continue
            entry_row = rows[entry_index]
            entry_price = entry_row["open"] or entry_row["close"]
            target_price = entry_price * (1 + target_pct / 100)
            stop_price = entry_price * (1 - stop_pct / 100)
            exit_row = rows[min(entry_index + args.max_hold_days, len(rows) - 1)]
            exit_price = exit_row["close"]
            exit_reason = "time"
            for j in range(entry_index, min(entry_index + args.max_hold_days, len(rows) - 1) + 1):
                day = rows[j]
                if day["low"] <= stop_price:
                    exit_row = day
                    exit_price = stop_price
                    exit_reason = "stop"
                    break
                if day["high"] >= target_price:
                    exit_row = day
                    exit_price = target_price
                    exit_reason = "target"
                    break
            pnl = (args.capital_per_stock / entry_price) * (exit_price - entry_price) if entry_price else 0
            trades.append({
                "signal_date": signal_date,
                "symbol": pick["symbol"],
                "entry_date": entry_row["trade_date"],
                "exit_date": exit_row["trade_date"],
                "exit_reason": exit_reason,
                "return_pct": pct(exit_price, entry_price),
                "pnl": pnl,
            })
    return trades


def summarize(run, target, stop, trades, args):
    invested = len(trades) * args.capital_per_stock
    pnl = sum(trade["pnl"] for trade in trades)
    return {
        "run": run,
        "target_pct": target,
        "stop_pct": stop,
        "trades": len(trades),
        "invested_turnover": invested,
        "net_pnl": pnl,
        "return_on_turnover_pct": (pnl / invested) * 100 if invested else 0,
        "avg_trade_return_pct": avg([trade["return_pct"] for trade in trades]),
        "win_rate_pct": avg([1 if trade["pnl"] > 0 else 0 for trade in trades]) * 100,
        "target_hit_pct": avg([1 if trade["exit_reason"] == "target" else 0 for trade in trades]) * 100,
        "stop_hit_pct": avg([1 if trade["exit_reason"] == "stop" else 0 for trade in trades]) * 100,
    }


def write_summary(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "run", "target_pct", "stop_pct", "trades", "invested_turnover", "net_pnl",
        "return_on_turnover_pct", "avg_trade_return_pct", "win_rate_pct", "target_hit_pct", "stop_hit_pct",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: round(row[key], 4) if isinstance(row[key], float) else row[key] for key in fieldnames})


def print_report(rows, args):
    print(f"Portfolio test: top {args.top_n} by current-day volume, Rs. {args.capital_per_stock:,.0f} each, buy next open")
    for row in rows:
        print(
            f"{row['run']}: trades={row['trades']:,}, pnl=Rs. {row['net_pnl']:,.0f}, "
            f"turnover_ret={row['return_on_turnover_pct']:+.2f}%, avg_trade={row['avg_trade_return_pct']:+.2f}%, "
            f"win={row['win_rate_pct']:.2f}%, target={row['target_hit_pct']:.2f}%, stop={row['stop_hit_pct']:.2f}%"
        )


if __name__ == "__main__":
    main()

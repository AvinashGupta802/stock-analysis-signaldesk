import argparse
import csv
import sqlite3
from collections import defaultdict
from pathlib import Path

from backtest_exchange_eod import avg, load_instruments, load_rows, pct, rsi_series


LONG_RULES = {
    "long_trend": 2,
    "long_momentum": 2,
    "volume_long": 2,
    "breakout_20": 2,
    "close_near_high": 1,
}


def main():
    parser = argparse.ArgumentParser(description="Portfolio backtest for NSE buy recommendations.")
    parser.add_argument("--db", default="data/stock_analysis_exchange.sqlite3")
    parser.add_argument("--from-date", default="2024-08-15")
    parser.add_argument("--to-date", default="2026-08-24")
    parser.add_argument("--capital-per-stock", type=float, default=10_000)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--min-price", type=float, default=100)
    parser.add_argument("--max-price", type=float, default=500)
    parser.add_argument("--min-adv20", type=float, default=1_000_000)
    parser.add_argument("--min-rel-volume", type=float, default=1.5)
    parser.add_argument("--rsi-min", type=float, default=50)
    parser.add_argument("--rsi-max", type=float, default=68)
    parser.add_argument("--threshold", type=int, default=5)
    parser.add_argument("--max-hold-days", type=int, default=5)
    parser.add_argument("--targets", default="10,12.5,15")
    parser.add_argument("--stops", default="10")
    parser.add_argument("--output", default="outputs/portfolio_buy_backtest.csv")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    instruments = load_instruments(conn, "NSE")

    recommendations_by_date = defaultdict(list)
    price_rows_by_symbol = {}
    processed = 0
    for instrument in instruments:
        rows = [dict(row) for row in load_rows(conn, instrument["id"])]
        if len(rows) < 60:
            continue
        price_rows_by_symbol[instrument["symbol"]] = rows
        collect_recommendations(instrument, rows, args, recommendations_by_date)
        processed += 1
        if processed % 500 == 0:
            print(f"Scored {processed:,} NSE instruments")
    conn.close()

    targets = [float(item.strip()) for item in args.targets.split(",") if item.strip()]
    stops = [float(item.strip()) for item in args.stops.split(",") if item.strip()]
    runs = []
    trades_by_run = {}
    for target in targets:
        for stop in stops:
            run_key = f"target{target:g}_stop{stop:g}"
            trades = simulate_portfolio(recommendations_by_date, price_rows_by_symbol, args, target, stop)
            runs.append(summarize_run(run_key, target, stop, trades, args))
            trades_by_run[run_key] = trades

    write_summary(Path(args.output), runs)
    write_trades(Path(args.output).with_name(Path(args.output).stem + "_trades.csv"), trades_by_run)
    print_report(runs, processed, args)
    print(f"CSV: {args.output}")


def collect_recommendations(instrument, rows, args, recommendations_by_date):
    closes = [row["close"] for row in rows]
    highs = [row["high"] for row in rows]
    lows = [row["low"] for row in rows]
    volumes = [row["volume"] for row in rows]
    rsi14 = rsi_series(closes, 14)

    for i in range(50, len(rows) - args.max_hold_days - 1):
        row = rows[i]
        if row["trade_date"] < args.from_date or row["trade_date"] > args.to_date:
            continue
        ctx = build_context(i, rows, closes, highs, lows, volumes, rsi14)
        if not passes_filters(ctx, args):
            continue
        score, buy_rules = score_long(ctx, args)
        if score < args.threshold:
            continue
        recommendations_by_date[row["trade_date"]].append({
            "symbol": instrument["symbol"],
            "name": instrument["name"],
            "index": i,
            "score": score,
            "buy_rules": buy_rules,
            "close": row["close"],
            "change_3": ctx["change_3"],
            "rel_volume": ctx["rel_volume"],
            "rsi": ctx["rsi"],
        })


def build_context(i, rows, closes, highs, lows, volumes, rsi14):
    close = closes[i]
    avg_volume20 = avg(volumes[i - 20:i])
    day_range = max(rows[i]["high"] - rows[i]["low"], 0.01)
    return {
        "close": close,
        "volume": volumes[i],
        "avg_volume20": avg_volume20,
        "rel_volume": volumes[i] / avg_volume20 if avg_volume20 else 0,
        "rsi": rsi14[i],
        "sma5": avg(closes[i - 5:i]),
        "sma20": avg(closes[i - 20:i]),
        "change_1": pct(close, closes[i - 1]),
        "change_3": pct(close, closes[i - 3]),
        "high20": max(highs[i - 19:i + 1]),
        "close_position": (close - rows[i]["low"]) / day_range,
    }


def passes_filters(ctx, args):
    return (
        args.min_price <= ctx["close"] <= args.max_price
        and ctx["avg_volume20"] >= args.min_adv20
        and ctx["rel_volume"] >= args.min_rel_volume
        and args.rsi_min <= ctx["rsi"] <= args.rsi_max
        and abs(ctx["change_1"]) <= 15
    )


def score_long(ctx, args):
    score = 0
    buy_rules = 0

    def add(condition, weight):
        nonlocal score, buy_rules
        if condition:
            score += weight
            buy_rules += 1

    add(ctx["close"] > ctx["sma5"] and ctx["close"] > ctx["sma20"], LONG_RULES["long_trend"])
    add(1.2 <= ctx["change_3"] <= 12, LONG_RULES["long_momentum"])
    add(ctx["rel_volume"] >= args.min_rel_volume and ctx["change_1"] > 0, LONG_RULES["volume_long"])
    add(pct(ctx["close"], ctx["high20"]) > -2, LONG_RULES["breakout_20"])
    add(ctx["close_position"] >= 0.75, LONG_RULES["close_near_high"])
    return score, buy_rules


def simulate_portfolio(recommendations_by_date, price_rows_by_symbol, args, target_pct, stop_pct):
    trades = []
    for signal_date in sorted(recommendations_by_date):
        candidates = sorted(
            recommendations_by_date[signal_date],
            key=lambda row: (row["score"], row["rel_volume"], row["change_3"]),
            reverse=True,
        )[:args.top_n]
        for candidate in candidates:
            rows = price_rows_by_symbol[candidate["symbol"]]
            entry_index = candidate["index"] + 1
            exit_index_limit = min(entry_index + args.max_hold_days, len(rows) - 1)
            if entry_index >= len(rows):
                continue
            entry_row = rows[entry_index]
            entry_price = entry_row["open"] or entry_row["close"]
            target_price = entry_price * (1 + target_pct / 100)
            stop_price = entry_price * (1 - stop_pct / 100)
            exit_row = rows[exit_index_limit]
            exit_price = exit_row["close"]
            exit_reason = "time"
            for hold_index in range(entry_index, exit_index_limit + 1):
                day = rows[hold_index]
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
            shares = args.capital_per_stock / entry_price if entry_price else 0
            pnl = shares * (exit_price - entry_price)
            trades.append({
                "signal_date": signal_date,
                "entry_date": entry_row["trade_date"],
                "exit_date": exit_row["trade_date"],
                "symbol": candidate["symbol"],
                "score": candidate["score"],
                "entry_price": entry_price,
                "exit_price": exit_price,
                "exit_reason": exit_reason,
                "pnl": pnl,
                "return_pct": pct(exit_price, entry_price),
                "rsi": candidate["rsi"],
                "rel_volume": candidate["rel_volume"],
            })
    return trades


def summarize_run(run_key, target, stop, trades, args):
    invested = len(trades) * args.capital_per_stock
    pnl = sum(trade["pnl"] for trade in trades)
    wins = [trade for trade in trades if trade["pnl"] > 0]
    targets = [trade for trade in trades if trade["exit_reason"] == "target"]
    stops = [trade for trade in trades if trade["exit_reason"] == "stop"]
    timed = [trade for trade in trades if trade["exit_reason"] == "time"]
    by_signal_date = defaultdict(float)
    for trade in trades:
        by_signal_date[trade["signal_date"]] += trade["pnl"]
    day_pnls = list(by_signal_date.values())
    return {
        "run": run_key,
        "target_pct": target,
        "stop_pct": stop,
        "trades": len(trades),
        "signal_days": len(by_signal_date),
        "invested_turnover": invested,
        "net_pnl": pnl,
        "return_on_turnover_pct": (pnl / invested) * 100 if invested else 0,
        "avg_trade_pnl": avg([trade["pnl"] for trade in trades]),
        "avg_trade_return_pct": avg([trade["return_pct"] for trade in trades]),
        "win_rate_pct": (len(wins) / len(trades)) * 100 if trades else 0,
        "target_hit_pct": (len(targets) / len(trades)) * 100 if trades else 0,
        "stop_hit_pct": (len(stops) / len(trades)) * 100 if trades else 0,
        "time_exit_pct": (len(timed) / len(trades)) * 100 if trades else 0,
        "avg_day_pnl": avg(day_pnls),
        "best_day_pnl": max(day_pnls) if day_pnls else 0,
        "worst_day_pnl": min(day_pnls) if day_pnls else 0,
    }


def write_summary(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "run", "target_pct", "stop_pct", "trades", "signal_days", "invested_turnover", "net_pnl",
        "return_on_turnover_pct", "avg_trade_pnl", "avg_trade_return_pct", "win_rate_pct",
        "target_hit_pct", "stop_hit_pct", "time_exit_pct", "avg_day_pnl", "best_day_pnl", "worst_day_pnl",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: round(row[key], 4) if isinstance(row[key], float) else row[key] for key in fieldnames})


def write_trades(path, trades_by_run):
    fieldnames = [
        "run", "signal_date", "entry_date", "exit_date", "symbol", "score", "entry_price", "exit_price",
        "exit_reason", "pnl", "return_pct", "rsi", "rel_volume",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for run, trades in trades_by_run.items():
            for trade in trades:
                row = {"run": run, **trade}
                writer.writerow({key: round(row[key], 4) if isinstance(row[key], float) else row[key] for key in fieldnames})


def print_report(rows, processed, args):
    print("Portfolio backtest complete")
    print(f"Exchange: NSE")
    print(f"Instruments processed: {processed:,}")
    print(f"Top picks per signal day: {args.top_n}")
    print(f"Capital per stock: Rs. {args.capital_per_stock:,.0f}")
    print(f"Max hold: {args.max_hold_days} trading days")
    for row in rows:
        print(
            f"{row['run']}: trades={row['trades']:,}, days={row['signal_days']:,}, "
            f"pnl=Rs. {row['net_pnl']:,.0f}, turnover_ret={row['return_on_turnover_pct']:+.2f}%, "
            f"avg_trade={row['avg_trade_return_pct']:+.2f}%, win={row['win_rate_pct']:.2f}%, "
            f"target={row['target_hit_pct']:.2f}%, stop={row['stop_hit_pct']:.2f}%, time={row['time_exit_pct']:.2f}%, "
            f"worst_day=Rs. {row['worst_day_pnl']:,.0f}"
        )


if __name__ == "__main__":
    main()

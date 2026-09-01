import argparse
import csv
import sqlite3
from collections import defaultdict
from pathlib import Path

from backtest_exchange_eod import avg, ema_series, load_instruments, load_rows, pct, rsi_series


def main():
    parser = argparse.ArgumentParser(description="Backtest a dual-pattern NSE buy setup.")
    parser.add_argument("--db", default="data/stock_analysis_exchange.sqlite3")
    parser.add_argument("--from-date", default="2024-08-15")
    parser.add_argument("--to-date", default="2026-08-24")
    parser.add_argument("--min-price", type=float, default=100)
    parser.add_argument("--max-price", type=float, default=500)
    parser.add_argument("--min-adv20", type=float, default=1_000_000)
    parser.add_argument("--rsi-min", type=float, default=50)
    parser.add_argument("--rsi-max", type=float, default=72)
    parser.add_argument("--max-ema9-distance", type=float, default=5)
    parser.add_argument("--breakout-rel-volume", type=float, default=1.5)
    parser.add_argument("--quiet-near-high-pct", type=float, default=5)
    parser.add_argument("--quiet-roc3-min", type=float, default=0.5)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--capital-per-stock", type=float, default=10_000)
    parser.add_argument("--targets", default="5,7.5,10,12.5,15")
    parser.add_argument("--stops", default="5,7.5,10")
    parser.add_argument("--max-hold-days", type=int, default=5)
    parser.add_argument("--output", default="outputs/dual_buy_setup_backtest.csv")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    instruments = load_instruments(conn, "NSE")

    picks_by_date = defaultdict(list)
    price_rows = {}
    processed = 0
    for instrument in instruments:
        rows = [dict(row) for row in load_rows(conn, instrument["id"])]
        if len(rows) < 80:
            continue
        price_rows[instrument["symbol"]] = rows
        collect_picks(instrument, rows, args, picks_by_date)
        processed += 1
        if processed % 500 == 0:
            print(f"Scanned {processed:,} NSE instruments, signal days={len(picks_by_date):,}")
    conn.close()

    all_picks = [pick for rows in picks_by_date.values() for pick in rows]
    print_signal_stats(all_picks)

    targets = [float(value.strip()) for value in args.targets.split(",") if value.strip()]
    stops = [float(value.strip()) for value in args.stops.split(",") if value.strip()]
    summaries = []
    trades_by_run = {}
    for target in targets:
        for stop in stops:
            run = f"target{target:g}_stop{stop:g}"
            trades = simulate(picks_by_date, price_rows, args, target, stop)
            summaries.append(summarize(run, target, stop, trades, args))
            trades_by_run[run] = trades

    write_summary(Path(args.output), summaries)
    write_trades(Path(args.output).with_name(Path(args.output).stem + "_trades.csv"), trades_by_run)
    print_report(summaries, processed, args)
    print(f"CSV: {args.output}")


def collect_picks(instrument, rows, args, picks_by_date):
    closes = [row["close"] for row in rows]
    highs = [row["high"] for row in rows]
    lows = [row["low"] for row in rows]
    volumes = [row["volume"] for row in rows]
    ema9 = ema_series(closes, 9)
    rsi14 = rsi_series(closes, 14)

    for i in range(60, len(rows) - args.max_hold_days - 1):
        row = rows[i]
        if row["trade_date"] < args.from_date or row["trade_date"] > args.to_date:
            continue
        ctx = build_context(i, rows, closes, highs, lows, volumes, ema9, rsi14)
        passed, setup_type, score, reasons = evaluate_setup(ctx, args)
        if not passed:
            continue
        picks_by_date[row["trade_date"]].append({
            "symbol": instrument["symbol"],
            "name": instrument["name"],
            "index": i,
            "setup_type": setup_type,
            "score": score,
            "close": row["close"],
            "rel_volume": ctx["rel_volume"],
            "rsi": ctx["rsi"],
            "roc3": ctx["roc3"],
            "near_high_pct": ctx["near_high_pct"],
            "ema9_distance": ctx["ema9_distance"],
            "future_5d_close": ctx["future_5d_close"],
            "future_5d_high": ctx["future_5d_high"],
            "reasons": "; ".join(reasons),
        })


def build_context(i, rows, closes, highs, lows, volumes, ema9, rsi14):
    close = closes[i]
    avg_volume20 = avg(volumes[i - 20:i])
    high20 = max(highs[i - 19:i + 1])
    prior_roc3 = pct(closes[i - 1], closes[i - 4])
    return {
        "close": close,
        "avg_volume20": avg_volume20,
        "rel_volume": volumes[i] / avg_volume20 if avg_volume20 else 0,
        "rsi": rsi14[i],
        "roc3": pct(close, closes[i - 3]),
        "prior_roc3": prior_roc3,
        "high20": high20,
        "near_high_pct": abs(pct(close, high20)),
        "ema9_distance": pct(close, ema9[i]),
        "change1": pct(close, closes[i - 1]),
        "future_5d_close": pct(rows[i + 5]["close"], close),
        "future_5d_high": pct(max(row["high"] for row in rows[i + 1:i + 6]), close),
    }


def evaluate_setup(ctx, args):
    reasons = []
    if not (args.min_price <= ctx["close"] <= args.max_price):
        return False, "", 0, reasons
    if ctx["avg_volume20"] < args.min_adv20:
        return False, "", 0, reasons
    if not (args.rsi_min <= ctx["rsi"] <= args.rsi_max):
        return False, "", 0, reasons
    if ctx["ema9_distance"] > args.max_ema9_distance:
        return False, "", 0, reasons

    score = 4
    reasons.extend([
        f"Price {args.min_price:g}-{args.max_price:g}",
        f"ADV20 >= {args.min_adv20:,.0f}",
        f"RSI {args.rsi_min:g}-{args.rsi_max:g}",
        f"EMA9 distance <= {args.max_ema9_distance:g}%",
    ])

    breakout = ctx["rel_volume"] >= args.breakout_rel_volume and ctx["change1"] > 0
    quiet = (
        ctx["near_high_pct"] <= args.quiet_near_high_pct
        and ctx["roc3"] >= args.quiet_roc3_min
        and ctx["roc3"] > ctx["prior_roc3"]
    )

    if breakout:
        reasons.append(f"Volume breakout: relative volume >= {args.breakout_rel_volume:g}x")
        score += 3
    if quiet:
        reasons.append(f"Quiet pre-breakout: within {args.quiet_near_high_pct:g}% of 20D high and ROC3 improving")
        score += 3

    if breakout and quiet:
        return True, "Both", score + 1, reasons
    if breakout:
        return True, "Volume Breakout", score, reasons
    if quiet:
        return True, "Quiet Pre-Breakout", score, reasons
    return False, "", 0, reasons


def print_signal_stats(picks):
    by_type = CounterLike()
    for pick in picks:
        by_type[pick["setup_type"]] += 1
    print(f"Raw setup signals: {len(picks):,}")
    for key, value in sorted(by_type.items()):
        print(f"  {key}: {value:,}")
    if picks:
        print(f"  Avg future 5D close return before top-N: {avg([pick.get('future_5d_close', 0) for pick in picks]):+.2f}%")


def simulate(picks_by_date, price_rows, args, target_pct, stop_pct):
    trades = []
    for signal_date in sorted(picks_by_date):
        picks = sorted(
            picks_by_date[signal_date],
            key=lambda pick: (pick["score"], pick["setup_type"] == "Both", pick["rel_volume"], pick["roc3"]),
            reverse=True,
        )[:args.top_n]
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
                "entry_date": entry_row["trade_date"],
                "exit_date": exit_row["trade_date"],
                "symbol": pick["symbol"],
                "setup_type": pick["setup_type"],
                "score": pick["score"],
                "entry_price": entry_price,
                "exit_price": exit_price,
                "exit_reason": exit_reason,
                "return_pct": pct(exit_price, entry_price),
                "pnl": pnl,
                "rsi": pick["rsi"],
                "rel_volume": pick["rel_volume"],
                "roc3": pick["roc3"],
                "near_high_pct": pick["near_high_pct"],
                "ema9_distance": pick["ema9_distance"],
                "reasons": pick["reasons"],
            })
    return trades


def summarize(run, target, stop, trades, args):
    invested = len(trades) * args.capital_per_stock
    pnl = sum(trade["pnl"] for trade in trades)
    by_date = defaultdict(float)
    for trade in trades:
        by_date[trade["signal_date"]] += trade["pnl"]
    day_pnls = list(by_date.values())
    return {
        "run": run,
        "target_pct": target,
        "stop_pct": stop,
        "trades": len(trades),
        "signal_days": len(by_date),
        "invested_turnover": invested,
        "net_pnl": pnl,
        "return_on_turnover_pct": (pnl / invested) * 100 if invested else 0,
        "avg_trade_return_pct": avg([trade["return_pct"] for trade in trades]),
        "win_rate_pct": avg([1 if trade["pnl"] > 0 else 0 for trade in trades]) * 100,
        "target_hit_pct": avg([1 if trade["exit_reason"] == "target" else 0 for trade in trades]) * 100,
        "stop_hit_pct": avg([1 if trade["exit_reason"] == "stop" else 0 for trade in trades]) * 100,
        "time_exit_pct": avg([1 if trade["exit_reason"] == "time" else 0 for trade in trades]) * 100,
        "best_day_pnl": max(day_pnls) if day_pnls else 0,
        "worst_day_pnl": min(day_pnls) if day_pnls else 0,
    }


def write_summary(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "run", "target_pct", "stop_pct", "trades", "signal_days", "invested_turnover", "net_pnl",
        "return_on_turnover_pct", "avg_trade_return_pct", "win_rate_pct", "target_hit_pct",
        "stop_hit_pct", "time_exit_pct", "best_day_pnl", "worst_day_pnl",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: round(row[key], 4) if isinstance(row[key], float) else row[key] for key in fieldnames})


def write_trades(path, trades_by_run):
    fieldnames = [
        "run", "signal_date", "entry_date", "exit_date", "symbol", "setup_type", "score",
        "entry_price", "exit_price", "exit_reason", "return_pct", "pnl", "rsi", "rel_volume",
        "roc3", "near_high_pct", "ema9_distance", "reasons",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for run, trades in trades_by_run.items():
            for trade in trades:
                row = {"run": run, **trade}
                writer.writerow({key: round(row[key], 4) if isinstance(row[key], float) else row[key] for key in fieldnames})


def print_report(rows, processed, args):
    print("Dual buy setup backtest complete")
    print(f"NSE instruments processed: {processed:,}")
    print(f"Top N: {args.top_n}, capital per stock: Rs. {args.capital_per_stock:,.0f}, max hold: {args.max_hold_days} days")
    print(
        f"Setup values: price {args.min_price:g}-{args.max_price:g}, ADV20>={args.min_adv20:,.0f}, "
        f"RSI {args.rsi_min:g}-{args.rsi_max:g}, EMA9 distance<={args.max_ema9_distance:g}%, "
        f"breakout RVOL>={args.breakout_rel_volume:g}, quiet near high<={args.quiet_near_high_pct:g}%, quiet ROC3>={args.quiet_roc3_min:g}"
    )
    for row in rows:
        print(
            f"{row['run']}: trades={row['trades']:,}, days={row['signal_days']:,}, "
            f"pnl=Rs. {row['net_pnl']:,.0f}, turnover_ret={row['return_on_turnover_pct']:+.2f}%, "
            f"avg_trade={row['avg_trade_return_pct']:+.2f}%, win={row['win_rate_pct']:.2f}%, "
            f"target={row['target_hit_pct']:.2f}%, stop={row['stop_hit_pct']:.2f}%, time={row['time_exit_pct']:.2f}%, "
            f"worst_day=Rs. {row['worst_day_pnl']:,.0f}"
        )


class CounterLike(defaultdict):
    def __init__(self):
        super().__init__(int)


if __name__ == "__main__":
    main()

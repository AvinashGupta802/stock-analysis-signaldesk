"""Deep, walk-forward backtest for SignalDesk experimental setup rules."""

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from server import (
    EXPERIMENTAL_SETUP_RULES,
    apply_rule,
    build_backtest_context,
    build_indicators,
    connect,
    load_group_stocks,
    load_rows,
    normalize_rule,
    pct,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs"


def main():
    parser = argparse.ArgumentParser(description="Deep backtest experimental setup and confirmation rules.")
    parser.add_argument("--group", default="all", help="Stock group id, for example all, liquid, or nifty500")
    parser.add_argument("--from-date", default="2024-08-01")
    parser.add_argument("--to-date", default="2026-11-11")
    parser.add_argument("--validation-from", default="2026-01-01")
    parser.add_argument("--hold-days", default="2,5,10,15,20,30")
    parser.add_argument("--targets", default="5,10,15")
    parser.add_argument("--stops", default="5,7,10")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--capital", type=float, default=10_000)
    parser.add_argument("--output-prefix", default="experimental_setups")
    args = parser.parse_args()

    holds = parse_numbers(args.hold_days, int)
    targets = parse_numbers(args.targets, float)
    stops = parse_numbers(args.stops, float)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"{args.output_prefix}_{args.group}_{timestamp}"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    rules = [normalize_rule(rule) | {"id": rule["id"]} for rule in EXPERIMENTAL_SETUP_RULES]
    print(f"Building signals for {len(rules)} experimental rules on group '{args.group}'...")
    signals, rows_by_symbol, stock_count = build_signals(
        args.group, args.from_date, args.to_date, max(holds), rules
    )
    print(f"Stocks: {stock_count:,}; signals: {sum(len(items) for items in signals.values()):,}")

    periods = [
        ("full", args.from_date, args.to_date),
        ("development", args.from_date, previous_date(args.validation_from)),
        ("validation", args.validation_from, args.to_date),
    ]
    summaries = []
    for rule in rules:
        rule_signals = signals[rule["id"]]
        for period_name, period_from, period_to in periods:
            period_signals = [item for item in rule_signals if period_from <= item["date"] <= period_to]
            for hold_days in holds:
                for stop_pct in stops:
                    summaries.append(run_configuration(
                        rule, period_name, period_signals, rows_by_symbol, args.top_n,
                        args.capital, hold_days, None, stop_pct, "stop_or_time",
                    ))
                    for target_pct in targets:
                        summaries.append(run_configuration(
                            rule, period_name, period_signals, rows_by_symbol, args.top_n,
                            args.capital, hold_days, target_pct, stop_pct, "target_stop_time",
                        ))

    summary_path = OUTPUT_DIR / f"{prefix}_summary.csv"
    write_csv(summary_path, summaries)

    event_rows = build_event_rows(signals, rows_by_symbol, holds)
    event_path = OUTPUT_DIR / f"{prefix}_events.csv"
    write_csv(event_path, event_rows)

    overlap_path = OUTPUT_DIR / f"{prefix}_overlap.csv"
    write_csv(overlap_path, build_overlap_rows(signals))

    ranked = sorted(summaries, key=ranking_score, reverse=True)
    best_keys = {configuration_key(row) for row in ranked if row["period"] == "validation" and row["trades"] >= 10}
    best_keys = set(list(best_keys)[:12])
    trade_rows = []
    for row in summaries:
        if row["period"] != "validation" or configuration_key(row) not in best_keys:
            continue
        rule = next(item for item in rules if item["id"] == row["rule_id"])
        period_signals = [item for item in signals[rule["id"]] if args.validation_from <= item["date"] <= args.to_date]
        trades = simulate(
            period_signals, rows_by_symbol, args.top_n, args.capital, int(row["hold_days"]),
            blank_to_none(row["target_pct"]), float(row["stop_pct"]), row["exit_policy"],
        )
        for trade in trades:
            trade_rows.append({
                "rule_id": rule["id"], "rule_name": rule["name"],
                "hold_days": row["hold_days"], "target_pct": row["target_pct"],
                "stop_pct": row["stop_pct"], "exit_policy": row["exit_policy"], **trade,
            })
    trades_path = OUTPUT_DIR / f"{prefix}_best_validation_trades.csv"
    write_csv(trades_path, trade_rows)

    config_path = OUTPUT_DIR / f"{prefix}_config.json"
    config_path.write_text(json.dumps({
        "arguments": vars(args), "rules": EXPERIMENTAL_SETUP_RULES,
        "stock_count": stock_count, "signal_counts": {key: len(value) for key, value in signals.items()},
    }, indent=2), encoding="utf-8")

    print("\nTop validation configurations")
    for row in [item for item in ranked if item["period"] == "validation"][:15]:
        print(
            f"{row['rule_name']} | {row['exit_policy']} | hold {row['hold_days']} | "
            f"target {row['target_pct'] or '-'} | stop {row['stop_pct']} | trades {row['trades']} | "
            f"return {row['return_on_turnover_pct']:+.2f}% | win {row['win_rate_pct']:.2f}% | "
            f"P/L Rs. {row['net_pnl']:+.2f}"
        )
    print("\nCreated:")
    for path in (summary_path, event_path, overlap_path, trades_path, config_path):
        print(path)


def build_signals(group, from_date, to_date, max_hold, rules):
    signals = {rule["id"]: [] for rule in rules}
    rows_by_symbol = {}
    with connect() as conn:
        stocks = load_group_stocks(conn, group)
        total = len(stocks)
        for number, stock in enumerate(stocks, 1):
            rows = load_rows(conn, stock["id"])
            if len(rows) < 30:
                continue
            rows_by_symbol[stock["symbol"]] = rows
            indicators = build_indicators(rows)
            for index in range(21, len(rows) - max_hold - 1):
                trade_date = rows[index]["trade_date"]
                if trade_date < from_date or trade_date > to_date:
                    continue
                ctx = build_backtest_context(rows, indicators, index)
                for rule in rules:
                    passed, reasons = apply_rule(ctx, rule)
                    if passed:
                        signals[rule["id"]].append({
                            "symbol": stock["symbol"], "date": trade_date, "index": index,
                            "close": rows[index]["close"], "volume": rows[index]["volume"],
                            "reasons": reasons,
                        })
            if number % 100 == 0 or number == total:
                print(f"Processed {number:,}/{total:,} stocks", flush=True)
    return signals, rows_by_symbol, len(stocks)


def run_configuration(rule, period, signals, rows_by_symbol, top_n, capital, hold_days, target, stop, policy):
    trades = simulate(signals, rows_by_symbol, top_n, capital, hold_days, target, stop, policy)
    returns = [trade["return_pct"] for trade in trades]
    pnl = sum(trade["pnl"] for trade in trades)
    turnover = len(trades) * capital
    return {
        "rule_id": rule["id"], "rule_name": rule["name"], "period": period,
        "exit_policy": policy, "hold_days": hold_days, "target_pct": "" if target is None else target,
        "stop_pct": stop, "trades": len(trades), "signal_days": len({trade["signal_date"] for trade in trades}),
        "net_pnl": round(pnl, 2), "return_on_turnover_pct": round((pnl / turnover * 100) if turnover else 0, 4),
        "win_rate_pct": round(rate(returns, lambda value: value > 0), 2),
        "target_hit_pct": round(rate(trades, lambda item: item["exit_reason"] == "target"), 2),
        "stop_hit_pct": round(rate(trades, lambda item: item["exit_reason"] == "stop"), 2),
        "avg_return_pct": round(mean(returns), 4), "median_return_pct": round(median(returns), 4),
        "avg_mfe_pct": round(mean([trade["mfe_pct"] for trade in trades]), 4),
        "avg_mae_pct": round(mean([trade["mae_pct"] for trade in trades]), 4),
        "max_trade_gain_pct": round(max(returns, default=0), 4),
        "max_trade_loss_pct": round(min(returns, default=0), 4),
    }


def simulate(signals, rows_by_symbol, top_n, capital, hold_days, target_pct, stop_pct, policy):
    by_date = defaultdict(list)
    for signal in signals:
        by_date[signal["date"]].append(signal)
    trades = []
    for signal_date in sorted(by_date):
        selected = sorted(by_date[signal_date], key=lambda item: (item["volume"], item["symbol"]), reverse=True)[:top_n]
        for signal in selected:
            rows = rows_by_symbol[signal["symbol"]]
            entry_index = signal["index"] + 1
            if entry_index >= len(rows):
                continue
            entry = rows[entry_index]
            entry_price = entry["open"] or entry["close"]
            stop_price = entry_price * (1 - stop_pct / 100)
            target_price = entry_price * (1 + target_pct / 100) if target_pct is not None else None
            final_index = min(entry_index + hold_days - 1, len(rows) - 1)
            exit_row = rows[final_index]
            exit_price = exit_row["close"]
            exit_reason = "time"
            max_high = entry["high"]
            min_low = entry["low"]
            for day_index in range(entry_index, final_index + 1):
                day = rows[day_index]
                max_high = max(max_high, day["high"])
                min_low = min(min_low, day["low"])
                if day["low"] <= stop_price:
                    exit_row, exit_price, exit_reason = day, stop_price, "stop"
                    break
                if policy == "target_stop_time" and target_price is not None and day["high"] >= target_price:
                    exit_row, exit_price, exit_reason = day, target_price, "target"
                    break
            return_pct = pct(exit_price, entry_price)
            shares = capital / entry_price if entry_price else 0
            trades.append({
                "symbol": signal["symbol"], "signal_date": signal_date,
                "entry_date": entry["trade_date"], "entry_price": round(entry_price, 4),
                "exit_date": exit_row["trade_date"], "exit_price": round(exit_price, 4),
                "exit_reason": exit_reason, "return_pct": round(return_pct, 4),
                "pnl": round((exit_price - entry_price) * shares, 2),
                "mfe_pct": round(pct(max_high, entry_price), 4),
                "mae_pct": round(pct(min_low, entry_price), 4),
            })
    return trades


def build_event_rows(signals, rows_by_symbol, holds):
    rows = []
    for rule_id, items in signals.items():
        for signal in items:
            prices = rows_by_symbol[signal["symbol"]]
            row = {"rule_id": rule_id, "symbol": signal["symbol"], "signal_date": signal["date"], "signal_close": signal["close"]}
            for hold in holds:
                target_index = min(signal["index"] + hold, len(prices) - 1)
                future = prices[target_index]
                window = prices[signal["index"] + 1:target_index + 1]
                row[f"return_{hold}d_pct"] = round(pct(future["close"], signal["close"]), 4)
                row[f"mfe_{hold}d_pct"] = round(pct(max((item["high"] for item in window), default=signal["close"]), signal["close"]), 4)
                row[f"mae_{hold}d_pct"] = round(pct(min((item["low"] for item in window), default=signal["close"]), signal["close"]), 4)
            rows.append(row)
    return rows


def build_overlap_rows(signals):
    keys = {rule_id: {(item["symbol"], item["date"]) for item in items} for rule_id, items in signals.items()}
    rows = []
    rule_ids = list(keys)
    for left_index, left in enumerate(rule_ids):
        for right in rule_ids[left_index + 1:]:
            intersection = keys[left] & keys[right]
            union = keys[left] | keys[right]
            rows.append({
                "left_rule": left, "right_rule": right, "left_signals": len(keys[left]),
                "right_signals": len(keys[right]), "same_stock_date": len(intersection),
                "jaccard_pct": round(len(intersection) / len(union) * 100, 4) if union else 0,
            })
    return rows


def previous_date(value):
    return (datetime.strptime(value, "%Y-%m-%d").date() - timedelta(days=1)).isoformat()


def parse_numbers(value, cast):
    return [cast(item.strip()) for item in value.split(",") if item.strip()]


def blank_to_none(value):
    return None if value in (None, "") else float(value)


def rate(items, predicate):
    return (sum(1 for item in items if predicate(item)) / len(items) * 100) if items else 0


def mean(values):
    return sum(values) / len(values) if values else 0


def median(values):
    ordered = sorted(values)
    if not ordered:
        return 0
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def ranking_score(row):
    if row["trades"] < 10:
        return -999999
    return row["return_on_turnover_pct"] * 4 + row["win_rate_pct"] * 0.08 - abs(min(row["max_trade_loss_pct"], 0)) * 0.25


def configuration_key(row):
    return row["rule_id"], row["exit_policy"], str(row["hold_days"]), str(row["target_pct"]), str(row["stop_pct"])


def write_csv(path, rows):
    rows = list(rows)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()

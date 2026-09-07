import argparse
import csv
from collections import defaultdict
from pathlib import Path

from server import (
    apply_rule,
    build_backtest_context,
    build_indicators,
    connect,
    load_group_stocks,
    load_rows,
    simulate_trades,
    summarize_trades,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "outputs" / "momentum_rule_group_sweep.csv"


def main():
    parser = argparse.ArgumentParser(description="Sweep momentum and swing rule groups on NSE EOD data.")
    parser.add_argument("--from-date", default="2026-06-01")
    parser.add_argument("--to-date", default="2026-09-04")
    parser.add_argument("--group", default="all")
    parser.add_argument("--capital", type=float, default=10_000)
    parser.add_argument("--hold-days", default="3,5,10,15,21")
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    args = parser.parse_args()

    rules = build_rules()
    rule_groups = build_rule_groups(rules)
    hold_days_options = [int(item.strip()) for item in args.hold_days.split(",") if item.strip()]
    max_hold_days = max(hold_days_options) if hold_days_options else 21
    candidates_by_rule, rows_by_symbol = build_rule_candidates(args.group, args.from_date, args.to_date, rules, max_hold_days)

    runs = []
    for rule in rules:
        runs.extend(backtest_candidate_set(
            kind="single",
            name=rule["name"],
            picks_by_date=candidates_by_rule[rule["id"]],
            rows_by_symbol=rows_by_symbol,
            capital=args.capital,
            hold_days_options=hold_days_options,
        ))

    for group in rule_groups:
        picks_by_date = combine_group_candidates(candidates_by_rule, group)
        runs.extend(backtest_candidate_set(
            kind="group",
            name=group["name"],
            picks_by_date=picks_by_date,
            rows_by_symbol=rows_by_symbol,
            capital=args.capital,
            hold_days_options=hold_days_options,
            min_matches=group["minMatches"],
            rule_count=len(group["ruleIds"]),
        ))

    runs.sort(key=score_run, reverse=True)
    write_csv(Path(args.output), runs)
    print(f"Wrote {len(runs)} runs to {args.output}")
    print_top("Best balanced runs", runs[:25])
    profit_leaders = sorted(runs, key=lambda row: (row["returnOnTurnoverPct"], row["netPnl"]), reverse=True)
    print_top("Highest return runs", profit_leaders[:20])
    print_family_leaders(runs)


def build_rules():
    return [
        rule("rule_screenshot_strict", "Momentum Screenshot Strict", [
            price(100, 999999),
            {"id": "price_change_1d", "values": {"minPriceChange1D": 5, "maxPriceChange1D": 999}},
            {"id": "adv20_min", "values": {"minAdv20": 20_000}},
            {"id": "rsi14_range", "values": {"rsiMin": 70, "rsiMax": 100}},
            {"id": "rsi14_rising", "values": {"minRsiRise": 0}},
            {"id": "ema10_above_ema20", "values": {"minEmaGapPct": 0}},
            {"id": "cci14_strong_trend", "values": {"minCci14": 200, "maxCci14": 999}},
        ]),
        rule("rule_momentum_balanced", "Momentum Balanced", [
            price(100, 1000),
            {"id": "price_change_1d", "values": {"minPriceChange1D": 1, "maxPriceChange1D": 8}},
            {"id": "rsi14_range", "values": {"rsiMin": 58, "rsiMax": 74}},
            {"id": "rsi14_rising", "values": {"minRsiRise": 0}},
            {"id": "ema10_above_ema20", "values": {"minEmaGapPct": 0}},
            {"id": "cci14_strong_trend", "values": {"minCci14": 110, "maxCci14": 280}},
            {"id": "atr_risk", "values": {"minAtrPct": 0, "maxAtrPct": 8}},
        ]),
        rule("rule_momentum_soft", "Momentum Soft Entry", [
            price(100, 1000),
            {"id": "price_change_1d", "values": {"minPriceChange1D": 0.5, "maxPriceChange1D": 6}},
            {"id": "rsi14_range", "values": {"rsiMin": 55, "rsiMax": 70}},
            {"id": "rsi14_rising", "values": {"minRsiRise": -1}},
            {"id": "ema10_above_ema20", "values": {"minEmaGapPct": 0}},
            {"id": "cci14_strong_trend", "values": {"minCci14": 75, "maxCci14": 220}},
            {"id": "atr_risk", "values": {"minAtrPct": 0, "maxAtrPct": 7}},
        ]),
        rule("rule_volume_momentum", "Volume Momentum Breakout", [
            price(100, 1000),
            {"id": "relative_volume", "values": {"minRelativeVolume": 1.5, "maxRelativeVolume": 999}},
            {"id": "price_change_1d", "values": {"minPriceChange1D": 1, "maxPriceChange1D": 10}},
            {"id": "ema10_above_ema20", "values": {"minEmaGapPct": 0}},
            {"id": "cci14_strong_trend", "values": {"minCci14": 110, "maxCci14": 999}},
            {"id": "atr_risk", "values": {"minAtrPct": 0, "maxAtrPct": 9}},
        ]),
        rule("rule_delivery_momentum", "Delivery Momentum", [
            price(100, 1000),
            {"id": "relative_volume", "values": {"minRelativeVolume": 1.2, "maxRelativeVolume": 999}},
            {"id": "delivery_pct_range", "values": {"minDeliveryPct": 50, "maxDeliveryPct": 100}},
            {"id": "relative_delivery_qty", "values": {"minRelativeDelivery": 1.2, "maxRelativeDelivery": 999}},
            {"id": "price_change_1d", "values": {"minPriceChange1D": 0.5, "maxPriceChange1D": 10}},
            {"id": "ema10_above_ema20", "values": {"minEmaGapPct": 0}},
        ]),
        rule("rule_multi_period_trend", "Multi-Period Trend", [
            price(100, 1000),
            {"id": "multi_period_momentum", "values": multi_period(use_15d=True, use_3m=True)},
            {"id": "ema10_above_ema20", "values": {"minEmaGapPct": 0}},
            {"id": "rsi14_range", "values": {"rsiMin": 55, "rsiMax": 74}},
            {"id": "atr_risk", "values": {"minAtrPct": 0, "maxAtrPct": 8}},
        ]),
        rule("rule_quiet_trend", "Quiet Trend Compression", [
            price(100, 1000),
            {"id": "range_compression_10d", "values": {"minCompression10D": 0, "maxCompression10D": 12}},
            {"id": "close_near_20d_high", "values": {"maxDistanceFrom20DHigh": 3}},
            {"id": "ema_trend", "values": {"minEmaTrendChecks": 3}},
            {"id": "atr_risk", "values": {"minAtrPct": 3, "maxAtrPct": 6}},
            {"id": "rsi14_range", "values": {"rsiMin": 50, "rsiMax": 68}},
            {"id": "obv_accumulation_3d", "values": {"minObv3D": 0.5, "maxAbsMomentum3D": 8}},
        ]),
        rule("rule_controlled_breakout", "Controlled Breakout", [
            price(100, 1000),
            {"id": "close_near_20d_high", "values": {"maxDistanceFrom20DHigh": 3}},
            {"id": "price_change_1d", "values": {"minPriceChange1D": 0, "maxPriceChange1D": 6}},
            {"id": "ema10_above_ema20", "values": {"minEmaGapPct": 0}},
            {"id": "cci14_strong_trend", "values": {"minCci14": 75, "maxCci14": 250}},
            {"id": "atr_risk", "values": {"minAtrPct": 0, "maxAtrPct": 7}},
        ]),
        rule("rule_macd_momentum_confirm", "MACD Momentum Confirm", [
            price(100, 1000),
            {"id": "macd_bullish_momentum", "values": {"minMacdLine": -999, "minMacdHistogram": 0, "minMacdHistogramChange": 0}},
            {"id": "ema10_above_ema20", "values": {"minEmaGapPct": 0}},
            {"id": "rsi14_range", "values": {"rsiMin": 55, "rsiMax": 75}},
            {"id": "atr_risk", "values": {"minAtrPct": 0, "maxAtrPct": 8}},
        ]),
    ]


def build_rule_groups(rules):
    ids = {item["id"] for item in rules}

    def group(name, min_matches, rule_ids):
        return {"name": name, "minMatches": min_matches, "ruleIds": [item for item in rule_ids if item in ids]}

    return [
        group("Momentum Consensus", 2, [
            "rule_momentum_balanced",
            "rule_volume_momentum",
            "rule_multi_period_trend",
        ]),
        group("High Conviction Momentum", 3, [
            "rule_momentum_balanced",
            "rule_volume_momentum",
            "rule_delivery_momentum",
            "rule_multi_period_trend",
        ]),
        group("Controlled Swing Agreement", 2, [
            "rule_momentum_soft",
            "rule_controlled_breakout",
            "rule_quiet_trend",
            "rule_macd_momentum_confirm",
        ]),
        group("Delivery Plus Trend", 2, [
            "rule_delivery_momentum",
            "rule_multi_period_trend",
            "rule_controlled_breakout",
        ]),
        group("Aggressive Screenshot Agreement", 1, [
            "rule_screenshot_strict",
        ]),
        group("Momentum Or Trend Watch", 2, [
            "rule_momentum_balanced",
            "rule_momentum_soft",
            "rule_volume_momentum",
            "rule_controlled_breakout",
            "rule_macd_momentum_confirm",
        ]),
    ]


def build_rule_candidates(group_id, from_date, to_date, rules, max_hold_days):
    candidates_by_rule = {rule["id"]: defaultdict(list) for rule in rules}
    rows_by_symbol = {}
    with connect() as conn:
        stocks = load_group_stocks(conn, group_id)
        for stock in stocks:
            rows = load_rows(conn, stock["id"])
            if len(rows) < 60:
                continue
            rows_by_symbol[stock["symbol"]] = rows
            indicators = build_indicators(rows)
            for index in range(21, len(rows) - max_hold_days - 1):
                row = rows[index]
                if row["trade_date"] < from_date or row["trade_date"] > to_date:
                    continue
                ctx = build_backtest_context(rows, indicators, index)
                for rule_item in rules:
                    passed, _ = apply_rule(ctx, rule_item)
                    if passed:
                        candidates_by_rule[rule_item["id"]][row["trade_date"]].append({
                            "symbol": stock["symbol"],
                            "index": index,
                            "volume": row["volume"],
                            "close": row["close"],
                        })
    return candidates_by_rule, rows_by_symbol


def combine_group_candidates(candidates_by_rule, group):
    by_date_symbol = defaultdict(dict)
    for rule_id in group["ruleIds"]:
        for trade_date, picks in candidates_by_rule[rule_id].items():
            for pick in picks:
                key = (trade_date, pick["symbol"])
                existing = by_date_symbol[key]
                if not existing:
                    existing.update(pick)
                    existing["matchCount"] = 0
                    existing["matchedRuleIds"] = []
                existing["matchCount"] += 1
                existing["matchedRuleIds"].append(rule_id)

    out = defaultdict(list)
    for (trade_date, _symbol), pick in by_date_symbol.items():
        if pick["matchCount"] >= group["minMatches"]:
            out[trade_date].append(pick)
    return out


def backtest_candidate_set(kind, name, picks_by_date, rows_by_symbol, capital, hold_days_options, min_matches=1, rule_count=1):
    if not picks_by_date:
        return []
    total_signals = sum(len(items) for items in picks_by_date.values())
    runs = []
    for top_n in [3, 5, 10]:
        for target_pct, stop_pct in [(5, 3), (5, 5), (7, 5), (10, 7), (12, 8)]:
            for hold_days in hold_days_options:
                trades = simulate_trades(picks_by_date, rows_by_symbol, top_n, capital, target_pct, stop_pct, hold_days)
                if not trades:
                    continue
                runs.append({
                    "kind": kind,
                    "name": name,
                    "topN": top_n,
                    "targetPct": target_pct,
                    "stopPct": stop_pct,
                    "holdDays": hold_days,
                    "minMatches": min_matches,
                    "ruleCount": rule_count,
                    "totalSignals": total_signals,
                    "signalDays": len(picks_by_date),
                    **summarize_trades(trades, capital),
                })
    return runs


def score_run(row):
    if row["trades"] < 25:
        trade_penalty = -5
    elif row["trades"] > 450:
        trade_penalty = -1
    else:
        trade_penalty = 0
    return (
        row["returnOnTurnoverPct"] * 2
        + row["winRatePct"] / 20
        - row["stopHitPct"] / 25
        + trade_penalty,
        row["netPnl"],
    )


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def print_top(title, rows):
    print(f"\n{title}")
    for row in rows:
        print(format_row(row))


def print_family_leaders(rows):
    print("\nBest by rule/group")
    by_name = defaultdict(list)
    for row in rows:
        by_name[(row["kind"], row["name"])].append(row)
    leaders = [max(items, key=score_run) for items in by_name.values()]
    leaders.sort(key=score_run, reverse=True)
    for row in leaders:
        print(format_row(row))


def format_row(row):
    return (
        f"{row['kind']:<6} {row['name']:<30} top{row['topN']:<2} "
        f"t/s {row['targetPct']:.0f}/{row['stopPct']:.0f} hold {row['holdDays']:<2} "
        f"trades {row['trades']:<4} pnl {row['netPnl']:>10.2f} "
        f"ret {row['returnOnTurnoverPct']:>6.2f}% win {row['winRatePct']:>5.1f}% "
        f"target {row['targetHitPct']:>5.1f}% stop {row['stopHitPct']:>5.1f}% "
        f"signals {row['totalSignals']}"
    )


def rule(rule_id, name, filters):
    return {"id": rule_id, "name": name, "filters": filters}


def price(min_price, max_price):
    return {"id": "price_range", "values": {"minPrice": min_price, "maxPrice": max_price}}


def multi_period(use_15d=False, use_3m=False):
    return {
        "useMomentum1W": False,
        "minMomentum1W": 0,
        "maxMomentum1W": 15,
        "useMomentum15D": use_15d,
        "minMomentum15D": 2,
        "maxMomentum15D": 25,
        "useMomentum1M": False,
        "minMomentum1M": 5,
        "maxMomentum1M": 30,
        "useMomentum3M": use_3m,
        "minMomentum3M": 10,
        "maxMomentum3M": 60,
        "useMomentum6M": False,
        "minMomentum6M": 15,
        "maxMomentum6M": 120,
        "useMomentum1Y": False,
        "minMomentum1Y": 20,
        "maxMomentum1Y": 250,
        "useMomentum6MTo12M": False,
        "minMomentum6MTo12M": -20,
        "maxMomentum6MTo12M": 80,
    }


if __name__ == "__main__":
    main()

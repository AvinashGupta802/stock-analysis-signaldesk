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
OUTPUT_PATH = ROOT / "outputs" / "macd_filter_sweep.csv"


MACD_DEFAULT = {
    "id": "macd_bullish_momentum",
    "values": {"minMacdLine": 0, "minMacdHistogram": 0, "minMacdHistogramChange": 0},
}

MACD_EARLY = {
    "id": "macd_bullish_momentum",
    "values": {"minMacdLine": -999, "minMacdHistogram": 0, "minMacdHistogramChange": 0},
}


def main():
    parser = argparse.ArgumentParser(description="Backtest where MACD Bullish Momentum adds value.")
    parser.add_argument("--from-date", default="2026-06-01")
    parser.add_argument("--to-date", default="2026-08-20")
    parser.add_argument("--group", default="all")
    parser.add_argument("--capital", type=float, default=10_000)
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    args = parser.parse_args()

    rules = build_rule_variants()
    candidates = {rule["name"]: defaultdict(list) for rule in rules}
    rows_by_symbol = {}

    with connect() as conn:
        stocks = load_group_stocks(conn, args.group)
        for stock in stocks:
            rows = load_rows(conn, stock["id"])
            if len(rows) < 60:
                continue
            rows_by_symbol[stock["symbol"]] = rows
            indicators = build_indicators(rows)
            for index in range(21, len(rows) - 22):
                row = rows[index]
                if row["trade_date"] < args.from_date or row["trade_date"] > args.to_date:
                    continue
                ctx = build_backtest_context(rows, indicators, index)
                for rule in rules:
                    passed, _ = apply_rule(ctx, rule)
                    if passed:
                        candidates[rule["name"]][row["trade_date"]].append({
                            "symbol": stock["symbol"],
                            "index": index,
                            "volume": row["volume"],
                            "close": row["close"],
                        })

    runs = []
    for rule in rules:
        picks_by_date = candidates[rule["name"]]
        if not picks_by_date:
            continue
        total_signals = sum(len(items) for items in picks_by_date.values())
        for top_n in [5, 10]:
            for target_pct, stop_pct in [(5, 3), (7, 5), (10, 7)]:
                for hold_days in [5, 10, 15, 21]:
                    trades = simulate_trades(picks_by_date, rows_by_symbol, top_n, args.capital, target_pct, stop_pct, hold_days)
                    if not trades:
                        continue
                    summary = summarize_trades(trades, args.capital)
                    runs.append({
                        "rule": rule["name"],
                        "family": rule["family"],
                        "macd": rule["macd"],
                        "top_n": top_n,
                        "target_pct": target_pct,
                        "stop_pct": stop_pct,
                        "hold_days": hold_days,
                        "total_signals": total_signals,
                        "signal_days": len(picks_by_date),
                        **summary,
                    })

    runs.sort(key=lambda item: (item["returnOnTurnoverPct"], item["netPnl"]), reverse=True)
    write_csv(Path(args.output), runs)
    print(f"Wrote {len(runs)} runs to {args.output}")
    print_best(runs)
    print_family_comparison(runs)


def build_rule_variants():
    base_rules = [
        rule("MACD Only", "macd_only", [price(), MACD_DEFAULT]),
        rule("MACD Early Only", "macd_only", [price(), MACD_EARLY]),
        rule("Volume Delivery Core", "volume_delivery", [
            price(),
            {"id": "relative_volume", "values": {"minRelativeVolume": 1.5, "maxRelativeVolume": 999}},
            {"id": "delivery_pct_range", "values": {"minDeliveryPct": 60, "maxDeliveryPct": 100}},
        ]),
        rule("Breakout Trend Quality", "breakout_trend", [
            price(),
            {"id": "close_near_20d_high", "values": {"maxDistanceFrom20DHigh": 2}},
            {"id": "ema_trend", "values": {"minEmaTrendChecks": 3}},
            {"id": "atr_risk", "values": {"minAtrPct": 0, "maxAtrPct": 8}},
        ]),
        rule("Quiet Trend Compression", "quiet_trend", [
            price(),
            {"id": "range_compression_10d", "values": {"minCompression10D": 0, "maxCompression10D": 12}},
            {"id": "close_near_20d_high", "values": {"maxDistanceFrom20DHigh": 3}},
            {"id": "ema_trend", "values": {"minEmaTrendChecks": 3}},
            {"id": "atr_risk", "values": {"minAtrPct": 3, "maxAtrPct": 6}},
            {"id": "rsi14_range", "values": {"rsiMin": 50, "rsiMax": 68}},
            {"id": "obv_accumulation_3d", "values": {"minObv3D": 0.5, "maxAbsMomentum3D": 8}},
        ]),
        rule("OBV Consolidation Breakout", "obv_consolidation", [
            price(),
            {"id": "range_compression_10d", "values": {"minCompression10D": 0, "maxCompression10D": 12}},
            {"id": "obv_accumulation_3d", "values": {"minObv3D": 0.5, "maxAbsMomentum3D": 2}},
            {"id": "atr_risk", "values": {"minAtrPct": 0, "maxAtrPct": 8}},
        ]),
        rule("Reversal Accumulation", "reversal_accumulation", [
            {"id": "price_range", "values": {"minPrice": 50, "maxPrice": 1000}},
            {"id": "price_momentum_3d", "values": {"minMomentum3D": -6, "maxMomentum3D": 3}},
            {"id": "atr_risk", "values": {"minAtrPct": 3, "maxAtrPct": 8}},
            {"id": "relative_volume", "values": {"minRelativeVolume": 1.5, "maxRelativeVolume": 999}},
            {"id": "relative_delivery_qty", "values": {"minRelativeDelivery": 1.5, "maxRelativeDelivery": 999}},
        ]),
    ]

    variants = []
    for item in base_rules:
        variants.append(item)
        if item["family"] != "macd_only":
            variants.append({
                **item,
                "name": item["name"] + " + MACD",
                "macd": "default",
                "filters": [*item["filters"], MACD_DEFAULT],
            })
            variants.append({
                **item,
                "name": item["name"] + " + MACD Early",
                "macd": "early",
                "filters": [*item["filters"], MACD_EARLY],
            })
    return variants


def price():
    return {"id": "price_range", "values": {"minPrice": 100, "maxPrice": 500}}


def rule(name, family, filters):
    return {"name": name, "family": family, "macd": "none", "filters": filters}


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def print_best(rows):
    print("\nTOP RUNS")
    for row in rows[:20]:
        print(format_row(row))


def print_family_comparison(rows):
    print("\nBEST BY FAMILY / MACD ROLE")
    groups = defaultdict(list)
    for row in rows:
        groups[(row["family"], row["macd"])].append(row)
    leaders = [max(items, key=lambda item: (item["returnOnTurnoverPct"], item["netPnl"])) for items in groups.values()]
    leaders.sort(key=lambda item: (item["family"], item["macd"]))
    for row in leaders:
        print(format_row(row))


def format_row(row):
    return (
        f"{row['rule']:<42} top{row['top_n']} tgt/stop {row['target_pct']:.0f}/{row['stop_pct']:.0f} "
        f"hold {row['hold_days']:<2} trades {row['trades']:<4} pnl {row['netPnl']:>10.2f} "
        f"ret {row['returnOnTurnoverPct']:>6.2f}% win {row['winRatePct']:>5.1f}% "
        f"target {row['targetHitPct']:>5.1f}% stop {row['stopHitPct']:>5.1f}% signals {row['total_signals']}"
    )


if __name__ == "__main__":
    main()

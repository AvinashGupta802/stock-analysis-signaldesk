import argparse
import csv
from collections import defaultdict
from datetime import date
from pathlib import Path

from server import (
    apply_rule,
    build_backtest_context,
    build_indicators,
    connect,
    load_group_stocks,
    load_rows,
    load_strategy,
    simulate_trades,
    summarize_trades,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs"


def main():
    parser = argparse.ArgumentParser(
        description="Deep-audit the active DB rules and rule groups without changing strategy data."
    )
    parser.add_argument("--from-date", default="2026-06-01")
    parser.add_argument("--to-date", default="2026-09-23")
    parser.add_argument("--universes", default="all,liquid,nifty500")
    parser.add_argument("--hold-days", default="2,3,5,7,10,15,21")
    parser.add_argument("--top-n", default="3,5,10")
    parser.add_argument("--exits", default="5:5,8:6,10:7,12:8,15:10")
    parser.add_argument("--capital", type=float, default=10_000)
    parser.add_argument("--output-prefix", default=f"saved_strategy_deep_audit_{date.today():%Y%m%d}")
    args = parser.parse_args()

    universes = parse_strings(args.universes)
    hold_days_options = parse_ints(args.hold_days)
    top_n_options = parse_ints(args.top_n)
    exits = parse_exits(args.exits)
    max_hold = max(hold_days_options)

    with connect() as conn:
        strategy = load_strategy(conn)
    rules = strategy["rules"]
    rule_by_id = {rule["id"]: rule for rule in rules}
    groups = [
        {
            **group,
            "rules": [rule_by_id[rule_id] for rule_id in group["ruleIds"] if rule_id in rule_by_id],
        }
        for group in strategy["ruleGroups"]
    ]
    groups = [group for group in groups if group["rules"]]
    print(f"Loaded {len(rules)} active rules and {len(groups)} active groups from SQLite", flush=True)

    windows = build_windows(args.from_date, args.to_date)
    output_rows = []
    for universe in universes:
        print(f"Building saved-strategy signals for {universe}...", flush=True)
        rows_by_symbol, picks = build_picks(
            universe, args.from_date, args.to_date, max_hold, rules, groups
        )
        print(
            f"{universe}: {len(rows_by_symbol):,} stocks; "
            f"{sum(len(items) for strategy_picks in picks.values() for items in strategy_picks.values()):,} signals",
            flush=True,
        )
        strategies = [
            {"id": rule["id"], "name": rule["name"], "type": "rule", "minMatches": 1}
            for rule in rules
        ] + [
            {
                "id": group["id"],
                "name": group["name"],
                "type": "group",
                "minMatches": group["minMatches"],
            }
            for group in groups
        ]
        for strategy_number, item in enumerate(strategies, start=1):
            strategy_picks = picks[item["id"]]
            if strategy_number % 5 == 0:
                print(f"{universe}: tested {strategy_number}/{len(strategies)} strategies", flush=True)
            for window_name, window_from, window_to in windows:
                for hold_days in hold_days_options:
                    window_picks = {
                        signal_date: [
                            pick for pick in day_picks if pick["futureBars"] >= hold_days + 1
                        ]
                        for signal_date, day_picks in strategy_picks.items()
                        if window_from <= signal_date <= window_to
                    }
                    window_picks = {
                        signal_date: day_picks
                        for signal_date, day_picks in window_picks.items()
                        if day_picks
                    }
                    for top_n in top_n_options:
                        for target_pct, stop_pct in exits:
                            trades = simulate_trades(
                                window_picks,
                                rows_by_symbol,
                                top_n,
                                args.capital,
                                target_pct,
                                stop_pct,
                                hold_days,
                            )
                            summary = summarize_trades(trades, args.capital)
                            output_rows.append(
                                {
                                    "universe": universe,
                                    "strategyType": item["type"],
                                    "strategyId": item["id"],
                                    "strategyName": item["name"],
                                    "minMatches": item["minMatches"],
                                    "window": window_name,
                                    "fromDate": window_from,
                                    "toDate": window_to,
                                    "topN": top_n,
                                    "targetPct": target_pct,
                                    "stopPct": stop_pct,
                                    "holdDays": hold_days,
                                    "totalSignals": sum(len(day) for day in window_picks.values()),
                                    "signalDays": len(window_picks),
                                    **summary,
                                }
                            )

    OUTPUT_DIR.mkdir(exist_ok=True)
    detail_path = OUTPUT_DIR / f"{args.output_prefix}_details.csv"
    ranking_path = OUTPUT_DIR / f"{args.output_prefix}_rankings.csv"
    write_csv(detail_path, output_rows)
    rankings = build_rankings(output_rows)
    write_csv(ranking_path, rankings)
    print(f"Wrote {detail_path}", flush=True)
    print(f"Wrote {ranking_path}", flush=True)
    print_top(rankings)


def build_picks(universe, from_date, to_date, max_hold, rules, groups):
    rule_ids = [rule["id"] for rule in rules]
    picks = {strategy_id: defaultdict(list) for strategy_id in rule_ids}
    picks.update({group["id"]: defaultdict(list) for group in groups})
    rows_by_symbol = {}
    with connect() as conn:
        stocks = load_group_stocks(conn, universe)
        for stock_number, stock in enumerate(stocks, start=1):
            if stock_number % 250 == 0:
                print(f"{universe}: scanned {stock_number}/{len(stocks)} stocks", flush=True)
            rows = load_rows(conn, stock["id"])
            if len(rows) < 30:
                continue
            rows_by_symbol[stock["symbol"]] = rows
            indicators = build_indicators(rows)
            for index in range(21, len(rows) - 1):
                row = rows[index]
                signal_date = row["trade_date"]
                if signal_date < from_date or signal_date > to_date:
                    continue
                ctx = build_backtest_context(rows, indicators, index)
                passed_rule_ids = set()
                for rule in rules:
                    passed, _ = apply_rule(ctx, rule)
                    if not passed:
                        continue
                    passed_rule_ids.add(rule["id"])
                    picks[rule["id"]][signal_date].append(
                        make_pick(stock["symbol"], index, row, len(rows) - index - 1, 1)
                    )
                for group in groups:
                    match_count = sum(rule["id"] in passed_rule_ids for rule in group["rules"])
                    if match_count >= group["minMatches"]:
                        picks[group["id"]][signal_date].append(
                            make_pick(
                                stock["symbol"], index, row, len(rows) - index - 1, match_count
                            )
                        )
    return rows_by_symbol, picks


def make_pick(symbol, index, row, future_bars, match_count):
    return {
        "symbol": symbol,
        "index": index,
        "volume": row["volume"],
        "close": row["close"],
        "futureBars": future_bars,
        "matchCount": match_count,
    }


def build_windows(from_date, to_date):
    windows = [("full", from_date, to_date)]
    start_year, start_month = map(int, from_date[:7].split("-"))
    end_year, end_month = map(int, to_date[:7].split("-"))
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        month_start = f"{year:04d}-{month:02d}-01"
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        month_end = str(date.fromisoformat(f"{next_year:04d}-{next_month:02d}-01").toordinal() - 1)
        month_end = date.fromordinal(int(month_end)).isoformat()
        windows.append((f"{year:04d}-{month:02d}", max(from_date, month_start), min(to_date, month_end)))
        year, month = next_year, next_month
    return windows


def build_rankings(rows):
    monthly = defaultdict(dict)
    full_rows = []
    for row in rows:
        key = (
            row["universe"], row["strategyType"], row["strategyId"], row["strategyName"],
            row["minMatches"], row["topN"], row["targetPct"], row["stopPct"], row["holdDays"],
        )
        if row["window"] == "full":
            full_rows.append((key, row))
        else:
            monthly[key][row["window"]] = row

    rankings = []
    for key, full in full_rows:
        periods = [item for item in monthly[key].values() if item["trades"] > 0]
        positive_periods = sum(item["netPnl"] > 0 for item in periods)
        profitable_ratio = positive_periods / len(periods) if periods else 0
        worst_period_return = min((item["returnOnTurnoverPct"] for item in periods), default=0)
        score = (
            full["returnOnTurnoverPct"] * 0.35
            + full["winRatePct"] * 0.02
            + profitable_ratio * 3
            + min(worst_period_return, 0) * 0.5
        )
        rankings.append(
            {
                **full,
                "monthsWithTrades": len(periods),
                "profitableMonths": positive_periods,
                "profitableMonthPct": profitable_ratio * 100,
                "worstMonthReturnPct": worst_period_return,
                "robustnessScore": score,
            }
        )
    rankings.sort(
        key=lambda row: (row["robustnessScore"], row["netPnl"], row["trades"]), reverse=True
    )
    return rankings


def print_top(rows):
    print("Top 30 by robustness score", flush=True)
    for row in rows[:30]:
        print(
            f"{row['universe']:8} {row['strategyName'][:38]:38} "
            f"top{row['topN']} {row['targetPct']:g}/{row['stopPct']:g} hold{row['holdDays']:2} "
            f"trades {row['trades']:4} pnl {row['netPnl']:10.2f} "
            f"ret {row['returnOnTurnoverPct']:6.2f}% win {row['winRatePct']:5.1f}% "
            f"months+ {row['profitableMonthPct']:5.1f}% score {row['robustnessScore']:6.2f}",
            flush=True,
        )


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def parse_strings(value):
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_ints(value):
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def parse_exits(value):
    return [tuple(float(part) for part in item.split(":")) for item in parse_strings(value)]


if __name__ == "__main__":
    main()

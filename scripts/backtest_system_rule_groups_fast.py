import csv
from collections import defaultdict
from pathlib import Path

from backtest_system_rule_groups import GROUPS, RULE_BY_ID
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
OUTPUT_DIR = ROOT / "outputs"
FROM_DATE = "2026-06-01"
TO_DATE = "2026-09-07"
UNIVERSES = ["all", "liquid", "nifty500"]
HOLD_DAYS = [2, 3, 5, 10, 15, 21]
TOP_NS = [3, 5, 10]
EXITS = [(10, 7), (12, 8), (15, 10)]
CAPITAL_PER_STOCK = 10_000


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    output_path = OUTPUT_DIR / "system_rule_group_audit_fast_20260908.csv"
    rows = []
    for universe in UNIVERSES:
        print(f"Building picks for {universe}...")
        rows_by_symbol, group_picks = build_group_picks(universe)
        for group_id, group_name, min_matches, rule_ids in GROUPS:
            picks_by_date = group_picks[group_id]
            total_signals = sum(len(items) for items in picks_by_date.values())
            for hold_days in HOLD_DAYS:
                for top_n in TOP_NS:
                    for target_pct, stop_pct in EXITS:
                        trades = simulate_trades(
                            picks_by_date,
                            rows_by_symbol,
                            top_n,
                            CAPITAL_PER_STOCK,
                            target_pct,
                            stop_pct,
                            hold_days,
                        )
                        summary = summarize_trades(trades, CAPITAL_PER_STOCK)
                        rows.append(
                            {
                                "universe": universe,
                                "groupId": group_id,
                                "groupName": group_name,
                                "minMatches": min_matches,
                                "ruleCount": len(rule_ids),
                                "topN": top_n,
                                "targetPct": target_pct,
                                "stopPct": stop_pct,
                                "holdDays": hold_days,
                                "totalSignals": total_signals,
                                "signalDays": len(picks_by_date),
                                "trades": summary["trades"],
                                "netPnl": summary["netPnl"],
                                "returnOnTurnoverPct": summary["returnOnTurnoverPct"],
                                "avgTradeReturnPct": summary["avgTradeReturnPct"],
                                "winRatePct": summary["winRatePct"],
                                "targetHitPct": summary["targetHitPct"],
                                "stopHitPct": summary["stopHitPct"],
                            }
                        )
    write_rows(output_path, rows)
    print(f"Wrote {output_path}")
    print_top(rows)


def build_group_picks(universe):
    max_hold = max(HOLD_DAYS)
    rows_by_symbol = {}
    group_picks = {group_id: defaultdict(list) for group_id, *_ in GROUPS}
    with connect() as conn:
        stocks = load_group_stocks(conn, universe)
        for stock_number, stock in enumerate(stocks, start=1):
            if stock_number % 500 == 0:
                print(f"{universe}: scanned {stock_number}/{len(stocks)} stocks")
            rows = load_rows(conn, stock["id"])
            if len(rows) < 80:
                continue
            rows_by_symbol[stock["symbol"]] = rows
            indicators = build_indicators(rows)
            for index in range(21, len(rows) - max_hold - 1):
                row = rows[index]
                if row["trade_date"] < FROM_DATE or row["trade_date"] > TO_DATE:
                    continue
                ctx = build_backtest_context(rows, indicators, index)
                rule_passes = {}
                for rule_id, rule in RULE_BY_ID.items():
                    passed, reasons = apply_rule(ctx, rule)
                    rule_passes[rule_id] = {"passed": passed, "reasons": reasons}
                for group_id, _group_name, min_matches, rule_ids in GROUPS:
                    matched = [rule_id for rule_id in rule_ids if rule_passes[rule_id]["passed"]]
                    if len(matched) < min_matches:
                        continue
                    group_picks[group_id][row["trade_date"]].append(
                        {
                            "symbol": stock["symbol"],
                            "index": index,
                            "volume": row["volume"],
                            "close": row["close"],
                            "matchCount": len(matched),
                            "matchedRuleIds": matched,
                        }
                    )
    return rows_by_symbol, group_picks


def write_rows(path, rows):
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def print_top(rows):
    candidates = [row for row in rows if row["trades"] >= 25 and row["netPnl"] > 0]
    candidates.sort(key=lambda item: (item["returnOnTurnoverPct"], item["winRatePct"]), reverse=True)
    print("Top 30 by return on turnover")
    for row in candidates[:30]:
        print(
            f"{row['universe']:8} {row['groupName'][:38]:38} "
            f"top{row['topN']} t/s {row['targetPct']}/{row['stopPct']} hold {row['holdDays']:2} "
            f"trades {row['trades']:4} pnl {row['netPnl']:10.2f} "
            f"ret {row['returnOnTurnoverPct']:6.2f}% win {row['winRatePct']:5.1f}% "
            f"target {row['targetHitPct']:5.1f}% stop {row['stopHitPct']:5.1f}%"
        )


if __name__ == "__main__":
    main()

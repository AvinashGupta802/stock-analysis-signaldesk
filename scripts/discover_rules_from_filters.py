import argparse
import csv
from collections import defaultdict
from itertools import combinations
from pathlib import Path

from server import (
    apply_rule,
    build_backtest_context,
    build_indicators,
    connect,
    load_group_stocks,
    load_rows,
    pct,
    simulate_trades,
    summarize_trades,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs"


def main():
    parser = argparse.ArgumentParser(description="Discover candidate rules from current SignalDesk filters.")
    parser.add_argument("--from-date", default="2026-06-01")
    parser.add_argument("--to-date", default="2026-09-04")
    parser.add_argument("--group", default="all")
    parser.add_argument("--hold-days", default="5,10,15")
    parser.add_argument("--capital", type=float, default=10_000)
    parser.add_argument("--max-atoms-for-pairs", type=int, default=36)
    parser.add_argument("--max-pairs-for-triples", type=int, default=160)
    parser.add_argument("--output-prefix", default="discovered_rules")
    args = parser.parse_args()

    hold_days_options = parse_ints(args.hold_days)
    max_hold = max(hold_days_options)
    records, rows_by_symbol = build_records(args.group, args.from_date, args.to_date, max_hold)
    atoms = build_atoms()
    print(f"Records: {len(records):,}; atoms: {len(atoms)}; hold days: {hold_days_options}")

    atom_sets = evaluate_atoms(records, atoms)
    atom_scores = score_atom_sets(records, atoms, atom_sets)
    atom_scores.sort(key=quality_score, reverse=True)
    write_csv(OUTPUT_DIR / f"{args.output_prefix}_atoms.csv", rows_for_csv(atom_scores))
    print_top("Top single filter settings by reverse-engineered quality", atom_scores[:20])

    selected_atoms = [
        row["atom"]
        for row in atom_scores
        if row["count"] >= 80 and not row["atom"]["technical"]
    ][:args.max_atoms_for_pairs]

    candidate_rules = []
    candidate_rules.extend([make_candidate([row["atom"]], row) for row in atom_scores[:30] if row["count"] >= 80])

    pair_scores = []
    for left, right in combinations(selected_atoms, 2):
        if left["filter"]["id"] == right["filter"]["id"]:
            continue
        ids = atom_sets[left["id"]] & atom_sets[right["id"]]
        row = score_ids(records, ids)
        if row and row["count"] >= 40:
            row["name"] = f"{left['name']} + {right['name']}"
            row["atom_ids"] = f"{left['id']}|{right['id']}"
            row["filters"] = [left["filter"], right["filter"]]
            row["atoms"] = [left, right]
            pair_scores.append(row)
    pair_scores.sort(key=quality_score, reverse=True)
    write_csv(OUTPUT_DIR / f"{args.output_prefix}_pairs.csv", rows_for_csv(pair_scores))
    print_top("Top two-filter combinations", pair_scores[:20])
    candidate_rules.extend([make_candidate(row["atoms"], row) for row in pair_scores[:80]])

    triple_scores = []
    for pair in pair_scores[:args.max_pairs_for_triples]:
        used_ids = {atom["id"] for atom in pair["atoms"]}
        used_filters = {atom["filter"]["id"] for atom in pair["atoms"]}
        pair_ids = ids_from_atom_ids(atom_sets, pair["atom_ids"])
        for atom in selected_atoms:
            if atom["id"] in used_ids or atom["filter"]["id"] in used_filters:
                continue
            ids = pair_ids & atom_sets[atom["id"]]
            row = score_ids(records, ids)
            if row and row["count"] >= 25:
                atoms_for_rule = [*pair["atoms"], atom]
                row["name"] = " + ".join(item["name"] for item in atoms_for_rule)
                row["atom_ids"] = "|".join(item["id"] for item in atoms_for_rule)
                row["filters"] = [item["filter"] for item in atoms_for_rule]
                row["atoms"] = atoms_for_rule
                triple_scores.append(row)
    triple_scores = dedupe_rules(triple_scores)
    triple_scores.sort(key=quality_score, reverse=True)
    write_csv(OUTPUT_DIR / f"{args.output_prefix}_triples.csv", rows_for_csv(triple_scores))
    print_top("Top three-filter combinations", triple_scores[:20])
    candidate_rules.extend([make_candidate(row["atoms"], row) for row in triple_scores[:120]])

    fixed_groups = build_fixed_rule_groups()
    backtest_rows = backtest_candidates(
        records,
        rows_by_symbol,
        candidate_rules,
        fixed_groups,
        hold_days_options,
        args.capital,
    )
    backtest_rows.sort(key=backtest_score, reverse=True)
    write_csv(OUTPUT_DIR / f"{args.output_prefix}_backtests.csv", backtest_rows)
    print_top("Top portfolio backtests", backtest_rows[:30], formatter=format_backtest_row)
    print_family_summary(backtest_rows)


def build_records(group_id, from_date, to_date, max_hold):
    records = []
    rows_by_symbol = {}
    with connect() as conn:
        stocks = load_group_stocks(conn, group_id)
        for stock in stocks:
            rows = load_rows(conn, stock["id"])
            if len(rows) < 80:
                continue
            rows_by_symbol[stock["symbol"]] = rows
            indicators = build_indicators(rows)
            for index in range(21, len(rows) - max_hold - 1):
                row = rows[index]
                if row["trade_date"] < from_date or row["trade_date"] > to_date:
                    continue
                ctx = build_backtest_context(rows, indicators, index)
                records.append({
                    "id": len(records),
                    "symbol": stock["symbol"],
                    "date": row["trade_date"],
                    "index": index,
                    "volume": row["volume"],
                    "close": row["close"],
                    "ctx": ctx,
                    "future5": future_return(rows, index, 5),
                    "future10": future_return(rows, index, 10),
                    "future15": future_return(rows, index, 15),
                    "future10_high": future_high_return(rows, index, 10),
                    "future15_high": future_high_return(rows, index, 15),
                })
    return records, rows_by_symbol


def build_atoms():
    atoms = []

    def add(atom_id, name, filter_id, values, technical=False):
        atoms.append({
            "id": atom_id,
            "name": name,
            "filter": {"id": filter_id, "values": values},
            "technical": technical,
        })

    for low, high in [(10, 999999), (50, 1000), (100, 500), (100, 1000), (200, 1000)]:
        add(f"price_{low}_{high}", f"Price {low}-{high}", "price_range", {"minPrice": low, "maxPrice": high}, technical=True)
    for value in [20_000, 100_000, 500_000, 1_000_000]:
        add(f"adv20_{value}", f"20D ADV >= {value:,}", "adv20_min", {"minAdv20": value})
    for value in [20_000, 100_000, 500_000, 1_000_000]:
        add(f"daily_volume_{value}", f"Daily volume >= {value:,}", "daily_volume_range", {"minDailyVolume": value, "maxDailyVolume": 999_999_999})
    for value in [1.2, 1.5, 2.0, 3.0]:
        add(f"rvol_{value}", f"Volume >= {value:g}x 20D", "relative_volume", {"minRelativeVolume": value, "maxRelativeVolume": 999})
    for value in [1.2, 1.5, 2.0, 3.0]:
        add(f"rvol10_{value}", f"Volume >= {value:g}x 10D", "relative_volume_10d", {"minRelativeVolume10D": value, "maxRelativeVolume10D": 999})
    for value in [40, 50, 60, 70]:
        add(f"delivery_pct_{value}", f"Delivery % >= {value}", "delivery_pct_range", {"minDeliveryPct": value, "maxDeliveryPct": 100})
    for value in [1.0, 1.2, 1.5, 2.0]:
        add(f"rel_delivery_{value}", f"Delivery qty >= {value:g}x 20D", "relative_delivery_qty", {"minRelativeDelivery": value, "maxRelativeDelivery": 999})
    for low, high in [(-2, 2), (0, 5), (0.5, 6), (1, 8), (3, 12), (5, 999)]:
        add(f"price_1d_{low}_{high}", f"1D change {low:g}..{high:g}%", "price_change_1d", {"minPriceChange1D": low, "maxPriceChange1D": high})
    for low, high in [(-3, 3), (-2, 8), (0, 8), (1, 10), (2, 12)]:
        add(f"mom3_{low}_{high}", f"3D momentum {low:g}..{high:g}%", "price_momentum_3d", {"minMomentum3D": low, "maxMomentum3D": high})
    add("multi_15d_3m", "15D and 3M momentum positive", "multi_period_momentum", multi_values(use_15d=True, use_3m=True))
    add("multi_1m_3m", "1M and 3M momentum positive", "multi_period_momentum", multi_values(use_1m=True, use_3m=True))
    add("multi_3m_6m", "3M and 6M momentum positive", "multi_period_momentum", multi_values(use_3m=True, use_6m=True))
    add("multi_15d_1y", "15D and 1Y momentum positive", "multi_period_momentum", multi_values(use_15d=True, use_1y=True))
    for low, high in [(40, 100), (60, 100), (70, 100), (80, 100), (40, 80)]:
        add(f"range52_{low}_{high}", f"52W position {low}-{high}%", "range_position_52w", {"minRangePosition52W": low, "maxRangePosition52W": high})
    for value in [2, 3, 5, 8]:
        add(f"near20h_{value}", f"Close <= {value}% below 20D high", "close_near_20d_high", {"maxDistanceFrom20DHigh": value})
    for low in [60, 70, 80]:
        add(f"daypos_{low}", f"Close in top {100 - low}% of day range", "close_position_day_range", {"minClosePositionDay": low, "maxClosePositionDay": 100})
    for high in [8, 12, 18]:
        add(f"comp10_{high}", f"10D range compression <= {high}%", "range_compression_10d", {"minCompression10D": 0, "maxCompression10D": high})
    for value in [5, 20, 50]:
        add(f"liq_{value}", f"Rupee liquidity >= {value} cr", "rupee_liquidity", {"minRupeeLiquidityCr": value, "maxRupeeLiquidityCr": 999999})
    for value in [2, 3]:
        add(f"ema_trend_{value}", f"EMA trend checks >= {value}", "ema_trend", {"minEmaTrendChecks": value})
    for gap in [0, 0.5, 1.0]:
        add(f"ema10_20_{gap}", f"EMA10 above EMA20 by {gap:g}%", "ema10_above_ema20", {"minEmaGapPct": gap})
    add("macd_default", "MACD bullish", "macd_bullish_momentum", {"minMacdLine": 0, "minMacdHistogram": 0, "minMacdHistogramChange": 0})
    add("macd_early", "MACD early bullish", "macd_bullish_momentum", {"minMacdLine": -999, "minMacdHistogram": 0, "minMacdHistogramChange": 0})
    for low, high in [(0, 5), (0, 8), (3, 8), (3, 10)]:
        add(f"atr_{low}_{high}", f"ATR {low}-{high}%", "atr_risk", {"minAtrPct": low, "maxAtrPct": high})
    for obv, mom in [(0.5, 2), (0.5, 8), (1.0, 2), (1.0, 8)]:
        add(f"obv_{obv}_{mom}", f"OBV >= {obv:g}x with 3D move within {mom:g}%", "obv_accumulation_3d", {"minObv3D": obv, "maxAbsMomentum3D": mom})
    for low, high in [(45, 65), (50, 68), (55, 75), (60, 80), (70, 100)]:
        add(f"rsi_{low}_{high}", f"RSI {low}-{high}", "rsi14_range", {"rsiMin": low, "rsiMax": high})
    for value in [-1, 0, 2]:
        add(f"rsi_rise_{value}", f"RSI rising > {value:g}", "rsi14_rising", {"minRsiRise": value})
    for low, high in [(40, 70), (50, 80), (60, 90), (70, 100)]:
        add(f"mfi_{low}_{high}", f"MFI {low}-{high}", "mfi14_range", {"mfiMin": low, "mfiMax": high})
    for low, high in [(75, 220), (110, 280), (110, 999), (150, 999), (200, 999)]:
        add(f"cci_{low}_{high}", f"CCI {low}-{high}", "cci14_strong_trend", {"minCci14": low, "maxCci14": high})
    return atoms


def evaluate_atoms(records, atoms):
    atom_sets = {}
    for atom in atoms:
        ids = set()
        rule = {"name": atom["name"], "filters": [atom["filter"]]}
        for record in records:
            passed, _ = apply_rule(record["ctx"], rule)
            if passed:
                ids.add(record["id"])
        atom_sets[atom["id"]] = ids
    return atom_sets


def score_atom_sets(records, atoms, atom_sets):
    rows = []
    for atom in atoms:
        row = score_ids(records, atom_sets[atom["id"]])
        if not row:
            continue
        row["atom"] = atom
        row["name"] = atom["name"]
        row["atom_ids"] = atom["id"]
        row["filters"] = [atom["filter"]]
        rows.append(row)
    return rows


def score_ids(records, ids):
    if not ids:
        return None
    selected = [records[index] for index in ids]
    count = len(selected)
    if count == 0:
        return None
    return {
        "ids": set(ids),
        "count": count,
        "avgFuture5": avg([record["future5"] for record in selected]),
        "avgFuture10": avg([record["future10"] for record in selected]),
        "avgFuture15": avg([record["future15"] for record in selected]),
        "positive10Pct": avg([1 if record["future10"] > 0 else 0 for record in selected]) * 100,
        "hit10HighPct": avg([1 if record["future10_high"] >= 10 else 0 for record in selected]) * 100,
        "hit15HighPct": avg([1 if record["future15_high"] >= 10 else 0 for record in selected]) * 100,
    }


def backtest_candidates(records, rows_by_symbol, candidates, fixed_groups, hold_days_options, capital):
    record_by_id = {record["id"]: record for record in records}
    runs = []
    for candidate in candidates:
        picks = picks_from_ids(record_by_id, candidate["ids"])
        runs.extend(backtest_pick_set(candidate["kind"], candidate["name"], candidate["filterSummary"], picks, rows_by_symbol, hold_days_options, capital))

    candidate_by_name = {candidate["name"]: candidate for candidate in candidates}
    for group in fixed_groups:
        by_key = defaultdict(lambda: {"matchCount": 0, "symbols": set(), "ids": []})
        for name in group["members"]:
            candidate = candidate_by_name.get(name)
            if not candidate:
                continue
            for record_id in candidate["ids"]:
                record = record_by_id[record_id]
                key = (record["date"], record["symbol"])
                by_key[key]["matchCount"] += 1
                by_key[key]["ids"].append(record_id)
        ids = [
            payload["ids"][0]
            for payload in by_key.values()
            if payload["matchCount"] >= group["minMatches"]
        ]
        picks = picks_from_ids(record_by_id, ids, match_count=group["minMatches"])
        runs.extend(backtest_pick_set("group", group["name"], group["description"], picks, rows_by_symbol, hold_days_options, capital))
    return runs


def backtest_pick_set(kind, name, summary, picks_by_date, rows_by_symbol, hold_days_options, capital):
    if not picks_by_date:
        return []
    rows = []
    total_signals = sum(len(items) for items in picks_by_date.values())
    for top_n in [3, 5, 10]:
        for target_pct, stop_pct in [(5, 3), (7, 5), (10, 7), (12, 8), (15, 10)]:
            for hold_days in hold_days_options:
                trades = simulate_trades(picks_by_date, rows_by_symbol, top_n, capital, target_pct, stop_pct, hold_days)
                if not trades:
                    continue
                rows.append({
                    "kind": kind,
                    "name": name,
                    "summary": summary,
                    "topN": top_n,
                    "targetPct": target_pct,
                    "stopPct": stop_pct,
                    "holdDays": hold_days,
                    "totalSignals": total_signals,
                    "signalDays": len(picks_by_date),
                    **summarize_trades(trades, capital),
                })
    return rows


def build_fixed_rule_groups():
    return []


def make_candidate(atoms, score):
    return {
        "kind": f"{len(atoms)}filter",
        "name": " + ".join(atom["name"] for atom in atoms),
        "filterSummary": "; ".join(atom["name"] for atom in atoms),
        "filters": [atom["filter"] for atom in atoms],
        "ids": score["ids"],
    }


def rows_for_csv(rows):
    clean = []
    for row in rows:
        clean.append({
            "name": row["name"],
            "atomIds": row["atom_ids"],
            "count": row["count"],
            "avgFuture5": row["avgFuture5"],
            "avgFuture10": row["avgFuture10"],
            "avgFuture15": row["avgFuture15"],
            "positive10Pct": row["positive10Pct"],
            "hit10HighPct": row["hit10HighPct"],
            "hit15HighPct": row["hit15HighPct"],
        })
    return clean


def dedupe_rules(rows):
    seen = {}
    for row in rows:
        key = tuple(sorted(row["atom_ids"].split("|")))
        if key not in seen or quality_score(row) > quality_score(seen[key]):
            seen[key] = row
    return list(seen.values())


def ids_from_atom_ids(atom_sets, atom_ids):
    ids = None
    for atom_id in atom_ids.split("|"):
        ids = set(atom_sets[atom_id]) if ids is None else ids & atom_sets[atom_id]
    return ids or set()


def picks_from_ids(record_by_id, ids, match_count=1):
    picks = defaultdict(list)
    for record_id in ids:
        record = record_by_id[record_id]
        picks[record["date"]].append({
            "symbol": record["symbol"],
            "index": record["index"],
            "volume": record["volume"],
            "close": record["close"],
            "matchCount": match_count,
        })
    return picks


def quality_score(row):
    if row["count"] < 25:
        count_penalty = -10
    elif row["count"] < 60:
        count_penalty = -2
    elif row["count"] > 8000:
        count_penalty = -2
    else:
        count_penalty = 0
    return (
        row["avgFuture10"] * 2
        + row["avgFuture15"]
        + row["positive10Pct"] / 20
        + row["hit15HighPct"] / 12
        + count_penalty
    )


def backtest_score(row):
    if row["trades"] < 35:
        trade_penalty = -5
    elif row["trades"] > 600:
        trade_penalty = -1
    else:
        trade_penalty = 0
    return (
        row["returnOnTurnoverPct"] * 2
        + row["winRatePct"] / 20
        + row["targetHitPct"] / 40
        - row["stopHitPct"] / 25
        + trade_penalty,
        row["netPnl"],
    )


def future_return(rows, index, sessions):
    target_index = min(index + sessions, len(rows) - 1)
    return pct(rows[target_index]["close"], rows[index]["close"])


def future_high_return(rows, index, sessions):
    end = min(index + sessions, len(rows) - 1)
    high = max(row["high"] for row in rows[index + 1:end + 1])
    return pct(high, rows[index]["close"])


def multi_values(
    use_15d=False,
    use_1m=False,
    use_3m=False,
    use_6m=False,
    use_1y=False,
):
    return {
        "useMomentum1W": False,
        "minMomentum1W": 0,
        "maxMomentum1W": 15,
        "useMomentum15D": use_15d,
        "minMomentum15D": 2,
        "maxMomentum15D": 25,
        "useMomentum1M": use_1m,
        "minMomentum1M": 5,
        "maxMomentum1M": 30,
        "useMomentum3M": use_3m,
        "minMomentum3M": 10,
        "maxMomentum3M": 60,
        "useMomentum6M": use_6m,
        "minMomentum6M": 15,
        "maxMomentum6M": 120,
        "useMomentum1Y": use_1y,
        "minMomentum1Y": 20,
        "maxMomentum1Y": 250,
        "useMomentum6MTo12M": False,
        "minMomentum6MTo12M": -20,
        "maxMomentum6MTo12M": 80,
    }


def parse_ints(value):
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def avg(values):
    values = list(values)
    return sum(values) / len(values) if values else 0


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def print_top(title, rows, formatter=None):
    print(f"\n{title}")
    for row in rows:
        print((formatter or format_quality_row)(row))


def print_family_summary(rows):
    print("\nBest by discovered rule/group")
    by_name = defaultdict(list)
    for row in rows:
        by_name[(row["kind"], row["name"])].append(row)
    leaders = [max(items, key=backtest_score) for items in by_name.values()]
    leaders.sort(key=backtest_score, reverse=True)
    for row in leaders[:25]:
        print(format_backtest_row(row))


def format_quality_row(row):
    return (
        f"{row['name']:<85} count {row['count']:<5} "
        f"f10 {row['avgFuture10']:+5.2f}% f15 {row['avgFuture15']:+5.2f}% "
        f"pos10 {row['positive10Pct']:5.1f}% hit15H {row['hit15HighPct']:5.1f}%"
    )


def format_backtest_row(row):
    return (
        f"{row['kind']:<7} {row['name'][:62]:<62} top{row['topN']:<2} "
        f"t/s {row['targetPct']:.0f}/{row['stopPct']:.0f} hold {row['holdDays']:<2} "
        f"trades {row['trades']:<4} pnl {row['netPnl']:>10.2f} "
        f"ret {row['returnOnTurnoverPct']:>6.2f}% win {row['winRatePct']:>5.1f}% "
        f"target {row['targetHitPct']:>5.1f}% stop {row['stopHitPct']:>5.1f}% signals {row['totalSignals']}"
    )


if __name__ == "__main__":
    main()

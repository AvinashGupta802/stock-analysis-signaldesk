"""Discover combinations anchored by the experimental setup filters.

Candidates are selected using development-period results only. Validation metrics
are reported afterwards so they cannot influence which combinations are tested.
"""

import argparse
import csv
import json
from datetime import datetime, timedelta
from itertools import combinations
from pathlib import Path

from discover_rules_from_filters import (
    backtest_pick_set,
    backtest_score,
    build_atoms,
    build_records,
    evaluate_atoms,
    picks_from_ids,
    quality_score,
    score_ids,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs"


def main():
    parser = argparse.ArgumentParser(description="Discover rules around experimental setup filters.")
    parser.add_argument("--group", default="all")
    parser.add_argument("--from-date", default="2024-08-01")
    parser.add_argument("--to-date", default="2026-11-11")
    parser.add_argument("--validation-from", default="2026-01-01")
    parser.add_argument("--hold-days", default="2,5,10,15")
    parser.add_argument("--capital", type=float, default=10_000)
    parser.add_argument("--min-development-signals", type=int, default=40)
    parser.add_argument("--min-validation-signals", type=int, default=20)
    parser.add_argument("--complements-per-pattern", type=int, default=24)
    parser.add_argument("--shortlist", type=int, default=40)
    parser.add_argument("--output-prefix", default="experimental_combinations")
    args = parser.parse_args()

    holds = [int(value) for value in args.hold_days.split(",") if value.strip()]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"{args.output_prefix}_{args.group}_{stamp}"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Building records for group '{args.group}'...", flush=True)
    records, rows_by_symbol = build_records(args.group, args.from_date, args.to_date, max(holds))
    print(f"Records: {len(records):,}; stocks: {len(rows_by_symbol):,}", flush=True)
    record_by_id = {record["id"]: record for record in records}
    development_ids = {record["id"] for record in records if record["date"] < args.validation_from}
    validation_ids = {record["id"] for record in records if record["date"] >= args.validation_from}

    patterns = build_pattern_atoms()
    complements = [atom for atom in build_atoms() if not atom.get("technical")]
    atoms = patterns + complements
    print(f"Evaluating {len(patterns)} pattern variants and {len(complements)} confirmation settings...", flush=True)
    atom_sets = evaluate_atoms(records, atoms)

    candidates = []
    for pattern in patterns:
        pattern_dev = atom_sets[pattern["id"]] & development_ids
        pattern_val = atom_sets[pattern["id"]] & validation_ids
        add_candidate(candidates, pattern, [], pattern_dev, pattern_val, records, args)

        complement_rows = []
        for atom in complements:
            dev_ids = pattern_dev & atom_sets[atom["id"]]
            score = score_ids(records, dev_ids)
            if score and score["count"] >= args.min_development_signals:
                complement_rows.append((quality_score(score), atom, dev_ids))
        complement_rows.sort(key=lambda item: item[0], reverse=True)
        selected = [item[1] for item in complement_rows[:args.complements_per_pattern]]

        pair_rows = []
        for atom in selected:
            dev_ids = pattern_dev & atom_sets[atom["id"]]
            val_ids = pattern_val & atom_sets[atom["id"]]
            add_candidate(candidates, pattern, [atom], dev_ids, val_ids, records, args)
        for left, right in combinations(selected, 2):
            if left["filter"]["id"] == right["filter"]["id"]:
                continue
            dev_ids = pattern_dev & atom_sets[left["id"]] & atom_sets[right["id"]]
            score = score_ids(records, dev_ids)
            if not score or score["count"] < args.min_development_signals:
                continue
            pair_rows.append((quality_score(score), left, right, dev_ids))
            val_ids = pattern_val & atom_sets[left["id"]] & atom_sets[right["id"]]
            add_candidate(candidates, pattern, [left, right], dev_ids, val_ids, records, args)

        pair_rows.sort(key=lambda item: item[0], reverse=True)
        for _, left, right, pair_dev in pair_rows[:80]:
            used_filters = {left["filter"]["id"], right["filter"]["id"]}
            for third in selected:
                if third["filter"]["id"] in used_filters:
                    continue
                dev_ids = pair_dev & atom_sets[third["id"]]
                if len(dev_ids) < args.min_development_signals:
                    continue
                val_ids = pattern_val & atom_sets[left["id"]] & atom_sets[right["id"]] & atom_sets[third["id"]]
                add_candidate(candidates, pattern, [left, right, third], dev_ids, val_ids, records, args)

    candidates = dedupe_candidates(candidates)
    candidates.sort(key=lambda row: row["developmentScore"], reverse=True)
    candidate_path = OUTPUT_DIR / f"{prefix}_candidates.csv"
    write_csv(candidate_path, [csv_candidate(row) for row in candidates])

    eligible = [
        row for row in candidates
        if row["developmentCount"] >= args.min_development_signals
        and row["validationCount"] >= args.min_validation_signals
    ][:args.shortlist]
    backtests = []
    for number, candidate in enumerate(eligible, 1):
        print(f"Backtesting shortlist {number}/{len(eligible)}: {candidate['name']}", flush=True)
        for period, ids in (("development", candidate["developmentIds"]), ("validation", candidate["validationIds"])):
            picks = picks_from_ids(record_by_id, ids)
            for row in backtest_pick_set(
                f"{len(candidate['atoms'])}filter",
                candidate["name"],
                candidate["filterSummary"],
                picks,
                rows_by_symbol,
                holds,
                args.capital,
            ):
                row["period"] = period
                row["candidateId"] = candidate["id"]
                backtests.append(row)

    backtests.sort(key=lambda row: (row["period"] == "validation", backtest_score(row)), reverse=True)
    backtest_path = OUTPUT_DIR / f"{prefix}_backtests.csv"
    write_csv(backtest_path, backtests)

    config_path = OUTPUT_DIR / f"{prefix}_config.json"
    config_path.write_text(json.dumps({
        "arguments": vars(args),
        "record_count": len(records),
        "stock_count": len(rows_by_symbol),
        "selection_policy": "Candidates selected and ranked on development data only; validation is report-only.",
        "pattern_variants": patterns,
        "shortlisted_candidates": [config_candidate(row) for row in eligible],
    }, indent=2), encoding="utf-8")

    print("\nTop validation backtests from development-selected candidates", flush=True)
    validation_rows = [row for row in backtests if row["period"] == "validation"]
    validation_rows.sort(key=backtest_score, reverse=True)
    for row in validation_rows[:20]:
        print(
            f"{row['name'][:70]} | top {row['topN']} | hold {row['holdDays']} | "
            f"target/stop {row['targetPct']}/{row['stopPct']} | trades {row['trades']} | "
            f"return {row['returnOnTurnoverPct']:+.2f}% | win {row['winRatePct']:.1f}%",
            flush=True,
        )
    print("\nCreated:", flush=True)
    for path in (candidate_path, backtest_path, config_path):
        print(path, flush=True)


def build_pattern_atoms():
    return [
        atom("pause_balanced", "Pause: balanced", "short_pause_after_impulse", {
            "impulseLookbackSessions": 6, "minImpulseGainPct": 3, "minPauseSessions": 2,
            "maxPauseSessions": 5, "maxPauseRangePct": 4, "maxDistanceFromPauseHighPct": 2,
            "maxPauseVolumeRatio": 1.3, "requireAboveEma20": True,
        }),
        atom("pause_tight", "Pause: tight", "short_pause_after_impulse", {
            "impulseLookbackSessions": 6, "minImpulseGainPct": 4, "minPauseSessions": 2,
            "maxPauseSessions": 4, "maxPauseRangePct": 3, "maxDistanceFromPauseHighPct": 1.5,
            "maxPauseVolumeRatio": 1.0, "requireAboveEma20": True,
        }),
        atom("pause_early", "Pause: early", "short_pause_after_impulse", {
            "impulseLookbackSessions": 5, "minImpulseGainPct": 2, "minPauseSessions": 1,
            "maxPauseSessions": 3, "maxPauseRangePct": 4, "maxDistanceFromPauseHighPct": 2,
            "maxPauseVolumeRatio": 1.2, "requireAboveEma20": True,
        }),
        atom("pullback_balanced", "Pullback recovery: balanced", "recent_pullback_recovery", {
            "pullbackLookbackSessions": 20, "minPullbackPct": 5, "maxPullbackPct": 20,
            "maxSessionsSinceLow": 7, "minRecoveryFromLowPct": 1, "maxRecoveryFromLowPct": 8,
        }),
        atom("pullback_shallow", "Pullback recovery: shallow", "recent_pullback_recovery", {
            "pullbackLookbackSessions": 20, "minPullbackPct": 3, "maxPullbackPct": 12,
            "maxSessionsSinceLow": 5, "minRecoveryFromLowPct": 1, "maxRecoveryFromLowPct": 6,
        }),
        atom("pullback_confirmed", "Pullback recovery: confirmed", "recent_pullback_recovery", {
            "pullbackLookbackSessions": 30, "minPullbackPct": 7, "maxPullbackPct": 18,
            "maxSessionsSinceLow": 6, "minRecoveryFromLowPct": 2, "maxRecoveryFromLowPct": 10,
        }),
        atom("base_balanced", "Base dry-up: balanced", "base_tightness_volume_dryup", {
            "baseSessions": 4, "maxBaseCloseRangePct": 5, "maxBaseVolumeRatio": 1,
            "maxBaseSingleDayDeclinePct": 3,
        }),
        atom("base_tight", "Base dry-up: tight", "base_tightness_volume_dryup", {
            "baseSessions": 5, "maxBaseCloseRangePct": 3, "maxBaseVolumeRatio": 0.8,
            "maxBaseSingleDayDeclinePct": 2,
        }),
        atom("base_short", "Base dry-up: short", "base_tightness_volume_dryup", {
            "baseSessions": 3, "maxBaseCloseRangePct": 4, "maxBaseVolumeRatio": 0.9,
            "maxBaseSingleDayDeclinePct": 2.5,
        }),
    ]


def atom(atom_id, name, filter_id, values):
    return {"id": atom_id, "name": name, "filter": {"id": filter_id, "values": values}}


def add_candidate(rows, pattern, complements, development_ids, validation_ids, records, args):
    if len(development_ids) < args.min_development_signals:
        return
    development = score_ids(records, development_ids)
    validation = score_ids(records, validation_ids)
    atoms = [pattern, *complements]
    rows.append({
        "id": "|".join(item["id"] for item in atoms),
        "name": " + ".join(item["name"] for item in atoms),
        "filterSummary": "; ".join(item["name"] for item in atoms),
        "atoms": atoms,
        "developmentIds": set(development_ids),
        "validationIds": set(validation_ids),
        "developmentCount": development["count"],
        "developmentScore": quality_score(development),
        "development": development,
        "validationCount": validation["count"] if validation else 0,
        "validation": validation,
    })


def dedupe_candidates(rows):
    unique = {}
    for row in rows:
        key = tuple(sorted(item["id"] for item in row["atoms"]))
        if key not in unique or row["developmentScore"] > unique[key]["developmentScore"]:
            unique[key] = row
    return list(unique.values())


def csv_candidate(row):
    development = row["development"]
    validation = row["validation"] or {}
    return {
        "candidate_id": row["id"], "name": row["name"], "filter_count": len(row["atoms"]),
        "development_count": row["developmentCount"], "development_score": round(row["developmentScore"], 4),
        "development_avg_5d": round(development["avgFuture5"], 4),
        "development_avg_10d": round(development["avgFuture10"], 4),
        "development_avg_15d": round(development["avgFuture15"], 4),
        "development_positive_10d_pct": round(development["positive10Pct"], 2),
        "validation_count": row["validationCount"],
        "validation_avg_5d": round(validation.get("avgFuture5", 0), 4),
        "validation_avg_10d": round(validation.get("avgFuture10", 0), 4),
        "validation_avg_15d": round(validation.get("avgFuture15", 0), 4),
        "validation_positive_10d_pct": round(validation.get("positive10Pct", 0), 2),
    }


def config_candidate(row):
    return {
        "id": row["id"], "name": row["name"],
        "filters": [item["filter"] for item in row["atoms"]],
        "development_count": row["developmentCount"], "validation_count": row["validationCount"],
    }


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

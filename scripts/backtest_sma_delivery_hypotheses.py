"""Walk-forward research for recent SMA crossover and delivery-burst filters."""

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from discover_rules_from_filters import (
    backtest_pick_set,
    backtest_score,
    build_records,
    evaluate_atoms,
    picks_from_ids,
    quality_score,
    score_ids,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs"


def main():
    parser = argparse.ArgumentParser(description="Backtest SMA crossover and delivery-burst hypotheses.")
    parser.add_argument("--group", default="nifty500")
    parser.add_argument("--from-date", default="2026-06-01")
    parser.add_argument("--to-date", default="2026-11-11")
    parser.add_argument("--validation-from", default="2026-09-15")
    parser.add_argument("--hold-days", default="2,5,10,15")
    parser.add_argument("--capital", type=float, default=10_000)
    parser.add_argument("--min-development-signals", type=int, default=25)
    parser.add_argument("--min-validation-signals", type=int, default=10)
    parser.add_argument("--shortlist", type=int, default=60)
    parser.add_argument("--output-prefix", default="sma_delivery_discovery")
    args = parser.parse_args()

    holds = [int(value) for value in args.hold_days.split(",") if value.strip()]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"{args.output_prefix}_{args.group}_{stamp}"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Building {args.group} records from {args.from_date} to {args.to_date}...", flush=True)
    records, rows_by_symbol = build_records(args.group, args.from_date, args.to_date, max(holds))
    record_by_id = {record["id"]: record for record in records}
    development_ids = {record["id"] for record in records if record["date"] < args.validation_from}
    validation_ids = {record["id"] for record in records if record["date"] >= args.validation_from}
    print(
        f"Records: {len(records):,}; stocks: {len(rows_by_symbol):,}; "
        f"development records: {len(development_ids):,}; validation records: {len(validation_ids):,}",
        flush=True,
    )

    sma_atoms, delivery_atoms, setup_atoms = build_atoms()
    atoms = [*sma_atoms, *delivery_atoms, *setup_atoms]
    print(
        f"Evaluating {len(sma_atoms)} SMA settings, {len(delivery_atoms)} delivery settings, "
        f"and {len(setup_atoms)} setup filters...",
        flush=True,
    )
    atom_sets = evaluate_atoms(records, atoms)

    candidates = []
    for atom in [*sma_atoms, *delivery_atoms]:
        add_candidate(candidates, [atom], atom_sets, development_ids, validation_ids, records, args)

    pair_candidates = []
    for sma in sma_atoms:
        for delivery in delivery_atoms:
            candidate = add_candidate(
                candidates, [sma, delivery], atom_sets,
                development_ids, validation_ids, records, args,
            )
            if candidate:
                pair_candidates.append(candidate)

    pair_candidates.sort(key=lambda row: row["development_score"], reverse=True)
    for pair in pair_candidates[:160]:
        for setup in setup_atoms:
            add_candidate(
                candidates, [*pair["atoms"], setup], atom_sets,
                development_ids, validation_ids, records, args,
            )

    for setup in setup_atoms:
        for atom in [*sma_atoms, *delivery_atoms]:
            add_candidate(
                candidates, [setup, atom], atom_sets,
                development_ids, validation_ids, records, args,
            )

    candidates = dedupe(candidates)
    candidates.sort(key=lambda row: row["development_score"], reverse=True)
    candidate_path = OUTPUT_DIR / f"{prefix}_candidates.csv"
    write_csv(candidate_path, [candidate_csv(row) for row in candidates])

    eligible = [
        row for row in candidates
        if row["development_count"] >= args.min_development_signals
        and row["validation_count"] >= args.min_validation_signals
    ][:args.shortlist]
    backtests = []
    for number, candidate in enumerate(eligible, 1):
        print(f"Backtesting {number}/{len(eligible)}: {candidate['name']}", flush=True)
        for period, ids in (
            ("development", candidate["development_ids"]),
            ("validation", candidate["validation_ids"]),
        ):
            picks = picks_from_ids(record_by_id, ids)
            rows = backtest_pick_set(
                f"{len(candidate['atoms'])}filter", candidate["name"], candidate["name"],
                picks, rows_by_symbol, holds, args.capital,
            )
            for row in rows:
                row["period"] = period
                row["candidateId"] = candidate["id"]
                backtests.append(row)

    backtest_path = OUTPUT_DIR / f"{prefix}_backtests.csv"
    write_csv(backtest_path, backtests)
    config_path = OUTPUT_DIR / f"{prefix}_config.json"
    config_path.write_text(json.dumps({
        "arguments": vars(args),
        "delivery_coverage_note": "NSE delivery history in the local database begins on 2026-06-01.",
        "selection_policy": "Candidate combinations are ranked on development data only; validation is report-only.",
        "sma_settings": sma_atoms,
        "delivery_settings": delivery_atoms,
        "setup_filters": setup_atoms,
        "shortlisted_candidates": [candidate_config(row) for row in eligible],
    }, indent=2), encoding="utf-8")

    validation_rows = [row for row in backtests if row["period"] == "validation"]
    validation_rows.sort(key=backtest_score, reverse=True)
    print("\nTop validation configurations", flush=True)
    for row in validation_rows[:20]:
        print(
            f"{row['name'][:78]} | top {row['topN']} | hold {row['holdDays']} | "
            f"target/stop {row['targetPct']}/{row['stopPct']} | trades {row['trades']} | "
            f"return {row['returnOnTurnoverPct']:+.2f}% | win {row['winRatePct']:.1f}%",
            flush=True,
        )
    print("\nCreated:", flush=True)
    for path in (candidate_path, backtest_path, config_path):
        print(path, flush=True)


def build_atoms():
    sma_atoms = []
    for period in [5, 7, 10, 15, 20, 30, 50, 60, 100, 200]:
        for lookback in [1, 3, 5]:
            sma_atoms.append(atom(
                f"sma_cross_{period}_{lookback}",
                f"Cross above SMA{period} within {lookback}D",
                "recent_sma_crossover",
                {
                    "smaPeriod": period,
                    "crossoverLookbackSessions": lookback,
                    "requireCurrentlyAbove": True,
                    "smaSlopeLookbackSessions": 3,
                    "minSmaSlopePct": 0,
                },
            ))

    delivery_atoms = []
    for average_period in [5, 10, 15, 20, 30, 50, 60]:
        for lookback in [3, 5]:
            for ratio in [1.2, 1.5, 2.0]:
                delivery_atoms.append(atom(
                    f"delivery_burst_{average_period}_{lookback}_{ratio:g}",
                    f"Delivery burst >= {ratio:g}x {average_period}D within {lookback}D",
                    "recent_delivery_burst",
                    {
                        "deliveryBurstLookbackSessions": lookback,
                        "deliveryAveragePeriod": average_period,
                        "minDeliveryBurstRatio": ratio,
                        "maxDeliveryBurstRatio": 999,
                        "minPriceResponseSinceBurstPct": 0.5,
                        "maxPriceResponseSinceBurstPct": 999,
                    },
                ))

    setup_atoms = [
        atom("setup_pause", "Balanced impulse pause", "short_pause_after_impulse", {
            "impulseLookbackSessions": 6, "minImpulseGainPct": 3,
            "minPauseSessions": 2, "maxPauseSessions": 5,
            "maxPauseRangePct": 4, "maxDistanceFromPauseHighPct": 2,
            "maxPauseVolumeRatio": 1.3, "requireAboveEma20": True,
        }),
        atom("setup_pullback", "Balanced pullback recovery", "recent_pullback_recovery", {
            "pullbackLookbackSessions": 20, "minPullbackPct": 5, "maxPullbackPct": 20,
            "maxSessionsSinceLow": 7, "minRecoveryFromLowPct": 1,
            "maxRecoveryFromLowPct": 8,
        }),
        atom("setup_base", "Balanced base dry-up", "base_tightness_volume_dryup", {
            "baseSessions": 4, "maxBaseCloseRangePct": 5,
            "maxBaseVolumeRatio": 1, "maxBaseSingleDayDeclinePct": 3,
        }),
    ]
    return sma_atoms, delivery_atoms, setup_atoms


def atom(atom_id, name, filter_id, values):
    return {"id": atom_id, "name": name, "filter": {"id": filter_id, "values": values}}


def add_candidate(rows, atoms, atom_sets, development_universe, validation_universe, records, args):
    ids = None
    for item in atoms:
        ids = set(atom_sets[item["id"]]) if ids is None else ids & atom_sets[item["id"]]
    development_ids = ids & development_universe
    if len(development_ids) < args.min_development_signals:
        return None
    validation_ids = ids & validation_universe
    development = score_ids(records, development_ids)
    validation = score_ids(records, validation_ids)
    row = {
        "id": "|".join(item["id"] for item in atoms),
        "name": " + ".join(item["name"] for item in atoms),
        "atoms": atoms,
        "development_ids": development_ids,
        "validation_ids": validation_ids,
        "development_count": len(development_ids),
        "validation_count": len(validation_ids),
        "development_score": quality_score(development),
        "development": development,
        "validation": validation,
    }
    rows.append(row)
    return row


def dedupe(rows):
    result = {}
    for row in rows:
        key = tuple(sorted(item["id"] for item in row["atoms"]))
        if key not in result:
            result[key] = row
    return list(result.values())


def candidate_csv(row):
    development = row["development"]
    validation = row["validation"] or {}
    return {
        "candidate_id": row["id"], "name": row["name"], "filter_count": len(row["atoms"]),
        "development_count": row["development_count"],
        "development_avg_5d": round(development["avgFuture5"], 4),
        "development_avg_10d": round(development["avgFuture10"], 4),
        "development_avg_15d": round(development["avgFuture15"], 4),
        "development_positive_10d_pct": round(development["positive10Pct"], 2),
        "validation_count": row["validation_count"],
        "validation_avg_5d": round(validation.get("avgFuture5", 0), 4),
        "validation_avg_10d": round(validation.get("avgFuture10", 0), 4),
        "validation_avg_15d": round(validation.get("avgFuture15", 0), 4),
        "validation_positive_10d_pct": round(validation.get("positive10Pct", 0), 2),
    }


def candidate_config(row):
    return {
        "id": row["id"], "name": row["name"],
        "filters": [item["filter"] for item in row["atoms"]],
        "development_count": row["development_count"],
        "validation_count": row["validation_count"],
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

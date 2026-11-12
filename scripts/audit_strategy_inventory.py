"""Audit active SignalDesk filters, rules, and groups for clutter and overlap."""

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from itertools import combinations
from pathlib import Path

from server import FILTER_LIBRARY, connect


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs"


def main():
    parser = argparse.ArgumentParser(description="Audit SignalDesk strategy inventory.")
    parser.add_argument("--output-prefix", default="strategy_inventory_audit")
    args = parser.parse_args()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"{args.output_prefix}_{timestamp}"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with connect() as conn:
        rules = load_rules(conn)
        groups = load_groups(conn)

    filter_rows = audit_filters(rules)
    rule_rows = audit_rules(rules, groups)
    group_rows = audit_groups(groups)
    paths = [
        write_csv(OUTPUT_DIR / f"{prefix}_filters.csv", filter_rows),
        write_csv(OUTPUT_DIR / f"{prefix}_rules.csv", rule_rows),
        write_csv(OUTPUT_DIR / f"{prefix}_groups.csv", group_rows),
    ]

    print(f"Active filters: {len(FILTER_LIBRARY)}")
    print(f"Active rules: {len(rules)}")
    print(f"Active groups: {len(groups)}")
    print(f"Unused filters: {sum(1 for row in filter_rows if row['usage_count'] == 0)}")
    print(f"Single-rule wrapper groups: {sum(1 for row in group_rows if row['classification'] == 'single_rule_wrapper')}")
    print(f"Exact duplicate rule pairs: {sum(1 for row in rule_rows if row['classification'] == 'exact_duplicate')}")
    print(f"Near-overlap rule pairs: {sum(1 for row in rule_rows if row['classification'] == 'near_overlap')}")
    print("Created:")
    for path in paths:
        print(path)


def load_rules(conn):
    rows = []
    for row in conn.execute(
        "SELECT rule_id, name, kind, version, filters_json FROM strategy_rules WHERE status = 'active' ORDER BY name"
    ):
        filters = json.loads(row["filters_json"] or "[]")
        rows.append({**dict(row), "filters": filters})
    return rows


def load_groups(conn):
    rows = []
    for row in conn.execute(
        "SELECT group_id, name, kind, min_matches, min_weighted_score, rule_ids_json FROM strategy_rule_groups WHERE status = 'active' ORDER BY name"
    ):
        rows.append({**dict(row), "rule_ids": json.loads(row["rule_ids_json"] or "[]")})
    return rows


def audit_filters(rules):
    usage = Counter(selected["id"] for rule in rules for selected in rule["filters"])
    return [
        {
            "filter_id": item["id"], "filter_name": item["name"], "category": item["category"],
            "usage_count": usage[item["id"]],
            "classification": "unused" if usage[item["id"]] == 0 else "used",
            "recommendation": "Review before hiding; keep available for user rules" if usage[item["id"]] == 0 else "keep",
        }
        for item in FILTER_LIBRARY
    ]


def audit_rules(rules, groups):
    group_usage = Counter(rule_id for group in groups for rule_id in group["rule_ids"])
    rows = []
    for rule in rules:
        rows.append({
            "left_rule_id": rule["rule_id"], "left_rule_name": rule["name"],
            "right_rule_id": "", "right_rule_name": "", "left_filter_count": len(rule["filters"]),
            "right_filter_count": "", "shared_filter_ids": "", "filter_id_jaccard_pct": "",
            "exact_values": "", "group_usage_count": group_usage[rule["rule_id"]],
            "classification": "unused_rule" if group_usage[rule["rule_id"]] == 0 else "rule_inventory",
            "recommendation": "Keep experimental rules ungrouped; review other unused rules" if group_usage[rule["rule_id"]] == 0 else "keep_pending_performance_review",
        })
    for left, right in combinations(rules, 2):
        left_ids = {item["id"] for item in left["filters"]}
        right_ids = {item["id"] for item in right["filters"]}
        shared = left_ids & right_ids
        union = left_ids | right_ids
        jaccard = len(shared) / len(union) * 100 if union else 100
        exact = canonical_filters(left["filters"]) == canonical_filters(right["filters"])
        if exact:
            classification = "exact_duplicate"
            recommendation = "Safe consolidation candidate after checking historical references"
        elif jaccard >= 75:
            classification = "near_overlap"
            recommendation = "Compare backtest and signal overlap; keep only stronger rule if behavior is redundant"
        else:
            continue
        rows.append({
            "left_rule_id": left["rule_id"], "left_rule_name": left["name"],
            "right_rule_id": right["rule_id"], "right_rule_name": right["name"],
            "left_filter_count": len(left["filters"]), "right_filter_count": len(right["filters"]),
            "shared_filter_ids": "|".join(sorted(shared)), "filter_id_jaccard_pct": round(jaccard, 2),
            "exact_values": exact, "group_usage_count": "", "classification": classification,
            "recommendation": recommendation,
        })
    return rows


def audit_groups(groups):
    membership_seen = {}
    rows = []
    for group in groups:
        membership = tuple(sorted(group["rule_ids"]))
        duplicate_of = membership_seen.get(membership, "")
        if len(group["rule_ids"]) == 1:
            classification = "single_rule_wrapper"
            recommendation = "Hide or replace with direct single-rule selection; it adds no agreement logic"
        elif duplicate_of:
            classification = "duplicate_membership"
            recommendation = f"Compare thresholds with {duplicate_of}; consolidate if behavior is equivalent"
        else:
            classification = "multi_rule_group"
            recommendation = "keep_pending_performance_review"
        membership_seen.setdefault(membership, group["name"])
        rows.append({
            "group_id": group["group_id"], "group_name": group["name"], "kind": group["kind"],
            "rule_count": len(group["rule_ids"]), "min_matches": group["min_matches"],
            "min_weighted_score": group["min_weighted_score"], "rule_ids": "|".join(group["rule_ids"]),
            "classification": classification, "duplicate_of": duplicate_of, "recommendation": recommendation,
        })
    return rows


def canonical_filters(filters):
    return json.dumps(filters, sort_keys=True, separators=(",", ":"))


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


if __name__ == "__main__":
    main()

"""Pure helpers for normalizing and evaluating weighted rule groups."""


def normalize_group_scoring(rules, min_matches, payload=None):
    """Return bounded weights and thresholds for a rule group."""
    payload = payload or {}
    raw_weights = payload.get("ruleWeights") if isinstance(payload.get("ruleWeights"), dict) else {}
    rule_weights = {}
    for index, rule in enumerate(rules):
        rule_id = rule.get("id") or f"rule_{index + 1}"
        try:
            weight = float(raw_weights.get(rule_id, 1))
        except (TypeError, ValueError):
            weight = 1.0
        rule_weights[rule_id] = max(0.25, min(weight, 3.0))

    total_weight = sum(rule_weights.values())
    default_score = (min_matches / len(rules) * 100) if rules else 100
    raw_score = payload.get("minWeightedScore")
    try:
        min_weighted_score = default_score if raw_score is None else float(raw_score)
    except (TypeError, ValueError):
        min_weighted_score = default_score

    return {
        "minMatches": min_matches,
        "minWeightedScore": max(1.0, min(min_weighted_score, 100.0)),
        "ruleWeights": rule_weights,
        "totalWeight": total_weight,
    }


def score_group_agreement(matched_rule_ids, scoring):
    """Evaluate count and weighted-score requirements for matched rules."""
    matched_rule_ids = list(dict.fromkeys(matched_rule_ids))
    matched_weight = sum(scoring["ruleWeights"].get(rule_id, 1.0) for rule_id in matched_rule_ids)
    weighted_score = (matched_weight / scoring["totalWeight"] * 100) if scoring["totalWeight"] else 0
    return {
        "passed": (
            len(matched_rule_ids) >= scoring["minMatches"]
            and weighted_score + 1e-9 >= scoring["minWeightedScore"]
        ),
        "matchCount": len(matched_rule_ids),
        "matchedWeight": matched_weight,
        "weightedScore": weighted_score,
    }

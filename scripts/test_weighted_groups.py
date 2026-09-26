import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from server import normalize_group_scoring, score_group_agreement


class WeightedGroupScoringTests(unittest.TestCase):
    def setUp(self):
        self.rules = [
            {"id": rule_id, "name": rule_id, "filters": [{"id": "test"}]}
            for rule_id in ("a", "b", "c", "d")
        ]

    def test_equal_weights_preserve_minimum_match_behavior(self):
        scoring = normalize_group_scoring(self.rules, 2, {})

        self.assertEqual(scoring["minWeightedScore"], 50)
        self.assertFalse(score_group_agreement(["a"], scoring)["passed"])
        self.assertTrue(score_group_agreement(["a", "b"], scoring)["passed"])

    def test_high_weight_does_not_bypass_minimum_rule_count(self):
        scoring = normalize_group_scoring(
            self.rules,
            2,
            {"ruleWeights": {"a": 3, "b": 1, "c": 1, "d": 1}, "minWeightedScore": 50},
        )

        result = score_group_agreement(["a"], scoring)
        self.assertEqual(result["weightedScore"], 50)
        self.assertFalse(result["passed"])

    def test_weighted_threshold_can_require_stronger_rules(self):
        scoring = normalize_group_scoring(
            self.rules,
            2,
            {"ruleWeights": {"a": 2, "b": 1, "c": 1, "d": 1}, "minWeightedScore": 60},
        )

        self.assertTrue(score_group_agreement(["a", "b"], scoring)["passed"])
        self.assertFalse(score_group_agreement(["b", "c"], scoring)["passed"])

    def test_weights_are_bounded(self):
        scoring = normalize_group_scoring(
            self.rules,
            1,
            {"ruleWeights": {"a": 99, "b": 0, "c": "bad"}},
        )

        self.assertEqual(scoring["ruleWeights"]["a"], 3)
        self.assertEqual(scoring["ruleWeights"]["b"], 0.25)
        self.assertEqual(scoring["ruleWeights"]["c"], 1)


if __name__ == "__main__":
    unittest.main()

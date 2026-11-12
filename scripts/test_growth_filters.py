import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))

from import_exchange_bhavcopy import parse_date
from server import EXPERIMENTAL_SETUP_RULES, FILTER_LIBRARY, FUNDAMENTAL_SYSTEM_RULES, evaluate_filter


class GrowthFilterTests(unittest.TestCase):
    def setUp(self):
        self.context = {
            "history_count": 252,
            "close": 120.0,
            "sma50": 110.0,
            "sma200": 100.0,
            "volume_sma10_vs_sma20": 1.4,
            "distance_from_52w_high": 10.0,
            "relative_strength_nifty500_3m": 6.0,
            "market_cap_cr": 10000.0,
            "revenue_growth_yoy": 20.0,
            "pat_growth_yoy": 25.0,
            "roce": 18.0,
            "annual_revenue_growth_yoy": 22.0,
            "annual_pat_growth_yoy": 30.0,
            "annual_roce": 21.0,
            "debt_to_equity": 0.5,
            "fundamental_equity": 1000.0,
        }

    def test_all_new_filters_are_in_library(self):
        filter_ids = {item["id"] for item in FILTER_LIBRARY}
        self.assertTrue(
            {
                "volume_sma10_vs_sma20",
                "distance_from_52w_high",
                "close_above_sma50",
                "sma50_above_sma200",
                "relative_strength_nifty500_3m",
            }.issubset(filter_ids)
        )

    def test_nse_index_date_format(self):
        self.assertEqual(parse_date("19-10-2026"), "2026-10-19")

    def test_fundamental_filters_and_rules_are_registered(self):
        filter_ids = {item["id"] for item in FILTER_LIBRARY}
        self.assertTrue(
            {
                "market_cap_range",
                "revenue_growth_yoy",
                "pat_growth_yoy",
                "roce_range",
                "annual_revenue_growth_yoy",
                "annual_pat_growth_yoy",
                "annual_roce_range",
                "debt_to_equity_range",
            }.issubset(filter_ids)
        )
        self.assertEqual(
            {rule["id"] for rule in FUNDAMENTAL_SYSTEM_RULES},
            {"rule_early_volume_signs", "rule_early_growth_relative_strength"},
        )

    def test_fundamental_filters_pass_valid_values(self):
        selections = [
            {"id": "market_cap_range", "values": {"minMarketCapCr": 2000, "maxMarketCapCr": 50000}},
            {"id": "revenue_growth_yoy", "values": {"minRevenueGrowthYoY": 15}},
            {"id": "pat_growth_yoy", "values": {"minPatGrowthYoY": 20}},
            {"id": "roce_range", "values": {"minRoce": 15}},
            {"id": "annual_revenue_growth_yoy", "values": {"minAnnualRevenueGrowthYoY": 15}},
            {"id": "annual_pat_growth_yoy", "values": {"minAnnualPatGrowthYoY": 20}},
            {"id": "annual_roce_range", "values": {"minAnnualRoce": 15}},
            {"id": "debt_to_equity_range", "values": {"maxDebtToEquity": 1.2}},
        ]
        self.assertTrue(all(evaluate_filter(self.context, selected)[0] for selected in selections))

    def test_missing_fundamentals_fail_with_explanation(self):
        context = dict(self.context, revenue_growth_yoy=None)
        passed, reason = evaluate_filter(context, {"id": "revenue_growth_yoy", "values": {}})
        self.assertFalse(passed)
        self.assertIn("unavailable", reason)

    def test_annual_and_quarterly_filters_use_separate_values(self):
        context = dict(
            self.context,
            revenue_growth_yoy=-5,
            annual_revenue_growth_yoy=20,
        )
        quarterly, _ = evaluate_filter(
            context, {"id": "revenue_growth_yoy", "values": {"minRevenueGrowthYoY": 15}}
        )
        annual, reason = evaluate_filter(
            context,
            {"id": "annual_revenue_growth_yoy", "values": {"minAnnualRevenueGrowthYoY": 15}},
        )
        self.assertFalse(quarterly)
        self.assertTrue(annual)
        self.assertIn("Annual revenue", reason)

    def test_growth_system_rule_uses_annual_filters(self):
        rule = next(
            item for item in FUNDAMENTAL_SYSTEM_RULES
            if item["id"] == "rule_early_growth_relative_strength"
        )
        self.assertEqual(rule["version"], 3)
        filter_ids = {item["id"] for item in rule["filters"]}
        self.assertTrue(
            {"annual_revenue_growth_yoy", "annual_pat_growth_yoy", "annual_roce_range"}.issubset(filter_ids)
        )
        self.assertFalse({"revenue_growth_yoy", "pat_growth_yoy", "roce_range"} & filter_ids)

    def test_volume_average_acceleration(self):
        passed, _ = evaluate_filter(
            self.context,
            {"id": "volume_sma10_vs_sma20", "values": {"minVolumeSmaRatio": 1.3}},
        )
        self.assertTrue(passed)

    def test_experimental_setup_filters_and_rules_are_registered(self):
        filter_ids = {item["id"] for item in FILTER_LIBRARY}
        self.assertTrue({
            "short_pause_after_impulse",
            "recent_pullback_recovery",
            "base_tightness_volume_dryup",
        }.issubset(filter_ids))
        self.assertEqual(
            {rule["id"] for rule in EXPERIMENTAL_SETUP_RULES},
            {
                "rule_experimental_impulse_pause_setup",
                "rule_experimental_pullback_base_reversal",
                "rule_experimental_base_breakout_confirmation",
            },
        )

    def test_experimental_pullback_and_base_filters(self):
        closes = [100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90, 90.2, 90.5, 91, 92]
        rows = [
            {"close": close, "volume": 50 if index >= 10 else 100}
            for index, close in enumerate(closes)
        ]
        context = {"_rows": rows, "_index": len(rows) - 1, "close": 92, "adv20": 100}
        pullback, _ = evaluate_filter(context, {
            "id": "recent_pullback_recovery",
            "values": {
                "pullbackLookbackSessions": 20,
                "minPullbackPct": 5,
                "maxPullbackPct": 20,
                "maxSessionsSinceLow": 7,
                "minRecoveryFromLowPct": 1,
                "maxRecoveryFromLowPct": 8,
            },
        })
        base, _ = evaluate_filter(context, {
            "id": "base_tightness_volume_dryup",
            "values": {
                "baseSessions": 4,
                "maxBaseCloseRangePct": 5,
                "maxBaseVolumeRatio": 1,
                "maxBaseSingleDayDeclinePct": 3,
            },
        })
        self.assertTrue(pullback)
        self.assertTrue(base)

    def test_experimental_impulse_pause_filter(self):
        closes = [100] * 20 + [104, 104.5, 103.8, 104.2, 104.4]
        rows = [
            {"close": close, "volume": 100 if index <= 20 else 70}
            for index, close in enumerate(closes)
        ]
        context = {
            "_rows": rows,
            "_index": len(rows) - 1,
            "close": closes[-1],
            "adv20": 100,
            "ema20": 101,
        }
        passed, reason = evaluate_filter(context, {
            "id": "short_pause_after_impulse",
            "values": {
                "impulseLookbackSessions": 6,
                "minImpulseGainPct": 3,
                "minPauseSessions": 2,
                "maxPauseSessions": 5,
                "maxPauseRangePct": 4,
                "maxDistanceFromPauseHighPct": 2,
                "maxPauseVolumeRatio": 1.3,
                "requireAboveEma20": True,
            },
        })
        self.assertTrue(passed, reason)

    def test_distance_from_high_requires_full_history(self):
        short_context = dict(self.context, history_count=200)
        passed, reason = evaluate_filter(
            short_context,
            {"id": "distance_from_52w_high", "values": {"maxDistanceFrom52WHigh": 15}},
        )
        self.assertFalse(passed)
        self.assertIn("252", reason)

    def test_long_term_trend_filters(self):
        close_passed, _ = evaluate_filter(
            self.context,
            {"id": "close_above_sma50", "values": {"minCloseVsSma50Pct": 5}},
        )
        trend_passed, _ = evaluate_filter(
            self.context,
            {"id": "sma50_above_sma200", "values": {"minSma50VsSma200Pct": 5}},
        )
        self.assertTrue(close_passed)
        self.assertTrue(trend_passed)

    def test_relative_strength_reports_missing_benchmark(self):
        missing_context = dict(self.context, relative_strength_nifty500_3m=None)
        passed, reason = evaluate_filter(
            missing_context,
            {
                "id": "relative_strength_nifty500_3m",
                "values": {"minRelativeStrengthNifty5003M": 5},
            },
        )
        self.assertFalse(passed)
        self.assertIn("unavailable", reason)

    def test_relative_strength_uses_excess_return(self):
        passed, _ = evaluate_filter(
            self.context,
            {
                "id": "relative_strength_nifty500_3m",
                "values": {"minRelativeStrengthNifty5003M": 5},
            },
        )
        self.assertTrue(passed)


if __name__ == "__main__":
    unittest.main()

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))

from import_exchange_bhavcopy import parse_date
from server import FILTER_LIBRARY, evaluate_filter


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

    def test_volume_average_acceleration(self):
        passed, _ = evaluate_filter(
            self.context,
            {"id": "volume_sma10_vs_sma20", "values": {"minVolumeSmaRatio": 1.3}},
        )
        self.assertTrue(passed)

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

import sys
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_bse_fallback as fallback
import import_nse_fundamentals as fundamentals
import server


SHARE_HTML = """
<html><body>
  <ix:nonFraction name='in-bse-shp:NumberOfShares'
    contextRef='ShareholdingPattern_ContextI'>254991845</ix:nonFraction>
</body></html>
"""

FINANCIAL_PAYLOAD = {
    "table1": [
        {"Header": "2", "fld_desc": "Date Begin", "Value": "01-Jul-26"},
        {"Header": "2", "fld_desc": "Date End", "Value": "30-Sep-26"},
        {"Header": "1", "fld_desc": "Net Sales/Revenue From Operations", "Value": "1,200.50"},
        {"Header": "1", "fld_desc": "Profit (+)/ Loss (-) from Ordinary Activities before Tax", "Value": "160"},
        {"Header": "1", "fld_desc": "Finance Costs", "Value": "-40"},
        {"Header": "1", "fld_desc": "Net Profit (+)/ Loss (-) from Ordinary Activities after Tax", "Value": "120"},
    ]
}


class BseFallbackTests(unittest.TestCase):
    def test_share_count_is_read_from_ixbrl(self):
        self.assertEqual(fallback.parse_bse_outstanding_shares(SHARE_HTML), 254991845)

    def test_ixbrl_scale_is_applied(self):
        content = SHARE_HTML.replace(">254991845<", " scale='3'>255<")
        self.assertEqual(fallback.parse_bse_outstanding_shares(content), 255000)

    def test_structured_result_is_normalized(self):
        result = fallback.parse_bse_financial_result(FINANCIAL_PAYLOAD)
        self.assertEqual(result["period_start"], date(2026, 7, 1))
        self.assertEqual(result["period_end"], date(2026, 9, 30))
        self.assertEqual(result["revenue"], 1200.5)
        self.assertEqual(result["pat"], 120)
        self.assertEqual(result["finance_cost"], 40)
        self.assertEqual(result["ebit"], 200)

    def test_result_headline_must_name_period(self):
        period = date(2026, 9, 30)
        self.assertTrue(fallback.period_in_headline(period, "Results for quarter ended September 30, 2026"))
        self.assertFalse(fallback.period_in_headline(period, "Results for quarter ended June 30, 2026"))

    def test_quarter_id_tracks_completed_quarter(self):
        self.assertEqual(fallback.quarter_id_for_cutoff(date(2025, 6, 30)), 126)
        self.assertEqual(fallback.quarter_id_for_cutoff(date(2025, 6, 1)), 125)
        self.assertEqual(fallback.quarter_id_for_cutoff(date(2026, 11, 9)), 131)

    def test_point_in_time_selection_prefers_nse_for_same_metric(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sources.sqlite3"
            conn = sqlite3.connect(path)
            try:
                conn.executescript(fundamentals.SCHEMA)
                financial_values = (
                    "2026-07-01", "2026-09-30", "2026-11-01 10:00:00", "Consolidated",
                    10.0, 20.0,
                )
                conn.execute(
                    """INSERT INTO company_fundamentals
                       (filing_id, symbol, period_start, period_end, available_at, consolidated,
                        revenue_growth_yoy, pat_growth_yoy, source_exchange)
                       VALUES ('NSE-FIN', 'TEST', ?, ?, ?, ?, ?, ?, 'NSE')""",
                    financial_values,
                )
                conn.execute(
                    """INSERT INTO company_fundamentals
                       (filing_id, symbol, period_start, period_end, available_at, consolidated,
                        revenue_growth_yoy, pat_growth_yoy, source_exchange)
                       VALUES ('BSE-FIN', 'TEST', ?, ?, ?, ?, 99, 99, 'BSE')""",
                    financial_values[:4],
                )
                conn.execute(
                    """INSERT INTO share_capital_filings
                       (filing_id, symbol, as_of_date, available_at, outstanding_shares, source_exchange)
                       VALUES ('NSE-SHP', 'TEST', '2026-06-30', '2026-07-20 10:00:00', 100, 'NSE')"""
                )
                conn.execute(
                    """INSERT INTO share_capital_filings
                       (filing_id, symbol, as_of_date, available_at, outstanding_shares, source_exchange)
                       VALUES ('BSE-SHP', 'TEST', '2026-09-30', '2026-10-20 10:00:00', 200, 'BSE')"""
                )
                conn.commit()
            finally:
                conn.close()
            original_db = server.DB_PATH
            try:
                server.DB_PATH = path
                server.fundamental_history.cache_clear()
                server.point_in_time_fundamentals.cache_clear()
                result = server.point_in_time_fundamentals("TEST", "2026-11-09")
            finally:
                server.DB_PATH = original_db
                server.fundamental_history.cache_clear()
                server.point_in_time_fundamentals.cache_clear()
            self.assertEqual(result["revenue_growth_yoy"], 10)
            self.assertEqual(result["fundamental_source_exchange"], "NSE")
            self.assertEqual(result["outstanding_shares"], 100)
            self.assertEqual(result["market_cap_source_exchange"], "NSE")


if __name__ == "__main__":
    unittest.main()

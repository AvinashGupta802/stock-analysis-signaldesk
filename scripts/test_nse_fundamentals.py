import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_nse_fundamentals as fundamentals
from run_daily_pipeline import analysis_is_complete, fundamental_poll_start


FINANCIAL_XML = b"""<?xml version="1.0"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:f="urn:test">
  <xbrli:context id="Q">
    <xbrli:entity><xbrli:identifier scheme="test">1</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2026-07-01</xbrli:startDate><xbrli:endDate>2026-09-30</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="YTD">
    <xbrli:entity><xbrli:identifier scheme="test">1</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-09-30</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="I">
    <xbrli:entity><xbrli:identifier scheme="test">1</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2026-09-30</xbrli:instant></xbrli:period>
  </xbrli:context>
  <f:RevenueFromOperations contextRef="Q">1200</f:RevenueFromOperations>
  <f:RevenueFromOperations contextRef="YTD">2200</f:RevenueFromOperations>
  <f:ProfitLossForPeriod contextRef="Q">120</f:ProfitLossForPeriod>
  <f:ProfitBeforeTax contextRef="Q">160</f:ProfitBeforeTax>
  <f:FinanceCosts contextRef="Q">40</f:FinanceCosts>
  <f:BorrowingsCurrent contextRef="I">100</f:BorrowingsCurrent>
  <f:BorrowingsNoncurrent contextRef="I">300</f:BorrowingsNoncurrent>
  <f:Equity contextRef="I">1600</f:Equity>
</xbrli:xbrl>"""


SHAREHOLDING_XML = b"""<?xml version="1.0"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi" xmlns:s="urn:test">
  <xbrli:context id="TOTAL">
    <xbrli:entity><xbrli:identifier scheme="test">1</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2026-09-30</xbrli:instant></xbrli:period>
    <xbrli:scenario><xbrldi:explicitMember dimension="s:Axis">s:ShareholdingPatternMember</xbrldi:explicitMember></xbrli:scenario>
  </xbrli:context>
  <s:NumberOfFullyPaidUpEquityShares contextRef="TOTAL">13312748854</s:NumberOfFullyPaidUpEquityShares>
</xbrli:xbrl>"""


class FundamentalsImporterTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript(fundamentals.SCHEMA)

    def tearDown(self):
        self.conn.close()

    def test_shortest_period_is_selected_for_quarter(self):
        parsed = fundamentals.parse_xbrl(FINANCIAL_XML)
        revenue = fundamentals.select_flow_fact(
            parsed["facts"], fundamentals.FLOW_CONCEPTS["revenue"], "2026-09-30"
        )
        self.assertEqual(revenue, 1200)

    def test_financial_metrics_are_normalized(self):
        parsed = fundamentals.parse_xbrl(FINANCIAL_XML)
        fundamentals.store_financial(
            self.conn,
            "FIN-1",
            "TEST",
            {"consolidated": "Consolidated"},
            "2026-11-01 10:00:00",
            "2026-09-30",
            parsed,
        )
        row = self.conn.execute(
            "SELECT revenue, pat, total_debt, equity, debt_to_equity, roce FROM company_fundamentals"
        ).fetchone()
        self.assertEqual(row[:4], (1200, 120, 400, 1600))
        self.assertAlmostEqual(row[4], 0.25)
        self.assertGreater(row[5], 0)

    def test_shareholding_total_is_selected(self):
        parsed = fundamentals.parse_xbrl(SHAREHOLDING_XML)
        fundamentals.store_shareholding(
            self.conn,
            "SHP-1",
            "TEST",
            {"pr_and_prgrp": "50.44", "public_val": "49.56"},
            "2026-10-21 16:25:15",
            "2026-09-30",
            parsed,
        )
        row = self.conn.execute(
            "SELECT outstanding_shares, promoter_pct, public_pct FROM share_capital_filings"
        ).fetchone()
        self.assertEqual(row, (13312748854, 50.44, 49.56))

    def test_nse_timestamps_are_normalized(self):
        self.assertEqual(
            fundamentals.parse_nse_datetime("21-OCT-2026 16:25:15"),
            "2026-10-21 16:25:15",
        )

    def test_daily_poll_uses_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.sqlite3"
            conn = sqlite3.connect(path)
            try:
                conn.execute("CREATE TABLE fundamental_filings (available_at TEXT)")
                conn.execute("INSERT INTO fundamental_filings VALUES ('2026-11-09 10:00:00')")
                conn.commit()
            finally:
                conn.close()
            self.assertEqual(fundamental_poll_start(path, fundamentals.date(2026, 1, 1)), fundamentals.date(2026, 11, 2))

    def test_analysis_completeness_requires_every_active_rule_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.sqlite3"
            conn = sqlite3.connect(path)
            try:
                conn.execute(
                    "CREATE TABLE strategy_rules (rule_id TEXT, version INTEGER, status TEXT)"
                )
                conn.execute(
                    "CREATE TABLE rule_daily_results (rule_id TEXT, rule_version INTEGER, trade_date TEXT)"
                )
                conn.executemany(
                    "INSERT INTO strategy_rules VALUES (?, ?, 'active')",
                    [("rule_one", 1), ("rule_two", 2)],
                )
                conn.execute(
                    "INSERT INTO rule_daily_results VALUES ('rule_one', 1, '2026-11-06')"
                )
                conn.commit()
                self.assertFalse(analysis_is_complete(path, "2026-11-06"))
                conn.execute(
                    "INSERT INTO rule_daily_results VALUES ('rule_two', 2, '2026-11-06')"
                )
                conn.commit()
            finally:
                conn.close()
            self.assertTrue(analysis_is_complete(path, "2026-11-06"))

    def test_missing_shareholding_selects_latest_uncovered_symbol(self):
        self.conn.execute(
            "INSERT INTO share_capital_filings VALUES ('SHP-1', 'COVERED', '2026-09-30', '2026-10-10 10:00:00', 100, NULL, NULL)"
        )
        records = [
            {"symbol": "COVERED", "broadcastDate": "11-OCT-2026 10:00:00"},
            {"symbol": "MISSING", "broadcastDate": "10-OCT-2026 10:00:00"},
            {"symbol": "MISSING", "broadcastDate": "12-OCT-2026 10:00:00"},
        ]
        selected = fundamentals.missing_latest_shareholding_filings(self.conn, records)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["symbol"], "MISSING")
        self.assertEqual(selected[0]["broadcastDate"], "12-OCT-2026 10:00:00")

    def test_filing_symbol_is_canonicalized_by_isin(self):
        self.conn.execute(
            "CREATE TABLE instruments (exchange TEXT, series TEXT, isin TEXT, symbol TEXT)"
        )
        self.conn.execute(
            "INSERT INTO instruments VALUES ('NSE', 'EQ', 'INE917I01010', 'BAJAJAUTO')"
        )
        records = [{"symbol": "BAJAJ-AUTO", "isin": "INE917I01010"}]
        normalized = fundamentals.canonicalize_record_symbols(self.conn, records)
        self.assertEqual(normalized[0]["symbol"], "BAJAJAUTO")
        self.assertEqual(records[0]["symbol"], "BAJAJ-AUTO")


if __name__ == "__main__":
    unittest.main()

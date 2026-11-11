import sqlite3
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))

from server import load_group_stocks, unavailable_history_result


class ActiveStockUniverseTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE instruments (
              id INTEGER PRIMARY KEY,
              exchange TEXT,
              symbol TEXT,
              name TEXT,
              isin TEXT,
              series TEXT,
              last_trade_date TEXT
            );
            CREATE TABLE daily_prices (
              instrument_id INTEGER,
              trade_date TEXT,
              volume REAL
            );
            CREATE TABLE stock_group_members (
              group_id TEXT,
              exchange TEXT,
              symbol TEXT
            );
            """
        )
        self.conn.executemany(
            "INSERT INTO instruments VALUES (?, 'NSE', ?, ?, ?, 'EQ', ?)",
            [
                (1, "ACTIVE", "Active Limited", "INE000A01001", "2026-11-09"),
                (2, "STALE", "Stale Limited", "INE000A01002", "2026-11-06"),
            ],
        )
        self.conn.executemany(
            "INSERT INTO daily_prices VALUES (?, ?, ?)",
            [(1, "2026-11-09", 200000), (2, "2026-11-06", 200000)],
        )
        self.conn.executemany(
            "INSERT INTO stock_group_members VALUES ('watch', 'NSE', ?)",
            [("ACTIVE",), ("STALE",)],
        )

    def tearDown(self):
        self.conn.close()

    def test_builtin_group_uses_selected_date_universe(self):
        stocks = load_group_stocks(self.conn, "all", "2026-11-09")
        self.assertEqual([stock["symbol"] for stock in stocks], ["ACTIVE"])

    def test_custom_group_keeps_only_members_traded_on_selected_date(self):
        stocks = load_group_stocks(self.conn, "watch", "2026-11-09")
        self.assertEqual([stock["symbol"] for stock in stocks], ["ACTIVE"])

    def test_group_definition_without_date_keeps_all_members(self):
        stocks = load_group_stocks(self.conn, "watch")
        self.assertEqual([stock["symbol"] for stock in stocks], ["ACTIVE", "STALE"])

    def test_short_history_explains_recent_listing(self):
        result = unavailable_history_result(
            {"symbol": "NEWIPO", "name": "New IPO Limited"}, "2026-11-09", 8
        )
        self.assertIn("Only 8 NSE trading sessions", result["reason"])
        self.assertIn("recent listing", result["reason"])


if __name__ == "__main__":
    unittest.main()

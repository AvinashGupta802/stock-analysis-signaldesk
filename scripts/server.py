import json
import sqlite3
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "stock_analysis_exchange.sqlite3"

ACTIVE_STEP = {
    "step": 1,
    "name": "Price Range Filter",
    "type": "Universe filter",
    "status": "Testing",
    "plainMeaning": "Only keep NSE stocks whose closing price is within the selected minimum and maximum price.",
    "whyItMatters": "This removes very low-priced stocks and very expensive stocks before we test any buy rule.",
    "defaultValues": {"minPrice": 100, "maxPrice": 500},
}

BUILTIN_GROUPS = [
    {"id": "all", "name": "All NSE Stocks", "description": "All imported NSE stocks.", "kind": "system"},
    {"id": "liquid", "name": "NSE Liquid Stocks", "description": "NSE stocks with current-day volume >= 100,000.", "kind": "system"},
]

GROUP_SCHEMA = """
CREATE TABLE IF NOT EXISTS stock_groups (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  kind TEXT NOT NULL DEFAULT 'custom',
  source TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS stock_group_members (
  group_id TEXT NOT NULL,
  exchange TEXT NOT NULL DEFAULT 'NSE',
  symbol TEXT NOT NULL,
  name TEXT,
  weight REAL,
  PRIMARY KEY (group_id, exchange, symbol),
  FOREIGN KEY (group_id) REFERENCES stock_groups(id) ON DELETE CASCADE
);
"""


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/bootstrap":
            return self.send_json(get_bootstrap())
        if parsed.path == "/api/recommendations":
            return self.send_json(get_recommendations(parse_qs(parsed.query)))
        if parsed.path == "/api/prices":
            return self.send_json(get_prices(parse_qs(parsed.query)))
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/groups":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            return self.send_json(save_custom_group(payload))
        return self.send_json({"error": "Not found"}, 404)

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_bootstrap():
    with connect() as conn:
        ensure_group_schema(conn)
        stats = conn.execute(
            """
            SELECT
              COUNT(*) AS stock_count,
              (SELECT COUNT(*)
               FROM daily_prices p
               JOIN instruments i ON i.id = p.instrument_id
               WHERE i.exchange = 'NSE') AS price_count,
              MIN(first_trade_date) AS first_date,
              MAX(last_trade_date) AS last_date
            FROM instruments
            WHERE exchange = 'NSE'
            """
        ).fetchone()
        dates = [
            row["trade_date"]
            for row in conn.execute(
                """
                SELECT DISTINCT p.trade_date
                FROM daily_prices p
                JOIN instruments i ON i.id = p.instrument_id
                WHERE i.exchange = 'NSE'
                ORDER BY p.trade_date DESC
                LIMIT 260
                """
            )
        ]
        groups = load_groups(conn)
    return {
        "mode": "sqlite",
        "stats": dict(stats),
        "dates": list(reversed(dates)),
        "groups": groups,
        "activeStep": ACTIVE_STEP,
        "defaults": {"minPrice": 100, "maxPrice": 500},
    }


def get_recommendations(params):
    group = first(params, "group", "all")
    trade_date = first(params, "date")
    search = first(params, "search", "").strip().upper()
    min_price = number_param(params, "minPrice", 100)
    max_price = number_param(params, "maxPrice", 500)
    limit = int(number_param(params, "limit", 200))

    rows = []
    with connect() as conn:
        stocks = load_group_stocks(conn, group)
        for stock in stocks:
            if search and search not in stock["symbol"].upper() and search not in (stock["name"] or "").upper():
                continue
            item = evaluate_price_filter(conn, stock, trade_date, min_price, max_price)
            if item:
                rows.append(item)

    rows.sort(key=lambda row: (row["volume"], row["symbol"]), reverse=True)
    return {
        "group": group,
        "date": trade_date,
        "minPrice": min_price,
        "maxPrice": max_price,
        "total": len(rows),
        "results": rows[:limit],
        "metrics": build_metrics(rows),
        "explanation": {
            "name": ACTIVE_STEP["name"],
            "plainMeaning": ACTIVE_STEP["plainMeaning"],
            "decision": f"Pass if close is between Rs. {min_price:g} and Rs. {max_price:g}.",
        },
    }


def evaluate_price_filter(conn, stock, trade_date, min_price, max_price):
    current = conn.execute(
        """
        SELECT trade_date, open, high, low, close, volume
        FROM daily_prices
        WHERE instrument_id = ? AND trade_date = ?
        """,
        (stock["id"], trade_date),
    ).fetchone()
    if not current:
        return None
    if current["close"] < min_price or current["close"] > max_price:
        return None
    next_row = conn.execute(
        """
        SELECT trade_date, close
        FROM daily_prices
        WHERE instrument_id = ? AND trade_date > ?
        ORDER BY trade_date
        LIMIT 1
        """,
        (stock["id"], trade_date),
    ).fetchone()
    next_return = pct(next_row["close"], current["close"]) if next_row else None
    return {
        "symbol": stock["symbol"],
        "name": stock["name"] or stock["symbol"],
        "exchange": "NSE",
        "close": current["close"],
        "volume": current["volume"],
        "nextDate": next_row["trade_date"] if next_row else None,
        "nextClose": next_row["close"] if next_row else None,
        "nextDayReturn": next_return,
        "status": "Eligible",
        "reason": f"Close Rs. {current['close']:.2f} is inside Rs. {min_price:g}-{max_price:g}.",
    }


def get_prices(params):
    symbol = first(params, "symbol", "").upper()
    date = first(params, "date")
    with connect() as conn:
        stock = conn.execute(
            "SELECT id FROM instruments WHERE exchange = 'NSE' AND symbol = ? LIMIT 1",
            (symbol,),
        ).fetchone()
        if not stock:
            return {"symbol": symbol, "prices": []}
        rows = conn.execute(
            """
            SELECT trade_date AS date, open, high, low, close, volume
            FROM daily_prices
            WHERE instrument_id = ? AND trade_date <= COALESCE(?, trade_date)
            ORDER BY trade_date DESC
            LIMIT 80
            """,
            (stock["id"], date),
        ).fetchall()
    return {"symbol": symbol, "prices": [dict(row) for row in reversed(rows)]}


def build_metrics(rows):
    completed = [row for row in rows if row["nextDayReturn"] is not None]
    return {
        "eligibleStocks": len(rows),
        "avgNextDayMove": avg([row["nextDayReturn"] for row in completed]),
        "nextDayPositiveRate": avg([1 if row["nextDayReturn"] > 0 else 0 for row in completed]),
        "pendingOutcomes": len(rows) - len(completed),
    }


def load_group_stocks(conn, group):
    if group in {"all", "liquid"}:
        volume_clause = "AND latest.volume >= 100000" if group == "liquid" else ""
        return conn.execute(
            f"""
            SELECT i.id, i.symbol, COALESCE(i.name, i.symbol) AS name
            FROM instruments i
            JOIN daily_prices latest
              ON latest.instrument_id = i.id
             AND latest.trade_date = i.last_trade_date
            WHERE i.exchange = 'NSE'
              {volume_clause}
            ORDER BY i.symbol
            """
        ).fetchall()
    return conn.execute(
        """
        SELECT i.id, i.symbol, COALESCE(i.name, i.symbol) AS name
        FROM stock_group_members m
        JOIN instruments i ON i.exchange = m.exchange AND i.symbol = m.symbol
        WHERE m.group_id = ? AND i.exchange = 'NSE'
        ORDER BY i.symbol
        """,
        (group,),
    ).fetchall()


def load_groups(conn):
    groups = [dict(group) for group in BUILTIN_GROUPS]
    rows = conn.execute(
        """
        SELECT g.id, g.name, g.description, g.kind, COUNT(m.symbol) AS member_count
        FROM stock_groups g
        LEFT JOIN stock_group_members m ON m.group_id = g.id
        GROUP BY g.id, g.name, g.description, g.kind
        ORDER BY g.name
        """
    ).fetchall()
    for row in rows:
        item = dict(row)
        if item["member_count"]:
            item["description"] = f"{item['description']} - {item['member_count']} stocks"
        groups.append(item)
    return groups


def save_custom_group(payload):
    name = str(payload.get("name") or "").strip()
    symbols = parse_symbols(str(payload.get("symbols") or ""))
    if not name:
        return {"error": "Group name is required"}
    if not symbols:
        return {"error": "At least one symbol is required"}
    group_id = "custom_" + slugify(name)
    with connect() as conn:
        ensure_group_schema(conn)
        conn.execute(
            """
            INSERT INTO stock_groups (id, name, description, kind, source, updated_at)
            VALUES (?, ?, ?, 'custom', 'user', CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
              name = excluded.name,
              description = excluded.description,
              updated_at = CURRENT_TIMESTAMP
            """,
            (group_id, name, f"User watchlist - {len(symbols)} requested symbols"),
        )
        conn.execute("DELETE FROM stock_group_members WHERE group_id = ?", (group_id,))
        added = []
        missing = []
        for symbol in symbols:
            row = conn.execute(
                """
                SELECT exchange, symbol, COALESCE(name, symbol) AS name
                FROM instruments
                WHERE exchange = 'NSE' AND symbol = ?
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
            if not row:
                missing.append(symbol)
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO stock_group_members (group_id, exchange, symbol, name)
                VALUES (?, ?, ?, ?)
                """,
                (group_id, row["exchange"], row["symbol"], row["name"]),
            )
            added.append(row["symbol"])
        conn.commit()
    return {"id": group_id, "name": name, "added": added, "missing": missing}


def ensure_group_schema(conn):
    conn.executescript(GROUP_SCHEMA)


def parse_symbols(raw):
    cleaned = raw.replace(",", " ").replace("\n", " ").replace("\t", " ")
    symbols = []
    for item in cleaned.split(" "):
        symbol = "".join(char for char in item.upper().strip() if char.isalnum())
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    return symbols


def slugify(value):
    text = "".join(char.lower() if char.isalnum() else "_" for char in value.strip())
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_") or "watchlist"


def number_param(params, key, default):
    raw = first(params, key)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def first(params, key, default=None):
    values = params.get(key)
    return values[0] if values else default


def pct(value, base):
    return ((value - base) / base) * 100 if base else 0


def avg(values):
    return sum(values) / len(values) if values else 0


if __name__ == "__main__":
    port = 8000
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"SignalDesk Rule Lab running at http://127.0.0.1:{port}")
    print(f"SQLite DB: {DB_PATH}")
    server.serve_forever()

import json
import sqlite3
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "stock_analysis_exchange.sqlite3"

FILTERS = [
    {"id": "price_20", "name": "Price >= Rs. 20", "description": "Avoid very low priced stocks."},
    {"id": "price_50", "name": "Price >= Rs. 50", "description": "Cleaner swing-trading universe."},
    {"id": "price_range", "name": "Custom price range", "description": "Use the min/max price fields below."},
    {"id": "adv_min", "name": "20D ADV minimum", "description": "Use the 20-day average volume field below."},
    {"id": "rel_volume_min", "name": "Relative volume minimum", "description": "Use the relative volume rule threshold below."},
    {"id": "rsi_range", "name": "RSI 14 range", "description": "Use the RSI min/max fields below."},
    {"id": "ema9_distance_max", "name": "EMA9 distance maximum", "description": "Avoid entries where close is too far above 9-day EMA."},
    {"id": "volume_100k", "name": "Volume >= 100k", "description": "Basic current-day liquidity filter."},
    {"id": "volume_500k", "name": "Volume >= 500k", "description": "Stronger current-day liquidity filter."},
    {"id": "no_extreme_15", "name": "Avoid >15% one-day move", "description": "Reduces chase-risk after extreme candles."},
]

RULES = [
    {"id": "long_trend", "name": "Long: above 5 & 20 DMA", "weight": 2, "side": "long", "description": "Short trend aligned upward."},
    {"id": "short_trend", "name": "Short: below 5 & 20 DMA", "weight": 2, "side": "short", "description": "Short trend aligned downward."},
    {"id": "long_momentum", "name": "Long: 3-day momentum", "weight": 2, "side": "long", "description": "3-day gain between 1.2% and 12%."},
    {"id": "short_momentum", "name": "Short: 3-day weakness", "weight": 2, "side": "short", "description": "3-day fall between -1.2% and -12%."},
    {"id": "volume_long", "name": "Long: relative volume breakout", "weight": 2, "side": "long", "description": "Current volume / 20D ADV above configured threshold on positive close."},
    {"id": "volume_short", "name": "Short: relative volume breakdown", "weight": 2, "side": "short", "description": "Current volume / 20D ADV above configured threshold on negative close."},
    {"id": "breakout_20", "name": "Long: near 20-day high", "weight": 2, "side": "long", "description": "Close is within 2% of 20-day high."},
    {"id": "dual_buy_setup", "name": "Long: breakout or quiet setup", "weight": 4, "side": "long", "description": "Passes when either volume breakout or quiet pre-breakout setup appears."},
    {"id": "breakdown_20", "name": "Short: near 20-day low", "weight": 2, "side": "short", "description": "Close is within 2% of 20-day low."},
    {"id": "close_near_high", "name": "Long: close near day high", "weight": 1, "side": "long", "description": "Close in top 25% of daily range."},
    {"id": "close_near_low", "name": "Short: close near day low", "weight": 1, "side": "short", "description": "Close in bottom 25% of daily range."},
]

DEFAULT_FILTERS = ["price_range", "adv_min", "rsi_range", "ema9_distance_max", "no_extreme_15"]
DEFAULT_FILTER_CONFIG = {
    "minPrice": 100,
    "maxPrice": 500,
    "minAdv20": 1_000_000,
    "relVolumeMin": 1.5,
    "rsiMin": 50,
    "rsiMax": 68,
    "ema9DistanceMax": 5,
    "quietNearHighPct": 5,
    "quietRoc3Min": 1.5,
}
DEFAULT_RULES = [rule["id"] for rule in RULES if rule["side"] == "long"]

BUILTIN_GROUPS = [
    {"id": "liquid", "name": "NSE Liquid Stocks", "description": "NSE stocks with close >= Rs. 20 and volume >= 100k", "kind": "system"},
    {"id": "active", "name": "NSE Active Stocks", "description": "NSE stocks with close >= Rs. 20 and volume >= 10k", "kind": "system"},
    {"id": "all", "name": "All NSE Stocks", "description": "All imported NSE stocks with enough EOD history", "kind": "system"},
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

CREATE INDEX IF NOT EXISTS idx_stock_group_members_symbol ON stock_group_members(exchange, symbol);
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



def ensure_group_schema(conn):
    conn.executescript(GROUP_SCHEMA)


def save_custom_group(payload):
    name = str(payload.get("name") or "").strip()
    raw_symbols = str(payload.get("symbols") or "")
    symbols = parse_symbols(raw_symbols)
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
              kind = 'custom',
              source = 'user',
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
                WHERE symbol = ?
                  AND exchange = 'NSE'
                ORDER BY symbol
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
            added.append(f"{row['exchange']}:{row['symbol']}")
        conn.commit()
    return {"id": group_id, "name": name, "added": added, "missing": missing}


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

def get_bootstrap():
    with connect() as conn:
        ensure_group_schema(conn)
        stats = conn.execute(
            """
            SELECT
              COUNT(*) AS stock_count,
              (SELECT COUNT(*)
               FROM daily_prices p
               JOIN instruments i2 ON i2.id = p.instrument_id
               WHERE i2.exchange = 'NSE') AS price_count,
              MIN(first_trade_date) AS first_date,
              MAX(last_trade_date) AS last_date
            FROM instruments
            WHERE exchange = 'NSE'
            """
        ).fetchone()
        raw_dates = [
            row["trade_date"]
            for row in conn.execute(
                """
                SELECT DISTINCT trade_date
                FROM daily_prices
                JOIN instruments ON instruments.id = daily_prices.instrument_id
                WHERE instruments.exchange = 'NSE'
                ORDER BY trade_date DESC
                LIMIT 400
                """
            )
        ]
        dates = latest_continuous_dates(raw_dates)
        groups = load_groups(conn)
        return {
            "mode": "sqlite",
            "stats": dict(stats),
            "groups": groups,
            "dates": dates,
            "filters": FILTERS,
            "rules": RULES,
            "defaults": {"filters": DEFAULT_FILTERS, "filterConfig": DEFAULT_FILTER_CONFIG, "rules": DEFAULT_RULES},
        }



def load_groups(conn):
    groups = [dict(group) for group in BUILTIN_GROUPS]
    try:
        rows = conn.execute(
            """
            SELECT g.id, g.name, g.description, g.kind, COUNT(m.symbol) AS member_count
            FROM stock_groups g
            LEFT JOIN stock_group_members m ON m.group_id = g.id
            GROUP BY g.id, g.name, g.description, g.kind
            ORDER BY CASE g.kind WHEN 'nse_index' THEN 0 ELSE 1 END, g.name
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return groups
    for row in rows:
        item = dict(row)
        item["description"] = f"{item['description']} - {item['member_count']} stocks" if item.get("member_count") else item["description"]
        groups.append(item)
    return groups


def load_group_stocks(conn, group):
    base_select = """
        SELECT id, symbol, COALESCE(name, symbol) AS name, exchange,
               exchange_code AS bse_code, source_file
        FROM instruments
    """
    if group in {"liquid", "active", "all"}:
        return conn.execute(base_select + " WHERE exchange = 'NSE' ORDER BY symbol").fetchall()
    return conn.execute(
        """
        SELECT i.id, i.symbol, COALESCE(i.name, i.symbol) AS name, i.exchange,
               i.exchange_code AS bse_code, i.source_file
        FROM instruments i
        JOIN stock_group_members m
          ON m.exchange = i.exchange AND m.symbol = i.symbol
        WHERE m.group_id = ?
          AND i.exchange = 'NSE'
        ORDER BY i.symbol
        """,
        (group,),
    ).fetchall()

def latest_continuous_dates(desc_dates):
    if not desc_dates:
        return []
    picked = [desc_dates[0]]
    previous = datetime.strptime(desc_dates[0], "%Y-%m-%d")
    for value in desc_dates[1:]:
        current = datetime.strptime(value, "%Y-%m-%d")
        if (previous - current).days > 10:
            break
        picked.append(value)
        previous = current
    return list(reversed(picked))
def get_recommendations(params):
    trade_date = first(params, "date")
    group = first(params, "group", "liquid")
    threshold = int(first(params, "threshold", "5"))
    limit = int(first(params, "limit", "200"))
    search = first(params, "search", "").strip().upper()
    include_hold = first(params, "includeHold", "0") == "1"
    signal_view = first(params, "signalView", "all")
    selected_filters = parse_csv_param(params, "filters", DEFAULT_FILTERS)
    selected_rules = parse_csv_param(params, "rules", DEFAULT_RULES)
    filter_config = parse_filter_config(params)
    min_price, min_volume = group_filters(group)

    results = []
    with connect() as conn:
        stocks = load_group_stocks(conn, group)
        for stock in stocks:
            if search and search not in stock["symbol"].upper() and search not in (stock["name"] or "").upper():
                continue
            result = evaluate_stock(conn, stock, trade_date, threshold, min_price, min_volume, selected_filters, selected_rules, filter_config, include_hold)
            if result and matches_signal_view(result, signal_view):
                results.append(result)

    results.sort(key=lambda row: (abs(row["score"]), sortable_return(row["nextDayReturn"])), reverse=True)
    return {
        "date": trade_date,
        "group": group,
        "threshold": threshold,
        "filters": selected_filters,
        "rules": selected_rules,
        "filterConfig": filter_config,
        "search": search,
        "includeHold": include_hold,
        "signalView": signal_view,
        "total": len(results),
        "results": results[:limit],
        "metrics": build_metrics(results),
    }


def matches_signal_view(result, signal_view):
    if signal_view == "long":
        return result["score"] > 0
    if signal_view == "short":
        return result["score"] < 0
    if signal_view == "hold":
        return result["score"] == 0
    return True
def get_prices(params):
    symbol = first(params, "symbol", "").upper()
    date = first(params, "date")
    with connect() as conn:
        stock = conn.execute("SELECT id FROM instruments WHERE symbol = ? AND exchange = 'NSE' LIMIT 1", (symbol,)).fetchone()
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


def evaluate_stock(conn, stock, trade_date, threshold, min_price, min_volume, selected_filters, selected_rules, filter_config, include_hold=False):
    history = conn.execute(
        """
        SELECT trade_date, open, high, low, close, volume
        FROM daily_prices
        WHERE instrument_id = ? AND trade_date <= ?
        ORDER BY trade_date DESC
        LIMIT 80
        """,
        (stock["id"], trade_date),
    ).fetchall()
    if len(history) < 21:
        return None
    series = list(reversed(history))
    current = series[-1]
    if current["trade_date"] != trade_date or not has_continuous_recent_history(series):
        return None
    if current["close"] < min_price or current["volume"] < min_volume:
        return None
    ctx = build_context(series)
    if not passes_filters(ctx, selected_filters, filter_config):
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

    score, rule_results = score_series(ctx, selected_rules, filter_config)
    if score == 0 and not include_hold:
        return None
    buy_rules = sum(1 for item in rule_results if item["signal"] == "Buy")
    sell_rules = sum(1 for item in rule_results if item["signal"] == "Sell")
    hold_rules = len(rule_results) - buy_rules - sell_rules
    next_return = pct(next_row["close"], current["close"]) if next_row else None

    return {
        "symbol": stock["symbol"],
        "name": stock["name"] or stock["symbol"],
        "sector": stock["exchange"] or "Exchange",
        "bseCode": stock["bse_code"],
        "source": stock["source_file"],
        "close": current["close"],
        "avgVolume20": ctx["avg_volume_20"],
        "relativeVolume": ctx["relative_volume"],
        "rsi14": ctx["rsi_14"],
        "ema9": ctx["ema_9"],
        "ema9Distance": ctx["ema9_distance"],
        "nearHigh20Pct": ctx["near_high_20_pct"],
        "roc3": ctx["change_3"],
        "nextClose": next_row["close"] if next_row else None,
        "nextDate": next_row["trade_date"] if next_row else None,
        "nextDayReturn": next_return,
        "score": score,
        "buyRules": buy_rules,
        "sellRules": sell_rules,
        "holdRules": hold_rules,
        "signal": classify(score, threshold),
        "ruleResults": rule_results,
    }


def build_context(series):
    closes = [row["close"] for row in series]
    highs = [row["high"] for row in series]
    lows = [row["low"] for row in series]
    volumes = [row["volume"] for row in series]
    ema9_values = ema_series(closes, 9)
    current = series[-1]
    previous = series[-2]
    daily_range = max(current["high"] - current["low"], 0.01)
    high_20 = max(highs[-20:])
    return {
        "series": series,
        "current": current,
        "previous": previous,
        "close": current["close"],
        "volume": current["volume"],
        "avg_volume_5": avg(volumes[-6:-1]),
        "avg_volume_20": avg(volumes[-21:-1]),
        "relative_volume": current["volume"] / avg(volumes[-21:-1]) if avg(volumes[-21:-1]) else 0,
        "rsi_14": rsi(closes, 14),
        "ema_9": ema9_values[-1],
        "ema9_distance": pct(current["close"], ema9_values[-1]),
        "sma_5": avg(closes[-6:-1]),
        "sma_20": avg(closes[-21:-1]),
        "change_1": pct(current["close"], previous["close"]),
        "change_3": pct(current["close"], closes[-4]),
        "prior_change_3": pct(previous["close"], closes[-5]),
        "high_20": high_20,
        "near_high_20_pct": abs(pct(current["close"], high_20)),
        "low_20": min(lows[-20:]),
        "close_position": (current["close"] - current["low"]) / daily_range,
    }


def passes_filters(ctx, selected_filters, filter_config):
    if "price_20" in selected_filters and ctx["close"] < 20:
        return False
    if "price_50" in selected_filters and ctx["close"] < 50:
        return False
    if "price_range" in selected_filters and ctx["close"] < filter_config["minPrice"]:
        return False
    if "price_range" in selected_filters and ctx["close"] > filter_config["maxPrice"]:
        return False
    if "adv_min" in selected_filters and ctx["avg_volume_20"] < filter_config["minAdv20"]:
        return False
    if "rel_volume_min" in selected_filters and ctx["relative_volume"] < filter_config["relVolumeMin"]:
        return False
    if "rsi_range" in selected_filters and ctx["rsi_14"] < filter_config["rsiMin"]:
        return False
    if "rsi_range" in selected_filters and ctx["rsi_14"] > filter_config["rsiMax"]:
        return False
    if "ema9_distance_max" in selected_filters and ctx["ema9_distance"] > filter_config["ema9DistanceMax"]:
        return False
    if "volume_100k" in selected_filters and ctx["volume"] < 100_000:
        return False
    if "volume_500k" in selected_filters and ctx["volume"] < 500_000:
        return False
    if "no_extreme_15" in selected_filters and abs(ctx["change_1"]) > 15:
        return False
    return True


def score_series(ctx, selected_rules, filter_config):
    score = 0
    results = []

    def add(rule_id, signal, reason):
        nonlocal score
        rule = next((item for item in RULES if item["id"] == rule_id), None)
        if not rule or rule_id not in selected_rules:
            return
        if signal == "Buy":
            score += rule["weight"]
        elif signal == "Sell":
            score -= rule["weight"]
        results.append({"rule": rule["name"], "signal": signal, "weight": rule["weight"], "reason": reason})

    add("long_trend", "Buy" if ctx["close"] > ctx["sma_5"] and ctx["close"] > ctx["sma_20"] else "Hold", f"Close vs 5/20 DMA {pct(ctx['close'], ctx['sma_5']):+.2f}% / {pct(ctx['close'], ctx['sma_20']):+.2f}%")
    add("short_trend", "Sell" if ctx["close"] < ctx["sma_5"] and ctx["close"] < ctx["sma_20"] else "Hold", f"Close vs 5/20 DMA {pct(ctx['close'], ctx['sma_5']):+.2f}% / {pct(ctx['close'], ctx['sma_20']):+.2f}%")
    add("long_momentum", "Buy" if 1.2 <= ctx["change_3"] <= 12 else "Hold", f"3-day change {ctx['change_3']:+.2f}%")
    add("short_momentum", "Sell" if -12 <= ctx["change_3"] <= -1.2 else "Hold", f"3-day change {ctx['change_3']:+.2f}%")
    rel_min = filter_config["relVolumeMin"]
    add("volume_long", "Buy" if ctx["relative_volume"] >= rel_min and ctx["change_1"] > 0 else "Hold", f"Relative volume {ctx['relative_volume']:.2f}x vs 20D ADV")
    add("volume_short", "Sell" if ctx["relative_volume"] >= rel_min and ctx["change_1"] < 0 else "Hold", f"Relative volume {ctx['relative_volume']:.2f}x vs 20D ADV")
    add("breakout_20", "Buy" if pct(ctx["close"], ctx["high_20"]) > -2 else "Hold", f"Below 20-day high {abs(pct(ctx['close'], ctx['high_20'])):.2f}%")
    quiet_setup = (
        ctx["near_high_20_pct"] <= filter_config["quietNearHighPct"]
        and ctx["change_3"] >= filter_config["quietRoc3Min"]
        and ctx["change_3"] > ctx["prior_change_3"]
    )
    volume_setup = ctx["relative_volume"] >= filter_config["relVolumeMin"] and ctx["change_1"] > 0
    setup_reason = (
        f"Volume breakout {ctx['relative_volume']:.2f}x >= {filter_config['relVolumeMin']:.2f}x; "
        f"Quiet setup {ctx['near_high_20_pct']:.2f}% from 20D high, ROC3 {ctx['change_3']:+.2f}% vs prior {ctx['prior_change_3']:+.2f}%"
    )
    add("dual_buy_setup", "Buy" if volume_setup or quiet_setup else "Hold", setup_reason)
    add("breakdown_20", "Sell" if pct(ctx["close"], ctx["low_20"]) < 2 else "Hold", f"Above 20-day low {pct(ctx['close'], ctx['low_20']):+.2f}%")
    add("close_near_high", "Buy" if ctx["close_position"] >= 0.75 else "Hold", f"Close position in candle {ctx['close_position']:.2f}")
    add("close_near_low", "Sell" if ctx["close_position"] <= 0.25 else "Hold", f"Close position in candle {ctx['close_position']:.2f}")
    return score, results


def has_continuous_recent_history(series):
    recent = series[-25:]
    first_date = datetime.strptime(recent[0]["trade_date"], "%Y-%m-%d")
    last_date = datetime.strptime(recent[-1]["trade_date"], "%Y-%m-%d")
    return (last_date - first_date).days <= 45


def build_metrics(results):
    longs = [row for row in results if row["score"] > 0]
    shorts = [row for row in results if row["score"] < 0]
    completed = [row for row in results if row["nextDayReturn"] is not None]
    return {
        "totalSignals": len(results),
        "buyCandidates": len(longs),
        "sellCandidates": len(shorts),
        "avgNextDayMove": avg([row["nextDayReturn"] for row in completed]),
        "hitRate": avg([
            1 if (row["score"] > 0 and row["nextDayReturn"] > 0) or (row["score"] < 0 and row["nextDayReturn"] < 0) else 0
            for row in completed
        ]),
        "pendingOutcomes": len(results) - len(completed),
    }


def group_filters(group):
    if group == "liquid":
        return 20, 100_000
    if group == "active":
        return 20, 10_000
    if group == "all":
        return 0, 0
    return 0, 0


def classify(score, threshold):
    if score >= threshold:
        return "Strong Buy"
    if score > 0:
        return "Buy"
    if score <= -threshold:
        return "Strong Sell"
    if score < 0:
        return "Sell"
    return "Watch"



def parse_filter_config(params):
    return {
        "minPrice": number_param(params, "minPrice", DEFAULT_FILTER_CONFIG["minPrice"]),
        "maxPrice": number_param(params, "maxPrice", DEFAULT_FILTER_CONFIG["maxPrice"]),
        "minAdv20": number_param(params, "minAdv20", DEFAULT_FILTER_CONFIG["minAdv20"]),
        "relVolumeMin": number_param(params, "relVolumeMin", DEFAULT_FILTER_CONFIG["relVolumeMin"]),
        "rsiMin": number_param(params, "rsiMin", DEFAULT_FILTER_CONFIG["rsiMin"]),
        "rsiMax": number_param(params, "rsiMax", DEFAULT_FILTER_CONFIG["rsiMax"]),
        "ema9DistanceMax": number_param(params, "ema9DistanceMax", DEFAULT_FILTER_CONFIG["ema9DistanceMax"]),
        "quietNearHighPct": number_param(params, "quietNearHighPct", DEFAULT_FILTER_CONFIG["quietNearHighPct"]),
        "quietRoc3Min": number_param(params, "quietRoc3Min", DEFAULT_FILTER_CONFIG["quietRoc3Min"]),
    }


def number_param(params, key, default):
    raw = first(params, key)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def parse_csv_param(params, key, default):
    raw = first(params, key)
    if raw is None:
        return list(default)
    return [item for item in raw.split(",") if item]


def sortable_return(value):
    return value if value is not None else 0


def first(params, key, default=None):
    values = params.get(key)
    return values[0] if values else default


def pct(value, base):
    return ((value - base) / base) * 100 if base else 0


def avg(values):
    return sum(values) / len(values) if values else 0


def ema_series(values, period):
    if not values:
        return []
    out = []
    multiplier = 2 / (period + 1)
    current = values[0]
    for value in values:
        current = (value * multiplier) + (current * (1 - multiplier))
        out.append(current)
    return out


def rsi(values, period=14):
    if len(values) <= period:
        return 50
    gains = []
    losses = []
    for index in range(1, period + 1):
        change = values[index] - values[index - 1]
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))
    avg_gain = avg(gains)
    avg_loss = avg(losses)
    current_rsi = 100 if avg_loss == 0 else 100 - (100 / (1 + (avg_gain / avg_loss)))
    for index in range(period + 1, len(values)):
        change = values[index] - values[index - 1]
        gain = max(change, 0)
        loss = abs(min(change, 0))
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
        current_rsi = 100 if avg_loss == 0 else 100 - (100 / (1 + (avg_gain / avg_loss)))
    if avg_loss == 0:
        return 100
    return current_rsi


if __name__ == "__main__":
    port = 8000
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"SignalDesk running at http://127.0.0.1:{port}")
    print(f"SQLite DB: {DB_PATH}")
    server.serve_forever()




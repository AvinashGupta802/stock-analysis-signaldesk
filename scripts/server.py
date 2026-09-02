import json
import sqlite3
from collections import defaultdict
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "stock_analysis_exchange.sqlite3"

FILTER_LIBRARY = [
    {
        "id": "price_range",
        "name": "Price Range",
        "category": "Universe",
        "meaning": "Keep stocks whose closing price is between a minimum and maximum value.",
        "fields": [
            {"key": "minPrice", "label": "Min price", "default": 100, "step": 1},
            {"key": "maxPrice", "label": "Max price", "default": 500, "step": 1},
        ],
    },
    {
        "id": "adv20_min",
        "name": "20D Average Volume",
        "category": "Liquidity",
        "meaning": "Keep stocks that have enough average traded quantity over the last 20 trading days.",
        "fields": [
            {"key": "minAdv20", "label": "Min 20D ADV", "default": 1_000_000, "step": 10000},
        ],
    },
    {
        "id": "relative_volume",
        "name": "Volume vs 20D Avg",
        "category": "Participation",
        "meaning": "Keep stocks whose current day volume is higher or lower than their normal 20-day average volume.",
        "fields": [
            {"key": "minRelativeVolume", "label": "Min relative volume", "default": 1.5, "step": 0.1},
            {"key": "maxRelativeVolume", "label": "Max relative volume", "default": 999, "step": 0.1},
        ],
    },
    {
        "id": "delivery_pct_range",
        "name": "Delivery % Range",
        "category": "Delivery",
        "meaning": "Keep stocks where enough of the day's traded quantity was carried forward as delivery.",
        "fields": [
            {"key": "minDeliveryPct", "label": "Min delivery %", "default": 50, "step": 1},
            {"key": "maxDeliveryPct", "label": "Max delivery %", "default": 100, "step": 1},
        ],
    },
    {
        "id": "relative_delivery_qty",
        "name": "Delivery Qty vs 20D Avg",
        "category": "Delivery",
        "meaning": "Keep stocks whose delivered quantity is higher or lower than their normal 20-day delivered quantity.",
        "fields": [
            {"key": "minRelativeDelivery", "label": "Min delivery qty ratio", "default": 1.5, "step": 0.1},
            {"key": "maxRelativeDelivery", "label": "Max delivery qty ratio", "default": 999, "step": 0.1},
        ],
    },
    {
        "id": "price_momentum_3d",
        "name": "3-Day Price Momentum",
        "category": "Price Trend",
        "meaning": "Keep stocks whose close has moved up or down by a chosen percentage over the last 3 trading days.",
        "fields": [
            {"key": "minMomentum3D", "label": "Min 3D change %", "default": 2, "step": 0.5},
            {"key": "maxMomentum3D", "label": "Max 3D change %", "default": 12, "step": 0.5},
        ],
    },
    {
        "id": "range_position_52w",
        "name": "52W Range Position",
        "category": "Market Structure",
        "meaning": "Keep stocks whose close is in a chosen zone between their 52-week low and 52-week high.",
        "fields": [
            {"key": "minRangePosition52W", "label": "Min range position %", "default": 70, "step": 1},
            {"key": "maxRangePosition52W", "label": "Max range position %", "default": 100, "step": 1},
        ],
    },
    {
        "id": "obv_accumulation_3d",
        "name": "OBV Accumulation 3D",
        "category": "Volume Accumulation",
        "meaning": "Keep stocks where OBV is rising while price has stayed within a 3-day consolidation range.",
        "fields": [
            {"key": "minObv3D", "label": "Min OBV/20D ADV", "default": 1, "step": 0.1},
            {"key": "maxAbsMomentum3D", "label": "Max 3D price move %", "default": 2, "step": 0.5},
        ],
    },
    {
        "id": "rsi14_range",
        "name": "RSI 14 Range",
        "category": "Momentum Risk",
        "meaning": "Keep stocks whose RSI shows momentum but is not too overheated.",
        "fields": [
            {"key": "rsiMin", "label": "RSI min", "default": 50, "step": 1},
            {"key": "rsiMax", "label": "RSI max", "default": 68, "step": 1},
        ],
    },
]

DEFAULT_RULE = {
    "name": "Price Range Only",
    "filters": [
        {"id": "price_range", "values": {"minPrice": 100, "maxPrice": 500}},
    ],
}

BUILTIN_GROUPS = [
    {"id": "all", "name": "All NSE Stocks", "description": "All imported NSE stocks.", "kind": "system"},
    {"id": "liquid", "name": "NSE Liquid Stocks", "description": "NSE stocks with latest volume >= 100,000.", "kind": "system"},
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
        if parsed.path == "/api/prices":
            return self.send_json(get_prices(parse_qs(parsed.query)))
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        payload = self.read_payload()
        if parsed.path == "/api/rule/results":
            return self.send_json(get_rule_results(payload))
        if parsed.path == "/api/rule/backtest":
            try:
                return self.send_json(backtest_rule(payload))
            except Exception as exc:
                return self.send_json({"error": str(exc)}, 500)
        if parsed.path == "/api/groups":
            return self.send_json(save_custom_group(payload))
        return self.send_json({"error": "Not found"}, 404)

    def read_payload(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

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
        delivery_window = conn.execute(
            """
            SELECT MIN(d.trade_date) AS first_date, MAX(d.trade_date) AS last_date
            FROM daily_delivery d
            JOIN instruments i ON i.id = d.instrument_id
            WHERE i.exchange = 'NSE' AND i.series = 'EQ'
            """
        ).fetchone()
        stats = conn.execute(
            """
            SELECT
              COUNT(*) AS stock_count,
              (SELECT COUNT(*)
               FROM daily_prices p
               JOIN instruments i ON i.id = p.instrument_id
               WHERE i.exchange = 'NSE') AS price_count,
              (SELECT COUNT(*)
               FROM daily_delivery d
               JOIN instruments i ON i.id = d.instrument_id
               WHERE i.exchange = 'NSE') AS delivery_count,
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
        "filterLibrary": FILTER_LIBRARY,
        "defaultRule": DEFAULT_RULE,
        "defaultBacktest": {
            "fromDate": delivery_window["first_date"] or "2024-08-15",
            "toDate": delivery_window["last_date"] or "2026-08-24",
            "topN": 10,
            "capitalPerStock": 10_000,
            "targetPct": 5,
            "stopPct": 5,
            "maxHoldDays": 5,
        },
    }


def get_rule_results(payload):
    rule = normalize_rule(payload.get("rule") or DEFAULT_RULE)
    group = payload.get("group") or "all"
    trade_date = payload.get("date")
    search = str(payload.get("search") or "").strip().upper()
    limit = int(payload.get("limit") or 200)
    rows = []
    with connect() as conn:
        stocks = load_group_stocks(conn, group)
        for stock in stocks:
            if search and search not in stock["symbol"].upper() and search not in (stock["name"] or "").upper():
                continue
            result = evaluate_stock_on_date(conn, stock, trade_date, rule)
            if result["passed"]:
                rows.append(result)
    rows.sort(key=lambda row: (row["volume"], row["symbol"]), reverse=True)
    return {
        "rule": rule,
        "date": trade_date,
        "group": group,
        "total": len(rows),
        "results": rows[:limit],
        "metrics": build_scan_metrics(rows),
    }


def backtest_rule(payload):
    rule = normalize_rule(payload.get("rule") or DEFAULT_RULE)
    group = payload.get("group") or "all"
    from_date = payload.get("fromDate") or "2024-08-15"
    to_date = payload.get("toDate") or "2026-08-24"
    top_n = int(payload.get("topN") or 10)
    capital = float(payload.get("capitalPerStock") or 10_000)
    target_pct = float(payload.get("targetPct") or 5)
    stop_pct = float(payload.get("stopPct") or 5)
    max_hold_days = int(payload.get("maxHoldDays") or 5)

    picks_by_date = defaultdict(list)
    rows_by_symbol = {}
    with connect() as conn:
        stocks = load_group_stocks(conn, group)
        for stock in stocks:
            rows = load_rows(conn, stock["id"])
            if len(rows) < 30:
                continue
            rows_by_symbol[stock["symbol"]] = rows
            indicators = build_indicators(rows)
            for index in range(21, len(rows) - max_hold_days - 1):
                row = rows[index]
                if row["trade_date"] < from_date or row["trade_date"] > to_date:
                    continue
                ctx = build_backtest_context(rows, indicators, index)
                passed, reasons = apply_rule(ctx, rule)
                if passed:
                    picks_by_date[row["trade_date"]].append({
                        "symbol": stock["symbol"],
                        "index": index,
                        "volume": row["volume"],
                        "close": row["close"],
                        "reasons": reasons,
                    })

    trades = simulate_trades(picks_by_date, rows_by_symbol, top_n, capital, target_pct, stop_pct, max_hold_days)
    return {
        "rule": rule,
        "fromDate": from_date,
        "toDate": to_date,
        "totalSignals": sum(len(items) for items in picks_by_date.values()),
        "signalDays": len(picks_by_date),
        "summary": summarize_trades(trades, capital),
        "tradesPreview": trades[:25],
    }


def evaluate_stock_on_date(conn, stock, trade_date, rule):
    rows = conn.execute(
        """
        SELECT
          p.trade_date, p.open, p.high, p.low, p.close, p.volume,
          d.deliverable_qty, d.delivery_pct
        FROM daily_prices p
        LEFT JOIN daily_delivery d
          ON d.instrument_id = p.instrument_id
         AND d.trade_date = p.trade_date
        WHERE p.instrument_id = ? AND p.trade_date <= ?
        ORDER BY p.trade_date DESC
        LIMIT 280
        """,
        (stock["id"], trade_date),
    ).fetchall()
    if len(rows) < 21:
        return {"passed": False}
    series = [dict(row) for row in reversed(rows)]
    if series[-1]["trade_date"] != trade_date:
        return {"passed": False}
    ctx = build_context(series, len(series) - 1)
    passed, reasons = apply_rule(ctx, rule)
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
    return {
        "passed": passed,
        "symbol": stock["symbol"],
        "name": stock["name"],
        "close": ctx["close"],
        "volume": ctx["volume"],
        "deliverableQty": ctx["deliverable_qty"],
        "deliveryPct": ctx["delivery_pct"],
        "avgDelivery20": ctx["avg_delivery_20"],
        "relativeDelivery": ctx["relative_delivery"],
        "adv20": ctx["adv20"],
        "relativeVolume": ctx["relative_volume"],
        "momentum3D": ctx["momentum_3d"],
        "high52W": ctx["high_52w"],
        "low52W": ctx["low_52w"],
        "rangePosition52W": ctx["range_position_52w"],
        "obv3D": ctx["obv_3d"],
        "rsi14": ctx["rsi14"],
        "nextDate": next_row["trade_date"] if next_row else None,
        "nextClose": next_row["close"] if next_row else None,
        "nextDayReturn": pct(next_row["close"], ctx["close"]) if next_row else None,
        "reasons": reasons,
    }


def apply_rule(ctx, rule):
    reasons = []
    for selected in rule["filters"]:
        definition = filter_definition(selected["id"])
        passed, reason = evaluate_filter(ctx, selected)
        reasons.append({
            "filter": definition["name"] if definition else selected["id"],
            "passed": passed,
            "reason": reason,
        })
        if not passed:
            return False, reasons
    return True, reasons


def evaluate_filter(ctx, selected):
    values = selected.get("values") or {}
    filter_id = selected["id"]
    if filter_id == "price_range":
        min_price = float(values.get("minPrice", 100))
        max_price = float(values.get("maxPrice", 500))
        passed = min_price <= ctx["close"] <= max_price
        return passed, f"Close Rs. {ctx['close']:.2f}; required Rs. {min_price:g}-{max_price:g}."
    if filter_id == "adv20_min":
        min_adv20 = float(values.get("minAdv20", 1_000_000))
        passed = ctx["adv20"] >= min_adv20
        return passed, f"20D ADV {ctx['adv20']:,.0f}; required >= {min_adv20:,.0f}."
    if filter_id == "relative_volume":
        min_relative_volume = float(values.get("minRelativeVolume", 1.5))
        max_relative_volume = float(values.get("maxRelativeVolume", 999))
        passed = min_relative_volume <= ctx["relative_volume"] <= max_relative_volume
        return passed, f"Relative volume {ctx['relative_volume']:.2f}x; required {min_relative_volume:g}x-{max_relative_volume:g}x."
    if filter_id == "delivery_pct_range":
        min_delivery_pct = float(values.get("minDeliveryPct", 50))
        max_delivery_pct = float(values.get("maxDeliveryPct", 100))
        if ctx["delivery_pct"] is None:
            return False, "Delivery % is not available for this stock/date."
        passed = min_delivery_pct <= ctx["delivery_pct"] <= max_delivery_pct
        return passed, f"Delivery {ctx['delivery_pct']:.2f}%; required {min_delivery_pct:g}%-{max_delivery_pct:g}%."
    if filter_id == "relative_delivery_qty":
        min_relative_delivery = float(values.get("minRelativeDelivery", 1.5))
        max_relative_delivery = float(values.get("maxRelativeDelivery", 999))
        if ctx["deliverable_qty"] is None or ctx["avg_delivery_20"] <= 0:
            return False, "20D average delivery quantity is not available for this stock/date."
        passed = min_relative_delivery <= ctx["relative_delivery"] <= max_relative_delivery
        return passed, f"Delivery quantity {ctx['relative_delivery']:.2f}x 20D average; required {min_relative_delivery:g}x-{max_relative_delivery:g}x."
    if filter_id == "price_momentum_3d":
        min_momentum = float(values.get("minMomentum3D", 2))
        max_momentum = float(values.get("maxMomentum3D", 12))
        passed = min_momentum <= ctx["momentum_3d"] <= max_momentum
        return passed, f"3D price change {ctx['momentum_3d']:+.2f}%; required {min_momentum:g}%-{max_momentum:g}%."
    if filter_id == "range_position_52w":
        min_range_position = float(values.get("minRangePosition52W", 70))
        max_range_position = float(values.get("maxRangePosition52W", 100))
        passed = min_range_position <= ctx["range_position_52w"] <= max_range_position
        return passed, f"52W range position {ctx['range_position_52w']:.2f}%; required {min_range_position:g}%-{max_range_position:g}%."
    if filter_id == "obv_accumulation_3d":
        min_obv = float(values.get("minObv3D", 1))
        max_abs_momentum = float(values.get("maxAbsMomentum3D", 2))
        passed = ctx["obv_3d"] >= min_obv and abs(ctx["momentum_3d"]) <= max_abs_momentum
        return passed, f"OBV change {ctx['obv_3d']:.2f}x 20D ADV and 3D price move {ctx['momentum_3d']:+.2f}%; required OBV >= {min_obv:g}x and price move within +/-{max_abs_momentum:g}%."
    if filter_id == "rsi14_range":
        rsi_min = float(values.get("rsiMin", 50))
        rsi_max = float(values.get("rsiMax", 68))
        passed = rsi_min <= ctx["rsi14"] <= rsi_max
        return passed, f"RSI 14 {ctx['rsi14']:.2f}; required {rsi_min:g}-{rsi_max:g}."
    return False, "Unknown filter."


def build_context(rows, index):
    window = rows[:index + 1]
    closes = [row["close"] for row in window]
    highs = [row["high"] for row in window]
    lows = [row["low"] for row in window]
    volumes = [row["volume"] for row in window]
    delivery_quantities = [row.get("deliverable_qty") for row in window]
    current = rows[index]
    adv20 = avg(volumes[-21:-1])
    avg_delivery_20 = avg_available(delivery_quantities[-21:-1])
    range_window = rows[max(0, index - 251):index + 1]
    high_52w = max(row["high"] for row in range_window)
    low_52w = min(row["low"] for row in range_window)
    obv = obv_series(closes, volumes)
    return {
        "date": current["trade_date"],
        "close": current["close"],
        "volume": current["volume"],
        "deliverable_qty": current.get("deliverable_qty"),
        "delivery_pct": current.get("delivery_pct"),
        "avg_delivery_20": avg_delivery_20,
        "relative_delivery": relative_to_avg(current.get("deliverable_qty"), avg_delivery_20),
        "adv20": adv20,
        "relative_volume": relative_to_avg(current["volume"], adv20),
        "momentum_3d": pct(current["close"], rows[index - 3]["close"]) if index >= 3 else 0,
        "high_52w": high_52w,
        "low_52w": low_52w,
        "range_position_52w": range_position(current["close"], low_52w, high_52w),
        "obv_3d": relative_to_avg(obv[-1] - obv[-4], adv20) if len(obv) >= 4 else 0,
        "rsi14": rsi(closes, 14),
    }


def build_indicators(rows):
    closes = [row["close"] for row in rows]
    highs = [row["high"] for row in rows]
    lows = [row["low"] for row in rows]
    volumes = [row["volume"] for row in rows]
    delivery_quantities = [row.get("deliverable_qty") for row in rows]
    obv = obv_series(closes, volumes)
    adv20 = [0] * len(rows)
    for index in range(20, len(rows)):
        adv20[index] = avg(volumes[index - 20:index])
    relative_volume = [0] * len(rows)
    avg_delivery_20 = [0] * len(rows)
    relative_delivery = [0] * len(rows)
    for index in range(len(rows)):
        relative_volume[index] = relative_to_avg(volumes[index], adv20[index])
        avg_delivery_20[index] = avg_available(delivery_quantities[index - 20:index]) if index >= 20 else 0
        relative_delivery[index] = relative_to_avg(delivery_quantities[index], avg_delivery_20[index])
    momentum_3d = [0] * len(rows)
    high_52w = [0] * len(rows)
    low_52w = [0] * len(rows)
    range_position_52w = [50] * len(rows)
    obv_3d = [0] * len(rows)
    for index in range(len(rows)):
        start = max(0, index - 251)
        high_52w[index] = max(highs[start:index + 1])
        low_52w[index] = min(lows[start:index + 1])
        range_position_52w[index] = range_position(closes[index], low_52w[index], high_52w[index])
    for index in range(3, len(rows)):
        momentum_3d[index] = pct(closes[index], closes[index - 3])
        obv_3d[index] = relative_to_avg(obv[index] - obv[index - 3], adv20[index])
    return {
        "adv20": adv20,
        "relative_volume": relative_volume,
        "avg_delivery_20": avg_delivery_20,
        "relative_delivery": relative_delivery,
        "momentum_3d": momentum_3d,
        "high_52w": high_52w,
        "low_52w": low_52w,
        "range_position_52w": range_position_52w,
        "obv_3d": obv_3d,
        "rsi14": rsi_series(closes, 14),
    }


def build_backtest_context(rows, indicators, index):
    current = rows[index]
    return {
        "date": current["trade_date"],
        "close": current["close"],
        "volume": current["volume"],
        "deliverable_qty": current.get("deliverable_qty"),
        "delivery_pct": current.get("delivery_pct"),
        "avg_delivery_20": indicators["avg_delivery_20"][index],
        "relative_delivery": indicators["relative_delivery"][index],
        "adv20": indicators["adv20"][index],
        "relative_volume": indicators["relative_volume"][index],
        "momentum_3d": indicators["momentum_3d"][index],
        "high_52w": indicators["high_52w"][index],
        "low_52w": indicators["low_52w"][index],
        "range_position_52w": indicators["range_position_52w"][index],
        "obv_3d": indicators["obv_3d"][index],
        "rsi14": indicators["rsi14"][index],
    }


def simulate_trades(picks_by_date, rows_by_symbol, top_n, capital, target_pct, stop_pct, max_hold_days):
    trades = []
    for signal_date in sorted(picks_by_date):
        picks = sorted(picks_by_date[signal_date], key=lambda row: (row["volume"], row["symbol"]), reverse=True)[:top_n]
        for pick in picks:
            rows = rows_by_symbol[pick["symbol"]]
            entry_index = pick["index"] + 1
            if entry_index >= len(rows):
                continue
            entry_row = rows[entry_index]
            entry_price = entry_row["open"] or entry_row["close"]
            target_price = entry_price * (1 + target_pct / 100)
            stop_price = entry_price * (1 - stop_pct / 100)
            exit_row = rows[min(entry_index + max_hold_days, len(rows) - 1)]
            exit_price = exit_row["close"]
            exit_reason = "time"
            for hold_index in range(entry_index, min(entry_index + max_hold_days, len(rows) - 1) + 1):
                day = rows[hold_index]
                if day["low"] <= stop_price:
                    exit_row = day
                    exit_price = stop_price
                    exit_reason = "stop"
                    break
                if day["high"] >= target_price:
                    exit_row = day
                    exit_price = target_price
                    exit_reason = "target"
                    break
            pnl = (capital / entry_price) * (exit_price - entry_price) if entry_price else 0
            trades.append({
                "signalDate": signal_date,
                "symbol": pick["symbol"],
                "entryDate": entry_row["trade_date"],
                "exitDate": exit_row["trade_date"],
                "exitReason": exit_reason,
                "entryPrice": entry_price,
                "exitPrice": exit_price,
                "returnPct": pct(exit_price, entry_price),
                "pnl": pnl,
            })
    return trades


def summarize_trades(trades, capital):
    invested = len(trades) * capital
    pnl = sum(trade["pnl"] for trade in trades)
    return {
        "trades": len(trades),
        "investedTurnover": invested,
        "netPnl": pnl,
        "returnOnTurnoverPct": (pnl / invested) * 100 if invested else 0,
        "avgTradeReturnPct": avg([trade["returnPct"] for trade in trades]),
        "winRatePct": avg([1 if trade["pnl"] > 0 else 0 for trade in trades]) * 100,
        "targetHitPct": avg([1 if trade["exitReason"] == "target" else 0 for trade in trades]) * 100,
        "stopHitPct": avg([1 if trade["exitReason"] == "stop" else 0 for trade in trades]) * 100,
    }


def build_scan_metrics(rows):
    completed = [row for row in rows if row["nextDayReturn"] is not None]
    return {
        "passedStocks": len(rows),
        "avgNextDayMove": avg([row["nextDayReturn"] for row in completed]),
        "nextDayPositiveRate": avg([1 if row["nextDayReturn"] > 0 else 0 for row in completed]) * 100,
        "pendingOutcomes": len(rows) - len(completed),
    }


def normalize_rule(rule):
    filters = []
    for item in rule.get("filters") or []:
        definition = filter_definition(item.get("id"))
        if not definition:
            continue
        defaults = {field["key"]: field["default"] for field in definition["fields"]}
        defaults.update(item.get("values") or {})
        filters.append({"id": definition["id"], "values": defaults})
    return {"name": str(rule.get("name") or "Untitled Rule").strip() or "Untitled Rule", "filters": filters}


def filter_definition(filter_id):
    return next((item for item in FILTER_LIBRARY if item["id"] == filter_id), None)


def get_prices(params):
    symbol = first(params, "symbol", "").upper()
    date = first(params, "date")
    with connect() as conn:
        stock = conn.execute("SELECT id FROM instruments WHERE exchange = 'NSE' AND symbol = ? LIMIT 1", (symbol,)).fetchone()
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


def load_rows(conn, instrument_id):
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT
              p.trade_date, p.open, p.high, p.low, p.close, p.volume,
              d.deliverable_qty, d.delivery_pct
            FROM daily_prices p
            LEFT JOIN daily_delivery d
              ON d.instrument_id = p.instrument_id
             AND d.trade_date = p.trade_date
            WHERE p.instrument_id = ?
            ORDER BY p.trade_date
            """,
            (instrument_id,),
        ).fetchall()
    ]


def load_group_stocks(conn, group):
    if group in {"all", "liquid"}:
        volume_clause = "AND latest.volume >= 100000" if group == "liquid" else ""
        return conn.execute(
            f"""
            SELECT i.id, i.symbol, COALESCE(i.name, i.symbol) AS name
            FROM instruments i
            JOIN daily_prices latest ON latest.instrument_id = i.id AND latest.trade_date = i.last_trade_date
            WHERE i.exchange = 'NSE' AND i.series = 'EQ' {volume_clause}
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
            ON CONFLICT(id) DO UPDATE SET name = excluded.name, description = excluded.description, updated_at = CURRENT_TIMESTAMP
            """,
            (group_id, name, f"User watchlist - {len(symbols)} requested symbols"),
        )
        conn.execute("DELETE FROM stock_group_members WHERE group_id = ?", (group_id,))
        added = []
        missing = []
        for symbol in symbols:
            row = conn.execute(
                "SELECT exchange, symbol, COALESCE(name, symbol) AS name FROM instruments WHERE exchange = 'NSE' AND symbol = ? LIMIT 1",
                (symbol,),
            ).fetchone()
            if not row:
                missing.append(symbol)
                continue
            conn.execute(
                "INSERT OR REPLACE INTO stock_group_members (group_id, exchange, symbol, name) VALUES (?, ?, ?, ?)",
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


def first(params, key, default=None):
    values = params.get(key)
    return values[0] if values else default


def pct(value, base):
    return ((value - base) / base) * 100 if base else 0


def avg(values):
    return sum(values) / len(values) if values else 0


def avg_available(values):
    filtered = [value for value in values if value is not None]
    return avg(filtered)


def relative_to_avg(value, average):
    return (value / average) if value is not None and average else 0


def range_position(close, low, high):
    spread = high - low
    return ((close - low) / spread) * 100 if spread else 50


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
    value = 100 if avg_loss == 0 else 100 - (100 / (1 + (avg_gain / avg_loss)))
    for index in range(period + 1, len(values)):
        change = values[index] - values[index - 1]
        avg_gain = ((avg_gain * (period - 1)) + max(change, 0)) / period
        avg_loss = ((avg_loss * (period - 1)) + abs(min(change, 0))) / period
        value = 100 if avg_loss == 0 else 100 - (100 / (1 + (avg_gain / avg_loss)))
    return value


def rsi_series(values, period=14):
    out = [50] * len(values)
    if len(values) <= period:
        return out
    gains = []
    losses = []
    for index in range(1, period + 1):
        change = values[index] - values[index - 1]
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))
    avg_gain = avg(gains)
    avg_loss = avg(losses)
    out[period] = 100 if avg_loss == 0 else 100 - (100 / (1 + (avg_gain / avg_loss)))
    for index in range(period + 1, len(values)):
        change = values[index] - values[index - 1]
        avg_gain = ((avg_gain * (period - 1)) + max(change, 0)) / period
        avg_loss = ((avg_loss * (period - 1)) + abs(min(change, 0))) / period
        out[index] = 100 if avg_loss == 0 else 100 - (100 / (1 + (avg_gain / avg_loss)))
    return out


def obv_series(closes, volumes):
    out = [0] * len(closes)
    for index in range(1, len(closes)):
        if closes[index] > closes[index - 1]:
            out[index] = out[index - 1] + volumes[index]
        elif closes[index] < closes[index - 1]:
            out[index] = out[index - 1] - volumes[index]
        else:
            out[index] = out[index - 1]
    return out


if __name__ == "__main__":
    port = 8000
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"SignalDesk Rule Builder running at http://127.0.0.1:{port}")
    print(f"SQLite DB: {DB_PATH}")
    server.serve_forever()

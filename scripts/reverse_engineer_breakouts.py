import argparse
import sqlite3
from pathlib import Path

from server import (
    DB_PATH,
    atr_series,
    avg,
    avg_available,
    ema_series,
    obv_series,
    pct,
    range_position,
    rsi_series,
)


def main():
    parser = argparse.ArgumentParser(description="Reverse engineer recent NSE swing winners.")
    parser.add_argument("--symbols", default="MANAKSTEEL", help="Comma separated symbols to inspect.")
    parser.add_argument("--lookback", type=int, default=21)
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--min-price", type=float, default=50)
    parser.add_argument("--max-price", type=float, default=1000)
    args = parser.parse_args()

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        for symbol in [item.strip().upper() for item in args.symbols.split(",") if item.strip()]:
            explain_symbol(conn, symbol, args.lookback)
        print("\nRECENT ONE-MONTH WINNERS")
        winners = recent_winners(conn, args.lookback, args.top, args.min_price, args.max_price)
        for row in winners:
            print_winner(row)
        print_summary(winners)


def explain_symbol(conn, symbol, lookback):
    instrument = conn.execute(
        "SELECT id, symbol, COALESCE(name, symbol) AS name FROM instruments WHERE exchange='NSE' AND symbol=? LIMIT 1",
        (symbol,),
    ).fetchone()
    if not instrument:
        print(f"\n{symbol}: not found")
        return
    rows = load_rows(conn, instrument["id"])
    if len(rows) <= lookback:
        print(f"\n{symbol}: not enough rows")
        return
    latest = len(rows) - 1
    start = latest - lookback
    move = pct(rows[latest]["close"], rows[start]["close"])
    print(f"\n{instrument['symbol']} - {instrument['name']}")
    print(f"Last {lookback} trading days: {rows[start]['trade_date']} close {rows[start]['close']:.2f} -> {rows[latest]['trade_date']} close {rows[latest]['close']:.2f} = {move:+.2f}%")
    print("Candidate signal days before/during move:")
    for index in range(max(21, start - 10), min(latest, start + 8)):
        features = build_features(rows, index)
        future = pct(rows[min(latest, index + lookback)]["close"], rows[index]["close"])
        if future >= 10 or features["relative_volume"] >= 1.5 or features["relative_delivery"] >= 1.5:
            print_feature_line(rows[index], features, future)


def recent_winners(conn, lookback, limit, min_price, max_price):
    winners = []
    instruments = conn.execute(
        """
        SELECT id, symbol, COALESCE(name, symbol) AS name
        FROM instruments
        WHERE exchange='NSE' AND series='EQ'
        ORDER BY symbol
        """
    ).fetchall()
    for instrument in instruments:
        rows = load_rows(conn, instrument["id"])
        if len(rows) <= lookback + 25:
            continue
        latest = len(rows) - 1
        start = latest - lookback
        start_close = rows[start]["close"]
        latest_close = rows[latest]["close"]
        if not (min_price <= start_close <= max_price):
            continue
        one_month_return = pct(latest_close, start_close)
        if one_month_return < 20:
            continue
        trigger_index = find_trigger_index(rows, start, latest, lookback)
        features = build_features(rows, trigger_index)
        winners.append({
            "symbol": instrument["symbol"],
            "name": instrument["name"],
            "return": one_month_return,
            "trigger_date": rows[trigger_index]["trade_date"],
            "trigger_close": rows[trigger_index]["close"],
            "features": features,
        })
    winners.sort(key=lambda item: item["return"], reverse=True)
    return winners[:limit]


def find_trigger_index(rows, start, latest, horizon):
    best_index = start
    for index in range(max(21, start - 10), latest):
        forward = pct(rows[min(latest, index + horizon)]["close"], rows[index]["close"])
        features = build_features(rows, index)
        if forward >= 15 and (
            features["relative_volume"] >= 1.5
            or features["relative_delivery"] >= 1.5
            or features["close_position_day"] >= 70
            or features["distance_from_20d_high"] >= -3
        ):
            return index
        if forward > pct(rows[min(latest, best_index + horizon)]["close"], rows[best_index]["close"]):
            best_index = index
    return best_index


def build_features(rows, index):
    closes = [row["close"] for row in rows[:index + 1]]
    highs = [row["high"] for row in rows[:index + 1]]
    lows = [row["low"] for row in rows[:index + 1]]
    volumes = [row["volume"] for row in rows[:index + 1]]
    delivery_quantities = [row.get("deliverable_qty") for row in rows[:index + 1]]
    row = rows[index]
    adv20 = avg(volumes[-21:-1])
    avg_delivery_20 = avg_available(delivery_quantities[-21:-1])
    high_20d = max(highs[-20:])
    low_20d = min(lows[-20:])
    high_52w = max(highs[-252:])
    low_52w = min(lows[-252:])
    ema9 = ema_series(closes, 9)[-1]
    ema20 = ema_series(closes, 20)[-1]
    sma50 = avg(closes[-50:])
    atr14 = atr_series(rows[:index + 1], 14)[-1]
    obv = obv_series(closes, volumes)
    return {
        "momentum_3d": pct(row["close"], rows[index - 3]["close"]) if index >= 3 else 0,
        "momentum_5d": pct(row["close"], rows[index - 5]["close"]) if index >= 5 else 0,
        "relative_volume": row["volume"] / adv20 if adv20 else 0,
        "delivery_pct": row.get("delivery_pct"),
        "relative_delivery": row.get("deliverable_qty") / avg_delivery_20 if row.get("deliverable_qty") is not None and avg_delivery_20 else 0,
        "close_position_day": range_position(row["close"], row["low"], row["high"]),
        "distance_from_20d_high": pct(row["close"], high_20d),
        "range_position_52w": range_position(row["close"], low_52w, high_52w),
        "compression_10d": ((max(highs[-10:]) - min(lows[-10:])) / row["close"]) * 100 if row["close"] else 0,
        "range_width_20d": ((high_20d - low_20d) / row["close"]) * 100 if row["close"] else 0,
        "ema_checks": sum([row["close"] > ema9, row["close"] > ema20, ema20 > sma50]),
        "atr_pct": (atr14 / row["close"]) * 100 if row["close"] else 0,
        "rsi14": rsi_series(closes, 14)[-1],
        "obv_3d": (obv[-1] - obv[-4]) / adv20 if len(obv) >= 4 and adv20 else 0,
    }


def load_rows(conn, instrument_id):
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT p.trade_date, p.open, p.high, p.low, p.close, p.volume,
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


def print_feature_line(row, features, future):
    print(
        f"{row['trade_date']} close {row['close']:.2f} future {future:+.2f}% | "
        f"rvol {features['relative_volume']:.2f}x del% {show(features['delivery_pct'])} "
        f"reldel {features['relative_delivery']:.2f}x mom3 {features['momentum_3d']:+.2f}% "
        f"daypos {features['close_position_day']:.0f}% 20dh {features['distance_from_20d_high']:+.2f}% "
        f"ema {features['ema_checks']}/3 atr {features['atr_pct']:.2f}% rsi {features['rsi14']:.1f} "
        f"comp10 {features['compression_10d']:.2f}% obv {features['obv_3d']:.2f}x"
    )


def print_winner(item):
    f = item["features"]
    print(
        f"{item['symbol']:14} {item['return']:+7.2f}% trigger {item['trigger_date']} close {item['trigger_close']:.2f} | "
        f"rvol {f['relative_volume']:.2f}x del% {show(f['delivery_pct'])} reldel {f['relative_delivery']:.2f}x "
        f"mom3 {f['momentum_3d']:+.2f}% daypos {f['close_position_day']:.0f}% 20dh {f['distance_from_20d_high']:+.2f}% "
        f"ema {f['ema_checks']}/3 atr {f['atr_pct']:.2f}% rsi {f['rsi14']:.1f} comp10 {f['compression_10d']:.2f}%"
    )


def print_summary(winners):
    if not winners:
        return
    checks = [
        ("close in upper 70% of day range", lambda f: f["close_position_day"] >= 70),
        ("within 3% of 20D high", lambda f: f["distance_from_20d_high"] >= -3),
        ("EMA trend at least 2/3", lambda f: f["ema_checks"] >= 2),
        ("ATR between 3% and 8%", lambda f: 3 <= f["atr_pct"] <= 8),
        ("RSI between 45 and 70", lambda f: 45 <= f["rsi14"] <= 70),
        ("relative volume >= 1.5x", lambda f: f["relative_volume"] >= 1.5),
        ("relative delivery >= 1.5x", lambda f: f["relative_delivery"] >= 1.5),
        ("delivery percentage >= 60%", lambda f: f["delivery_pct"] is not None and f["delivery_pct"] >= 60),
        ("3D momentum between -6% and +3%", lambda f: -6 <= f["momentum_3d"] <= 3),
        ("10D range compression <= 12%", lambda f: f["compression_10d"] <= 12),
    ]
    print("\nCOMMON TRIGGER-DAY FINGERPRINTS")
    for label, check in checks:
        count = sum(1 for item in winners if check(item["features"]))
        print(f"{label:36} {count:2}/{len(winners)} = {(count / len(winners)) * 100:5.1f}%")


def show(value):
    return "N/A" if value is None else f"{value:.1f}"


if __name__ == "__main__":
    main()

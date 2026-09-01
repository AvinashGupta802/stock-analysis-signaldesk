import argparse
import csv
import sqlite3
from collections import defaultdict
from pathlib import Path

RULE_WEIGHTS = {
    "long_trend": 2,
    "short_trend": 2,
    "long_momentum": 2,
    "short_momentum": 2,
    "volume_long": 2,
    "volume_short": 2,
    "breakout_20": 2,
    "breakdown_20": 2,
    "close_near_high": 1,
    "close_near_low": 1,
}


def main():
    parser = argparse.ArgumentParser(description="Backtest short-term EOD signals on clean NSE/BSE bhavcopy DB.")
    parser.add_argument("--db", default="data/stock_analysis_exchange.sqlite3")
    parser.add_argument("--exchange", choices=["NSE", "BSE", "all"], default="NSE")
    parser.add_argument("--from-date", default="2024-08-15")
    parser.add_argument("--to-date", default="2026-08-14")
    parser.add_argument("--min-price", type=float, default=20)
    parser.add_argument("--min-volume", type=int, default=0)
    parser.add_argument("--max-price", type=float, default=0, help="0 means no max price filter")
    parser.add_argument("--min-adv20", type=float, default=0)
    parser.add_argument("--min-rel-volume", type=float, default=0)
    parser.add_argument("--min-rupee-volume-cr", type=float, default=0, help="Minimum close * 20D ADV in crore rupees")
    parser.add_argument("--strategy", choices=["score", "velocity_long"], default="score")
    parser.add_argument("--threshold", type=int, default=5)
    parser.add_argument("--output", default="outputs/backtest_exchange_summary.csv")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    instruments = load_instruments(conn, args.exchange)

    all_results = []
    by_symbol = defaultdict(list)
    processed = 0
    for instrument in instruments:
        rows = load_rows(conn, instrument["id"])
        if len(rows) < 60:
            continue
        results = evaluate_instrument(instrument, rows, args)
        all_results.extend(results)
        key = f"{instrument['exchange']}:{instrument['symbol']}"
        by_symbol[key].extend(results)
        processed += 1
        if processed % 500 == 0:
            print(f"Backtested {processed:,} instruments, {len(all_results):,} signals")

    conn.close()
    write_summary(Path(args.output), by_symbol)

    print("Backtest complete")
    print(f"Exchange: {args.exchange}")
    print(f"Instruments processed: {processed:,}")
    print(f"Signal rows: {len(all_results):,}")
    print(f"Strategy: {args.strategy}")
    print(f"Filters: min_price={args.min_price:g}, max_price={args.max_price:g}, min_volume={args.min_volume:,}, min_adv20={args.min_adv20:,.0f}, min_rel_volume={args.min_rel_volume:g}, min_rupee_volume_cr={args.min_rupee_volume_cr:g}")
    report("Long signals", [r for r in all_results if r["score"] > 0], long_side=True)
    report("Strong long signals", [r for r in all_results if r["score"] >= args.threshold], long_side=True)
    report("Short signals", [r for r in all_results if r["score"] < 0], long_side=False)
    report("Strong short signals", [r for r in all_results if r["score"] <= -args.threshold], long_side=False)
    print(f"CSV: {args.output}")


def load_instruments(conn, exchange):
    where = "" if exchange == "all" else "WHERE exchange = ?"
    params = () if exchange == "all" else (exchange,)
    return conn.execute(
        f"SELECT id, exchange, symbol, COALESCE(name, symbol) AS name FROM instruments {where} ORDER BY exchange, symbol",
        params,
    ).fetchall()


def load_rows(conn, instrument_id):
    return conn.execute(
        """
        SELECT trade_date, open, high, low, close, volume
        FROM daily_prices
        WHERE instrument_id = ?
        ORDER BY trade_date
        """,
        (instrument_id,),
    ).fetchall()


def evaluate_instrument(instrument, rows, args):
    out = []
    closes = [r["close"] for r in rows]
    highs = [r["high"] for r in rows]
    lows = [r["low"] for r in rows]
    volumes = [r["volume"] for r in rows]
    ema9 = ema_series(closes, 9)
    ema20 = ema_series(closes, 20)
    rsi14 = rsi_series(closes, 14)
    atr14 = atr_series(rows, 14)
    for i in range(50, len(rows) - 5):
        row = rows[i]
        if row["trade_date"] < args.from_date or row["trade_date"] > args.to_date:
            continue
        avg_volume20 = avg(volumes[i - 20:i])
        rel_volume = row["volume"] / avg_volume20 if avg_volume20 else 0
        rupee_volume_cr = (row["close"] * avg_volume20) / 10_000_000
        if row["close"] < args.min_price or row["volume"] < args.min_volume:
            continue
        if args.max_price and row["close"] > args.max_price:
            continue
        if args.min_adv20 and avg_volume20 < args.min_adv20:
            continue
        if args.min_rel_volume and rel_volume < args.min_rel_volume:
            continue
        if args.min_rupee_volume_cr and rupee_volume_cr < args.min_rupee_volume_cr:
            continue
        if args.strategy == "velocity_long":
            score, buy_rules, sell_rules = velocity_long_day(i, rows, closes, volumes, ema9, ema20, rsi14, args)
        else:
            score, buy_rules, sell_rules = score_day(i, rows, closes, highs, lows, volumes, args)
        if score == 0:
            continue
        stop_distance_pct = ((2 * atr14[i]) / row["close"]) * 100 if row["close"] and atr14[i] else 0
        out.append({
            "exchange": instrument["exchange"],
            "symbol": instrument["symbol"],
            "date": row["trade_date"],
            "score": score,
            "buy_rules": buy_rules,
            "sell_rules": sell_rules,
            "adv20": avg_volume20,
            "rel_volume": rel_volume,
            "rupee_volume_cr": rupee_volume_cr,
            "atr_stop_pct": stop_distance_pct,
            "ret_1d": pct(rows[i + 1]["close"], row["close"]),
            "ret_2d": pct(rows[i + 2]["close"], row["close"]),
            "ret_3d": pct(rows[i + 3]["close"], row["close"]),
            "ret_5d": pct(rows[i + 5]["close"], row["close"]),
            "max_upside_5d": pct(max(r["high"] for r in rows[i + 1:i + 6]), row["close"]),
            "max_drawdown_5d": pct(min(r["low"] for r in rows[i + 1:i + 6]), row["close"]),
        })
    return out


def score_day(i, rows, closes, highs, lows, volumes, args):
    close = closes[i]
    previous_close = closes[i - 1]
    sma5 = avg(closes[i - 5:i])
    sma20 = avg(closes[i - 20:i])
    avg_volume20 = avg(volumes[i - 20:i])
    change1 = pct(close, previous_close)
    change3 = pct(close, closes[i - 3])
    high20 = max(highs[i - 19:i + 1])
    low20 = min(lows[i - 19:i + 1])
    day_range = max(rows[i]["high"] - rows[i]["low"], 0.01)
    close_position = (close - rows[i]["low"]) / day_range

    score = 0
    buy_rules = 0
    sell_rules = 0

    def add(condition, side, weight):
        nonlocal score, buy_rules, sell_rules
        if not condition:
            return
        if side == "buy":
            score += weight
            buy_rules += 1
        else:
            score -= weight
            sell_rules += 1

    add(close > sma5 and close > sma20, "buy", RULE_WEIGHTS["long_trend"])
    add(close < sma5 and close < sma20, "sell", RULE_WEIGHTS["short_trend"])
    add(1.2 <= change3 <= 12, "buy", RULE_WEIGHTS["long_momentum"])
    add(-12 <= change3 <= -1.2, "sell", RULE_WEIGHTS["short_momentum"])
    rel_min = args.min_rel_volume or 1.5
    rel_volume = volumes[i] / avg_volume20 if avg_volume20 else 0
    add(rel_volume >= rel_min and change1 > 0, "buy", RULE_WEIGHTS["volume_long"])
    add(rel_volume >= rel_min and change1 < 0, "sell", RULE_WEIGHTS["volume_short"])
    add(pct(close, high20) > -2, "buy", RULE_WEIGHTS["breakout_20"])
    add(pct(close, low20) < 2, "sell", RULE_WEIGHTS["breakdown_20"])
    add(close_position >= 0.75, "buy", RULE_WEIGHTS["close_near_high"])
    add(close_position <= 0.25, "sell", RULE_WEIGHTS["close_near_low"])
    return score, buy_rules, sell_rules


def velocity_long_day(i, rows, closes, volumes, ema9, ema20, rsi14, args):
    close = closes[i]
    sma50 = avg(closes[i - 50:i])
    avg_volume20 = avg(volumes[i - 20:i])
    rel_min = args.min_rel_volume or 1.5
    rel_volume = volumes[i] / avg_volume20 if avg_volume20 else 0
    roc3 = pct(close, closes[i - 3])
    dist_ema9 = pct(close, ema9[i])
    dist_ema20 = pct(close, ema20[i])
    day_range = max(rows[i]["high"] - rows[i]["low"], 0.01)
    close_position = (close - rows[i]["low"]) / day_range

    conditions = [
        close > ema9[i],
        close > ema20[i],
        ema20[i] > sma50,
        4 <= roc3 <= 12,
        rel_volume >= rel_min,
        50 <= rsi14[i] < 72,
        dist_ema9 <= 5,
        dist_ema20 <= 10,
        close_position >= 0.6,
    ]
    if not all(conditions):
        return 0, 0, 0
    return 9, 6, 0


def report(label, rows, long_side):
    print(f"{label}: {len(rows):,}")
    if not rows:
        return
    for key in ["ret_2d", "ret_3d", "ret_5d"]:
        hits = [1 if (r[key] > 0 if long_side else r[key] < 0) else 0 for r in rows]
        print(f"  {key}: avg {avg([r[key] for r in rows]):+.2f}%, hit {avg(hits) * 100:.2f}%")
    print(f"  5d upside avg: {avg([r['max_upside_5d'] for r in rows]):+.2f}%")
    print(f"  5d drawdown avg: {avg([r['max_drawdown_5d'] for r in rows]):+.2f}%")


def write_summary(path, by_symbol):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["instrument", "signals", "avg_rel_volume", "avg_2d", "hit_2d", "avg_5d", "hit_5d"])
        writer.writeheader()
        for instrument, rows in sorted(by_symbol.items()):
            if not rows:
                continue
            writer.writerow({
                "instrument": instrument,
                "signals": len(rows),
                "avg_rel_volume": round(avg([r.get("rel_volume", 0) for r in rows]), 4),
                "avg_2d": round(avg([r["ret_2d"] for r in rows]), 4),
                "hit_2d": round(avg([1 if ((r["score"] > 0 and r["ret_2d"] > 0) or (r["score"] < 0 and r["ret_2d"] < 0)) else 0 for r in rows]), 4),
                "avg_5d": round(avg([r["ret_5d"] for r in rows]), 4),
                "hit_5d": round(avg([1 if ((r["score"] > 0 and r["ret_5d"] > 0) or (r["score"] < 0 and r["ret_5d"] < 0)) else 0 for r in rows]), 4),
            })


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


def rsi_series(values, period):
    out = [50] * len(values)
    if len(values) <= period:
        return out
    gains = []
    losses = []
    for i in range(1, period + 1):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))
    avg_gain = avg(gains)
    avg_loss = avg(losses)
    out[period] = 100 if avg_loss == 0 else 100 - (100 / (1 + (avg_gain / avg_loss)))
    for i in range(period + 1, len(values)):
        change = values[i] - values[i - 1]
        gain = max(change, 0)
        loss = abs(min(change, 0))
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
        out[i] = 100 if avg_loss == 0 else 100 - (100 / (1 + (avg_gain / avg_loss)))
    return out


def atr_series(rows, period):
    out = [0] * len(rows)
    true_ranges = []
    for i, row in enumerate(rows):
        previous_close = rows[i - 1]["close"] if i else row["close"]
        true_range = max(row["high"] - row["low"], abs(row["high"] - previous_close), abs(row["low"] - previous_close))
        true_ranges.append(true_range)
        if i >= period:
            out[i] = avg(true_ranges[i - period + 1:i + 1])
    return out


if __name__ == "__main__":
    main()

"""Audit SMA and delivery behaviour around the five chart-derived examples."""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from server import connect, load_rows


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs"
SYMBOLS = ["EMCURE", "SAILIFE", "ASAHIINDIA", "SIMPLEXINF", "AFFORDABLE"]
SMA_PERIODS = [5, 7, 10, 15, 20, 30, 50, 60, 100, 200]
DELIVERY_PERIODS = [5, 10, 15, 20, 30, 50, 60]


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    detail_rows = []
    summary_rows = []

    with connect() as conn:
        for symbol in SYMBOLS:
            stock = conn.execute(
                "SELECT id FROM instruments WHERE exchange = 'NSE' AND symbol = ? ORDER BY id LIMIT 1",
                (symbol,),
            ).fetchone()
            if not stock:
                print(f"{symbol}: not found")
                continue
            rows = load_rows(conn, stock["id"])
            anchor = strongest_recent_move(rows, sessions=5, lookback=120)
            if anchor is None:
                continue
            gain, anchor_index = anchor
            start = max(200, anchor_index - 10)
            for index in range(start, anchor_index + 1):
                detail_rows.append(build_detail(symbol, rows, index, anchor_index, gain))
            summary_rows.append(build_summary(symbol, rows, anchor_index, gain))

    detail_path = OUTPUT_DIR / "pattern_examples_sma_delivery_detail.csv"
    summary_path = OUTPUT_DIR / "pattern_examples_sma_delivery_summary.csv"
    write_csv(detail_path, detail_rows)
    write_csv(summary_path, summary_rows)
    print_summary(summary_rows)
    print(f"\nCreated:\n{summary_path}\n{detail_path}")


def strongest_recent_move(rows, sessions, lookback):
    first = max(200, len(rows) - lookback)
    candidates = []
    for index in range(first, len(rows) - sessions):
        gain = percent(rows[index + sessions]["close"], rows[index]["close"])
        candidates.append((gain, index))
    return max(candidates) if candidates else None


def build_detail(symbol, rows, index, anchor_index, anchor_gain):
    current = rows[index]
    output = {
        "symbol": symbol,
        "trade_date": current["trade_date"],
        "sessions_before_move": anchor_index - index,
        "anchor_date": rows[anchor_index]["trade_date"],
        "anchor_5d_gain_pct": round(anchor_gain, 4),
        "close": current["close"],
        "delivery_pct": current.get("delivery_pct"),
        "deliverable_qty": current.get("deliverable_qty"),
    }
    closes = [row["close"] for row in rows]
    for period in SMA_PERIODS:
        value = average(closes[index - period + 1:index + 1])
        previous = average(closes[index - period - 2:index - 2])
        output[f"sma_{period}"] = round(value, 4)
        output[f"close_vs_sma_{period}_pct"] = round(percent(current["close"], value), 4)
        output[f"sma_{period}_slope_3d_pct"] = round(percent(value, previous), 4)
        output[f"crossed_above_sma_{period}_within_3d"] = crossed_above(rows, index, period, 3)
    delivery = [row.get("deliverable_qty") for row in rows]
    delivery_pct = [row.get("delivery_pct") for row in rows]
    for period in DELIVERY_PERIODS:
        qty_avg = average_available(delivery[index - period:index])
        pct_avg = average_available(delivery_pct[index - period:index])
        output[f"delivery_qty_vs_{period}d_avg"] = ratio(current.get("deliverable_qty"), qty_avg)
        output[f"delivery_pct_vs_{period}d_avg"] = ratio(current.get("delivery_pct"), pct_avg)
    return output


def build_summary(symbol, rows, index, gain):
    current = rows[index]
    closes = [row["close"] for row in rows]
    output = {
        "symbol": symbol,
        "move_start": current["trade_date"],
        "move_end": rows[index + 5]["trade_date"],
        "move_5d_pct": round(gain, 4),
        "close": current["close"],
        "delivery_available": current.get("deliverable_qty") is not None,
        "delivery_pct": current.get("delivery_pct"),
    }
    for period in SMA_PERIODS:
        value = average(closes[index - period + 1:index + 1])
        previous = average(closes[index - period - 2:index - 2])
        output[f"above_sma_{period}"] = current["close"] > value
        output[f"sma_{period}_rising"] = value > previous
        output[f"close_vs_sma_{period}_pct"] = round(percent(current["close"], value), 4)
    delivery = [row.get("deliverable_qty") for row in rows]
    delivery_pct = [row.get("delivery_pct") for row in rows]
    for period in DELIVERY_PERIODS:
        output[f"delivery_qty_vs_{period}d_avg"] = ratio(
            current.get("deliverable_qty"), average_available(delivery[index - period:index])
        )
        output[f"delivery_pct_vs_{period}d_avg"] = ratio(
            current.get("delivery_pct"), average_available(delivery_pct[index - period:index])
        )
    return output


def crossed_above(rows, index, period, lookback):
    closes = [row["close"] for row in rows]
    for point in range(max(period, index - lookback + 1), index + 1):
        current_sma = average(closes[point - period + 1:point + 1])
        previous_sma = average(closes[point - period:point])
        if closes[point] > current_sma and closes[point - 1] <= previous_sma:
            return True
    return False


def average(values):
    return sum(values) / len(values) if values else 0


def average_available(values):
    available = [value for value in values if value is not None]
    return average(available) if available else None


def ratio(value, baseline):
    if value is None or baseline in (None, 0):
        return None
    return round(value / baseline, 4)


def percent(value, baseline):
    return ((value / baseline) - 1) * 100 if baseline else 0


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows):
    print("Five-stock SMA and delivery audit")
    for row in rows:
        above = [str(period) for period in SMA_PERIODS if row[f"above_sma_{period}"]]
        rising = [str(period) for period in SMA_PERIODS if row[f"sma_{period}_rising"]]
        delivery = row.get("delivery_qty_vs_20d_avg")
        delivery_text = "unavailable" if delivery is None else f"{delivery:.2f}x 20D"
        print(
            f"{row['symbol']}: {row['move_start']} to {row['move_end']} {row['move_5d_pct']:+.2f}% | "
            f"above SMA {','.join(above) or '-'} | rising SMA {','.join(rising) or '-'} | "
            f"delivery qty {delivery_text}"
        )


if __name__ == "__main__":
    main()

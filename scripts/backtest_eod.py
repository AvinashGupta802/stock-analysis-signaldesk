import argparse
import csv
import sqlite3
from collections import defaultdict
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Run EOD signal backtest on imported SQLite data.")
    parser.add_argument("--db", default="data/stock_analysis.sqlite3")
    parser.add_argument("--from-date", default="2020-01-01")
    parser.add_argument("--to-date", default="2023-11-01")
    parser.add_argument("--min-price", type=float, default=20)
    parser.add_argument("--min-volume", type=int, default=10000)
    parser.add_argument("--threshold", type=int, default=5)
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--output", default="outputs/backtest_summary.csv")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    stocks = conn.execute("SELECT id, symbol FROM stocks ORDER BY symbol").fetchall()

    all_results = []
    by_symbol = defaultdict(list)
    processed = 0

    for stock_id, symbol in stocks:
      rows = load_rows(conn, stock_id)
      if len(rows) < 30:
          continue
      results = evaluate_symbol(symbol, rows, args)
      all_results.extend(results)
      by_symbol[symbol].extend(results)
      processed += 1
      if processed % 250 == 0:
          print(f"Backtested {processed:,} stocks, {len(all_results):,} signals")

    conn.close()

    buys = [row for row in all_results if row["score"] > 0]
    sells = [row for row in all_results if row["score"] < 0]
    strong_buys = [row for row in all_results if row["score"] >= args.threshold]
    strong_sells = [row for row in all_results if row["score"] <= -args.threshold]

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_symbol_summary(output_path, by_symbol)

    print("Backtest complete")
    print(f"Stocks processed: {processed:,}")
    print(f"All evaluated stock-days: {len(all_results):,}")
    print_summary("Buy signals", buys)
    print_summary("Strong buy signals", strong_buys)
    print_summary("Sell signals", sells, inverse=True)
    print_summary("Strong sell signals", strong_sells, inverse=True)
    print(f"Symbol summary CSV: {output_path}")


def load_rows(conn, stock_id):
    conn.row_factory = sqlite3.Row
    return conn.execute(
        """
        SELECT trade_date, open, high, low, close, volume, dividends, stock_splits
        FROM daily_prices
        WHERE stock_id = ?
        ORDER BY trade_date
        """,
        (stock_id,),
    ).fetchall()


def evaluate_symbol(symbol, rows, args):
    results = []
    closes = [row["close"] for row in rows]
    highs = [row["high"] for row in rows]
    volumes = [row["volume"] for row in rows]

    for index in range(20, len(rows) - 5):
        row = rows[index]
        trade_date = row["trade_date"]
        if trade_date < args.from_date or trade_date > args.to_date:
            continue
        if row["close"] < args.min_price or row["volume"] < args.min_volume:
            continue

        score, buy_rules, sell_rules = score_day(index, closes, highs, volumes)
        if score == 0:
            continue

        next_close_return = pct(rows[index + 1]["close"], row["close"])
        three_day_return = pct(rows[index + 3]["close"], row["close"])
        five_day_return = pct(rows[index + 5]["close"], row["close"])
        max_upside = pct(max(r["high"] for r in rows[index + 1 : index + 6]), row["close"])
        max_drawdown = pct(min(r["low"] for r in rows[index + 1 : index + 6]), row["close"])

        results.append(
            {
                "symbol": symbol,
                "date": trade_date,
                "score": score,
                "buy_rules": buy_rules,
                "sell_rules": sell_rules,
                "next_close_return": next_close_return,
                "three_day_return": three_day_return,
                "five_day_return": five_day_return,
                "max_upside": max_upside,
                "max_drawdown": max_drawdown,
            }
        )
    return results


def score_day(index, closes, highs, volumes):
    score = 0
    buy_rules = 0
    sell_rules = 0

    def add(signal, weight):
        nonlocal score, buy_rules, sell_rules
        if signal > 0:
            score += weight
            buy_rules += 1
        elif signal < 0:
            score -= weight
            sell_rules += 1

    close = closes[index]
    prev_close = closes[index - 1]
    avg5 = avg(closes[index - 5 : index])
    avg20 = avg(closes[index - 20 : index])
    volume_avg5 = avg(volumes[index - 5 : index])
    recent_high = max(highs[index - 9 : index + 1])
    change3 = pct(close, closes[index - 3])
    day_change = pct(close, prev_close)

    add(1 if close > avg5 else -1, 2)
    add(1 if close > avg20 else -1, 2)
    add(1 if change3 > 1.2 else -1 if change3 < -1.2 else 0, 2)
    add(1 if volumes[index] > volume_avg5 * 1.08 else -1 if volumes[index] < volume_avg5 * 0.92 else 0, 1)
    add(1 if pct(close, recent_high) > -1.4 else 0, 2)
    add(-1 if day_change < -1.6 else 1 if day_change > 0.7 else 0, 2)

    return score, buy_rules, sell_rules


def print_summary(label, rows, inverse=False):
    if not rows:
        print(f"{label}: none")
        return
    hit = sum(1 for row in rows if is_hit(row, inverse)) / len(rows)
    print(
        f"{label}: {len(rows):,} | "
        f"hit {hit:.1%} | "
        f"next {avg([r['next_close_return'] for r in rows]):.2f}% | "
        f"3d {avg([r['three_day_return'] for r in rows]):.2f}% | "
        f"5d {avg([r['five_day_return'] for r in rows]):.2f}% | "
        f"max up {avg([r['max_upside'] for r in rows]):.2f}% | "
        f"max dd {avg([r['max_drawdown'] for r in rows]):.2f}%"
    )


def write_symbol_summary(path, by_symbol):
    rows = []
    for symbol, results in by_symbol.items():
        strong_buys = [row for row in results if row["score"] >= 5]
        if len(strong_buys) < 20:
            continue
        rows.append(
            {
                "symbol": symbol,
                "strong_buy_count": len(strong_buys),
                "hit_rate": sum(1 for row in strong_buys if row["next_close_return"] > 0) / len(strong_buys),
                "avg_next_close_return": avg([row["next_close_return"] for row in strong_buys]),
                "avg_3d_return": avg([row["three_day_return"] for row in strong_buys]),
                "avg_5d_return": avg([row["five_day_return"] for row in strong_buys]),
                "avg_max_upside": avg([row["max_upside"] for row in strong_buys]),
                "avg_max_drawdown": avg([row["max_drawdown"] for row in strong_buys]),
            }
        )
    rows.sort(key=lambda row: (row["hit_rate"], row["avg_next_close_return"]), reverse=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else ["symbol"])
        writer.writeheader()
        writer.writerows(rows)


def is_hit(row, inverse):
    return row["next_close_return"] < 0 if inverse else row["next_close_return"] > 0


def pct(value, base):
    return ((value - base) / base) * 100


def avg(values):
    return sum(values) / len(values) if values else 0


if __name__ == "__main__":
    main()

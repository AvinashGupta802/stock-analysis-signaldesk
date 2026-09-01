import argparse
import csv
import sqlite3
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "stock_analysis_exchange.sqlite3"
OUTPUT_PATH = ROOT / "outputs" / "delivery_volume_matrix.csv"


def main():
    parser = argparse.ArgumentParser(description="Sweep short swing rule combinations.")
    parser.add_argument("--from-date", default="2026-06-01")
    parser.add_argument("--to-date", default="2026-08-24")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--capital", type=float, default=10_000)
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    args = parser.parse_args()

    rows_by_symbol = load_rows()
    candidates_by_date = build_candidates(rows_by_symbol, args.from_date, args.to_date, max_hold_days=10)

    relative_volumes = [1.2, 1.5, 2.0]
    delivery_pcts = [40, 50, 60]
    target_stops = [(3, 3), (5, 3), (5, 5), (7, 5), (10, 5)]
    hold_days = [3, 5, 7, 10]

    results = []
    for min_rvol in relative_volumes:
        for min_delivery in delivery_pcts:
            for target_pct, stop_pct in target_stops:
                for hold_days_value in hold_days:
                    filtered = filter_candidates(candidates_by_date, min_rvol, min_delivery)
                    trades = simulate_trades(
                        filtered,
                        rows_by_symbol,
                        args.top_n,
                        args.capital,
                        target_pct,
                        stop_pct,
                        hold_days_value,
                    )
                    summary = summarize(trades, args.capital)
                    results.append({
                        "min_relative_volume": min_rvol,
                        "min_delivery_pct": min_delivery,
                        "target_pct": target_pct,
                        "stop_pct": stop_pct,
                        "max_hold_days": hold_days_value,
                        "total_signals": sum(len(items) for items in filtered.values()),
                        "signal_days": len(filtered),
                        **summary,
                    })

    results.sort(key=lambda row: (row["return_on_turnover_pct"], row["net_pnl"]), reverse=True)
    write_results(Path(args.output), results)
    print(f"Wrote {len(results)} combinations to {args.output}")
    print("Top 15 combinations")
    for row in results[:15]:
        print(
            f"rvol>={row['min_relative_volume']}x delivery>={row['min_delivery_pct']}% "
            f"target/stop={row['target_pct']}/{row['stop_pct']} hold={row['max_hold_days']}d "
            f"trades={row['trades']} pnl={row['net_pnl']:.2f} "
            f"ret={row['return_on_turnover_pct']:.2f}% win={row['win_rate_pct']:.2f}% "
            f"target={row['target_hit_pct']:.2f}% stop={row['stop_hit_pct']:.2f}%"
        )


def load_rows():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT
          i.symbol,
          p.trade_date,
          p.open,
          p.high,
          p.low,
          p.close,
          p.volume,
          d.deliverable_qty,
          d.delivery_pct
        FROM instruments i
        JOIN daily_prices p ON p.instrument_id = i.id
        LEFT JOIN daily_delivery d
          ON d.instrument_id = i.id
         AND d.trade_date = p.trade_date
        WHERE i.exchange = 'NSE'
          AND i.series = 'EQ'
        ORDER BY i.symbol, p.trade_date
        """
    ).fetchall()
    conn.close()

    grouped = defaultdict(list)
    for row in rows:
        grouped[row["symbol"]].append(dict(row))
    return grouped


def build_candidates(rows_by_symbol, from_date, to_date, max_hold_days):
    candidates_by_date = defaultdict(list)
    for symbol, rows in rows_by_symbol.items():
        if len(rows) < 30:
            continue
        volumes = [row["volume"] for row in rows]
        for index in range(21, len(rows) - max_hold_days - 1):
            row = rows[index]
            if row["trade_date"] < from_date or row["trade_date"] > to_date:
                continue
            adv20 = avg(volumes[index - 20:index])
            relative_volume = row["volume"] / adv20 if adv20 else 0
            delivery_pct = row["delivery_pct"]
            if not (100 <= row["close"] <= 500) or delivery_pct is None:
                continue
            candidates_by_date[row["trade_date"]].append({
                "symbol": symbol,
                "index": index,
                "volume": row["volume"],
                "relative_volume": relative_volume,
                "delivery_pct": delivery_pct,
            })
    return candidates_by_date


def filter_candidates(candidates_by_date, min_rvol, min_delivery):
    filtered = {}
    for trade_date, candidates in candidates_by_date.items():
        items = [
            item for item in candidates
            if item["relative_volume"] >= min_rvol and item["delivery_pct"] >= min_delivery
        ]
        if items:
            filtered[trade_date] = items
    return filtered


def simulate_trades(candidates_by_date, rows_by_symbol, top_n, capital, target_pct, stop_pct, max_hold_days):
    trades = []
    for signal_date in sorted(candidates_by_date):
        picks = sorted(candidates_by_date[signal_date], key=lambda row: (row["volume"], row["symbol"]), reverse=True)[:top_n]
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
                "return_pct": pct(exit_price, entry_price),
                "pnl": pnl,
                "exit_reason": exit_reason,
            })
    return trades


def summarize(trades, capital):
    invested = len(trades) * capital
    pnl = sum(trade["pnl"] for trade in trades)
    return {
        "trades": len(trades),
        "invested_turnover": invested,
        "net_pnl": pnl,
        "return_on_turnover_pct": (pnl / invested) * 100 if invested else 0,
        "avg_trade_return_pct": avg([trade["return_pct"] for trade in trades]),
        "win_rate_pct": avg([1 if trade["pnl"] > 0 else 0 for trade in trades]) * 100,
        "target_hit_pct": avg([1 if trade["exit_reason"] == "target" else 0 for trade in trades]) * 100,
        "stop_hit_pct": avg([1 if trade["exit_reason"] == "stop" else 0 for trade in trades]) * 100,
    }


def write_results(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def pct(value, base):
    return ((value - base) / base) * 100 if base else 0


def avg(values):
    return sum(values) / len(values) if values else 0


if __name__ == "__main__":
    main()

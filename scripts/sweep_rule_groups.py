import argparse
import csv
import sqlite3
from collections import defaultdict
from itertools import product
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "stock_analysis_exchange.sqlite3"
OUTPUT_PATH = ROOT / "outputs" / "rule_group_sweep.csv"

EXCLUDED_SYMBOL_PARTS = (
    "BEES",
    "ETF",
    "LIQUID",
    "GOLD",
    "SILVER",
    "GILT",
)
EXCLUDED_NAME_PARTS = (
    " ETF",
    "EXCHANGE TRADED",
    "LIQUID",
    "GOLD",
    "SILVER",
    "MUTUAL FUND",
)


def main():
    parser = argparse.ArgumentParser(description="Sweep named buy-rule groups on NSE EOD data.")
    parser.add_argument("--from-date", default="2026-06-01")
    parser.add_argument("--to-date", default="2026-08-24")
    parser.add_argument("--capital", type=float, default=10_000)
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    args = parser.parse_args()

    rows_by_symbol = load_rows()
    candidates_by_date = build_candidates(rows_by_symbol, args.from_date, args.to_date, max_hold_days=15)
    rule_groups = build_rule_groups()
    exits = list(product([5, 7, 10, 15], [(5, 3), (5, 5), (7, 5), (10, 5), (10, 7)], [5, 10]))

    results = []
    for group_name, configs in rule_groups.items():
        for config in configs:
            filtered = filter_candidates(candidates_by_date, config)
            if not filtered:
                continue
            total_signals = sum(len(items) for items in filtered.values())
            for hold_days, (target_pct, stop_pct), top_n in exits:
                trades = simulate_trades(filtered, rows_by_symbol, top_n, args.capital, target_pct, stop_pct, hold_days)
                if not trades:
                    continue
                results.append({
                    "rule_group": group_name,
                    **config,
                    "top_n": top_n,
                    "target_pct": target_pct,
                    "stop_pct": stop_pct,
                    "max_hold_days": hold_days,
                    "total_signals": total_signals,
                    "signal_days": len(filtered),
                    **summarize(trades, args.capital),
                })

    results.sort(key=lambda row: (row["return_on_turnover_pct"], row["net_pnl"]), reverse=True)
    write_results(Path(args.output), results)
    print(f"Wrote {len(results):,} rule runs to {args.output}")
    print_best(results)
    print_group_leaders(results)


def build_rule_groups():
    rvols = [1.2, 1.5, 2.0, 3.0]
    delivery_pcts = [40, 50, 60, 70]
    rel_deliveries = [1.0, 1.2, 1.5, 2.0]
    momentum_ranges = [(-2, 8), (0, 8), (0, 12), (1, 10), (2, 12)]
    obv_configs = [(0.5, 1), (0.5, 2), (1.0, 2), (1.5, 2), (1.0, 3)]

    return {
        "volume_delivery_core": [
            config(min_rvol=rvol, min_delivery_pct=delivery)
            for rvol, delivery in product(rvols, delivery_pcts)
        ],
        "relative_delivery_confirmation": [
            config(min_rvol=rvol, min_delivery_pct=delivery, min_relative_delivery=rel_delivery)
            for rvol, delivery, rel_delivery in product(rvols, delivery_pcts, rel_deliveries)
        ],
        "momentum_continuation": [
            config(min_rvol=rvol, min_delivery_pct=delivery, momentum_min=momentum_min, momentum_max=momentum_max)
            for rvol, delivery, (momentum_min, momentum_max) in product(rvols, delivery_pcts, momentum_ranges)
        ],
        "obv_consolidation": [
            config(min_delivery_pct=delivery, min_obv_3d=obv_min, max_abs_momentum_3d=max_abs_momentum)
            for delivery, (obv_min, max_abs_momentum) in product(delivery_pcts, obv_configs)
        ],
        "volume_delivery_obv": [
            config(
                min_rvol=rvol,
                min_delivery_pct=delivery,
                min_obv_3d=obv_min,
                max_abs_momentum_3d=max_abs_momentum,
            )
            for rvol, delivery, (obv_min, max_abs_momentum) in product(rvols, delivery_pcts, obv_configs)
        ],
        "full_confirmation": [
            config(
                min_rvol=rvol,
                min_delivery_pct=delivery,
                min_relative_delivery=rel_delivery,
                momentum_min=momentum_min,
                momentum_max=momentum_max,
            )
            for rvol, delivery, rel_delivery, (momentum_min, momentum_max) in product(
                [1.5, 2.0],
                [50, 60],
                [1.2, 1.5],
                [(0, 12), (1, 10), (2, 12)],
            )
        ],
    }


def config(
    min_rvol=None,
    min_delivery_pct=None,
    min_relative_delivery=None,
    momentum_min=None,
    momentum_max=None,
    min_obv_3d=None,
    max_abs_momentum_3d=None,
):
    return {
        "min_relative_volume": min_rvol,
        "min_delivery_pct": min_delivery_pct,
        "min_relative_delivery": min_relative_delivery,
        "momentum_min": momentum_min,
        "momentum_max": momentum_max,
        "min_obv_3d": min_obv_3d,
        "max_abs_momentum_3d": max_abs_momentum_3d,
    }


def load_rows():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT
          i.symbol,
          COALESCE(i.name, i.symbol) AS name,
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
        if is_excluded_symbol(row["symbol"], row["name"]):
            continue
        grouped[row["symbol"]].append(dict(row))
    return grouped


def is_excluded_symbol(symbol, name):
    symbol_text = str(symbol or "").upper()
    name_text = str(name or "").upper()
    return any(part in symbol_text for part in EXCLUDED_SYMBOL_PARTS) or any(part in name_text for part in EXCLUDED_NAME_PARTS)


def build_candidates(rows_by_symbol, from_date, to_date, max_hold_days):
    candidates_by_date = defaultdict(list)
    for symbol, rows in rows_by_symbol.items():
        if len(rows) < 45:
            continue
        closes = [row["close"] for row in rows]
        volumes = [row["volume"] for row in rows]
        delivery_quantities = [row.get("deliverable_qty") for row in rows]
        obv = obv_series(closes, volumes)
        for index in range(21, len(rows) - max_hold_days - 1):
            row = rows[index]
            if row["trade_date"] < from_date or row["trade_date"] > to_date:
                continue
            delivery_pct = row["delivery_pct"]
            deliverable_qty = row.get("deliverable_qty")
            adv20 = avg(volumes[index - 20:index])
            avg_delivery20 = avg_available(delivery_quantities[index - 20:index])
            if not (100 <= row["close"] <= 500) or delivery_pct is None or deliverable_qty is None:
                continue
            candidates_by_date[row["trade_date"]].append({
                "symbol": symbol,
                "index": index,
                "volume": row["volume"],
                "relative_volume": row["volume"] / adv20 if adv20 else 0,
                "delivery_pct": delivery_pct,
                "relative_delivery": deliverable_qty / avg_delivery20 if avg_delivery20 else 0,
                "momentum_3d": pct(closes[index], closes[index - 3]) if index >= 3 else 0,
                "obv_3d": (obv[index] - obv[index - 3]) / adv20 if index >= 3 and adv20 else 0,
            })
    return candidates_by_date


def filter_candidates(candidates_by_date, cfg):
    filtered = {}
    for trade_date, candidates in candidates_by_date.items():
        items = [item for item in candidates if passes_config(item, cfg)]
        if items:
            filtered[trade_date] = items
    return filtered


def passes_config(item, cfg):
    if cfg["min_relative_volume"] is not None and item["relative_volume"] < cfg["min_relative_volume"]:
        return False
    if cfg["min_delivery_pct"] is not None and item["delivery_pct"] < cfg["min_delivery_pct"]:
        return False
    if cfg["min_relative_delivery"] is not None and item["relative_delivery"] < cfg["min_relative_delivery"]:
        return False
    if cfg["momentum_min"] is not None and item["momentum_3d"] < cfg["momentum_min"]:
        return False
    if cfg["momentum_max"] is not None and item["momentum_3d"] > cfg["momentum_max"]:
        return False
    if cfg["min_obv_3d"] is not None and item["obv_3d"] < cfg["min_obv_3d"]:
        return False
    if cfg["max_abs_momentum_3d"] is not None and abs(item["momentum_3d"]) > cfg["max_abs_momentum_3d"]:
        return False
    return True


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


def print_best(results):
    print("Top 20 rule runs")
    for row in results[:20]:
        print(format_row(row))


def print_group_leaders(results):
    print("\nBest run by rule group")
    for group_name in sorted({row["rule_group"] for row in results}):
        best = max((row for row in results if row["rule_group"] == group_name), key=lambda row: row["return_on_turnover_pct"])
        print(format_row(best))


def format_row(row):
    return (
        f"{row['rule_group']} | top={row['top_n']:.0f} target/stop={row['target_pct']:.0f}/{row['stop_pct']:.0f} "
        f"hold={row['max_hold_days']:.0f}d trades={row['trades']:.0f} pnl={row['net_pnl']:.2f} "
        f"ret={row['return_on_turnover_pct']:.2f}% win={row['win_rate_pct']:.2f}% "
        f"target={row['target_hit_pct']:.2f}% stop={row['stop_hit_pct']:.2f}% | "
        f"rvol={show(row['min_relative_volume'])} del%={show(row['min_delivery_pct'])} "
        f"reldel={show(row['min_relative_delivery'])} mom={show_range(row['momentum_min'], row['momentum_max'])} "
        f"obv={show(row['min_obv_3d'])} absMom={show(row['max_abs_momentum_3d'])}"
    )


def show(value):
    return "-" if value is None else f"{value:g}"


def show_range(low, high):
    return "-" if low is None or high is None else f"{low:g}..{high:g}"


def pct(value, base):
    return ((value - base) / base) * 100 if base else 0


def avg(values):
    return sum(values) / len(values) if values else 0


def avg_available(values):
    filtered = [value for value in values if value is not None]
    return avg(filtered)


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
    main()

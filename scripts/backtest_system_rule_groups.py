import csv
from pathlib import Path

from server import backtest_rule_group


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs"


def momentum_values(**overrides):
    values = {
        "useMomentum1W": False,
        "minMomentum1W": 0,
        "maxMomentum1W": 15,
        "useMomentum15D": False,
        "minMomentum15D": 2,
        "maxMomentum15D": 25,
        "useMomentum1M": False,
        "minMomentum1M": 5,
        "maxMomentum1M": 30,
        "useMomentum3M": False,
        "minMomentum3M": 10,
        "maxMomentum3M": 60,
        "useMomentum6M": False,
        "minMomentum6M": 15,
        "maxMomentum6M": 120,
        "useMomentum1Y": False,
        "minMomentum1Y": 20,
        "maxMomentum1Y": 250,
        "useMomentum6MTo12M": False,
        "minMomentum6MTo12M": -20,
        "maxMomentum6MTo12M": 80,
    }
    values.update(overrides)
    return values


RULES = [
    {
        "id": "rule_volume_delivery_core",
        "name": "Volume Delivery Core",
        "filters": [
            {"id": "relative_volume", "values": {"minRelativeVolume": 1.5, "maxRelativeVolume": 999}},
            {"id": "delivery_pct_range", "values": {"minDeliveryPct": 60, "maxDeliveryPct": 100}},
        ],
    },
    {
        "id": "rule_breakout_trend_quality",
        "name": "Breakout Trend Quality",
        "filters": [
            {"id": "close_near_20d_high", "values": {"maxDistanceFrom20DHigh": 2}},
            {"id": "ema_trend", "values": {"minEmaTrendChecks": 3}},
            {"id": "atr_risk", "values": {"minAtrPct": 0, "maxAtrPct": 8}},
        ],
    },
    {
        "id": "rule_delivery_accumulation",
        "name": "Delivery Accumulation",
        "filters": [
            {"id": "delivery_pct_range", "values": {"minDeliveryPct": 60, "maxDeliveryPct": 100}},
            {"id": "relative_delivery_qty", "values": {"minRelativeDelivery": 1.5, "maxRelativeDelivery": 999}},
        ],
    },
    {
        "id": "rule_obv_consolidation",
        "name": "OBV Consolidation Breakout",
        "filters": [
            {"id": "range_compression_10d", "values": {"minCompression10D": 0, "maxCompression10D": 12}},
            {"id": "obv_accumulation_3d", "values": {"minObv3D": 0.5, "maxAbsMomentum3D": 2}},
            {"id": "atr_risk", "values": {"minAtrPct": 0, "maxAtrPct": 8}},
        ],
    },
    {
        "id": "rule_momentum_controlled",
        "name": "Momentum Controlled",
        "filters": [
            {"id": "price_momentum_3d", "values": {"minMomentum3D": 2, "maxMomentum3D": 8}},
            {"id": "rsi14_range", "values": {"rsiMin": 50, "rsiMax": 68}},
            {"id": "atr_risk", "values": {"minAtrPct": 0, "maxAtrPct": 8}},
        ],
    },
    {
        "id": "rule_multi_period_trend",
        "name": "Multi-Period Trend",
        "filters": [
            {"id": "multi_period_momentum", "values": momentum_values(useMomentum15D=True, useMomentum3M=True)},
            {"id": "atr_risk", "values": {"minAtrPct": 0, "maxAtrPct": 8}},
        ],
    },
    {
        "id": "rule_quiet_trend_compression",
        "name": "Quiet Trend Compression",
        "filters": [
            {"id": "range_compression_10d", "values": {"minCompression10D": 0, "maxCompression10D": 12}},
            {"id": "close_near_20d_high", "values": {"maxDistanceFrom20DHigh": 3}},
            {"id": "ema_trend", "values": {"minEmaTrendChecks": 3}},
            {"id": "atr_risk", "values": {"minAtrPct": 3, "maxAtrPct": 6}},
            {"id": "rsi14_range", "values": {"rsiMin": 50, "rsiMax": 68}},
            {"id": "obv_accumulation_3d", "values": {"minObv3D": 0.5, "maxAbsMomentum3D": 8}},
        ],
    },
    {
        "id": "rule_discovered_high_rsi_long_momentum_delivery",
        "name": "Discovered: High RSI Long Momentum Delivery",
        "filters": [
            {"id": "rsi14_range", "values": {"rsiMin": 70, "rsiMax": 100}},
            {"id": "multi_period_momentum", "values": momentum_values(useMomentum3M=True, useMomentum6M=True)},
            {"id": "delivery_pct_range", "values": {"minDeliveryPct": 40, "maxDeliveryPct": 100}},
        ],
    },
    {
        "id": "rule_discovered_long_momentum_cci_delivery",
        "name": "Discovered: Long Momentum CCI Delivery",
        "filters": [
            {"id": "multi_period_momentum", "values": momentum_values(useMomentum15D=True, useMomentum1Y=True)},
            {"id": "delivery_pct_range", "values": {"minDeliveryPct": 40, "maxDeliveryPct": 100}},
            {"id": "cci14_strong_trend", "values": {"minCci14": 200, "maxCci14": 999}},
        ],
    },
    {
        "id": "rule_discovered_52w_volume_rsi",
        "name": "Discovered: 52W High Volume RSI",
        "filters": [
            {"id": "range_position_52w", "values": {"minRangePosition52W": 70, "maxRangePosition52W": 100}},
            {"id": "relative_volume", "values": {"minRelativeVolume": 1.5, "maxRelativeVolume": 999}},
            {"id": "rsi14_range", "values": {"rsiMin": 60, "rsiMax": 80}},
        ],
    },
    {
        "id": "rule_discovered_pause_breakout_volume",
        "name": "Discovered: Pause Breakout Volume",
        "filters": [
            {"id": "price_change_1d", "values": {"minPriceChange1D": 5, "maxPriceChange1D": 999}},
            {"id": "price_momentum_3d", "values": {"minMomentum3D": -3, "maxMomentum3D": 3}},
            {"id": "relative_volume", "values": {"minRelativeVolume": 3, "maxRelativeVolume": 999}},
        ],
    },
    {
        "id": "rule_deep_compression_ema_launch",
        "name": "Deep: Compression EMA Launch",
        "filters": [
            {"id": "price_change_1d", "values": {"minPriceChange1D": 5, "maxPriceChange1D": 999}},
            {"id": "range_compression_10d", "values": {"minCompression10D": 0, "maxCompression10D": 8}},
            {"id": "ema_trend", "values": {"minEmaTrendChecks": 3}},
        ],
    },
    {
        "id": "rule_deep_10d_volume_near_high",
        "name": "Deep: 10D Volume Near High",
        "filters": [
            {"id": "relative_volume_10d", "values": {"minRelativeVolume10D": 3, "maxRelativeVolume10D": 999}},
            {"id": "price_momentum_3d", "values": {"minMomentum3D": -3, "maxMomentum3D": 3}},
            {"id": "range_position_52w", "values": {"minRangePosition52W": 80, "maxRangePosition52W": 100}},
        ],
    },
    {
        "id": "rule_deep_mfi_cci_long_momentum",
        "name": "Deep: MFI CCI Long Momentum",
        "filters": [
            {"id": "multi_period_momentum", "values": momentum_values(useMomentum15D=True, useMomentum1Y=True)},
            {"id": "mfi14_range", "values": {"mfiMin": 40, "mfiMax": 70}},
            {"id": "cci14_strong_trend", "values": {"minCci14": 200, "maxCci14": 999}},
        ],
    },
    {
        "id": "rule_screenshot_momentum_proxy",
        "name": "Screenshot: Momentum Stocks Proxy",
        "filters": [
            {"id": "price_change_1d", "values": {"minPriceChange1D": 5, "maxPriceChange1D": 999}},
            {"id": "rsi14_range", "values": {"rsiMin": 70, "rsiMax": 100}},
            {"id": "rsi14_rising", "values": {"minRsiRise": 0}},
            {"id": "daily_volume_range", "values": {"minDailyVolume": 20000, "maxDailyVolume": 999999999}},
            {"id": "ema10_above_ema20", "values": {"minEmaGapPct": 0}},
            {"id": "cci14_strong_trend", "values": {"minCci14": 200, "maxCci14": 999}},
        ],
    },
    {
        "id": "rule_delivery_atr_accumulation",
        "name": "Delivery ATR Accumulation",
        "filters": [
            {"id": "delivery_pct_range", "values": {"minDeliveryPct": 70, "maxDeliveryPct": 100}},
            {"id": "atr_risk", "values": {"minAtrPct": 3, "maxAtrPct": 8}},
            {"id": "relative_delivery_qty", "values": {"minRelativeDelivery": 2, "maxRelativeDelivery": 999}},
        ],
    },
    {
        "id": "rule_delivery_mfi_strength",
        "name": "Delivery MFI Strength",
        "filters": [
            {"id": "delivery_pct_range", "values": {"minDeliveryPct": 70, "maxDeliveryPct": 100}},
            {"id": "atr_risk", "values": {"minAtrPct": 3, "maxAtrPct": 8}},
            {"id": "mfi14_range", "values": {"mfiMin": 40, "mfiMax": 70}},
        ],
    },
    {
        "id": "rule_delivery_volume_breakout",
        "name": "Delivery Volume Breakout",
        "filters": [
            {"id": "delivery_pct_range", "values": {"minDeliveryPct": 50, "maxDeliveryPct": 100}},
            {"id": "relative_volume", "values": {"minRelativeVolume": 3, "maxRelativeVolume": 999}},
            {"id": "range_position_52w", "values": {"minRangePosition52W": 60, "maxRangePosition52W": 100}},
        ],
    },
    {
        "id": "rule_delivery_momentum_confirmation",
        "name": "Delivery Momentum Confirmation",
        "filters": [
            {"id": "relative_delivery_qty", "values": {"minRelativeDelivery": 1.5, "maxRelativeDelivery": 999}},
            {"id": "multi_period_momentum", "values": momentum_values(useMomentum3M=True, useMomentum6M=True)},
            {"id": "delivery_pct_range", "values": {"minDeliveryPct": 70, "maxDeliveryPct": 100}},
        ],
    },
    {
        "id": "rule_pause_breakout_confirmation",
        "name": "Pause Breakout Confirmation",
        "filters": [
            {"id": "relative_volume", "values": {"minRelativeVolume": 3, "maxRelativeVolume": 999}},
            {"id": "close_near_20d_high", "values": {"maxDistanceFrom20DHigh": 2}},
            {"id": "price_momentum_3d", "values": {"minMomentum3D": -3, "maxMomentum3D": 3}},
        ],
    },
    {
        "id": "rule_obv_macd_volume_accumulation",
        "name": "OBV MACD Volume Accumulation",
        "filters": [
            {"id": "obv_accumulation_3d", "values": {"minObv3D": 1, "maxAbsMomentum3D": 2}},
            {"id": "macd_bullish_momentum", "values": {"minMacdLine": 0, "minMacdHistogram": 0, "minMacdHistogramChange": 0}},
            {"id": "relative_volume_10d", "values": {"minRelativeVolume10D": 3, "maxRelativeVolume10D": 999}},
        ],
    },
]

RULE_BY_ID = {rule["id"]: rule for rule in RULES}

GROUPS = [
    ("group_core_agreement", "Core Agreement", 2, ["rule_volume_delivery_core", "rule_breakout_trend_quality"]),
    ("group_swing_quality", "Swing Quality Basket", 2, ["rule_volume_delivery_core", "rule_breakout_trend_quality", "rule_delivery_accumulation", "rule_momentum_controlled", "rule_multi_period_trend"]),
    ("group_breakout_watch", "Breakout Watch", 2, ["rule_breakout_trend_quality", "rule_obv_consolidation", "rule_momentum_controlled"]),
    ("group_quiet_trend_watch", "Quiet Trend Watch", 1, ["rule_quiet_trend_compression"]),
    ("group_discovered_trend_strength", "Discovered: Trend Strength Group", 1, ["rule_discovered_high_rsi_long_momentum_delivery", "rule_discovered_52w_volume_rsi"]),
    ("group_discovered_strict_trend_agreement", "Discovered: Strict Trend Agreement", 2, ["rule_discovered_high_rsi_long_momentum_delivery", "rule_discovered_52w_volume_rsi"]),
    ("group_discovered_momentum_burst", "Discovered: Momentum Burst Group", 1, ["rule_discovered_long_momentum_cci_delivery", "rule_discovered_pause_breakout_volume"]),
    ("group_discovered_high_conviction_swing", "Discovered: High Conviction Swing", 2, ["rule_discovered_high_rsi_long_momentum_delivery", "rule_discovered_long_momentum_cci_delivery", "rule_discovered_52w_volume_rsi"]),
    ("group_deep_compression_breakout", "Deep: Compression Breakout Group", 1, ["rule_deep_compression_ema_launch", "rule_deep_10d_volume_near_high"]),
    ("group_deep_mfi_momentum", "Deep: MFI Momentum Group", 1, ["rule_deep_mfi_cci_long_momentum", "rule_discovered_long_momentum_cci_delivery"]),
    ("group_deep_high_conviction_research", "Deep: High Conviction Research", 2, ["rule_deep_compression_ema_launch", "rule_deep_10d_volume_near_high", "rule_deep_mfi_cci_long_momentum"]),
    ("group_screenshot_momentum_proxy", "Screenshot: Momentum Stocks Proxy", 1, ["rule_screenshot_momentum_proxy"]),
    ("group_delivery_atr_accumulation", "Delivery ATR Accumulation", 1, ["rule_delivery_atr_accumulation"]),
    ("group_delivery_mfi_strength", "Delivery MFI Strength", 1, ["rule_delivery_mfi_strength"]),
    ("group_delivery_volume_breakout", "Delivery Volume Breakout", 1, ["rule_delivery_volume_breakout"]),
    ("group_delivery_momentum_confirmation", "Delivery Momentum Confirmation", 1, ["rule_delivery_momentum_confirmation"]),
    ("group_pause_breakout_confirmation", "Pause Breakout Confirmation", 1, ["rule_pause_breakout_confirmation"]),
    ("group_obv_macd_volume_accumulation", "OBV MACD Volume Accumulation", 1, ["rule_obv_macd_volume_accumulation"]),
]


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    out = OUTPUT_DIR / "system_rule_group_audit_20260908.csv"
    universes = ["all", "liquid", "nifty500"]
    holds = [2, 3, 5, 10, 15, 21]
    top_ns = [3, 5, 10]
    exits = [(10, 7), (12, 8), (15, 10)]
    rows = []
    for universe in universes:
        for group_id, group_name, min_matches, rule_ids in GROUPS:
            rules = [RULE_BY_ID[rule_id] for rule_id in rule_ids]
            for hold in holds:
                for top_n in top_ns:
                    for target, stop in exits:
                        result = backtest_rule_group(
                            {
                                "group": universe,
                                "rules": rules,
                                "minMatches": min_matches,
                                "fromDate": "2026-06-01",
                                "toDate": "2026-09-07",
                                "topN": top_n,
                                "capitalPerStock": 10000,
                                "targetPct": target,
                                "stopPct": stop,
                                "maxHoldDays": hold,
                            }
                        )
                        summary = result["summary"]
                        rows.append(
                            {
                                "universe": universe,
                                "groupId": group_id,
                                "groupName": group_name,
                                "minMatches": min_matches,
                                "ruleCount": len(rules),
                                "topN": top_n,
                                "targetPct": target,
                                "stopPct": stop,
                                "holdDays": hold,
                                "totalSignals": result["totalSignals"],
                                "signalDays": result["signalDays"],
                                "trades": summary["trades"],
                                "netPnl": summary["netPnl"],
                                "returnOnTurnoverPct": summary["returnOnTurnoverPct"],
                                "avgTradeReturnPct": summary["avgTradeReturnPct"],
                                "winRatePct": summary["winRatePct"],
                                "targetHitPct": summary["targetHitPct"],
                                "stopHitPct": summary["stopHitPct"],
                            }
                        )
    fieldnames = list(rows[0])
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    rows.sort(key=lambda item: (item["returnOnTurnoverPct"], item["winRatePct"]), reverse=True)
    print(f"Wrote {out}")
    print("Top 20 by return on turnover")
    for row in rows[:20]:
        print(
            f"{row['universe']:8} {row['groupName'][:36]:36} "
            f"top{row['topN']} t/s {row['targetPct']}/{row['stopPct']} hold {row['holdDays']:2} "
            f"trades {row['trades']:4} pnl {row['netPnl']:10.2f} "
            f"ret {row['returnOnTurnoverPct']:6.2f}% win {row['winRatePct']:5.1f}% "
            f"target {row['targetHitPct']:5.1f}% stop {row['stopHitPct']:5.1f}%"
        )


if __name__ == "__main__":
    main()

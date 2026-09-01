# Buy Engine Rule Research Log

This branch rebuilds the NSE buy engine one rule or filter at a time.

For each item we will record:

1. Plain-English meaning.
2. User-editable value.
3. Individual backtest result.
4. Portfolio backtest result.
5. Combination backtest result after multiple rules exist.
6. Decision: keep, change, or remove.

## Current Plan

| Step | Type | Name | Status | Notes |
| --- | --- | --- | --- | --- |
| 1 | Universe | NSE only | Active | Avoid NSE/BSE confusion. |
| 2 | Filter | Price range | Active | Only live filter in the clean UI. Test by itself first. |
| 3 | Filter | 20D ADV | Planned | Liquidity and execution quality. |
| 4 | Filter | RSI 14 range | Planned | Avoid weak or over-extended names. |
| 5 | Rule | 3-day ROC | Planned | Short-term momentum. |
| 6 | Rule | Relative volume | Planned | Participation/volume confirmation. |
| 7 | Rule | Near 20D high | Planned | Breakout proximity. |
| 8 | Rule | Close position | Planned | Candle strength. |

## Testing Discipline

- Start with one active rule/filter.
- Backtest that item alone.
- Add the next item only after recording the effect.
- After three or more useful items exist, run criss-cross combination sweeps.
- Do not promote any rule to default unless the portfolio test improves after costs.

## Active UI

Only `NSE only + Price range` is active in the clean branch.

Not active yet:

- 20D ADV
- RSI
- Relative volume
- 3-day ROC
- Near 20D high
- Close position
- Any combined score

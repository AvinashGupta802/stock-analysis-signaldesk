# SignalDesk India

SignalDesk is an NSE end-of-day research application for finding and testing short-term swing-trading setups. It combines editable technical filters into rules, combines rules into weighted rule groups, stores daily analysis in SQLite, and provides a Stock Lab for examining one symbol over time.

This is a research tool, not financial advice. Backtest results do not include every real-world cost or guarantee future returns.

## Current Scope

- NSE cash-market EOD price, volume, and delivery data
- Typical holding periods from 2 to 15 trading days
- User-defined stock groups and combined groups
- Editable filters, rules, rule groups, and per-rule weights
- Stored EOD analysis with on-demand calculation when inputs change
- Rule and rule-group backtests
- Stock Lab history, best-fit groups, draft-rule suggestions, and draft backtests

## Run Locally

Requirements: Python 3.10 or newer and a modern browser. The application currently uses only Python standard-library modules at runtime.

```powershell
python scripts\server.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Keep the terminal open while using the application.

The application database is `data/stock_analysis_exchange.sqlite3`. SQLite runs as an embedded file, so PostgreSQL or another database server is not required.

## Data Import

Import NSE prices and delivery data for one trading date:

```powershell
python scripts\import_exchange_bhavcopy.py --exchange NSE --dataset both --date 2026-09-25
```

Import a date range:

```powershell
python scripts\import_exchange_bhavcopy.py --exchange NSE --dataset both --start-date 2026-09-01 --end-date 2026-09-25
```

The importer skips weekends and unavailable exchange files. Use `--no-download` to reprocess files already present under `data/raw`. Exchange formats and URLs can change, so verify row counts and the latest date after an import.

## EOD Workflow

Run the complete daily pipeline. With no date, it imports the previous weekday, verifies that both NSE reports exist, and then runs EOD analysis:

```powershell
python scripts\run_daily_pipeline.py
```

Run or repeat a specific trading date:

```powershell
python scripts\run_daily_pipeline.py --date 2026-09-25
```

If either the price or delivery report has not yet been published, the command stops before analysis and can safely be retried later.

After importing a trading day, evaluate every active saved rule and rule group and persist the results:

```powershell
python scripts\run_eod_analysis.py --date 2026-09-25
```

Omit `--date` to analyze the latest NSE date in SQLite. The UI reuses stored results when the stock group, rule definitions, weights, thresholds, and signal date match. A changed input is calculated on demand so stale results are not presented as current.

## Strategy Model

A **filter** is one measurable condition, such as RSI range, volume versus its 20-day average, delivery percentage, momentum, MACD, EMA trend, or ATR risk.

A **rule** is an AND combination of filters. A stock passes the rule only when it passes every filter in that rule.

A **rule group** combines rules. It can require both:

- a minimum number of matching rules; and
- a minimum weighted score.

The score is:

```text
matched rule weight / total group rule weight * 100
```

Rule weights are bounded from `0.25` to `3.0`. Equal weights preserve the original count-based behavior. The minimum rule count remains a hard guard, so one heavily weighted rule cannot pass a group that requires two matches.

Price range is a universe-level filter. It can be applied to a run independently instead of being duplicated inside every technical rule.

## Backtesting

Run the saved-strategy deep audit without changing strategy definitions in SQLite:

```powershell
python scripts\deep_audit_saved_strategy.py --from-date 2026-06-01 --to-date 2026-09-25 --universes all,liquid,nifty500 --hold-days 2,3,5,7,10,15 --top-n 3,5,10 --exits 5:5,8:6,10:7,12:8,15:10
```

Reports are written to `outputs`. Use out-of-sample dates when comparing strategies, and consider brokerage, taxes, slippage, liquidity, survivorship bias, overlapping positions, and available capital before interpreting returns.

## Main API

The browser uses these local endpoints:

- `GET /api/bootstrap` - strategy catalog, groups, dates, and application state
- `GET /api/prices` - chart history
- `GET /api/stocks/search` - symbol lookup for Stock Lab
- `POST /api/rule/results` - one rule on a selected universe and date
- `POST /api/rule-group/results` - weighted group results, stored when compatible
- `POST /api/rule/backtest` - rule backtest
- `POST /api/rule-group/backtest` - group backtest
- `POST /api/groups` and `/api/groups/combine` - custom stock groups
- `POST /api/strategy` - save rules and groups
- `POST /api/eod-analysis` - run and store analysis
- `POST /api/stock-lab` - single-stock research workflow

See [ARCHITECTURE.md](ARCHITECTURE.md) before extending the backend or database schema.

## Verification

Run the focused automated checks:

```powershell
python -m unittest scripts/test_weighted_groups.py
python -m py_compile scripts/server.py scripts/strategy_scoring.py scripts/deep_audit_saved_strategy.py
node --check app.js
```

After backend changes, also start the server and smoke-test `/api/bootstrap`, a stored rule-group request, and the Stock Lab.

## Sharing And Security

The local server blocks direct access to database, source, and output files. However, the POST APIs do not yet have authentication or authorization. A public Cloudflare Tunnel should therefore be treated as a temporary feedback link: anyone with the URL may be able to change strategy data. Add authentication or a read-only public mode before broader deployment.

## Repository Map

- `index.html`, `styles.css`, `app.js` - browser interface
- `scripts/server.py` - HTTP API, persistence orchestration, indicators, and analysis
- `scripts/strategy_scoring.py` - pure weighted rule-group scoring
- `scripts/import_exchange_bhavcopy.py` - NSE/BSE report download and import
- `scripts/run_eod_analysis.py` - saved-strategy EOD runner
- `scripts/deep_audit_saved_strategy.py` - long-running saved-strategy audit
- `data/` - SQLite database and raw exchange files
- `outputs/` - generated research reports

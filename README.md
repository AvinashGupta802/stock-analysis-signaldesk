# SignalDesk India

SignalDesk is an NSE end-of-day research application for finding and testing short-term swing-trading setups. It combines editable technical filters into rules, combines rules into weighted rule groups, stores daily analysis in SQLite, and provides a Stock Lab for examining one symbol over time.

This is a research tool, not financial advice. Backtest results do not include every real-world cost or guarantee future returns.

## Current Scope

- NSE cash-market EOD price, volume, delivery, and benchmark-index data
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

Import NSE price, delivery, and official index-close reports together:

```powershell
python scripts\import_exchange_bhavcopy.py --exchange NSE --dataset all --date 2026-09-25
```

The index report supplies the Nifty 500 history used by benchmark-relative-strength filters.

## NSE Fundamentals

Import financial-result and shareholding XBRL filings published in a date range:

```powershell
python scripts\import_nse_fundamentals.py --from-date 2026-11-01 --to-date 2026-11-09
```

Import or repair one company:

```powershell
python scripts\import_nse_fundamentals.py --symbol RELIANCE --from-date 2026-01-01 --to-date 2026-11-09
```

Recover missing outstanding-share counts without downloading every historical revision:

```powershell
python scripts\import_nse_fundamentals.py --from-date 2024-07-08 --to-date 2026-11-10 --shareholding-only --missing-share-counts-only
```

The recovery mode selects the latest filing for each symbol still missing a usable share count. Filing symbols are matched to bhavcopy instruments by ISIN, handling differences such as `BAJAJ-AUTO` versus `BAJAJAUTO`.

The importer stores raw XBRL under `data/raw/nse_fundamentals` and normalizes:

- revenue, PAT, PBT and finance cost;
- current and non-current debt, equity and capital employed;
- YoY revenue and PAT growth when the corresponding prior period is available;
- debt-to-equity and annualized period ROCE;
- outstanding shares, promoter percentage and public percentage;
- point-in-time market capitalization through the `daily_market_cap` SQLite view.

Every record retains the NSE broadcast timestamp. Backtests must select only filings whose `available_at` is on or before the signal time. ROCE currently annualizes the filing-period EBIT against current capital employed; it is an analytical estimate, not a company-reported ratio. Financial-sector companies can require sector-specific treatment.

The importer skips weekends and unavailable exchange files. Use `--no-download` to reprocess files already present under `data/raw`. Exchange formats and URLs can change, so verify row counts and the latest date after an import.

## EOD Workflow

Run the complete daily pipeline. With no date, it imports the previous weekday, verifies price, delivery, and Nifty 500 data, and then runs EOD analysis:

```powershell
python scripts\run_daily_pipeline.py
```

Run or repeat a specific trading date:

```powershell
python scripts\run_daily_pipeline.py --date 2026-09-25
```

Import every missing weekday after the latest complete database date and run EOD analysis in order:

```powershell
python scripts\run_daily_pipeline.py --catch-up
```

Or provide an explicit recovery range:

```powershell
python scripts\run_daily_pipeline.py --start-date 2026-10-20 --end-date 2026-11-06
```

Complete dates with existing EOD results are skipped. Exchange holidays and unpublished reports are reported and skipped without analyzing incomplete data.

If either the price or delivery report has not yet been published, that date is not analyzed and can safely be retried later.

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

The filter library also includes volume SMA10 versus SMA20, distance from the 52-week high, close versus SMA50, SMA50 versus SMA200, and three-month excess return versus the official Nifty 500 close series. Long-lookback filters reject stocks without enough history instead of calculating shortened substitutes.

Fundamental growth is split into explicit period definitions: `Quarterly Revenue Growth YoY`, `Quarterly PAT Growth YoY`, and `Quarterly Estimated ROCE` use the latest three-month filing period; `Annual Revenue Growth YoY`, `Annual PAT Growth YoY`, and `Annual ROCE` use full financial-year facts embedded in annual XBRL filings. The Early Growth & Relative Strength system rule uses the annual filters.

Two system rules reproduce the referenced scans:

- `Early Volume Signs`: market cap Rs. 2,000-50,000 crore, volume SMA10 at least 1.3x SMA20, and one-week return at least 2%.
- `Early Growth & Relative Strength`: market cap at least Rs. 500 crore, revenue growth at least 15%, PAT growth at least 20%, ROCE at least 15%, debt-to-equity at most 1.2, close above SMA50, SMA50 above SMA200, within 15% of the 52-week high, RSI at least 55, and three-month outperformance versus Nifty 500 of at least 5 percentage points.

Fundamental conditions use only filings broadcast by the signal date. Until historical financial and shareholding XBRL is backfilled, these rules will intentionally return limited or no historical matches rather than use future information.

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
python -m unittest scripts/test_growth_filters.py
python -m unittest scripts/test_nse_fundamentals.py
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
- `scripts/import_nse_fundamentals.py` - NSE financial and shareholding XBRL import
- `scripts/run_eod_analysis.py` - saved-strategy EOD runner
- `scripts/deep_audit_saved_strategy.py` - long-running saved-strategy audit
- `data/` - SQLite database and raw exchange files
- `outputs/` - generated research reports

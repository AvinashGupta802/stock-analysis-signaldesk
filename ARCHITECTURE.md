# SignalDesk Architecture

## System Shape

SignalDesk is a small client-server application with no framework build step:

```text
Browser UI (index.html, app.js, styles.css)
                    |
                    | JSON over HTTP
                    v
Python server (scripts/server.py)
          |                    |
          v                    v
strategy_scoring.py        SQLite database
                               ^
                               |
          import and EOD command-line scripts
```

`scripts/server.py` intentionally remains the compatibility boundary for the browser API. Pure calculations should move into focused modules when they can be tested without HTTP or database setup.

## Data Flow

1. `import_exchange_bhavcopy.py` downloads or reads exchange reports and upserts instruments, daily prices, delivery data, and benchmark-index closes.
2. `import_nse_fundamentals.py` stores raw XBRL and normalizes point-in-time financial and share-capital records.
3. `import_bse_fallback.py` matches NSE and BSE instruments by ISIN and fills only missing share counts and quarterly growth inputs from official BSE filings. NSE remains the preferred source.
4. Rules and rule groups are edited in the UI and stored in SQLite.
5. `run_eod_analysis.py` evaluates the active strategy for a date and stores rule and group results.
6. The UI requests results for a signal date and stock group. Compatible stored results are returned immediately; changed definitions are evaluated on demand.
7. Backtest and Stock Lab paths reuse the same rule evaluation and weighted-group scoring semantics.

## Strategy Boundaries

- **Filter:** one indicator comparison plus user-controlled values.
- **Rule:** all included filters must pass.
- **Rule group:** rules are combined using a minimum match count and weighted score.
- **Universe filter:** restricts eligible stocks for a run. Price range belongs here, not inside every rule.
- **Stock group:** a reusable list or index membership; it is separate from technical strategy logic.

`scripts/strategy_scoring.py` owns group weight normalization and agreement scoring. Keep it free of database, HTTP, and UI dependencies so every execution path can share it safely.

## SQLite Ownership

The main database is `data/stock_analysis_exchange.sqlite3`.

Core market-data tables:

- `instruments`
- `daily_prices`
- `daily_delivery`
- `benchmark_prices`

Fundamental-data tables and views:

- `fundamental_filings`
- `company_fundamentals`
- `share_capital_filings`
- `daily_market_cap`

Application and strategy tables:

- `stock_groups` and `stock_group_members`
- `strategy_state`
- `strategy_rules`
- `strategy_rule_groups`
- `rule_daily_results`
- `analysis_runs` and `analysis_results`

Schema creation and lightweight migrations currently run from server/import code. Before a larger deployment, move schema versions into explicit migration files and back up the database before each migration.

## Stored Result Validity

Stored analysis is valid only when its effective inputs match: signal date, stock universe, rule filters and values, group membership, rule weights, and group thresholds. New features that influence a result must be included in the stored-run identity or must force an on-demand calculation.

Fundamental queries must also enforce `available_at <= signal timestamp`. Period-end dates alone are not sufficient because using results before their exchange broadcast creates look-ahead bias.

Do not delete historical analysis merely because a strategy is edited. Treat the old result as belonging to the old strategy definition; versioned strategy snapshots are the preferred long-term design.

## Safe Extension Checklist

1. Add the filter definition and plain-language explanation to the shared catalog.
2. Calculate its indicator without using future rows.
3. Apply identical semantics in live analysis, EOD storage, backtesting, and Stock Lab.
4. Add focused tests for boundary values and missing history.
5. Confirm stored-result invalidation accounts for the new input.
6. Run Python compile checks, unit tests, JavaScript syntax checks, and API smoke tests.

## Current Technical Priorities

- Split indicator calculation, persistence, and endpoint routing out of `server.py` incrementally.
- Add integration tests around SQLite and the main API workflows.
- Introduce explicit database migrations and strategy-definition versioning.
- Add authentication or a read-only sharing mode before public hosting.
- Record transaction-cost and slippage assumptions with every backtest report.
- Add structured logging for imports, EOD runs, and failed rows.

These should be handled in small changes. Preserve API payloads and strategy semantics unless a migration and compatibility plan is part of the change.

# SignalDesk India

First-cut prototype for an Indian stock EOD recommendation app.

## What It Does

- Creates predefined stock groups such as Nifty Core, Banking Leaders, and IT Services.
- Imports per-stock EOD CSV/XLSX files in BSE-style and Yahoo-style historical formats.
- Runs a weighted rule engine on EOD candle data.
- Produces Buy, Sell, Watch, Strong Buy, and Strong Sell signals.
- Shows next-day result for quick backdated validation.
- Persists imported data in browser localStorage for MVP testing.

## Open The Prototype

Open `index.html` in a browser.

## Importing Data

Use the **Import EOD data** control in the sidebar.

Supported MVP formats:

- `Date`
- `Open`
- `High`
- `Low`
- `Close`
- `WAP`
- `No. of Shares`
- `No. of Trades`
- `Total Turnover`
- `Deliverable Quantity`
- `% Deli. Qty to Traded Qty`

Yahoo-style history:

- `Date`
- `Open`
- `High`
- `Low`
- `Close`
- `Volume`
- `Dividends`
- `Stock Splits`

The importer detects the stock symbol from the file name. For example:

```text
ARIES_BSE_Historical_01012022_to_22082026.xlsx -> ARIES
RELIANCE_NSE.csv -> RELIANCE
ARIES.NS.csv -> ARIES
```

CSV files work fully offline. XLSX import uses the SheetJS browser parser loaded from CDN, so the browser needs internet access once for that library. If XLSX does not load, save the same file as CSV and import it.

## Current Storage

Imported data is stored in browser `localStorage`. This is fine for a few stocks while testing the workflow. Do not import thousands of files into localStorage; the `share_history/v1` folder should be loaded through the next SQLite backend importer. For many stocks or long histories, the next step should be IndexedDB locally, then SQLite/PostgreSQL for a hosted app.



## Run The SQLite-Connected App

Start the local backend server:

```powershell
python scripts\server.py
```

Then open:

```text
http://127.0.0.1:8000
```

The browser UI now reads recommendations from `data/stock_analysis.sqlite3` through these local API endpoints:

- `/api/bootstrap`
- `/api/recommendations`
- `/api/prices`

If you open `index.html` directly without the server, the UI falls back to small demo data.

## BSE EOD Bhavcopy Download

Download and import a single BSE EOD bhavcopy date:

```powershell
python scripts\download_bse_bhavcopy.py --date 2026-08-21 --db data\stock_analysis.sqlite3
```

Download and import a date range:

```powershell
python scripts\download_bse_bhavcopy.py --start-date 2026-07-01 --end-date 2026-08-21 --db data\stock_analysis.sqlite3
```

The downloader tries the newer BSE CM bhavcopy CSV first, then falls back to the older `EQddmmyy_CSV.ZIP` format. Raw downloaded files are stored under `data/raw/bse_bhavcopy`.

For an EOD schedule, run this after BSE publishes the bhavcopy, then refresh the app at `http://127.0.0.1:8000`.
## SQLite Import And Backtest

Bulk historical CSV data should be imported into SQLite:

```powershell
python scripts\import_history.py --source C:\Users\Avinash\Downloads\share_history\v1 --db data\stock_analysis.sqlite3
```

Run the first EOD rule backtest:

```powershell
python scripts\backtest_eod.py --db data\stock_analysis.sqlite3 --from-date 2020-01-01 --to-date 2023-10-20 --min-price 20 --min-volume 10000 --threshold 5 --output outputs\backtest_summary.csv
```

Current imported database:

- `data/stock_analysis.sqlite3`
- 7,313 stocks
- 6,635,647 daily price rows
- date range from 1995-12-25 to 2026-08-21

## Swing Trading Rule Selection

The product is now aimed at short-term 2-5 trading day setups:

- `Strong Buy` means possible long swing setup.
- `Strong Sell` means possible short swing setup.

The app has predefined selectable filters and rules in the sidebar. The backend applies the selected rule IDs through `/api/recommendations`.

Current filter examples:

- price >= Rs. 20 / Rs. 50
- volume >= 100k / 500k
- avoid >15% one-day moves

Current rule examples:

- Long: above 5 & 20 DMA
- Short: below 5 & 20 DMA
- Long/short 3-day momentum
- Long/short volume breakout
- Long near 20-day high
- Short near 20-day low
- Close near day high / low

Next step: update `scripts/backtest_eod.py` to use the same selectable rule catalog and report 2-day, 3-day, and 5-day long/short outcomes.
## Next Build Steps

1. Add backend API endpoints over SQLite.
2. Add custom stock groups built from imported symbols.
3. Move rules into editable JSON/config.
4. Improve backtesting with liquidity filters, benchmark comparison, and transaction-cost assumptions.
5. Add NSE/BSE bhavcopy bulk import.
6. Add a replaceable market data provider interface.







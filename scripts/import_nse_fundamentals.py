"""Import NSE financial and shareholding XBRL filings into SQLite."""

import argparse
import json
import sqlite3
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "stock_analysis_exchange.sqlite3"
DEFAULT_RAW_DIR = ROOT / "data" / "raw" / "nse_fundamentals"
NSE_BASE = "https://www.nseindia.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-integrated-filing",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS fundamental_filings (
  filing_id TEXT PRIMARY KEY,
  filing_type TEXT NOT NULL,
  symbol TEXT NOT NULL,
  company_name TEXT,
  period_start TEXT,
  period_end TEXT,
  available_at TEXT NOT NULL,
  consolidated TEXT,
  audited TEXT,
  revision_type TEXT,
  xbrl_url TEXT NOT NULL,
  raw_path TEXT,
  parse_status TEXT NOT NULL,
  parse_message TEXT,
  source_json TEXT NOT NULL,
  imported_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_fundamental_filings_symbol_period
ON fundamental_filings(symbol, period_end, available_at);

CREATE TABLE IF NOT EXISTS company_fundamentals (
  filing_id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  period_start TEXT,
  period_end TEXT NOT NULL,
  available_at TEXT NOT NULL,
  consolidated TEXT,
  revenue REAL,
  pat REAL,
  pbt REAL,
  finance_cost REAL,
  ebit REAL,
  current_debt REAL,
  noncurrent_debt REAL,
  total_debt REAL,
  equity REAL,
  capital_employed REAL,
  revenue_growth_yoy REAL,
  pat_growth_yoy REAL,
  debt_to_equity REAL,
  roce REAL,
  roce_method TEXT,
  FOREIGN KEY (filing_id) REFERENCES fundamental_filings(filing_id)
);

CREATE INDEX IF NOT EXISTS idx_company_fundamentals_symbol_available
ON company_fundamentals(symbol, available_at, period_end);

CREATE TABLE IF NOT EXISTS share_capital_filings (
  filing_id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  as_of_date TEXT NOT NULL,
  available_at TEXT NOT NULL,
  outstanding_shares REAL,
  promoter_pct REAL,
  public_pct REAL,
  FOREIGN KEY (filing_id) REFERENCES fundamental_filings(filing_id)
);

CREATE INDEX IF NOT EXISTS idx_share_capital_symbol_available
ON share_capital_filings(symbol, available_at, as_of_date);

CREATE VIEW IF NOT EXISTS daily_market_cap AS
SELECT
  instruments.symbol,
  prices.trade_date,
  prices.close,
  shares.outstanding_shares,
  shares.as_of_date AS shares_as_of_date,
  shares.available_at AS shares_available_at,
  (prices.close * shares.outstanding_shares) / 10000000.0 AS market_cap_cr
FROM daily_prices AS prices
JOIN instruments AS instruments ON instruments.id = prices.instrument_id
JOIN share_capital_filings AS shares ON shares.filing_id = (
  SELECT candidate.filing_id
  FROM share_capital_filings AS candidate
  WHERE candidate.symbol = instruments.symbol
    AND candidate.outstanding_shares IS NOT NULL
    AND candidate.available_at <= prices.trade_date || ' 23:59:59'
  ORDER BY candidate.available_at DESC
  LIMIT 1
)
WHERE instruments.exchange = 'NSE';
"""

FLOW_CONCEPTS = {
    "revenue": ("RevenueFromOperations", "Revenue"),
    "pat": ("ProfitLossForPeriod", "ProfitLossForPeriodFromContinuingOperations"),
    "pbt": ("ProfitBeforeTax", "ProfitBeforeExceptionalItemsAndTax"),
    "finance_cost": ("FinanceCosts",),
}

INSTANT_CONCEPTS = {
    "current_debt": ("BorrowingsCurrent",),
    "noncurrent_debt": ("BorrowingsNoncurrent",),
    "equity": ("Equity", "EquityAttributableToOwnersOfParent"),
}


def main():
    parser = argparse.ArgumentParser(description="Import NSE financial and shareholding XBRL filings.")
    parser.add_argument("--from-date", help="Broadcast-date start in YYYY-MM-DD; defaults to yesterday.")
    parser.add_argument("--to-date", help="Broadcast-date end in YYYY-MM-DD; defaults to today.")
    parser.add_argument("--symbol", help="Optional NSE symbol.")
    parser.add_argument("--financial-only", action="store_true")
    parser.add_argument("--shareholding-only", action="store_true")
    parser.add_argument(
        "--missing-share-counts-only",
        action="store_true",
        help="Import only the latest shareholding filing for symbols without a usable share count.",
    )
    parser.add_argument(
        "--growth-pairs-only",
        action="store_true",
        help="Import the latest financial period and matching prior-year period per symbol.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Maximum filings per feed; zero means all.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--raw-dir", default=str(DEFAULT_RAW_DIR))
    parser.add_argument("--sleep", type=float, default=0.2)
    args = parser.parse_args()

    if args.financial_only and args.shareholding_only:
        raise SystemExit("Choose at most one of --financial-only and --shareholding-only.")
    if args.missing_share_counts_only and not args.shareholding_only:
        raise SystemExit("--missing-share-counts-only requires --shareholding-only.")
    if args.growth_pairs_only and args.shareholding_only:
        raise SystemExit("--growth-pairs-only cannot be used with --shareholding-only.")
    today = date.today()
    from_date = date.fromisoformat(args.from_date) if args.from_date else today - timedelta(days=1)
    to_date = date.fromisoformat(args.to_date) if args.to_date else today
    if from_date > to_date:
        raise SystemExit("--from-date must not be after --to-date")

    db_path = Path(args.db).resolve()
    raw_dir = Path(args.raw_dir).resolve()
    raw_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    opener = nse_opener()
    totals = {"metadata": 0, "downloaded": 0, "parsed": 0, "failed": 0}

    if not args.shareholding_only:
        filings = fetch_financial_filings(opener, from_date, to_date, args.symbol)
        filings = canonicalize_record_symbols(conn, filings)
        if args.growth_pairs_only:
            filings = latest_growth_pair_filings(filings)
        import_filings(conn, opener, raw_dir, filings, "financial", args.limit, args.sleep, totals)
    if not args.financial_only:
        filings = fetch_shareholding_filings(opener, from_date, to_date, args.symbol)
        filings = canonicalize_record_symbols(conn, filings)
        if args.missing_share_counts_only:
            filings = missing_latest_shareholding_filings(conn, filings)
        import_filings(conn, opener, raw_dir, filings, "shareholding", args.limit, args.sleep, totals)

    refresh_all_growth(conn)
    conn.commit()
    print("NSE fundamentals import complete")
    print(f"Metadata records: {totals['metadata']:,}")
    print(f"XBRL files downloaded: {totals['downloaded']:,}")
    print(f"Filings parsed: {totals['parsed']:,}")
    print(f"Failures: {totals['failed']:,}")
    conn.close()


def nse_opener():
    return build_opener(HTTPCookieProcessor(CookieJar()))


def fetch_json(opener, url):
    for attempt in range(2):
        try:
            with opener.open(Request(url, headers=HEADERS), timeout=45) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            if attempt:
                raise
            try:
                opener.open(Request(NSE_BASE + "/", headers=HEADERS), timeout=20).read(1)
            except Exception:
                pass
    return None


def fetch_financial_filings(opener, from_date, to_date, symbol=None):
    records = []
    current = from_date
    while current <= to_date:
        records.extend(fetch_financial_filings_for_day(opener, current, symbol))
        current += timedelta(days=1)
    unique = {}
    for record in records:
        filing_id = filing_identifier(record, "financial")
        if filing_id:
            unique[filing_id] = record
    return list(unique.values())


def fetch_financial_filings_for_day(opener, filing_date, symbol=None):
    params = {
        "index": "equities",
        "from_date": filing_date.strftime("%d-%m-%Y"),
        "to_date": filing_date.strftime("%d-%m-%Y"),
        "page": 1,
        "size": 5000,
    }
    if symbol:
        params["symbol"] = symbol.upper()
    payload = fetch_json(opener, NSE_BASE + "/api/integrated-filing-results?" + urlencode(params))
    records = payload.get("data", payload) if isinstance(payload, dict) else payload
    records = [item for item in records or [] if "financial" in str(item.get("type", "")).lower()]
    if records:
        return records

    legacy = []
    for period in ("Quarterly", "Annual"):
        legacy_params = dict(params, period=period)
        payload = fetch_json(opener, NSE_BASE + "/api/corporates-financial-results?" + urlencode(legacy_params))
        legacy.extend(payload if isinstance(payload, list) else payload.get("data", []))
    return legacy


def latest_growth_pair_filings(records):
    latest_period = {}
    for record in records:
        symbol = str(record.get("symbol") or "").strip().upper()
        period_end = filing_period_end(record, "financial")
        if symbol and period_end and period_end > latest_period.get(symbol, ""):
            latest_period[symbol] = period_end
    targets = {}
    for symbol, period_end in latest_period.items():
        current = date.fromisoformat(period_end)
        try:
            prior = current.replace(year=current.year - 1).isoformat()
        except ValueError:
            prior = current.replace(year=current.year - 1, day=28).isoformat()
        targets[symbol] = {period_end, prior}
    selected = {}
    for record in records:
        symbol = str(record.get("symbol") or "").strip().upper()
        period_end = filing_period_end(record, "financial")
        if period_end not in targets.get(symbol, set()):
            continue
        key = (symbol, period_end, str(record.get("consolidated") or ""))
        available_at = filing_available_at(record, "financial") or ""
        if key not in selected or available_at > selected[key][0]:
            selected[key] = (available_at, record)
    return [item[1] for item in selected.values()]


def fetch_shareholding_filings(opener, from_date, to_date, symbol=None):
    params = {"index": "equities"}
    if symbol:
        params["symbol"] = symbol.upper()
    else:
        params.update({
            "from_date": from_date.strftime("%d-%m-%Y"),
            "to_date": to_date.strftime("%d-%m-%Y"),
        })
    payload = fetch_json(opener, NSE_BASE + "/api/corporate-share-holdings-master?" + urlencode(params))
    records = payload if isinstance(payload, list) else payload.get("data", [])
    if not symbol:
        return records
    filtered = []
    for record in records:
        available_at = filing_available_at(record, "shareholding")
        if not available_at:
            continue
        available_date = datetime.fromisoformat(available_at).date()
        if from_date <= available_date <= to_date:
            filtered.append(record)
    return filtered


def missing_latest_shareholding_filings(conn, records):
    covered = {
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT symbol FROM share_capital_filings WHERE outstanding_shares IS NOT NULL"
        )
    }
    latest = {}
    for record in records:
        symbol = str(record.get("symbol") or "").strip().upper()
        if not symbol or symbol in covered:
            continue
        available_at = filing_available_at(record, "shareholding") or ""
        if symbol not in latest or available_at > latest[symbol][0]:
            latest[symbol] = (available_at, record)
    return [item[1] for item in sorted(latest.values(), key=lambda item: item[0], reverse=True)]


def canonicalize_record_symbols(conn, records):
    isin_symbols = {
        row[0]: row[1]
        for row in conn.execute(
            """
            SELECT isin, symbol
            FROM instruments
            WHERE exchange = 'NSE' AND series = 'EQ' AND isin IS NOT NULL AND isin != ''
            """
        )
    }
    normalized = []
    for record in records:
        item = dict(record)
        canonical = isin_symbols.get(str(item.get("isin") or "").strip().upper())
        if canonical:
            item["symbol"] = canonical
        normalized.append(item)
    return normalized


def import_filings(conn, opener, raw_dir, records, filing_type, limit, sleep_seconds, totals):
    records = records[:limit] if limit else records
    totals["metadata"] += len(records)
    for record in records:
        filing_id = filing_identifier(record, filing_type)
        symbol = str(record.get("symbol") or "").strip().upper()
        xbrl_url = str(record.get("xbrl") or "").strip()
        available_at = filing_available_at(record, filing_type)
        period_end = filing_period_end(record, filing_type)
        if not filing_id or not symbol or not available_at or not period_end or not xbrl_url.startswith("http"):
            totals["failed"] += 1
            continue
        destination = raw_destination(raw_dir, filing_type, symbol, xbrl_url)
        status = "parsed"
        message = None
        try:
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                with opener.open(Request(xbrl_url, headers=HEADERS), timeout=60) as response:
                    destination.write_bytes(response.read())
                totals["downloaded"] += 1
                time.sleep(sleep_seconds)
            parsed = parse_xbrl(destination.read_bytes())
            upsert_filing(conn, filing_id, filing_type, symbol, record, available_at, period_end, xbrl_url, destination, status, message)
            if filing_type == "financial":
                store_financial(conn, filing_id, symbol, record, available_at, period_end, parsed)
            else:
                store_shareholding(conn, filing_id, symbol, record, available_at, period_end, parsed)
            totals["parsed"] += 1
        except Exception as exc:
            status = "failed"
            message = str(exc)[:500]
            upsert_filing(conn, filing_id, filing_type, symbol, record, available_at, period_end, xbrl_url, destination, status, message)
            totals["failed"] += 1
        conn.commit()


def filing_identifier(record, filing_type):
    raw_id = (record.get("seq_Id") or record.get("seqNumber")) if filing_type == "financial" else record.get("recordId")
    return f"{'FIN' if filing_type == 'financial' else 'SHP'}-{raw_id}" if raw_id else None


def filing_available_at(record, filing_type):
    value = (record.get("broadcast_Date") or record.get("broadCastDate")) if filing_type == "financial" else record.get("broadcastDate")
    return parse_nse_datetime(value)


def filing_period_end(record, filing_type):
    value = (record.get("qe_Date") or record.get("toDate")) if filing_type == "financial" else record.get("date")
    return parse_nse_date(value)


def parse_nse_datetime(value):
    text = str(value or "").strip()
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%B-%Y %H:%M:%S"):
        try:
            return datetime.strptime(text.upper(), fmt).isoformat(sep=" ")
        except ValueError:
            continue
    return None


def parse_nse_date(value):
    text = str(value or "").strip()
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.upper(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def raw_destination(raw_dir, filing_type, symbol, url):
    filename = Path(urlparse(url).path).name or "filing.xml"
    return raw_dir / filing_type / symbol / filename


def parse_xbrl(content):
    root = ET.fromstring(content)
    contexts = {}
    for context in root:
        if local_name(context.tag) != "context":
            continue
        context_id = context.attrib.get("id")
        start = first_descendant_text(context, "startDate")
        end = first_descendant_text(context, "endDate")
        instant = first_descendant_text(context, "instant")
        dimensions = [node for node in context.iter() if local_name(node.tag) in {"explicitMember", "typedMember"}]
        contexts[context_id] = {
            "start": start,
            "end": end,
            "instant": instant,
            "has_dimensions": bool(dimensions),
            "members": [str(node.text or "").strip() for node in dimensions],
        }
    facts = []
    for element in root:
        context_id = element.attrib.get("contextRef")
        if not context_id or context_id not in contexts:
            continue
        text = str(element.text or "").strip()
        facts.append({
            "concept": local_name(element.tag),
            "context_id": context_id,
            "context": contexts[context_id],
            "text": text,
            "number": to_number(text),
        })
    return {"contexts": contexts, "facts": facts}


def store_financial(conn, filing_id, symbol, record, available_at, period_end, parsed):
    flows = {key: select_flow_fact(parsed["facts"], names, period_end) for key, names in FLOW_CONCEPTS.items()}
    instants = {key: select_instant_fact(parsed["facts"], names, period_end) for key, names in INSTANT_CONCEPTS.items()}
    period_start = next((fact["context"]["start"] for fact in parsed["facts"] if fact["context"]["end"] == period_end and fact["context"]["start"] and not fact["context"]["has_dimensions"]), None)
    current_debt = instants["current_debt"] or 0
    noncurrent_debt = instants["noncurrent_debt"] or 0
    total_debt = current_debt + noncurrent_debt
    equity = instants["equity"]
    ebit = (flows["pbt"] + flows["finance_cost"]) if flows["pbt"] is not None and flows["finance_cost"] is not None else None
    capital_employed = (equity + total_debt) if equity is not None else None
    debt_to_equity = safe_ratio(total_debt, equity)
    days = (date.fromisoformat(period_end) - date.fromisoformat(period_start)).days + 1 if period_start else None
    roce = safe_ratio(ebit * (365 / days), capital_employed, percent=True) if ebit is not None and capital_employed and days else None
    consolidated = record.get("consolidated")
    conn.execute(
        """
        INSERT OR REPLACE INTO company_fundamentals (
          filing_id, symbol, period_start, period_end, available_at, consolidated,
          revenue, pat, pbt, finance_cost, ebit, current_debt, noncurrent_debt,
          total_debt, equity, capital_employed, debt_to_equity, roce, roce_method
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (filing_id, symbol, period_start, period_end, available_at, consolidated,
         flows["revenue"], flows["pat"], flows["pbt"], flows["finance_cost"], ebit,
         current_debt, noncurrent_debt, total_debt, equity, capital_employed,
         debt_to_equity, roce, "annualized_period_ebit/current_capital" if roce is not None else None),
    )
    refresh_growth(conn, filing_id, symbol, period_end, consolidated, flows["revenue"], flows["pat"])


def store_shareholding(conn, filing_id, symbol, record, available_at, as_of_date, parsed):
    outstanding = None
    for fact in parsed["facts"]:
        if fact["concept"] != "NumberOfFullyPaidUpEquityShares" or fact["number"] is None:
            continue
        members = " ".join(fact["context"]["members"])
        if "ShareholdingPatternMember" in members:
            outstanding = fact["number"]
            break
    conn.execute(
        """
        INSERT OR REPLACE INTO share_capital_filings (
          filing_id, symbol, as_of_date, available_at, outstanding_shares, promoter_pct, public_pct
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (filing_id, symbol, as_of_date, available_at, outstanding,
         to_number(record.get("pr_and_prgrp")), to_number(record.get("public_val"))),
    )


def upsert_filing(conn, filing_id, filing_type, symbol, record, available_at, period_end, xbrl_url, destination, status, message):
    company_name = record.get("cmName") or record.get("name") or record.get("smName") or record.get("companyName")
    period_start = None
    conn.execute(
        """
        INSERT OR REPLACE INTO fundamental_filings (
          filing_id, filing_type, symbol, company_name, period_start, period_end,
          available_at, consolidated, audited, revision_type, xbrl_url, raw_path,
          parse_status, parse_message, source_json, imported_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (filing_id, filing_type, symbol, company_name, period_start, period_end, available_at,
         record.get("consolidated"), record.get("audited"), record.get("type_Sub") or record.get("revisedStatus") or record.get("reInd"),
         xbrl_url, str(destination), status, message, json.dumps(record, ensure_ascii=True)),
    )


def refresh_growth(conn, filing_id, symbol, period_end, consolidated, revenue, pat):
    current_date = date.fromisoformat(period_end)
    try:
        prior_date = current_date.replace(year=current_date.year - 1).isoformat()
    except ValueError:
        prior_date = current_date.replace(year=current_date.year - 1, day=28).isoformat()
    prior = conn.execute(
        """
        SELECT revenue, pat
        FROM company_fundamentals
        WHERE symbol = ? AND period_end = ? AND COALESCE(consolidated, '') = COALESCE(?, '')
        ORDER BY available_at DESC LIMIT 1
        """,
        (symbol, prior_date, consolidated),
    ).fetchone()
    revenue_growth = growth_pct(revenue, prior[0]) if prior else None
    pat_growth = growth_pct(pat, prior[1]) if prior else None
    conn.execute(
        "UPDATE company_fundamentals SET revenue_growth_yoy = ?, pat_growth_yoy = ? WHERE filing_id = ?",
        (revenue_growth, pat_growth, filing_id),
    )


def refresh_all_growth(conn):
    rows = conn.execute(
        "SELECT filing_id, symbol, period_end, consolidated, revenue, pat FROM company_fundamentals"
    ).fetchall()
    for filing_id, symbol, period_end, consolidated, revenue, pat in rows:
        refresh_growth(conn, filing_id, symbol, period_end, consolidated, revenue, pat)


def select_flow_fact(facts, concept_names, period_end):
    candidates = [
        fact for fact in facts
        if fact["concept"] in concept_names
        and fact["number"] is not None
        and fact["context"]["end"] == period_end
        and fact["context"]["start"]
        and not fact["context"]["has_dimensions"]
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda fact: date.fromisoformat(period_end) - date.fromisoformat(fact["context"]["start"]))
    return candidates[0]["number"]


def select_instant_fact(facts, concept_names, period_end):
    candidates = [
        fact for fact in facts
        if fact["concept"] in concept_names
        and fact["number"] is not None
        and fact["context"]["instant"] == period_end
        and not fact["context"]["has_dimensions"]
    ]
    return candidates[0]["number"] if candidates else None


def first_descendant_text(element, name):
    node = next((item for item in element.iter() if local_name(item.tag) == name), None)
    return str(node.text or "").strip() if node is not None else None


def local_name(tag):
    return tag.split("}")[-1]


def to_number(value):
    text = str(value or "").replace(",", "").strip()
    if not text or text.lower() in {"nil", "na", "n.a.", "-"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def safe_ratio(numerator, denominator, percent=False):
    if numerator is None or denominator in {None, 0}:
        return None
    value = numerator / denominator
    return value * 100 if percent else value


def growth_pct(current, previous):
    if current is None or previous in {None, 0}:
        return None
    return ((current / previous) - 1) * 100


if __name__ == "__main__":
    main()

"""Fill missing NSE company data from official BSE website filings matched by ISIN."""

import argparse
import calendar
import concurrent.futures
import json
import re
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode

from curl_cffi import requests

import import_nse_fundamentals as nse_fundamentals


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "stock_analysis_exchange.sqlite3"
DEFAULT_RAW_DIR = ROOT / "data" / "raw" / "bse_fallback"
BSE_SITE = "https://www.bseindia.com"
BSE_API = "https://api.bseindia.com/BseIndiaAPI/api"
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Origin": BSE_SITE,
    "Referer": BSE_SITE + "/",
}
THREAD_STATE = threading.local()


class IxbrlFacts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current = None
        self.facts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower().endswith("nonfraction"):
            self.current = {key.lower(): value for key, value in attrs}
            self.current["text"] = ""

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"] += data

    def handle_endtag(self, tag):
        if self.current is not None and tag.lower().endswith("nonfraction"):
            self.facts.append(self.current)
            self.current = None


def main():
    parser = argparse.ArgumentParser(description="Import BSE fallback fundamentals for NSE-listed companies.")
    parser.add_argument("--to-date", default=date.today().isoformat())
    parser.add_argument("--symbol", help="Optional NSE symbol.")
    parser.add_argument("--shareholding-only", action="store_true")
    parser.add_argument("--financial-only", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.15)
    parser.add_argument("--workers", type=int, default=4, help="Concurrent BSE sessions; use 1 for serial import.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--raw-dir", default=str(DEFAULT_RAW_DIR))
    args = parser.parse_args()
    if args.shareholding_only and args.financial_only:
        raise SystemExit("Choose at most one of --shareholding-only and --financial-only.")

    cutoff = date.fromisoformat(args.to_date)
    db_path = Path(args.db).resolve()
    raw_dir = Path(args.raw_dir).resolve()
    raw_dir.mkdir(parents=True, exist_ok=True)
    if args.workers < 1 or args.workers > 8:
        raise SystemExit("--workers must be between 1 and 8.")
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.executescript(nse_fundamentals.SCHEMA)
    nse_fundamentals.ensure_fundamental_columns(conn)
    companies = [dict(row) for row in fallback_companies(conn, args.symbol)]
    if args.limit:
        companies = companies[:args.limit]
    totals = {"companies": len(companies), "shares": 0, "financials": 0, "failed": 0}
    conn.close()
    worker_args = (db_path, raw_dir, cutoff, args.financial_only, args.shareholding_only, args.sleep)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(process_company, company, *worker_args) for company in companies]
        for future in concurrent.futures.as_completed(futures):
            symbol, shares, financials, error = future.result()
            totals["shares"] += shares
            totals["financials"] += financials
            if error:
                totals["failed"] += 1
                print(f"BSE fallback failed for {symbol}: {error}")

    conn = sqlite3.connect(db_path, timeout=60)
    nse_fundamentals.refresh_all_growth(conn)
    conn.commit()
    conn.close()
    print("BSE fallback import complete")
    print(f"Companies checked: {totals['companies']:,}")
    print(f"Share-count filings imported: {totals['shares']:,}")
    print(f"Financial periods imported: {totals['financials']:,}")
    print(f"Company failures: {totals['failed']:,}")


def worker_session():
    if not hasattr(THREAD_STATE, "session"):
        THREAD_STATE.session = requests.Session(impersonate="chrome")
        THREAD_STATE.session.get(BSE_SITE + "/", timeout=30)
    return THREAD_STATE.session


def process_company(company, db_path, raw_dir, cutoff, financial_only, shareholding_only, sleep_seconds):
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA busy_timeout = 60000")
    shares = 0
    financials = 0
    error = None
    try:
        session = worker_session()
        if not financial_only and not has_nse_shares(conn, company["symbol"], cutoff):
            shares = import_shareholding(conn, session, raw_dir, company, cutoff)
            conn.commit()
        if not shareholding_only and not has_complete_quarter_growth(conn, company["symbol"], cutoff):
            financials = import_quarter_pair(conn, session, raw_dir, company, cutoff)
            conn.commit()
    except Exception as exc:
        conn.rollback()
        error = str(exc)
    finally:
        conn.close()
        time.sleep(sleep_seconds)
    return company["symbol"], shares, financials, error


def fallback_companies(conn, symbol=None):
    params = []
    symbol_clause = ""
    if symbol:
        symbol_clause = "AND nse.symbol = ?"
        params.append(symbol.upper())
    return conn.execute(
        f"""
        SELECT nse.symbol, nse.name, nse.isin, bse.exchange_code AS bse_code
        FROM instruments AS nse
        JOIN instruments AS bse
          ON bse.exchange = 'BSE' AND bse.isin = nse.isin
         AND bse.exchange_code IS NOT NULL AND bse.exchange_code != ''
        WHERE nse.exchange = 'NSE' AND nse.series = 'EQ' AND nse.isin LIKE 'INE%'
          AND nse.last_trade_date = (
            SELECT MAX(prices.trade_date)
            FROM daily_prices AS prices
            JOIN instruments AS latest ON latest.id = prices.instrument_id
            WHERE latest.exchange = 'NSE'
          )
          {symbol_clause}
        GROUP BY nse.symbol
        ORDER BY nse.symbol
        """,
        params,
    ).fetchall()


def has_nse_shares(conn, symbol, cutoff):
    return bool(conn.execute(
        """SELECT 1 FROM share_capital_filings
           WHERE symbol = ? AND outstanding_shares IS NOT NULL
             AND available_at <= ? AND source_exchange = 'NSE' LIMIT 1""",
        (symbol, cutoff.isoformat() + " 23:59:59"),
    ).fetchone())


def has_complete_quarter_growth(conn, symbol, cutoff):
    return bool(conn.execute(
        """SELECT 1 FROM company_fundamentals
           WHERE symbol = ? AND available_at <= ? AND source_exchange = 'NSE'
             AND revenue_growth_yoy IS NOT NULL AND pat_growth_yoy IS NOT NULL
           LIMIT 1""",
        (symbol, cutoff.isoformat() + " 23:59:59"),
    ).fetchone())


def bse_get(session, endpoint, params):
    response = session.get(f"{BSE_API}/{endpoint}/w?{urlencode(params)}", headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def import_shareholding(conn, session, raw_dir, company, cutoff):
    payload = bse_get(session, "Corp_Shareholding_ng", {
        "scripcode": company["bse_code"], "flag": "0", "indtype": "",
    })
    filings = []
    for row in payload.get("Table", []):
        available_at = parse_bse_datetime(row.get("D") or row.get("broadcastTime"))
        period_end = parse_bse_date(row.get("EndDate"))
        attachment = str(row.get("XBRLAttachment") or "")
        if available_at and period_end and available_at.date() <= cutoff and attachment:
            filings.append((available_at, period_end, attachment, row))
    if not filings:
        return 0
    available_at, period_end, attachment, metadata = max(filings, key=lambda item: item[0])
    url = BSE_SITE + (attachment if attachment.startswith("/") else "/" + attachment)
    destination = raw_dir / "shareholding" / company["symbol"] / Path(attachment).name
    if not destination.exists():
        response = session.get(url, headers={"Referer": BSE_SITE + "/"}, timeout=60)
        response.raise_for_status()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.content)
    shares = parse_bse_outstanding_shares(destination.read_text(encoding="utf-8", errors="replace"))
    if not shares:
        raise ValueError("BSE iXBRL did not contain total outstanding shares")
    filing_id = f"BSE-SHP-{company['bse_code']}-{available_at:%Y%m%d%H%M%S}"
    store_filing(conn, filing_id, "shareholding", company, period_end, available_at, url, destination, metadata)
    conn.execute(
        """INSERT OR REPLACE INTO share_capital_filings
           (filing_id, symbol, as_of_date, available_at, outstanding_shares,
            promoter_pct, public_pct, source_exchange, source_reference)
           VALUES (?, ?, ?, ?, ?, NULL, NULL, 'BSE', ?)""",
        (filing_id, company["symbol"], period_end.isoformat(), available_at.isoformat(sep=" "), shares, url),
    )
    return 1


def parse_bse_outstanding_shares(content):
    parser = IxbrlFacts()
    parser.feed(content)
    preferred = []
    fallback = []
    for fact in parser.facts:
        concept = str(fact.get("name") or "").split(":")[-1]
        context = str(fact.get("contextref") or "")
        value = nse_fundamentals.to_number(fact.get("text"))
        if value is None:
            continue
        scale = int(fact.get("scale") or 0)
        value *= 10 ** scale
        if concept == "NumberOfShares" and "ShareholdingPattern" in context:
            preferred.append(value)
        elif concept == "NumberOfFullyPaidUpEquityShares" and "ShareholdingPattern" in context:
            fallback.append(value)
    return max(preferred or fallback, default=None)


def import_quarter_pair(conn, session, raw_dir, company, cutoff):
    latest_qid = quarter_id_for_cutoff(cutoff)
    imported = 0
    for qid in (latest_qid - 4, latest_qid):
        payload = bse_get(session, "Corp_detailedResult_Transpose_ng", {
            "Scrip_cd": company["bse_code"], "Qtr": f"{qid:.2f}",
        })
        parsed = parse_bse_financial_result(payload)
        if not parsed:
            continue
        available_at = result_available_at(session, company["bse_code"], parsed["period_end"], cutoff)
        if not available_at:
            continue
        filing_id = f"BSE-FIN-{company['bse_code']}-{qid}"
        raw_path = raw_dir / "financial" / company["symbol"] / f"{filing_id}.json"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
        url = f"{BSE_API}/Corp_detailedResult_Transpose_ng/w?" + urlencode({
            "Scrip_cd": company["bse_code"], "Qtr": f"{qid:.2f}",
        })
        store_filing(conn, filing_id, "financial", company, parsed["period_end"], available_at, url, raw_path, payload)
        conn.execute(
            """INSERT OR REPLACE INTO company_fundamentals (
                 filing_id, symbol, period_start, period_end, available_at, consolidated,
                 revenue, pat, pbt, finance_cost, ebit, current_debt, noncurrent_debt,
                 total_debt, equity, capital_employed, debt_to_equity, roce, roce_method,
                 source_exchange, source_reference
               ) VALUES (?, ?, ?, ?, ?, 'BSE structured result', ?, ?, ?, ?, ?,
                         NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 'BSE', ?)""",
            (filing_id, company["symbol"], parsed["period_start"].isoformat(),
             parsed["period_end"].isoformat(), available_at.isoformat(sep=" "),
             parsed["revenue"], parsed["pat"], parsed["pbt"], parsed["finance_cost"],
             parsed["ebit"], url),
        )
        imported += 1
    return imported


def parse_bse_financial_result(payload):
    rows = payload.get("table1", []) if isinstance(payload, dict) else []
    if not rows:
        return None
    meta = {row.get("fld_desc"): row.get("Value") for row in rows if row.get("Header") == "2"}
    lines = {row.get("fld_desc"): nse_fundamentals.to_number(row.get("Value")) for row in rows if row.get("Header") != "2"}
    period_start = parse_short_date(meta.get("Date Begin"))
    period_end = parse_short_date(meta.get("Date End"))
    revenue = lines.get("Net Sales/Revenue From Operations")
    pat = lines.get("Net Profit (+)/ Loss (-) from Ordinary Activities after Tax")
    pbt = lines.get("Profit (+)/ Loss (-) from Ordinary Activities before Tax")
    finance_cost = lines.get("Finance Costs")
    if not period_start or not period_end or revenue is None or pat is None:
        return None
    finance_cost = abs(finance_cost) if finance_cost is not None else None
    ebit = pbt + finance_cost if pbt is not None and finance_cost is not None else None
    return {"period_start": period_start, "period_end": period_end, "revenue": revenue,
            "pat": pat, "pbt": pbt, "finance_cost": finance_cost, "ebit": ebit}


def result_available_at(session, bse_code, period_end, cutoff):
    start = period_end + timedelta(days=1)
    end = min(cutoff, period_end + timedelta(days=150))
    if start > end:
        return None
    payload = bse_get(session, "AnnSubCategoryGetData", {
        "pageno": 1, "strCat": "Result", "strPrevDate": start.strftime("%Y%m%d"),
        "strScrip": bse_code, "strSearch": "P", "strToDate": end.strftime("%Y%m%d"),
        "strType": "C", "subcategory": "-1",
    })
    candidates = []
    for row in payload.get("Table", []):
        stamp = parse_bse_datetime(row.get("NEWS_DT") or row.get("DT_TM"))
        headline = str(row.get("HEADLINE") or row.get("NEWSSUB") or "")
        if stamp and stamp.date() <= cutoff and period_in_headline(period_end, headline):
            candidates.append(stamp)
    return min(candidates, default=None)


def period_in_headline(period_end, headline):
    normalized = re.sub(r"[^a-z0-9]", "", headline.lower())
    forms = (
        period_end.strftime("%B%d%Y"), period_end.strftime("%d%B%Y"),
        period_end.strftime("%B%Y"),
    )
    return any(re.sub(r"[^a-z0-9]", "", form.lower()) in normalized for form in forms)


def quarter_id_for_cutoff(cutoff):
    completed_month = (cutoff.month // 3) * 3
    year = cutoff.year
    if completed_month and cutoff < date(year, completed_month, calendar.monthrange(year, completed_month)[1]):
        completed_month -= 3
    if completed_month == 0:
        completed_month = 12
        year -= 1
    months_from_june_2025 = (year * 12 + completed_month) - (2025 * 12 + 6)
    return 126 + months_from_june_2025 // 3


def store_filing(conn, filing_id, filing_type, company, period_end, available_at, url, raw_path, metadata):
    conn.execute(
        """INSERT OR REPLACE INTO fundamental_filings (
             filing_id, filing_type, symbol, company_name, period_start, period_end,
             available_at, consolidated, audited, revision_type, xbrl_url, raw_path,
             parse_status, parse_message, source_json, imported_at, source_exchange, source_reference
           ) VALUES (?, ?, ?, ?, NULL, ?, ?, NULL, NULL, NULL, ?, ?,
                     'parsed', NULL, ?, CURRENT_TIMESTAMP, 'BSE', ?)""",
        (filing_id, filing_type, company["symbol"], company["name"], period_end.isoformat(),
         available_at.isoformat(sep=" "), url, str(raw_path), json.dumps(metadata, ensure_ascii=True), url),
    )


def parse_bse_datetime(value):
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    for fmt in ("%b %d %Y %I:%M%p", "%d-%b-%Y %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def parse_bse_date(value):
    stamp = parse_bse_datetime(value)
    return stamp.date() if stamp else None


def parse_short_date(value):
    try:
        return datetime.strptime(str(value or ""), "%d-%b-%y").date()
    except ValueError:
        return None


if __name__ == "__main__":
    main()

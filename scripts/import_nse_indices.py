import argparse
import csv
import io
import sqlite3
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / 'data' / 'stock_analysis_exchange.sqlite3'
DEFAULT_RAW_DIR = ROOT / 'data' / 'raw' / 'nse_indices'

INDEXES = [
    ('nifty50', 'Nifty 50', 'Large cap benchmark', 'ind_nifty50list.csv'),
    ('niftynext50', 'Nifty Next 50', 'Next 50 large cap stocks', 'ind_niftynext50list.csv'),
    ('nifty100', 'Nifty 100', 'Top 100 large cap universe', 'ind_nifty100list.csv'),
    ('nifty200', 'Nifty 200', 'Top 200 broad-market universe', 'ind_nifty200list.csv'),
    ('nifty500', 'Nifty 500', 'Broad NSE investable universe', 'ind_nifty500list.csv'),
    ('niftytotalmarket', 'Nifty Total Market', 'Total NSE broad-market universe', 'ind_niftytotalmarket_list.csv'),
    ('nifty500multicap502525', 'Nifty 500 Multicap 50:25:25', 'Large, mid, and small cap balanced universe', 'ind_nifty500Multicap502525_list.csv'),
    ('nifty500largemidsmallequalcap', 'Nifty500 LargeMidSmall Equal-Cap Weighted', 'Equal-cap large, mid, and small universe', 'ind_nifty500LargeMidSmallEqualCapWeighted_list.csv'),
    ('niftymidcap50', 'Nifty Midcap 50', 'Midcap 50 universe', 'ind_niftymidcap50list.csv'),
    ('niftymidcap100', 'Nifty Midcap 100', 'Midcap 100 universe', 'ind_niftymidcap100list.csv'),
    ('niftymidcap150', 'Nifty Midcap 150', 'Midcap 150 universe', 'ind_niftymidcap150list.csv'),
    ('niftymidcapselect', 'Nifty Midcap Select', 'Liquid midcap selection', 'ind_niftymidcapselect_list.csv'),
    ('niftysmallcap50', 'Nifty Smallcap 50', 'Smallcap 50 universe', 'ind_niftysmallcap50list.csv'),
    ('niftysmallcap100', 'Nifty Smallcap 100', 'Smallcap 100 universe', 'ind_niftysmallcap100list.csv'),
    ('niftysmallcap250', 'Nifty Smallcap 250', 'Smallcap 250 universe', 'ind_niftysmallcap250list.csv'),
    ('niftymicrocap250', 'Nifty Microcap 250', 'Microcap 250 universe', 'ind_niftymicrocap250_list.csv'),
    ('niftylargemidcap250', 'Nifty LargeMidcap 250', 'Large and midcap 250 universe', 'ind_niftylargemidcap250list.csv'),
    ('niftymidsmallcap400', 'Nifty MidSmallcap 400', 'Mid and smallcap 400 universe', 'ind_niftymidsmallcap400list.csv'),
]

SCHEMA = '''
CREATE TABLE IF NOT EXISTS stock_groups (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  kind TEXT NOT NULL DEFAULT 'custom',
  source TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS stock_group_members (
  group_id TEXT NOT NULL,
  exchange TEXT NOT NULL DEFAULT 'NSE',
  symbol TEXT NOT NULL,
  name TEXT,
  weight REAL,
  PRIMARY KEY (group_id, exchange, symbol),
  FOREIGN KEY (group_id) REFERENCES stock_groups(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_stock_group_members_symbol ON stock_group_members(exchange, symbol);
'''

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
    'Accept': 'text/csv,application/zip,*/*',
}


def main():
    parser = argparse.ArgumentParser(description='Import NSE index constituent groups into SQLite.')
    parser.add_argument('--db', default=str(DEFAULT_DB))
    parser.add_argument('--raw-dir', default=str(DEFAULT_RAW_DIR))
    parser.add_argument('--no-download', action='store_true')
    args = parser.parse_args()

    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    conn.executescript(SCHEMA)

    total_members = 0
    for group_id, name, description, filename in INDEXES:
        path = raw_dir / filename
        if not args.no_download or not path.exists() or path.stat().st_size == 0:
            data = download(filename)
            if not data:
                print(f'Skipped {name}: file unavailable')
                continue
            path.write_bytes(data)
        members = parse_members(path)
        save_group(conn, group_id, name, description, filename, members)
        conn.commit()
        total_members += len(members)
        print(f'Imported {name}: {len(members)} symbols')

    print('Index import complete')
    print(f'Groups: {conn.execute("select count(*) from stock_groups").fetchone()[0]}')
    print(f'Memberships: {conn.execute("select count(*) from stock_group_members").fetchone()[0]}')
    print(f'Imported memberships this run: {total_members}')
    conn.close()


def download(filename):
    urls = [
        f'https://archives.nseindia.com/content/indices/{filename}',
        f'https://www.niftyindices.com/IndexConstituent/{filename}',
    ]
    for url in urls:
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=30) as response:
                if response.status != 200:
                    continue
                data = response.read()
                if data[:2] == b'PK':
                    with zipfile.ZipFile(io.BytesIO(data)) as archive:
                        member = next((m for m in archive.namelist() if m.lower().endswith('.csv')), None)
                        return archive.read(member) if member else None
                if len(data) > 20:
                    return data
        except (HTTPError, URLError, TimeoutError, OSError):
            continue
    return None


def parse_members(path):
    with path.open('r', newline='', encoding='utf-8-sig') as handle:
        reader = csv.DictReader(handle)
        members = []
        for row in reader:
            symbol = clean(row.get('Symbol') or row.get('SYMBOL') or row.get('symbol'))
            if not symbol:
                continue
            name = clean(row.get('Company Name') or row.get('Company') or row.get('Security Name') or row.get('Name'))
            weight = to_float(row.get('Weightage') or row.get('Weight') or row.get('% Weight'))
            members.append({'symbol': symbol, 'name': name, 'weight': weight})
        return members


def save_group(conn, group_id, name, description, source, members):
    conn.execute(
        '''
        INSERT INTO stock_groups (id, name, description, kind, source, updated_at)
        VALUES (?, ?, ?, 'nse_index', ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
          name = excluded.name,
          description = excluded.description,
          kind = excluded.kind,
          source = excluded.source,
          updated_at = CURRENT_TIMESTAMP
        ''',
        (group_id, name, description, source),
    )
    conn.execute('DELETE FROM stock_group_members WHERE group_id = ?', (group_id,))
    conn.executemany(
        '''
        INSERT OR REPLACE INTO stock_group_members (group_id, exchange, symbol, name, weight)
        VALUES (?, 'NSE', ?, ?, ?)
        ''',
        [(group_id, m['symbol'], m['name'], m['weight']) for m in members],
    )


def clean(value):
    return str(value or '').strip().upper()


def to_float(value):
    text = str(value or '').strip().replace('%', '').replace(',', '')
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


if __name__ == '__main__':
    main()
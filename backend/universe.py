"""Provider-backed NSE/BSE discovery. Downloaded metadata is not a price feed.

No hard-coded stock universe, guessed ISINs, or packaged vendor master. A refresh
is atomic: a failed download/validation preserves the last successful catalogue.
"""
from __future__ import annotations
import gzip
import io
import json
import math
import sqlite3
from itertools import chain
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from .data import IST
from .market import timestamp, finite

MASTER_URL = 'https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz'
SUSPENDED_URL = 'https://assets.upstox.com/market-quote/instruments/exchange/suspended-instrument.json.gz'
SEGMENTS = {'NSE_EQ', 'BSE_EQ', 'NSE_INDEX', 'BSE_INDEX'}
NORMALIZATION_VERSION = 3


def normalize_contracts(rows, suspended=None):
    """Keep derivative identities separate from searchable cash listings."""
    blocked = {r.get('instrument_key') for r in (suspended or []) if isinstance(r, dict)}
    result = {}
    for r in rows:
        if not isinstance(r, dict) or r.get('segment') != 'NSE_FO': continue
        kind = r.get('instrument_type'); key = str(r.get('instrument_key', ''))
        underlying = str(r.get('underlying_key', '')); expiry = timestamp(r.get('expiry'))
        lot = finite(r.get('lot_size')); strike = finite(r.get('strike_price'))
        if (kind not in ('CE', 'PE', 'FUT') or not key.startswith('NSE_FO|') or len(key) > 110
                or not underlying.startswith(('NSE_EQ|', 'NSE_INDEX|')) or not expiry
                or not lot or lot < 1 or lot != int(lot) or key in blocked
                or (kind != 'FUT' and (not strike or strike <= 0))): continue
        result[key] = {'instrument_key': key, 'underlying_key': underlying,
                       'symbol': str(r.get('trading_symbol', '')), 'instrument_type': kind,
                       'expiry': expiry.date().isoformat(), 'lot_size': int(lot),
                       'strike': strike if kind != 'FUT' else None}
    return list(result.values())

def download_master(url: str) -> tuple[list, dict]:
    if url not in (MASTER_URL, SUSPENDED_URL):
        raise ValueError('Only the documented instrument-master URLs are allowed.')
    try:
        with urlopen(Request(url, headers={'User-Agent': 'IndiaQuantResearch/2.0', 'Accept': 'application/gzip'}), timeout=35) as response:
            if not response.geturl().startswith('https://assets.upstox.com/'):
                raise ValueError('Unexpected provider redirect.')
            compressed = response.read(32_000_001)
            if len(compressed) > 32_000_000:
                raise ValueError('Instrument master exceeded the download limit.')
            headers = {'last_modified': response.headers.get('Last-Modified'), 'http_date': response.headers.get('Date')}
        if compressed[:2] == b'\x1f\x8b':
            with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as f:
                raw = f.read(180_000_001)
        else:
            raw = compressed
        if len(raw) > 180_000_000:
            raise ValueError('Expanded instrument master exceeded the size limit.')
        rows = json.loads(raw)
        if not isinstance(rows, list):
            raise ValueError('Provider master must contain a JSON list.')
        return rows, headers
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        code = getattr(exc, 'code', None)
        raise ValueError(f'Instrument-master download failed{f" (HTTP {code})" if code else ""}. Your previous catalogue was preserved.') from None


def normalize_master(rows: list, suspended: list | None = None) -> list[dict]:
    if not isinstance(rows, list) or len(rows) > 600000:
        raise ValueError('Invalid instrument-master structure/size.')
    suspended = suspended or []
    if not isinstance(suspended, list) or len(suspended) > 600000:
        raise ValueError('Invalid suspended-master structure/size.')
    blocked = {}
    for r in suspended:
        if isinstance(r, dict):
            blocked.setdefault(str(r.get('instrument_key', '')), []).append(
                (str(r.get('instrument_type') or 'UNKNOWN').upper(), str(r.get('exchange_token') or '')))
    out = {}; ranks = {}
    # Keep suspended instruments searchable and visibly blocked, even if absent in BOD.
    for active, r in chain(((True, r) for r in rows), ((False, r) for r in suspended)):
        if not isinstance(r, dict) or r.get('segment') not in SEGMENTS:
            continue
        key = str(r.get('instrument_key', '')); segment = r['segment']
        name = str(r.get('name', '')).strip(); symbol = str(r.get('trading_symbol') or name).strip()
        if not key.startswith(segment + '|') or not 1 <= len(key) <= 110 or not symbol or len(symbol) > 140:
            raise ValueError('Invalid instrument identity in provider master.')
        lot = float(r.get('lot_size') or 1)
        if not math.isfinite(lot) or lot < 1 or int(lot) != lot:
            raise ValueError('Invalid lot size in instrument master.')
        kind = 'INDEX' if segment.endswith('_INDEX') else 'CASH'
        isin = str(r.get('isin') or '')
        typ = str(r.get('instrument_type') or 'UNKNOWN').upper()
        token = str(r.get('exchange_token') or '')
        # Different exchange series can share the same ISIN-based instrument_key.
        # A suspended BL/BE/etc. series must not suspend the active EQ listing.
        is_suspended = not active or any(
            (bt == 'UNKNOWN' or typ == 'UNKNOWN' or bt == typ)
            and (not token or not bk or bk == token) for bt, bk in blocked.get(key, []))
        security = str(r.get('security_type') or 'UNKNOWN')
        # Conservative research eligibility, not a guarantee of brokerage permissions.
        simple_equity = kind == 'CASH' and isin.startswith('INE') and typ in {'EQ', 'A', 'B', 'X'} and lot == 1
        item = {'instrument_key': key, 'exchange': segment.split('_')[0], 'segment': segment,
                'symbol': symbol, 'name': name, 'isin': isin, 'instrument_type': typ, 'exchange_token': token,
                'security_type': security, 'lot_size': int(lot), 'kind': kind,
                'suspended': is_suspended, 'simple_equity': simple_equity,
                'cas_eligible': bool(r.get('cas_eligible', False))}
        rank = (active, not is_suspended, simple_equity)
        if key not in out or rank > ranks[key]:
            out[key] = item
            ranks[key] = rank
    return sorted(out.values(), key=lambda r: (r['exchange'], r['symbol'], r['instrument_key']))


class Universe:
    def __init__(self, store):
        self.store = store
        with store.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS instruments(
                    instrument_key TEXT PRIMARY KEY, exchange TEXT, symbol TEXT,
                    name TEXT, isin TEXT, kind TEXT, body TEXT);
                CREATE INDEX IF NOT EXISTS instrument_symbol ON instruments(symbol COLLATE NOCASE);
                CREATE TABLE IF NOT EXISTS catalogue_meta(key TEXT PRIMARY KEY, body TEXT);
                CREATE TABLE IF NOT EXISTS watchlist(instrument_key TEXT PRIMARY KEY, added TEXT);
                CREATE TABLE IF NOT EXISTS market_history(instrument_key TEXT, timeframe TEXT,
                    dataset_id TEXT, updated TEXT, PRIMARY KEY(instrument_key,timeframe));
                CREATE TABLE IF NOT EXISTS signal_audit(id TEXT PRIMARY KEY, created TEXT, body TEXT);
                CREATE TABLE IF NOT EXISTS derivative_contracts(
                    instrument_key TEXT PRIMARY KEY, underlying_key TEXT, expiry TEXT, body TEXT);
                CREATE INDEX IF NOT EXISTS derivative_underlying ON derivative_contracts(underlying_key,expiry);
            ''')

    def replace(self, rows, suspended=None, source_meta=None):
        cleaned = normalize_master(rows, suspended)
        contracts = normalize_contracts(rows, suspended)
        if not cleaned or not {'NSE', 'BSE'}.issubset({r['exchange'] for r in cleaned}):
            raise ValueError('Catalogue must contain both NSE and BSE records; old cache retained.')
        stamp = self.store.now()
        meta = {'fetched_at': stamp, 'source': MASTER_URL, 'suspension_checked': suspended is not None,
                'normalization_version': NORMALIZATION_VERSION,
                'source_headers': source_meta or {}, 'counts': {ex: sum(r['exchange'] == ex for r in cleaned) for ex in ('NSE', 'BSE')},
                'total': len(cleaned), 'coverage': 'One preferred listing per provider key: active regular equity first, plus suspended-only keys and indices. Suspension is matched by series/token. Not an exchange-wide completeness certification.'}
        with self.store.db() as db:
            db.execute('DELETE FROM instruments')
            db.execute('DELETE FROM derivative_contracts')
            db.executemany('INSERT INTO derivative_contracts VALUES(?,?,?,?)',
                           [(r['instrument_key'], r['underlying_key'], r['expiry'], json.dumps(r)) for r in contracts])
            meta['derivative_contracts'] = len(contracts)
            db.executemany('INSERT INTO instruments VALUES(?,?,?,?,?,?,?)',
                [(r['instrument_key'], r['exchange'], r['symbol'], r['name'], r['isin'], r['kind'], json.dumps(r)) for r in cleaned])
            db.execute('INSERT OR REPLACE INTO catalogue_meta VALUES(?,?)', ('current', json.dumps(meta)))
            self.store.log(db, 'CATALOGUE_REFRESH', {'counts': meta['counts'], 'suspension_checked': meta['suspension_checked']})
        return self.status()

    def sync(self):
        rows, headers = download_master(MASTER_URL)
        # Do not silently suppress failure of the suspension check.
        suspended, _ = download_master(SUSPENDED_URL)
        return self.replace(rows, suspended, headers)

    def status(self):
        with self.store.db() as db:
            r = db.execute('SELECT body FROM catalogue_meta WHERE key="current"').fetchone()
        if not r:
            return {'total': 0, 'counts': {'NSE': 0, 'BSE': 0}, 'fetched_at': None, 'stale': True, 'suspension_checked': False}
        meta = json.loads(r['body'])
        age = (datetime.now(IST) - datetime.fromisoformat(meta['fetched_at'])).total_seconds()
        refresh_required = meta.get('normalization_version') != NORMALIZATION_VERSION
        meta.update(age_hours=round(max(age, 0) / 3600, 2), stale=age > 36 * 3600 or age < -60 or refresh_required,
                    refresh_required=refresh_required)
        return meta

    def get(self, key):
        with self.store.db() as db:
            r = db.execute('SELECT body FROM instruments WHERE instrument_key=?', (key,)).fetchone()
        if not r:
            raise ValueError('Instrument is absent from the current catalogue. Refresh it; do not guess a broker identifier.')
        return json.loads(r['body'])

    def eligible(self):
        with self.store.db() as db:
            rows = db.execute("SELECT body FROM instruments WHERE exchange='NSE' AND kind='CASH' ORDER BY symbol").fetchall()
        return [r for row in rows if (r := json.loads(row['body'])).get('simple_equity') and not r.get('suspended')]

    def contracts(self, key):
        today = datetime.now(IST).date().isoformat()
        with self.store.db() as db:
            rows = db.execute('SELECT body FROM derivative_contracts WHERE underlying_key=? AND expiry>=? ORDER BY expiry', (key, today)).fetchall()
        return [json.loads(r['body']) for r in rows]

    def fo_underlyings(self):
        today = datetime.now(IST).date().isoformat()
        with self.store.db() as db:
            rows = db.execute('SELECT DISTINCT i.body FROM instruments i JOIN derivative_contracts d ON i.instrument_key=d.underlying_key WHERE d.expiry>=?', (today,)).fetchall()
        return [r for row in rows if not (r := json.loads(row['body'])).get('suspended')
                and (r.get('simple_equity') or r['kind'] == 'INDEX')]

    def search(self, query='', exchange='ALL', kind='CASH', offset=0, limit=50):
        if exchange not in ('ALL', 'NSE', 'BSE') or kind not in ('ALL', 'CASH', 'INDEX'):
            raise ValueError('Invalid catalogue filter.')
        if not 0 <= offset <= 100000 or not 1 <= limit <= 100 or len(query) > 100:
            raise ValueError('Search range is invalid.')
        q = query.strip().upper(); escaped = q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        where = ['1=1']; args = []
        if exchange != 'ALL': where.append('exchange=?'); args.append(exchange)
        if kind != 'ALL': where.append('kind=?'); args.append(kind)
        if q:
            where.append("(UPPER(symbol) LIKE ? ESCAPE '\\' OR UPPER(name) LIKE ? ESCAPE '\\' OR UPPER(isin) LIKE ? ESCAPE '\\')")
            args += ['%' + escaped + '%'] * 3
        clause = ' AND '.join(where)
        with self.store.db() as db:
            count = db.execute('SELECT COUNT(*) FROM instruments WHERE ' + clause, args).fetchone()[0]
            result = db.execute('SELECT body FROM instruments WHERE ' + clause + ' ORDER BY CASE WHEN UPPER(symbol)=? THEN 0 ELSE 1 END,symbol,exchange LIMIT ? OFFSET ?', args + [q, limit, offset]).fetchall()
        return {'items': [json.loads(r['body']) for r in result], 'total': count, 'offset': offset,
                'next_offset': offset + limit if offset + limit < count else None}

    def watch(self):
        with self.store.db() as db:
            rs = db.execute('SELECT w.instrument_key,w.added,i.body FROM watchlist w LEFT JOIN instruments i USING(instrument_key) ORDER BY w.added').fetchall()
        return [dict(json.loads(r['body']), added=r['added']) if r['body'] else {'instrument_key': r['instrument_key'], 'symbol': r['instrument_key'], 'unavailable': True, 'added': r['added']} for r in rs]

    def set_watch(self, key, enabled=True):
        if enabled: self.get(key)
        with self.store.db() as db:
            if enabled:
                n = db.execute('SELECT COUNT(*) FROM watchlist').fetchone()[0]
                present = db.execute('SELECT 1 FROM watchlist WHERE instrument_key=?', (key,)).fetchone()
                if n >= 25 and not present:
                    raise ValueError('Local live watchlist limit: 25 instruments. Catalogue search is not limited to 25.')
                db.execute('INSERT OR IGNORE INTO watchlist VALUES(?,?)', (key, self.store.now()))
            else: db.execute('DELETE FROM watchlist WHERE instrument_key=?', (key,))
        return self.watch()

    def link(self, key, timeframe, dataset_id):
        self.get(key)
        with self.store.db() as db:
            db.execute('INSERT OR REPLACE INTO market_history VALUES(?,?,?,?)', (key, timeframe, dataset_id, self.store.now()))

    def history(self, key, timeframe):
        with self.store.db() as db:
            r = db.execute('SELECT dataset_id FROM market_history WHERE instrument_key=? AND timeframe=?', (key, timeframe)).fetchone()
        return self.store.dataset(r['dataset_id']) if r else None

    def instrument_for_dataset(self, ident):
        with self.store.db() as db:
            r = db.execute('SELECT instrument_key FROM market_history WHERE dataset_id=?', (ident,)).fetchone()
        return r['instrument_key'] if r else None

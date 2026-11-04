"""Current index membership and uncapped catalogue-backed stock discovery."""
import csv
import io
import json
import re
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError

from .data import IST, parse_time

SCOPES = {
    'nifty500': ('Nifty 500', 'ind_nifty500list.csv', 400),
    'nifty200': ('Nifty 200', 'ind_nifty200list.csv', 150),
    'nifty100': ('Nifty 100', 'ind_nifty100list.csv', 75),
    'nifty50': ('Nifty 50', 'ind_nifty50list.csv', 40),
    'all_nse': ('All regular NSE stocks', None, 0),
    'fo': ('All NSE F&O stocks and indices', None, 0),
}


def download_members(scope):
    _, filename, minimum = SCOPES[scope]
    errors = []
    for base in ('https://nsearchives.nseindia.com/content/indices/',
                 'https://www.niftyindices.com/IndexConstituent/'):
        url = base + filename
        try:
            request = Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'text/csv'})
            with urlopen(request, timeout=15) as response:
                if not response.geturl().startswith(base): raise ValueError('Unexpected membership redirect.')
                raw = response.read(1_000_001)
            if len(raw) > 1_000_000: raise ValueError('Membership file is too large.')
            rows = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
            members = {}
            for row in rows:
                symbol = (row.get('Symbol') or '').strip().upper()
                isin = (row.get('ISIN Code') or '').strip()
                if re.fullmatch(r'[A-Z0-9&._-]{1,40}', symbol) and isin.startswith('INE'):
                    members[symbol] = {'symbol': symbol, 'isin': isin}
            if not minimum <= len(members) <= 650: raise ValueError('Index file is incomplete or invalid.')
            return list(members.values()), url
        except (URLError, OSError, ValueError, UnicodeError) as exc:
            errors.append(str(exc)[:100])
    raise ValueError('Official index membership could not be downloaded: ' + '; '.join(errors))


def select_universe(universe, scope='nifty500', derivatives=False):
    if scope not in SCOPES: raise ValueError('Unknown stock universe.')
    eligible = universe.eligible(); missing = []; warnings = []
    coverage = {'requested': scope, 'label': SCOPES[scope][0], 'source': universe.status().get('source'),
                'membership_as_of': None, 'fallback': False, 'warnings': warnings}
    if SCOPES[scope][1]:
        with universe.store.db() as db:
            record = db.execute('SELECT body FROM catalogue_meta WHERE key=?', ('members:' + scope,)).fetchone()
        cached = json.loads(record['body']) if record else None
        age = (datetime.now(IST) - datetime.fromisoformat(cached['fetched_at'])).total_seconds() if cached else None
        if age is None or not 0 <= age < 24 * 3600:
            try:
                members, source = download_members(scope)
                cached = {'members': members, 'source': source, 'fetched_at': universe.store.now()}
                with universe.store.db() as db:
                    db.execute('INSERT OR REPLACE INTO catalogue_meta VALUES(?,?)', ('members:' + scope, json.dumps(cached)))
            except ValueError as exc:
                warnings.append(str(exc))
                if cached and age is not None and 0 <= age < 7 * 86400:
                    warnings.append('Using cached index membership; see its download time.')
                else:
                    cached = None
        if cached:
            by_identity = {(i['symbol'], i['isin']): i for i in eligible}
            selected = []
            for member in cached['members']:
                inst = by_identity.get((member['symbol'], member['isin']))
                if inst: selected.append(inst)
                else: missing.append(member['symbol'])
            eligible = selected
            coverage.update(source=cached['source'], membership_as_of=cached['fetched_at'],
                            constituents=len(cached['members']))
        else:
            coverage.update(label='All regular NSE stocks (index download unavailable)', fallback=True)
            warnings.append('Scanning all eligible NSE listings instead of guessing index membership.')
    if derivatives or scope == 'fo':
        fo = universe.fo_underlyings()
        keys = {i['instrument_key'] for i in eligible}
        eligible = [i for i in fo if scope in ('fo', 'all_nse') or i['instrument_key'] in keys or i['kind'] == 'INDEX']
        if derivatives: coverage['label'] += ' · F&O-eligible underlyings and indices'
    coverage['selected'] = len(eligible)
    return sorted(eligible, key=lambda i: (i['kind'] != 'INDEX', i['symbol'])), missing, coverage


def discovery_basket(universe):
    """Compatibility helper for callers that only need identities."""
    instruments, missing, _ = select_universe(universe)
    return instruments, missing


def history_due(dataset, timeframe, now=None):
    """Reuse completed history until a newer candle could have completed."""
    if not dataset or not dataset.get('bars'): return True
    now = now or datetime.now(IST)
    last = parse_time(dataset['bars'][-1]['t'], timeframe)
    if timeframe == '1d':
        expected = now.date() if now.hour >= 16 else (now - timedelta(days=1)).date()
        while expected.weekday() > 4: expected -= timedelta(days=1)
        return last.date() < expected
    if now.weekday() > 4 or now.hour * 60 + now.minute < 570:
        return (now.date() - last.date()).days > 4
    minute = min(now.hour * 60 + now.minute, 930)
    expected = now.replace(hour=9, minute=15, second=0, microsecond=0) + timedelta(minutes=((minute - 555) // 15 - 1) * 15)
    return last < expected

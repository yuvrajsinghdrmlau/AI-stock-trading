"""Read-only broker data adapter, bounded polling, provenance and freshness.

Tokens remain server-side. No guessed prices, scraped exchange pages or order APIs.
"""
from __future__ import annotations
import json
import math
import os
import threading
import time
from datetime import datetime, timedelta, date
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from .data import IST, validate_bars, parse_time


def timestamp(value):
    if value is None or value == '': return None
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.replace('.', '', 1).isdigit()):
            n = float(value)
            if n > 1e11: n /= 1000
            return datetime.fromtimestamp(n, IST)
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        # Do not guess the timezone of a live quote.
        return dt.astimezone(IST) if dt.tzinfo else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def finite(value, default=None):
    try:
        f = float(value)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def normalize_quote(raw, instrument_key, now=None):
    now = now or datetime.now(IST)
    if not isinstance(raw, dict): return {'instrument_key': instrument_key, 'fresh': False, 'status': 'MISSING', 'last_price': None}
    feed = timestamp(raw.get('timestamp')); trade = timestamp(raw.get('last_trade_time'))
    age = (now - feed).total_seconds() if feed else None
    trade_age = (now - trade).total_seconds() if trade else None
    ltp = finite(raw.get('last_price'))
    bid_rows = raw.get('depth', {}).get('buy', []); ask_rows = raw.get('depth', {}).get('sell', [])
    bids = [finite(r.get('price')) for r in bid_rows if finite(r.get('quantity'), 0) > 0]
    asks = [finite(r.get('price')) for r in ask_rows if finite(r.get('quantity'), 0) > 0]
    bid = max((b for b in bids if b and b > 0), default=None)
    ask = min((a for a in asks if a and a > 0), default=None)
    spread = (ask - bid) / ((ask + bid) / 2) * 10000 if bid and ask and ask >= bid else None
    fresh = bool(ltp and ltp > 0 and age is not None and -5 <= age <= 60 and trade_age is not None and -5 <= trade_age <= 120)
    status = 'FRESH_SNAPSHOT' if fresh else 'STALE_OR_UNVERIFIED'
    return {'instrument_key': instrument_key, 'last_price': ltp, 'bid': bid, 'ask': ask,
            'spread_bps': spread, 'volume': finite(raw.get('volume')),
            'open_interest': finite(raw.get('oi', raw.get('open_interest'))),
            'feed_time': feed.isoformat() if feed else None, 'trade_time': trade.isoformat() if trade else None,
            'received_at': now.isoformat(), 'feed_age_seconds': age, 'trade_age_seconds': trade_age,
            'fresh': fresh, 'status': status, 'lower_circuit': finite(raw.get('lower_circuit_limit')),
            'upper_circuit': finite(raw.get('upper_circuit_limit')), 'net_change': finite(raw.get('net_change')),
            'source': 'Upstox full-quote REST snapshot; polling, not tick streaming'}


class BrokerData:
    def __init__(self):
        self.lock = threading.Lock(); self.last_call = 0.; self.cache = {}

    @property
    def configured(self): return bool(os.getenv('UPSTOX_ACCESS_TOKEN', '').strip())

    def get(self, path, params=None):
        token = os.getenv('UPSTOX_ACCESS_TOKEN', '').strip()
        if not token: raise ValueError('Add your own UPSTOX_ACCESS_TOKEN to .env and restart. No live data is available without it.')
        allowed = ('/v2/market-quote/quotes', '/v2/market/status/', '/v3/historical-candle/', '/v2/option/chain', '/v2/option/contract')
        if not any(path.startswith(p) for p in allowed) or '..' in path:
            raise ValueError('Unsupported read-only provider path.')
        # Serial throttle below provider rate limits; no automatic retry storm.
        with self.lock:
            wait = 1.1 - (time.monotonic() - self.last_call)
            if wait > 0: time.sleep(wait)
            self.last_call = time.monotonic()
        url = 'https://api.upstox.com' + path + (('?' + urlencode(params)) if params else '')
        req = Request(url, headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json', 'User-Agent': 'IndiaQuantResearch/2.0'})
        try:
            with urlopen(req, timeout=20) as res:
                if not res.geturl().startswith('https://api.upstox.com/'):
                    raise ValueError('Unexpected broker redirect.')
                raw = res.read(12_000_001)
                if len(raw) > 12_000_000: raise ValueError('Broker response exceeds size limit.')
                data = json.loads(raw)
        except HTTPError as exc:
            hints = {401: 'Token expired or invalid. Refresh it locally.', 403: 'Account/data permission denied.', 429: 'Provider rate limit reached; pause refresh.'}
            raise ValueError(f'Broker HTTP {exc.code}. {hints.get(exc.code, "Verify instrument, dates and account access.")}') from None
        except (URLError, TimeoutError, OSError, json.JSONDecodeError):
            raise ValueError('Broker data unavailable or response invalid. No substitute data was generated.') from None
        if not isinstance(data, dict) or data.get('status') != 'success':
            raise ValueError('Broker did not return a successful response.')
        return data.get('data')

    def quotes(self, keys):
        keys = sorted(set(keys))
        if not keys: return {}
        if len(keys) > 25: raise ValueError('Poll up to 25 watched instruments per request.')
        # Raw data cached briefly, freshness always recomputed from source timestamps.
        ck = ('quotes', tuple(keys)); cached = self.cache.get(ck)
        if cached and time.monotonic() - cached[0] < 8: raw = cached[1]
        else:
            raw = self.get('/v2/market-quote/quotes', {'instrument_key': ','.join(keys)})
            if not isinstance(raw, dict): raise ValueError('Malformed broker quotes.')
            self.cache[ck] = (time.monotonic(), raw)
        by_key = {r.get('instrument_token') or r.get('instrument_key'): r for r in raw.values() if isinstance(r, dict)}
        return {key: normalize_quote(by_key.get(key), key) for key in keys}

    def exchange_status(self, exchange):
        if exchange not in ('NSE', 'BSE'): raise ValueError('Unknown exchange.')
        ck = ('market', exchange); old = self.cache.get(ck)
        if old and time.monotonic() - old[0] < 20: return old[1]
        raw = self.get('/v2/market/status/' + exchange)
        if not isinstance(raw, dict): raise ValueError('Malformed exchange status.')
        result = {'exchange': exchange, 'status': raw.get('status', 'UNKNOWN'),
                  'cas_status': (raw.get('cas_eligible_status') or {}).get('status'), 'checked_at': datetime.now(IST).isoformat()}
        self.cache[ck] = (time.monotonic(), result)
        return result

    def history(self, key, timeframe, existing=None):
        if timeframe not in ('1d', '15m'): raise ValueError('Use daily or 15-minute history.')
        now = datetime.now(IST); today = now.date(); yesterday = today - timedelta(days=1)
        unit, interval = ('days', '1') if timeframe == '1d' else ('minutes', '15')
        old = list(existing or [])
        # Keep original training prefixes stable; refresh recent bars, exposing revisions.
        start = (parse_time(old[-1]['t'], timeframe).date() - timedelta(days=7)) if old else today - timedelta(days=2920 if timeframe == '1d' else 360)
        if old and timeframe == '15m' and parse_time(old[-1]['t'],timeframe).date()==today:
            start=today  # Only the current-session endpoint is needed within a session.
        step = timedelta(days=2920 if timeframe == '1d' else 27)
        incoming = []; cursor = start
        while cursor <= yesterday:
            end = min(yesterday, cursor + step)
            raw = self.get(f'/v3/historical-candle/{quote(key, safe="")}/{unit}/{interval}/{end.isoformat()}/{cursor.isoformat()}')
            incoming += self._candle_rows(raw)
            cursor = end + timedelta(days=1)
        # Today's daily candle is never used before its conservative completion cutoff.
        raw = self.get(f'/v3/historical-candle/intraday/{quote(key, safe="")}/{unit}/{interval}') if timeframe == '15m' else None
        if raw is not None: incoming += self._candle_rows(raw)
        if timeframe == '1d' and now.hour >= 16:
            raw = self.get(f'/v3/historical-candle/{quote(key, safe="")}/days/1/{today.isoformat()}/{today.isoformat()}')
            incoming += self._candle_rows(raw)
        if not incoming and not old: raise ValueError('No candles are available for this instrument.')
        # Provider incremental rows replace old rows explicitly, not silently deduping a CSV.
        combined = {r['t']: r for r in old}; seen = set()
        for r in incoming:
            r['t'] = parse_time(r['t'], timeframe).isoformat()
            if r['t'] in seen: raise ValueError('Provider returned duplicate candles across its responses.')
            seen.add(r['t']); combined[r['t']] = r
        if len(combined) > 15000: raise ValueError('History exceeds local 15,000-bar limit. Create a new research workspace deliberately.')
        bars, warnings = validate_bars(list(combined.values()), timeframe, now)
        warnings.append('Authorized broker candles; corporate-action adjustment and vendor correctness are not independently verified.')
        return bars, warnings

    @staticmethod
    def _candle_rows(raw):
        if not isinstance(raw, dict) or not isinstance(raw.get('candles'), list): raise ValueError('Malformed broker candle response.')
        result = []
        for row in raw['candles']:
            if not isinstance(row, list) or len(row) < 6: raise ValueError('Malformed broker candle.')
            result.append(dict(zip(('t', 'o', 'h', 'l', 'c', 'v'), row[:6])))
        return result

    def option_chain(self, key, expiry):
        try: date.fromisoformat(expiry)
        except ValueError: raise ValueError('Select an exact expiry date from the returned contract list.') from None
        if date.fromisoformat(expiry) < datetime.now(IST).date(): raise ValueError('Expired contract requested.')
        rows = self.get('/v2/option/chain', {'instrument_key': key, 'expiry_date': expiry})
        if not isinstance(rows, list): raise ValueError('Malformed option chain.')
        # Exclude provider POP fields: no independent probability validation is available.
        out = []
        for row in rows:
            r = {'strike': finite(row.get('strike_price')), 'expiry': row.get('expiry'), 'spot': finite(row.get('underlying_spot_price'))}
            for label, field in (('call', 'call_options'), ('put', 'put_options')):
                leg = row.get(field) or {}; md = leg.get('market_data') or {}; greeks = leg.get('option_greeks') or {}
                r[label] = {'instrument_key': leg.get('instrument_key'), **{k: finite(md.get(k)) for k in ('ltp', 'bid_price', 'ask_price', 'volume', 'oi')},
                            **{k: finite(greeks.get(k)) for k in ('iv', 'delta', 'theta', 'gamma', 'vega')}}
            out.append(r)
        return {'rows': sorted(out, key=lambda r: r['strike'] or 0), 'received_at': datetime.now(IST).isoformat(),
                'status': 'READ_ONLY_SNAPSHOT', 'probability': None,
                'note': 'Receipt time is not an exchange quote timestamp. No option-profit model, trade recommendation or verified live premium freshness.'}

    def expiries(self, key):
        rows = self.get('/v2/option/contract', {'instrument_key': key})
        if not isinstance(rows, list): raise ValueError('Malformed option contracts.')
        today = datetime.now(IST).date().isoformat()
        return sorted({str(r['expiry']) for r in rows if isinstance(r, dict) and str(r.get('expiry', '')) >= today})

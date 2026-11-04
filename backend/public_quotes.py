"""Latest public prices with source timestamps; never a verified broker feed."""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

from .data import IST
from .public_history import yahoo_symbol

FRESHNESS_LIMIT_SECONDS = 120
STALE_AFTER_SECONDS = 900
MAX_RESPONSE_BYTES = 1_000_000
REQUEST_TIMEOUT_SECONDS = 12


def _number(value, *, positive=False):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or (positive and number <= 0):
        return None
    return number


def normalize_public_quote(payload, instrument, now=None):
    """Keep a recent timestamp distinct from independently verified real-time data."""
    ticker = yahoo_symbol(instrument)
    now = now or datetime.now(IST)
    if now.tzinfo is None:
        raise ValueError('Quote receipt time must include its timezone.')
    now = now.astimezone(IST)
    chart = payload.get('chart') if isinstance(payload, dict) else None
    results = chart.get('result') if isinstance(chart, dict) else None
    if (not isinstance(results, list) or len(results) != 1
            or not isinstance(results[0], dict) or chart.get('error')):
        raise ValueError('No public price was returned for this listing.')
    meta = results[0].get('meta')
    venues = {'NSE': {'NSI', 'NSE'}, 'BSE': {'BSE'}}
    if (not isinstance(meta, dict)
            or str(meta.get('symbol', '')).upper() != ticker.upper()
            or meta.get('currency') != 'INR'
            or meta.get('exchangeTimezoneName') != 'Asia/Kolkata'
            or meta.get('exchangeName') not in venues[instrument['exchange']]):
        raise ValueError('Public price identity, venue, currency or timezone did not match the listing.')
    price = _number(meta.get('regularMarketPrice'), positive=True)
    if price is None:
        raise ValueError('Public source did not supply a valid latest price.')
    stamp = _number(meta.get('regularMarketTime'), positive=True)
    price_time = None
    if stamp is not None:
        try:
            price_time = datetime.fromtimestamp(stamp, IST)
        except (ValueError, OverflowError, OSError):
            pass
    age = (now - price_time).total_seconds() if price_time else None
    verified_timestamp = age is not None and age >= -5
    recent = bool(verified_timestamp and age <= FRESHNESS_LIMIT_SECONDS)
    if not verified_timestamp:
        status = 'TIMESTAMP_UNVERIFIED'
    elif recent:
        status = 'PUBLIC_RECENT'
    elif age <= STALE_AFTER_SECONDS:
        status = 'PUBLIC_DELAYED'
    else:
        status = 'PUBLIC_STALE'
    previous_close = (_number(meta.get('previousClose'), positive=True)
                      or _number(meta.get('chartPreviousClose'), positive=True))
    volume = _number(meta.get('regularMarketVolume'))
    return {
        'instrument_key': instrument['instrument_key'], 'ticker': ticker,
        'last_price': price, 'price_time': price_time.isoformat() if price_time else None,
        'trade_time': price_time.isoformat() if price_time else None, 'feed_time': None,
        'received_at': now.isoformat(), 'age_seconds': round(age, 3) if age is not None else None,
        'freshness_limit_seconds': FRESHNESS_LIMIT_SECONDS,
        'recent_until': (price_time + timedelta(seconds=FRESHNESS_LIMIT_SECONDS)).isoformat()
        if verified_timestamp else None,
        'recent': recent, 'fresh': False, 'realtime_verified': False,
        'delayed': bool(verified_timestamp and age > FRESHNESS_LIMIT_SECONDS),
        'stale': not verified_timestamp or age > STALE_AFTER_SECONDS,
        'status': status, 'market_status': 'UNVERIFIED',
        'bid': None, 'ask': None, 'spread_bps': None,
        'previous_close': previous_close,
        'change_pct': (price / previous_close - 1) * 100 if previous_close else None,
        'day_open': _number(meta.get('regularMarketOpen'), positive=True),
        'day_high': _number(meta.get('regularMarketDayHigh'), positive=True),
        'day_low': _number(meta.get('regularMarketDayLow'), positive=True),
        'volume': volume if volume is not None and volume >= 0 else None,
        'source': 'Yahoo Finance public snapshot; delay not independently verified',
        'source_url': 'https://finance.yahoo.com/quote/' + quote(ticker, safe='') + '/',
    }


def public_quote(instrument, now=None):
    """Make one bounded read-only request, with no retry or synthetic-price fallback."""
    ticker = yahoo_symbol(instrument)
    path = '/v8/finance/chart/' + quote(ticker, safe='')
    params = urlencode({'range': '1d', 'interval': '1m', 'includePrePost': 'false'})
    request = Request('https://query1.finance.yahoo.com' + path + '?' + params,
                      headers={'Accept': 'application/json',
                               'User-Agent': 'Mozilla/5.0 IndiaQuantResearch/2.1'})
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            destination = urlsplit(response.geturl())
            if (destination.scheme != 'https' or destination.netloc != 'query1.finance.yahoo.com'
                    or destination.path != path):
                raise ValueError('Unexpected public-price redirect.')
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError('Public-price response exceeded the size limit.')
            payload = json.loads(raw)
    except HTTPError as exc:
        raise ValueError(f'Public price returned HTTP {exc.code}. Refresh later.') from None
    except (URLError, TimeoutError, OSError, json.JSONDecodeError, UnicodeError):
        raise ValueError('Public price is unavailable. Refresh later.') from None
    return normalize_public_quote(payload, instrument, now=now)

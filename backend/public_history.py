"""Optional, unauthenticated Yahoo historical candles for local chart research.

Yahoo's chart endpoint is unofficial and may be unavailable. These bars are never
treated as a broker quote, exchange status, or permission to trade.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .data import IST, validate_bars


def yahoo_symbol(instrument):
    if instrument.get('kind') != 'CASH' or not instrument.get('simple_equity'):
        raise ValueError('Public history supports regular NSE/BSE cash equities only.')
    symbol = str(instrument.get('symbol', ''))
    if instrument.get('exchange') in ('NSE', 'BSE'):
        if not re.fullmatch(r'[A-Z0-9&._-]{1,40}', symbol):
            raise ValueError('No safe Yahoo symbol mapping for this instrument.')
        return symbol + ('.NS' if instrument['exchange'] == 'NSE' else '.BO')
    raise ValueError('Unsupported exchange for public history.')


def public_history(instrument, timeframe):
    if timeframe not in ('1d', '15m'):
        raise ValueError('Use daily or 15-minute history.')
    ticker = yahoo_symbol(instrument)
    params = urlencode({'range': '10y' if timeframe == '1d' else '60d',
                        'interval': timeframe, 'includePrePost': 'false'})
    url = 'https://query1.finance.yahoo.com/v8/finance/chart/' + quote(ticker, safe='') + '?' + params
    req = Request(url, headers={'Accept': 'application/json', 'User-Agent': 'Mozilla/5.0 IndiaQuantResearch/2.0'})
    try:
        with urlopen(req, timeout=20) as response:
            if not response.geturl().startswith('https://query1.finance.yahoo.com/v8/finance/chart/'):
                raise ValueError('Unexpected public-data redirect.')
            raw = response.read(8_000_001)
            if len(raw) > 8_000_000:
                raise ValueError('Public history response exceeded the size limit.')
            payload = json.loads(raw)
    except HTTPError as exc:
        raise ValueError(f'Public historical data returned HTTP {exc.code}. Try later or import a CSV.') from None
    except (URLError, TimeoutError, OSError, json.JSONDecodeError):
        raise ValueError('Public historical data is unavailable. Try later or import an OHLCV CSV.') from None
    chart = payload.get('chart') if isinstance(payload, dict) else None
    results = chart.get('result') if isinstance(chart, dict) else None
    if not isinstance(results, list) or len(results) != 1:
        raise ValueError('No public history was returned for this listing. Import an OHLCV CSV instead.')
    result = results[0]
    meta = result.get('meta') or {}
    if (str(meta.get('symbol', '')).upper() != ticker.upper()
            or meta.get('currency') != 'INR'
            or meta.get('exchangeTimezoneName') != 'Asia/Kolkata'
            or (instrument['exchange'] == 'BSE' and meta.get('exchangeName') != 'BSE')):
        raise ValueError('Public data identity, currency, or timezone did not match the requested Indian listing.')
    timestamps = result.get('timestamp') or []
    indicators = result.get('indicators') or {}
    quotes = indicators.get('quote') or []
    if not isinstance(timestamps, list) or len(quotes) != 1:
        raise ValueError('Malformed public historical data.')
    series = quotes[0]
    fields = ('open', 'high', 'low', 'close', 'volume')
    if any(not isinstance(series.get(k), list) or len(series[k]) != len(timestamps) for k in fields):
        raise ValueError('Malformed public OHLCV columns.')
    rows = []
    for i, stamp in enumerate(timestamps):
        values = [series[k][i] for k in fields]
        if any(v is None for v in values):
            continue
        try:
            dt = datetime.fromtimestamp(int(stamp), IST)
        except (ValueError, TypeError, OverflowError, OSError):
            raise ValueError('Malformed public candle timestamp.') from None
        if timeframe == '1d':
            dt = datetime.combine(dt.date(), time(9, 15), IST)
        elif (dt.weekday() > 4 or not 555 <= dt.hour * 60 + dt.minute <= 915
              or (dt.hour * 60 + dt.minute - 555) % 15 or dt.second):
            continue
        rows.append(dict(zip(('t', 'o', 'h', 'l', 'c', 'v'), (dt.isoformat(), *values))))
    if len(rows) < 70:
        raise ValueError('Public source returned fewer than 70 candles for this listing. Try the NSE listing or import an OHLCV CSV.')
    bars, warnings = validate_bars(rows, timeframe)
    warnings.append('Yahoo Finance historical bars are unofficial, may be delayed or revised, and are not verified broker quotes. Check data rights before reuse.')
    return bars, warnings, ticker

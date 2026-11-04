"""Public snapshots never inherit broker freshness or invented market depth."""
import json
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from unittest.mock import patch

import pytest

from backend.data import IST
from backend.public_quotes import normalize_public_quote, public_quote

NOW = datetime(2026, 11, 4, 10, 30, tzinfo=IST)
INSTRUMENT = {'instrument_key': 'NSE_EQ|INEFIX000001', 'symbol': 'FIXTURE',
              'exchange': 'NSE', 'kind': 'CASH', 'simple_equity': True}


def payload(age=20):
    return {'chart': {'result': [{'meta': {
        'symbol': 'FIXTURE.NS', 'currency': 'INR', 'exchangeTimezoneName': 'Asia/Kolkata',
        'exchangeName': 'NSI', 'regularMarketPrice': 101.25,
        'regularMarketTime': (NOW - timedelta(seconds=age)).timestamp(),
        'previousClose': 100, 'regularMarketVolume': 50000}}], 'error': None}}


def test_recent_source_time_is_not_verified_live_or_broker_fresh():
    result = normalize_public_quote(payload(), INSTRUMENT, NOW)
    assert result['status'] == 'PUBLIC_RECENT' and result['recent']
    assert not result['fresh'] and not result['realtime_verified']
    assert result['price_time'] == '2026-11-04T10:29:40+05:30'
    assert result['recent_until'] == '2026-11-04T10:31:40+05:30'
    assert result['age_seconds'] == 20 and result['feed_time'] is None
    assert result['last_price'] == 101.25 and result['change_pct'] == pytest.approx(1.25)
    assert result['bid'] is result['ask'] is result['spread_bps'] is None
    assert result['market_status'] == 'UNVERIFIED'


@pytest.mark.parametrize('age,status,recent,stale', [
    (120, 'PUBLIC_RECENT', True, False), (121, 'PUBLIC_DELAYED', False, False),
    (900, 'PUBLIC_DELAYED', False, False), (901, 'PUBLIC_STALE', False, True),
    (86400, 'PUBLIC_STALE', False, True), (-6, 'TIMESTAMP_UNVERIFIED', False, True)])
def test_source_age_labels_are_not_reset_by_receipt_time(age, status, recent, stale):
    result = normalize_public_quote(payload(age), INSTRUMENT, NOW)
    assert (result['status'], result['recent'], result['stale']) == (status, recent, stale)
    assert result['received_at'] == NOW.isoformat()


@pytest.mark.parametrize('field,value', [('symbol', 'OTHER.NS'), ('currency', 'USD'),
                                       ('exchangeName', 'BSE'), ('exchangeTimezoneName', 'UTC')])
def test_wrong_listing_metadata_is_rejected(field, value):
    source = payload(); source['chart']['result'][0]['meta'][field] = value
    with pytest.raises(ValueError, match='identity'):
        normalize_public_quote(source, INSTRUMENT, NOW)


def test_bse_must_match_exact_symbol_and_venue():
    source = payload(); source['chart']['result'][0]['meta'].update(symbol='FIXTURE.BO', exchangeName='BSE')
    result = normalize_public_quote(source, {**INSTRUMENT, 'exchange': 'BSE'}, NOW)
    assert result['ticker'] == 'FIXTURE.BO'


@pytest.mark.parametrize('stamp', [None, 'bad', True, 1e30])
def test_missing_or_invalid_timestamp_keeps_price_unverified(stamp):
    source = payload(); source['chart']['result'][0]['meta']['regularMarketTime'] = stamp
    result = normalize_public_quote(source, INSTRUMENT, NOW)
    assert result['last_price'] == 101.25 and result['status'] == 'TIMESTAMP_UNVERIFIED'
    assert not result['recent'] and result['recent_until'] is None


@pytest.mark.parametrize('price', [None, 0, -1, True, float('inf')])
def test_invalid_price_is_not_replaced_by_candle_close(price):
    source = payload(); source['chart']['result'][0]['meta']['regularMarketPrice'] = price
    with pytest.raises(ValueError, match='valid latest price'):
        normalize_public_quote(source, INSTRUMENT, NOW)


class Response:
    def __init__(self, data=None, url='https://query1.finance.yahoo.com/v8/finance/chart/FIXTURE.NS'):
        self.raw = json.dumps(data or payload()).encode(); self.url = url
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def geturl(self): return self.url
    def read(self, length): return self.raw[:length]


def test_http_request_is_bounded_and_uses_exact_encoded_listing():
    with patch('backend.public_quotes.urlopen', return_value=Response()) as opening:
        result = public_quote(INSTRUMENT, NOW)
    request = opening.call_args.args[0]
    assert '/FIXTURE.NS?range=1d&interval=1m&includePrePost=false' in request.full_url
    assert opening.call_args.kwargs['timeout'] == 12 and result['last_price'] == 101.25


@pytest.mark.parametrize('error', [URLError('offline'), HTTPError('https://example.test', 429, 'rate', {}, None)])
def test_network_errors_return_no_substitute_quote(error):
    with patch('backend.public_quotes.urlopen', side_effect=error):
        with pytest.raises(ValueError, match='Public price'):
            public_quote(INSTRUMENT, NOW)


def test_oversized_response_and_other_listing_redirect_are_rejected():
    response = Response(); response.raw = b' ' * 1_000_001
    with patch('backend.public_quotes.urlopen', return_value=response):
        with pytest.raises(ValueError, match='size limit'): public_quote(INSTRUMENT, NOW)
    with patch('backend.public_quotes.urlopen', return_value=Response(url='https://query1.finance.yahoo.com/v8/finance/chart/OTHER.NS')):
        with pytest.raises(ValueError, match='redirect'): public_quote(INSTRUMENT, NOW)


def test_missing_result_is_explicitly_unavailable():
    for source in (None, {}, {'chart': {'result': None}}, {'chart': {'result': [None]}}):
        with pytest.raises(ValueError, match='No public price'):
            normalize_public_quote(source, INSTRUMENT, NOW)

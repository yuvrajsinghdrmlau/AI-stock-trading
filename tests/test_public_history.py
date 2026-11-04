"""No-key history keeps instrument identity and completed-bar validation."""
import json
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from backend.data import IST
from backend.public_history import public_history, yahoo_symbol
from backend.desk import Desk
from backend.store import Store
from backend.universe import Universe


class Response:
    def __init__(self, data):
        self.data = json.dumps(data).encode()

    def __enter__(self): return self
    def __exit__(self, *_): return False
    def geturl(self): return 'https://query1.finance.yahoo.com/v8/finance/chart/TEST.NS'
    def read(self, _): return self.data


class PublicHistoryTests(unittest.TestCase):
    def setUp(self):
        self.instrument = {'kind': 'CASH', 'simple_equity': True,
                           'exchange': 'NSE', 'symbol': 'TEST'}

    def fixture(self, symbol='TEST.NS'):
        dates = []
        day = datetime(2024, 1, 1, 9, 15, tzinfo=IST)
        while len(dates) < 80:
            if day.weekday() < 5: dates.append(int(day.timestamp()))
            day += timedelta(days=1)
        return {'chart': {'result': [{'meta': {'symbol': symbol, 'currency': 'INR',
            'exchangeTimezoneName': 'Asia/Kolkata'}, 'timestamp': dates,
            'indicators': {'quote': [{'open': [100] * 80, 'high': [102] * 80,
                'low': [99] * 80, 'close': [101] * 80, 'volume': [1000] * 80}]}}],
            'error': None}}

    def test_nse_completed_daily_bars(self):
        with patch('backend.public_history.urlopen', return_value=Response(self.fixture())):
            bars, warnings, ticker = public_history(self.instrument, '1d')
        self.assertEqual((len(bars), ticker), (80, 'TEST.NS'))
        self.assertEqual(bars[0]['t'], '2024-01-01T09:15:00+05:30')
        self.assertIn('unofficial', warnings[-1])

    def test_fifteen_minute_bars_use_ist_open_times(self):
        data = self.fixture()
        start = datetime(2024, 1, 1, 9, 15, tzinfo=IST)
        stamps = [int((start + timedelta(days=d, minutes=15 * k)).timestamp())
                  for d in range(4) for k in range(25)][:80]
        result = data['chart']['result'][0]
        result['timestamp'] = stamps
        result['indicators']['quote'][0] = {
            'open': [100] * 80, 'high': [102] * 80, 'low': [99] * 80,
            'close': [101] * 80, 'volume': [1000] * 80}
        with patch('backend.public_history.urlopen', return_value=Response(data)):
            bars, _, _ = public_history(self.instrument, '15m')
        self.assertEqual(len(bars), 80)
        self.assertEqual(bars[1]['t'], '2024-01-01T09:30:00+05:30')

    def test_wrong_listing_is_rejected(self):
        with patch('backend.public_history.urlopen', return_value=Response(self.fixture('OTHER.NS'))):
            with self.assertRaisesRegex(ValueError, 'identity'):
                public_history(self.instrument, '1d')

    def test_bse_uses_trading_symbol_and_checks_venue(self):
        inst = {**self.instrument, 'exchange': 'BSE'}
        self.assertEqual(yahoo_symbol(inst), 'TEST.BO')
        data = self.fixture('TEST.BO')
        data['chart']['result'][0]['meta']['exchangeName'] = 'BSE'
        with patch('backend.public_history.urlopen', return_value=Response(data)):
            bars, _, ticker = public_history(inst, '1d')
        self.assertEqual((len(bars), ticker), (80, 'TEST.BO'))
        data['chart']['result'][0]['meta']['exchangeName'] = 'NSE'
        with patch('backend.public_history.urlopen', return_value=Response(data)):
            with self.assertRaisesRegex(ValueError, 'identity'):
                public_history(inst, '1d')

    def test_special_instrument_cannot_be_guessed(self):
        with self.assertRaisesRegex(ValueError, 'regular'): yahoo_symbol({**self.instrument, 'simple_equity': False})

    def test_no_token_history_is_linked_to_selected_listing(self):
        class NoBroker:
            configured = False
        class ClosingStore(Store):
            @contextmanager
            def db(self):
                conn = super().db()
                try:
                    with conn: yield conn
                finally: conn.close()
        with tempfile.TemporaryDirectory() as directory:
            store = ClosingStore(Path(directory) / 'test.sqlite3')
            universe = Universe(store)
            rows = [
                {'segment': ex + '_EQ', 'instrument_key': ex + '_EQ|INE123456789',
                 'trading_symbol': 'TEST', 'name': 'TEST COMPANY', 'isin': 'INE123456789',
                 'instrument_type': 'EQ' if ex == 'NSE' else 'A', 'lot_size': 1}
                for ex in ('NSE', 'BSE')]
            universe.replace(rows, [])
            key = 'NSE_EQ|INE123456789'
            desk = Desk(store, universe, NoBroker(), None)
            with patch('backend.public_history.urlopen', return_value=Response(self.fixture())):
                result = desk.refresh_history(key, '1d')
            self.assertEqual(universe.history(key, '1d')['source'], 'Yahoo Finance historical | TEST.NS')
            self.assertEqual(result['bars'], 80)
            self.assertIsNone(universe.history('BSE_EQ|INE123456789', '1d'))


if __name__ == '__main__': unittest.main()

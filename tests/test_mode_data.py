"""Data readiness uses fictional bars and explicitly controlled feed timestamps."""
from datetime import datetime, timedelta

import pytest

from backend.data import IST, demo_bars
from backend.mode_data import mode_data, mode_dataset, mode_availability, age_cached_row, redact_unavailable
from backend.candle_builder import LiveCandleBuilder
from backend.market import normalize_quote

NOW = datetime(2026, 11, 4, 10, 35, tzinfo=IST)
KEY = 'NSE_EQ|INEFIX000001'
CONTRACT = {'instrument_key': 'NSE_FO|FIXTURE', 'lot_size': 25, 'expiry': '2026-11-30'}


class FakeFeed:
    def __init__(self, state='Live', tick=None, bars=None):
        self.state = state
        self.tick = tick or NOW.isoformat()
        self.bars = bars or {}

    def status(self, symbol):
        return {'status': self.state, 'last_tick_at': self.tick}

    def completed(self, symbol, timeframe):
        return self.bars.get(timeframe, [])


def bar(stamp, price=100):
    return {'t': stamp.isoformat(), 'o': price, 'h': price + 1,
            'l': price - 1, 'c': price, 'v': 100}


def dataset(tf='1d', source='Yahoo Finance historical | FIXTURE'):
    last = NOW.replace(hour=9,minute=15) - timedelta(days=1)
    return {'id':'fixture','sha':'fixture','synthetic':False,'timeframe':tf,
            'source':source,'bars':[bar(last)]}


def quote(symbol=KEY, **changes):
    result = {'instrument_key':symbol,'last_price':100.,'bid':99.9,'ask':100.,
              'open_interest':1000,'spread_bps':10,'fresh':True,
              'feed_time':NOW.isoformat(),'trade_time':NOW.isoformat(),
              'received_at':NOW.isoformat()}
    result.update(changes)
    return result


def test_daily_public_fallback_and_verified_broker_history():
    public=mode_data('Delivery',KEY,dataset=dataset(),now=NOW)
    assert public['status']=='Delayed' and public['available'] and public['price']==100
    broker=mode_data('Swing',KEY,dataset=dataset(source='Upstox V3 | '+KEY),
                     quote=quote(),broker_configured=True,now=NOW)
    assert broker['status']=='Live' and broker['available']
    disconnected=mode_data('Swing',KEY,dataset=dataset(source='Upstox V3 | '+KEY),
                           broker_configured=True,now=NOW)
    assert disconnected['status']=='Delayed' and 'not verified live' in disconnected['reason']


def test_intraday_live_builder_uses_only_completed_bars():
    old={'id':'fixture','sha':'old','synthetic':False,'timeframe':'15m',
         'source':'Yahoo Finance historical | FIXTURE','bars':demo_bars(11,'15m',100)}
    start=NOW.replace(hour=9,minute=15)
    today=[bar(start+timedelta(minutes=15*i),101+i) for i in range(6)]
    feed=FakeFeed(bars={'15m':today})
    combined=mode_dataset('Intraday',KEY,old,feed,NOW)
    assert combined['source'].startswith('Live candle builder')
    assert combined['bars'][-1]['t']==today[4]['t']
    assert mode_data('Intraday',KEY,dataset=old,feed=feed,now=NOW)['status']=='Live'
    feed.bars['15m'].append(bar(start+timedelta(minutes=15*6),999))
    assert mode_dataset('Intraday',KEY,old,feed,NOW)['bars'][-1]['c']!=999


def test_disconnected_and_stale_feed_cannot_claim_live_intraday():
    data=dataset('15m')
    data['bars']=[bar(NOW.replace(hour=10,minute=15))]
    for feed in (None,FakeFeed('Disconnected'),FakeFeed(tick=(NOW-timedelta(minutes=2)).isoformat())):
        state=mode_data('Intraday',KEY,dataset=data,feed=feed,now=NOW)
        assert state['status']=='Delayed' and state['available']
        assert 'no verified live' in state['reason']


def test_missing_option_quote_and_open_interest_never_enable_contract_price():
    for mode in ('Options','Futures'):
        for contract_quote in (None,quote(CONTRACT['instrument_key'],open_interest=None),
                               quote(CONTRACT['instrument_key'],feed_time=(NOW-timedelta(minutes=3)).isoformat())):
            state=mode_data(mode,KEY,dataset=dataset(),contract=CONTRACT,
                            contract_quote=contract_quote,now=NOW)
            assert state['status']=='Partial' and not state['actionable']
            assert 'Needs live quote' in state['reason']
        state=mode_data(mode,KEY,dataset=dataset(),contract=CONTRACT,
                        contract_quote=quote(CONTRACT['instrument_key']),broker_configured=True,now=NOW)
        assert state['status']=='Live' and state['actionable']
        disconnected=mode_data(mode,KEY,dataset=dataset(),contract=CONTRACT,
                               contract_quote=quote(CONTRACT['instrument_key']),now=NOW)
        assert disconnected['status']=='Partial' and not disconnected['actionable']


def test_session_closed_and_scalper_gate():
    after=NOW.replace(hour=16)
    data=dataset('15m');data['bars']=[bar(NOW.replace(hour=10,minute=15))]
    closed=mode_data('Intraday',KEY,dataset=data,now=after)
    assert closed['status']=='Stale' and closed['session_state']=='SESSION_CLOSED'
    assert not closed['available']
    assert mode_data('Scalper',KEY,now=NOW)['reason']=='Scalper unavailable: live data not connected'
    assert not mode_availability()['Scalper']['enabled']
    live=FakeFeed(bars={'1m':[bar(NOW.replace(minute=33))],
                        '5m':[bar(NOW.replace(minute=25))]})
    scalper=mode_data('Scalper',KEY,feed=live,now=NOW)
    assert scalper['status']=='Partial' and not scalper['available']
    assert 'validated scalper strategy' in scalper['reason']


def test_candle_builder_exposes_completed_ohlcv_and_rejects_old_ticks():
    builder=LiveCandleBuilder()
    first=NOW.replace(minute=30,second=0)
    builder.ingest(KEY,100,2,first,received_at=first)
    second=first+timedelta(seconds=30)
    builder.ingest(KEY,102,3,second,received_at=second)
    assert builder.status(KEY,second)['status']=='Live'
    assert builder.completed(KEY,'1m',now=second)==[]
    one=builder.completed(KEY,'1m',now=first+timedelta(minutes=1))
    assert one[0]['o']==100 and one[0]['h']==102 and one[0]['l']==100
    assert one[0]['c']==102 and one[0]['v']==5
    assert builder.completed(KEY,'5m',now=first+timedelta(minutes=1))==[]
    with pytest.raises(ValueError): builder.ingest(KEY,103,1,first,received_at=second)
    assert builder.status(KEY,second+timedelta(seconds=21))['status']=='Stale'


def test_saved_live_derivative_quote_expires_without_contract_levels():
    state=mode_data('Options',KEY,dataset=dataset(),contract=CONTRACT,
                    contract_quote=quote(CONTRACT['instrument_key']),broker_configured=True,now=NOW)
    row={'mode':'Options','holding':'Swing','generated_at':NOW.isoformat(),
         'data_status':state,'idea':{'decision':'REVIEW_TRADE','contract_levels':{'entry':100}}}
    current=age_cached_row(row,NOW+timedelta(seconds=19))
    assert current['data_status']['status']=='Live' and current['idea']['contract_levels']
    old=age_cached_row(row,NOW+timedelta(seconds=21))
    assert old['data_status']['status']=='Partial' and not old['data_status']['actionable']
    assert old['idea']['contract_levels'] is None and old['idea']['decision']=='QUOTE_EXPIRED'


def test_provider_quote_keeps_reported_open_interest_without_inventing_it():
    raw={'last_price':100,'timestamp':NOW.isoformat(),'last_trade_time':NOW.isoformat(),
         'depth':{'buy':[{'price':99,'quantity':1}],
                  'sell':[{'price':100,'quantity':1}]},'oi':1234}
    assert normalize_quote(raw,CONTRACT['instrument_key'],NOW)['open_interest']==1234
    raw.pop('oi')
    assert normalize_quote(raw,CONTRACT['instrument_key'],NOW)['open_interest'] is None


@pytest.mark.parametrize('mode', ['Delivery','Swing','Intraday','Options','Futures','Scalper'])
def test_no_mode_returns_a_price_when_data_unavailable(mode):
    state=mode_data(mode,KEY,now=NOW)
    assert state['status']=='Unavailable' and state['price'] is None
    row=redact_unavailable({'data_status':state,'quote':quote(),
                            'public_snapshot':{'last_price':100},'last_close':100,
                            'plan':{'reference_entry':100},'spark':[100],
                            'trade_plan':{'decision':'CONDITIONAL_BUY','entry':{'reference':100}},
                            'idea':{'action':'BUY_CALL','underlying_levels':{'trigger':100},
                                    'contract_levels':{'entry':20},'contract_quote':quote()}})
    assert row['quote'] is None and row['public_snapshot'] is None
    assert row['last_close'] is None and row['plan'] is None and not row['spark']
    assert row['trade_plan']['entry'] is None and row['idea']['contract_levels'] is None

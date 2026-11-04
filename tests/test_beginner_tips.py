"""Large-universe coverage and F&O direction/contract/risk regression tests."""
from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest

from backend.data import IST
from backend.derivative_ideas import build_derivative_idea
from backend.recommendations import select_universe, history_due
from backend.universe import normalize_contracts, Universe
from backend.store import Store
from backend.public_history import yahoo_symbol

NOW = datetime(2026, 11, 4, 10, 35, 0, tzinfo=IST)
KEY = 'NSE_EQ|INEFIX000001'
MARKET = {'status':'NORMAL_OPEN','checked_at':NOW.isoformat()}
INST = {'instrument_key': KEY, 'symbol': 'FIXTURE', 'kind': 'CASH', 'exchange': 'NSE'}


@pytest.fixture
def inputs(monkeypatch):
    last = {'t':'2026-11-04T10:15:00+05:30', 'o':98, 'h':101, 'l':97, 'c':100,
            'ema20':97, 'ema50':95, 'rsi':60, 'atr':2, 'rv':1.1, 'v':10000}
    monkeypatch.setattr('backend.derivative_ideas.indicators', lambda *_: [last])
    dataset = {'id':'test', 'timeframe':'15m', 'bars':[{}]*80, 'synthetic':False}
    contracts = [{'instrument_key':'NSE_FO|'+str(j), 'underlying_key':KEY,
                  'symbol':'FIXTURE '+kind, 'instrument_type':kind, 'expiry':'2026-11-30',
                  'strike':100 if kind != 'FUT' else None, 'lot_size':10}
                 for j,kind in enumerate(('CE','PE','FUT'))]
    account = {'settings':{'capital':100000,'risk_pct':.5},'cash':100000,'equity_cost_basis':100000}
    q = {'instrument_key':KEY,'last_price':101.1,'feed_time':NOW.isoformat(),'trade_time':NOW.isoformat(),
         'received_at':NOW.isoformat(),'fresh':True}
    return last,dataset,contracts,account,q


def build(inputs, product='Options', **kwargs):
    _,data,contracts,account,quote=inputs
    return build_derivative_idea(INST,data,contracts,product,'Intraday',
                                 {'stale':False,'suspension_checked':True},account,
                                 kwargs.pop('quote',quote),now=NOW,**kwargs)


def broker_fixture(contract_key, **changes):
    q = {'instrument_key':contract_key,'last_price':20,'bid':19.95,'ask':20,
         'fresh':True,'feed_time':NOW.isoformat(),'trade_time':NOW.isoformat(),'received_at':NOW.isoformat(),
         'spread_bps':25,'volume':10000}
    q.update(changes)
    broker=Mock(configured=True)
    broker.quotes.return_value={contract_key:q}
    return broker


def test_no_api_provides_real_call_contract_without_fabricated_premium(inputs):
    row=build(inputs)
    assert row['idea']['action']=='BUY_CALL'
    assert row['idea']['decision']=='CONTRACT_DATA_REQUIRED'
    assert row['idea']['contract']['instrument_key']=='NSE_FO|0'
    assert row['idea']['underlying_levels']['trigger']==101.05
    assert row['idea']['contract_levels'] is None


def test_bearish_signal_selects_put_and_reverses_underlying_stop(inputs):
    last,_,_,_,q=inputs
    last.update(o=102,h=103,l=99,c=100,ema20=102,ema50=104,rsi=40)
    q['last_price']=98.9
    p=build(inputs)['idea']
    assert p['action']=='BUY_PUT' and p['contract']['instrument_type']=='PE'
    assert p['underlying_levels']['stop']>p['underlying_levels']['trigger']>p['underlying_levels']['target']


def test_bearish_futures_are_sell_not_buy(inputs):
    last=inputs[0];last.update(o=102,h=103,l=99,c=100,ema20=102,ema50=104,rsi=40)
    inputs[4]['last_price']=98.9
    p=build(inputs,'Futures')['idea']
    assert p['action']=='SELL_FUTURE' and p['contract']['instrument_type']=='FUT'


def test_verified_contract_quote_produces_premium_levels_and_lot_cost(inputs):
    p=build(inputs,broker=broker_fixture('NSE_FO|0'),market=MARKET)['idea']
    assert p['decision']=='REVIEW_TRADE'
    assert p['contract_levels']['entry']==20
    assert p['contract_levels']['stop']==15 and p['contract_levels']['target']==30
    assert p['contract_levels']['premium_cost']==200
    assert p['contract_levels']['maximum_premium_loss']==200
    assert p['contract_levels']['quantity']==10
    assert not p['order_placed'] and p['probability'] is None


@pytest.mark.parametrize('changes',[{'fresh':False},{'spread_bps':300},{'bid':21},{'spread_bps':-1},
    {'feed_time':(NOW-timedelta(minutes=5)).isoformat()}, {'instrument_key':'NSE_FO|WRONG'}, {'volume':0},
    {'trade_time':(NOW-timedelta(seconds=120)).isoformat()}])
def test_unusable_derivative_quotes_never_issue_trade(inputs,changes):
    p=build(inputs,broker=broker_fixture('NSE_FO|0',**changes),market=MARKET)['idea']
    assert p['decision']!='REVIEW_TRADE' and p['contract_levels'] is None


def test_expiring_contracts_are_excluded_and_one_lot_risk_must_fit(inputs):
    inputs[2][0]['expiry']='2026-11-05'
    assert build(inputs)['idea']['contract'] is None
    inputs[2][0]['expiry']='2026-11-30'
    inputs[3]['equity_cost_basis']=100
    p=build(inputs,broker=broker_fixture('NSE_FO|0'),market=MARKET)['idea']
    assert p['decision']=='BUDGET_TOO_SMALL'


def test_stale_history_and_synthetic_history_do_not_generate_direction(inputs):
    inputs[0]['t']='2026-11-04T09:45:00+05:30'
    assert build(inputs)['idea']['action'] is None
    inputs[1]['synthetic']=True
    assert build(inputs)['idea']['action'] is None


def test_next_session_idea_has_a_deadline_but_no_premium_plan(inputs):
    inputs[0]['t']='2026-11-03T09:15:00+05:30'
    inputs[1]['timeframe']='1d'
    row=build_derivative_idea(INST,inputs[1],inputs[2],'Options','Swing',
          {'stale':False,'suspension_checked':True},inputs[3],now=NOW)
    assert row['idea']['action']=='BUY_CALL' and row['idea']['contract_levels'] is None
    assert row['idea']['expires_at']=='2026-11-04T15:00:00+05:30'
    row=build_derivative_idea(INST,inputs[1],inputs[2],'Options','Swing',
          {'stale':False,'suspension_checked':True},inputs[3],now=NOW.replace(hour=15))
    assert row['idea']['decision']=='WAIT_FOR_DATA' and row['idea']['action'] is None


def test_catalogue_contracts_preserve_expiry_lot_and_suspension():
    raw={'segment':'NSE_FO','instrument_type':'CE','instrument_key':'NSE_FO|42',
         'underlying_key':KEY,'expiry':int(datetime(2026,11,30,15,30,tzinfo=IST).timestamp()*1000),
         'lot_size':75,'strike_price':100,'trading_symbol':'FIXTURE CALL'}
    assert normalize_contracts([raw])[0]['expiry']=='2026-11-30'
    assert normalize_contracts([raw])[0]['lot_size']==75
    assert normalize_contracts([raw],[raw])==[]
    assert normalize_contracts([{**raw,'underlying_key':'GUESS'}])==[]


def test_all_nse_scan_exceeds_watchlist_limit_and_index_mapping_matches_isin(tmp_path,monkeypatch):
    u=Universe(Store(tmp_path/'fixture.db'))
    rows=[{'segment':'NSE_EQ','instrument_key':'NSE_EQ|INEFIX'+str(j).zfill(6),
           'isin':'INEFIX'+str(j).zfill(6),'trading_symbol':'FIX'+str(j),
           'name':'FICTIONAL STOCK','lot_size':1,'instrument_type':'EQ'} for j in range(150)]
    rows.append({**rows[0],'segment':'BSE_EQ','instrument_key':'BSE_EQ|INEFIX000000'})
    u.replace(rows,[])
    selected,missing,coverage=select_universe(u,'all_nse')
    assert len(selected)==150 and not missing and coverage['selected']==150
    assert u.watch()==[]
    monkeypatch.setattr('backend.recommendations.download_members',lambda _:(
        [{'symbol':'FIX0','isin':'INEWRONG'},{'symbol':'FIX1','isin':'INEFIX000001'}],'fixture'))
    selected,missing,_=select_universe(u,'nifty50')
    assert [i['symbol'] for i in selected]==['FIX1'] and missing==['FIX0']


def test_missing_official_index_list_falls_back_to_catalogue_without_claiming_index(tmp_path,monkeypatch):
    u=Universe(Store(tmp_path/'fixture.db'))
    rows=[{'segment':ex+'_EQ','instrument_key':ex+'_EQ|INEFIX000001','isin':'INEFIX000001',
           'trading_symbol':'FIXTURE','lot_size':1,'instrument_type':'EQ'} for ex in ('NSE','BSE')]
    u.replace(rows,[])
    monkeypatch.setattr('backend.recommendations.download_members',Mock(side_effect=ValueError('Offline fixture')))
    selected,_,coverage=select_universe(u)
    assert len(selected)==1 and coverage['fallback'] and 'All regular NSE' in coverage['label']


def test_history_cache_detects_new_completed_bar_and_public_index_mapping():
    data={'bars':[{'t':'2026-11-04T10:15:00+05:30'}]}
    assert not history_due(data,'15m',NOW)
    assert history_due(data,'15m',NOW+timedelta(minutes=15))
    assert yahoo_symbol({'kind':'INDEX','exchange':'NSE','symbol':'Nifty 50'})=='^NSEI'
    with pytest.raises(ValueError): yahoo_symbol({'kind':'INDEX','exchange':'NSE','symbol':'UNMAPPED'})

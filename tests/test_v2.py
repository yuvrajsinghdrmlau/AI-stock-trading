"""v2 tests use explicit fixtures; no live-market or profitability claims."""
import copy
import json
import os
from datetime import datetime, timedelta
from unittest.mock import patch
import pytest
os.environ['IQ_NO_DEFAULT_APP']='1'
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.data import IST, demo_bars, fingerprint
from backend.universe import Universe, normalize_master
from backend.market import normalize_quote, timestamp, BrokerData
from backend.desk import evaluate_candidate, filters_config, risk_plan
from backend.research import run_study, walkforward_study, partition, config_for
from backend.strategies import indicators, analyse
from backend.store import Store


def fixtures():
    # Deliberately fictional symbols/ISINs. Never shipped as a real catalogue.
    return [
        {'segment':'NSE_EQ','exchange':'NSE','instrument_key':'NSE_EQ|INEFAKE00001','trading_symbol':'TEST-ALPHA','name':'FICTIONAL ALPHA FIXTURE','isin':'INEFAKE00001','instrument_type':'EQ','lot_size':1},
        {'segment':'BSE_EQ','exchange':'BSE','instrument_key':'BSE_EQ|INEFAKE00001','trading_symbol':'TEST-ALPHA','name':'FICTIONAL ALPHA FIXTURE','isin':'INEFAKE00001','instrument_type':'A','lot_size':1},
        {'segment':'BSE_EQ','exchange':'BSE','instrument_key':'BSE_EQ|INEFAKE00002','trading_symbol':'TEST-SME','name':'FICTIONAL SME FIXTURE','isin':'INEFAKE00002','instrument_type':'M','lot_size':1000},
        {'segment':'NSE_INDEX','exchange':'NSE','instrument_key':'NSE_INDEX|TEST Index','trading_symbol':'TEST-INDEX','name':'FICTIONAL INDEX','instrument_type':'INDEX','lot_size':1}]

@pytest.fixture
def app(tmp_path):
    app=create_app(tmp_path,seed_demo=False,testing=True)
    app.state.universe.replace(fixtures(),[])
    return app

@pytest.fixture
def client(app):
    c=TestClient(app);c.app_=app;c.token=app.state.token
    return c

def post(c,path,body):return c.post(path,json=body,headers={'X-Desk-Token':c.token})

def test_nse_bse_same_isin_preserved(app):
    r=app.state.universe.search('TEST-ALPHA')
    assert r['total']==2 and len({i['instrument_key'] for i in r['items']})==2

def test_search_name_and_isin(app):
    assert app.state.universe.search('FICTIONAL ALPHA')['total']==2
    assert app.state.universe.search('INEFAKE00001',exchange='BSE')['total']==1

def test_other_series_searchable_but_not_eligible(app):
    r=app.state.universe.search('TEST-SME')['items'][0]
    assert r['lot_size']==1000 and not r['simple_equity']

def test_index_category(app):
    assert app.state.universe.search('',kind='INDEX')['total']==1
    assert app.state.universe.search('',kind='CASH')['total']==3

def test_pagination(app):
    r=app.state.universe.search('',kind='ALL',limit=2)
    assert r['next_offset']==2
    b=app.state.universe.search('',kind='ALL',offset=2,limit=2)
    assert b['next_offset'] is None
    assert not {x['instrument_key'] for x in r['items']} & {x['instrument_key'] for x in b['items']}

@pytest.mark.parametrize('query',["' OR 1=1 --",'%', '_'])
def test_search_is_parameterized_and_literal(app,query):
    assert app.state.universe.search(query)['total']==0

def test_suspension_is_visible_and_preserved():
    r=normalize_master(fixtures(),[fixtures()[0]])
    a=next(i for i in r if i['instrument_key']==fixtures()[0]['instrument_key'])
    assert a['suspended']

def test_catalogue_atomic_failed_refresh(app):
    before=app.state.universe.status()
    with pytest.raises(ValueError): app.state.universe.replace([fixtures()[0]],[])
    assert app.state.universe.status()['total']==before['total']

def test_failed_network_preserves_catalogue(app):
    with patch('backend.universe.download_master',side_effect=ValueError('network unavailable')):
        with pytest.raises(ValueError):app.state.universe.sync()
    assert app.state.universe.search('TEST-ALPHA')['total']==2

def test_watch_deduplicates_and_removes(app):
    u=app.state.universe;key=fixtures()[0]['instrument_key']
    u.set_watch(key);u.set_watch(key);assert len(u.watch())==1
    u.set_watch(key,False);assert not u.watch()

def test_watch_instrument_no_longer_available(app):
    u=app.state.universe;u.set_watch(fixtures()[0]['instrument_key'])
    u.replace(fixtures()[1:]+[dict(fixtures()[0],instrument_key='NSE_EQ|INEFAKE00009')],[])
    assert u.watch()[0]['unavailable']

def test_unknown_key_rejected(app):
    with pytest.raises(ValueError): app.state.universe.set_watch('NSE_EQ|GUESS')

def test_master_wrong_identifier_rejected():
    rows=fixtures();rows[0]['instrument_key']='MCX_FO|bad'
    with pytest.raises(ValueError):normalize_master(rows)

def test_missing_suspension_check_flag(app):
    app.state.universe.replace(fixtures(),None)
    assert not app.state.universe.status()['suspension_checked']

NOW=datetime(2026,11,3,10,30,20,tzinfo=IST)
def quote_fixture():
    return {'timestamp':NOW.isoformat(),'last_trade_time':str(int(NOW.timestamp()*1000)),
        'last_price':100.,'volume':100000,'instrument_token':fixtures()[0]['instrument_key'],
        'depth':{'buy':[{'price':99.95,'quantity':40}],'sell':[{'price':100.05,'quantity':50}]},
        'lower_circuit_limit':80,'upper_circuit_limit':120}

def test_fresh_quote_clock_and_spread():
    q=normalize_quote(quote_fixture(),'NSE_EQ|TEST',NOW)
    assert q['fresh'] and q['spread_bps']==pytest.approx(10)

@pytest.mark.parametrize('field',['timestamp','last_trade_time'])
def test_missing_timestamps_fail_closed(field):
    r=quote_fixture();r.pop(field)
    assert not normalize_quote(r,'X',NOW)['fresh']

def test_future_feed_rejected():
    r=quote_fixture();r['timestamp']=(NOW+timedelta(minutes=1)).isoformat()
    assert not normalize_quote(r,'X',NOW)['fresh']

def test_old_trade_not_fresh_even_new_response():
    r=quote_fixture();r['last_trade_time']=str(int((NOW-timedelta(minutes=5)).timestamp()*1000))
    assert not normalize_quote(r,'X',NOW)['fresh']

def test_crossed_or_one_sided_depth_no_spread():
    r=quote_fixture();r['depth']['buy'][0]['price']=101
    assert normalize_quote(r,'X',NOW)['spread_bps'] is None
    r['depth']['sell']=[]
    assert normalize_quote(r,'X',NOW)['spread_bps'] is None

def test_zero_price_no_fresh_quote():
    r=quote_fixture();r['last_price']=0
    assert not normalize_quote(r,'X',NOW)['fresh']

def test_naive_live_timestamp_not_assumed_ist():assert timestamp('2026-11-03T10:30:20') is None

def test_quotes_map_by_instrument_key_not_symbol(monkeypatch):
    b=BrokerData();row=quote_fixture()
    monkeypatch.setattr(b,'get',lambda *a,**k:{'NSE_EQ:TEST-ALPHA':row})
    key=fixtures()[0]['instrument_key']
    assert b.quotes([key])[key]['last_price']==100

def test_quote_absent_is_marked_missing(monkeypatch):
    b=BrokerData();monkeypatch.setattr(b,'get',lambda *a,**k:{})
    assert b.quotes(['NSE_EQ|TEST'])['NSE_EQ|TEST']['status']=='MISSING'

def test_broker_token_missing(monkeypatch):
    monkeypatch.delenv('UPSTOX_ACCESS_TOKEN',raising=False)
    with pytest.raises(ValueError,match='TOKEN'):BrokerData().get('/v2/market/status/NSE')

def test_broker_arbitrary_path_disallowed(monkeypatch):
    monkeypatch.setenv('UPSTOX_ACCESS_TOKEN','test-not-a-real-token')
    with pytest.raises(ValueError):BrokerData().get('/v2/order/place')

def candidate_args():
    inst=normalize_master(fixtures())[1]
    inst=next(x for x in normalize_master(fixtures()) if x['instrument_key']==fixtures()[0]['instrument_key'])
    a={'strategy':'vwap_pullback','last':{'t':'2026-11-03T10:15:00+05:30','c':100,'atr':1.,'v':100000.,'rv':1.5,'rsi':60.,'regime':'UPTREND'},'rule_pass':True,'setup_score':100}
    account={'settings':{'capital':10000.,'risk_pct':.5,'exposure_pct':20.,'max_positions':2,'total_risk_pct':1.,'daily_loss_pct':1.,'kill_switch':False},'cash':10000.,'equity_cost_basis':10000.,'realized_pnl':0.,'daily_realized_pnl':0.,'open_positions':[],'open_planned_risk':0.}
    model={'status':'RESEARCH_ESTIMATE','probability':.72,'config':config_for('vwap_pullback',{})}
    return [inst,{'id':'fixture','synthetic':False,'timeframe':'15m'},a,normalize_quote(quote_fixture(),'X',NOW),{'status':'NORMAL_OPEN'},model,account,{'stale':False,'suspension_checked':True},filters_config()]

def test_research_candidate_after_mechanical_gates():
    r=evaluate_candidate(*candidate_args(),now=NOW)
    assert r['status']=='PAPER_RESEARCH_CANDIDATE' and r['event_risk']=='NOT_CHECKED'
    assert 0<r['plan']['planned_loss_with_estimated_costs']<=50

@pytest.mark.parametrize('case',['closed','stale_quote','no_model','failed_model','synthetic','kill','wide_spread','old_candle','future_candle','catalogue','cash','suspended','lot','loss','risk','positions','gap','circuit'])
def test_research_vetoes_cannot_be_overridden_by_probability(case):
    args=candidate_args();args[5]['probability']=.999
    if case=='closed':args[4]['status']='NORMAL_CLOSE'
    elif case=='stale_quote':args[3]['fresh']=False
    elif case=='no_model':args[5]['probability']=None
    elif case=='failed_model':args[5]['status']='UNVALIDATED'
    elif case=='synthetic':args[1]['synthetic']=True
    elif case=='kill':args[6]['settings']['kill_switch']=True
    elif case=='wide_spread':args[3]['spread_bps']=100
    elif case=='old_candle':args[2]['last']['t']='2026-11-03T09:30:00+05:30'
    elif case=='future_candle':args[2]['last']['t']='2026-11-03T10:45:00+05:30'
    elif case=='catalogue':args[7]['stale']=True
    elif case=='cash':args[6]['cash']=0
    elif case=='suspended':args[0]['suspended']=True
    elif case=='lot':args[0]['simple_equity']=False
    elif case=='loss':args[6]['daily_realized_pnl']=-100
    elif case=='risk':args[6]['open_planned_risk']=100
    elif case=='positions':args[6]['open_positions']=[{},{}]
    elif case=='gap':args[3]['last_price']=103
    elif case=='circuit':args[3]['upper_circuit']=100
    r=evaluate_candidate(*args,now=NOW)
    assert r['status']=='NO_TRADE' and r['reasons']

def test_daily_is_next_open_watch_not_execute_now():
    args=candidate_args();args[1]['timeframe']='1d';args[2]['strategy']='trend_pullback';args[2]['last']['t']='2026-11-02T00:00:00+05:30';args[5]['config']=config_for('trend_pullback',{})
    assert evaluate_candidate(*args,now=NOW)['status']=='NEXT_OPEN_RESEARCH_WATCH'

@pytest.mark.parametrize('filters',[{'min_probability':.2},{'min_probability':float('nan')},{'min_price':100,'max_price':50},{'rsi_min':90,'rsi_max':10},{'uptrend_only':'yes'},{'made_up':1}])
def test_filter_validation(filters):
    with pytest.raises(ValueError):filters_config(filters)

def test_indicators_no_future_leak():
    bars=demo_bars(3,'1d',300);before=indicators(bars,'1d');changed=copy.deepcopy(bars)
    for row in changed[200:]:
        for key in ('o','h','l','c'):row[key]*=2
    after=indicators(changed,'1d')
    assert before[:200]==after[:200]
    assert all(k in before[-1] for k in ('macd','macd_signal','bb_upper','bb_lower'))

def test_chart_fields_available():
    r=analyse(demo_bars(1,'1d',300),'1d','trend_pullback')
    assert all(k in r['chart'][-1] for k in ('ema200','macd','rsi','bb_upper','support'))

def test_walkforward_disjoint_tests():
    bars=demo_bars(1,'1d',1500)
    d={'id':'x','symbol':'SIM','timeframe':'1d','bars':bars,'synthetic':True,'sha':fingerprint(bars),'source':'synthetic fixture'}
    r=walkforward_study(d,'trend_pullback',{})
    assert len(r['folds'])==3
    for a,b in zip(r['folds'],r['folds'][1:]): assert a['test_end_index']==b['test_start_index']
    for fold in r['folds']:
        assert fold['splits'][2]['to']<fold['splits'][3]['from']

def test_serialized_model_integrity_and_changed_data(app):
    u=app.state.universe;s=app.state.store;m=app.state.models;key=fixtures()[0]['instrument_key']
    bars=demo_bars(1,'1d',3200);ident=s.add_dataset('TEST-ALPHA','1d','synthetic test',True,bars)
    u.link(key,'1d',ident);data=s.dataset(ident)
    result=run_study(data,'trend_pullback',{},artifact_callback=m.save)
    assert result['model_id'] and m.list()[0]['artifact_sha256']
    inferred=m.infer(key,'trend_pullback',data)
    assert inferred['status'] in ('UNVALIDATED','NO_SETUP')
    changed=copy.deepcopy(data);changed['bars'][0]['v']+=1
    assert m.infer(key,'trend_pullback',changed)['status']=='DATA_REVISED'
    path=m.directory/(result['model_id']+'.joblib');path.write_bytes(b'not an artifact')
    assert m.infer(key,'trend_pullback',data)['status']=='ARTIFACT_INVALID'

def test_model_absent_is_not_random_confidence(app):
    assert app.state.models.infer(fixtures()[0]['instrument_key'],'trend_pullback',{})['probability'] is None

def test_quote_board_without_token_is_explicit(client,monkeypatch):
    monkeypatch.delenv('UPSTOX_ACCESS_TOKEN',raising=False)
    post(client,'/api/watchlist',{'instrument_key':fixtures()[0]['instrument_key']})
    r=post(client,'/api/desk/scan',{'mode':'Swing'}).json()
    assert not r['configured'] and all(row['probability'] is None for row in r['rows'])
    assert all(row['status']=='DATA_REQUIRED' for row in r['rows'])

def test_search_api_includes_separate_exchanges(client):
    r=client.get('/api/universe/search?q=TEST-ALPHA').json()
    assert r['total']==2

def test_v2_writes_require_token(client):
    assert client.post('/api/watchlist',json={'instrument_key':fixtures()[0]['instrument_key']}).status_code==403
    assert client.post('/api/desk/scan',json={'mode':'Swing'}).status_code==403

def test_fno_not_using_cash_model(client):
    assert post(client,'/api/desk/scan',{'mode':'F&O'}).status_code==400

def test_new_chart_without_history_not_fabricated(client):
    r=client.get('/api/market/chart',params={'instrument_key':fixtures()[0]['instrument_key']}).json()
    assert r['data_required'] and 'chart' not in r

def test_upstox_token_not_returned(client,monkeypatch):
    monkeypatch.setenv('UPSTOX_ACCESS_TOKEN','secret-fixture-token')
    r=client.get('/api/market/config')
    assert 'secret-fixture-token' not in r.text and r.json()['upstox_configured']

def test_chain_strips_unvalidated_pop(monkeypatch):
    b=BrokerData();raw=[{'strike_price':100,'expiry':'2030-01-01','call_options':{'option_greeks':{'iv':20,'pop':99}},'put_options':{}}]
    monkeypatch.setattr(b,'get',lambda *a,**k:raw)
    r=b.option_chain('NSE_INDEX|TEST','2030-01-01')
    assert r['probability'] is None and 'pop' not in r['rows'][0]['call']

def test_real_orders_still_disabled(client):assert post(client,'/api/live/orders',{}).status_code==403

# Automatic candle refresh is intentionally local, opt-in and session-bounded.
def _clock(monkeypatch,hour=10,minute=30,day=3):
    import backend.v2_api as module
    class Frozen(datetime):
        @classmethod
        def now(cls,tz=None):
            return datetime(2026,11,day,hour,minute,1,tzinfo=IST)
    monkeypatch.setattr(module,'datetime',Frozen)

@pytest.mark.parametrize('mode',['Swing','Delivery','F&O'])
def test_auto_candles_only_intraday(client,mode,monkeypatch):
    monkeypatch.setenv('UPSTOX_ACCESS_TOKEN','fixture-not-real')
    assert post(client,'/api/market/refresh-due',{'mode':mode}).json()['job_id'] is None

def test_auto_candles_without_credentials(client,monkeypatch):
    monkeypatch.delenv('UPSTOX_ACCESS_TOKEN',raising=False)
    assert post(client,'/api/market/refresh-due',{'mode':'Intraday'}).json()['job_id'] is None

@pytest.mark.parametrize('hour,minute,day',[(9,29,3),(14,45,3),(10,30,7)])
def test_auto_candles_outside_entry_window(client,monkeypatch,hour,minute,day):
    monkeypatch.setenv('UPSTOX_ACCESS_TOKEN','fixture-not-real');_clock(monkeypatch,hour,minute,day)
    assert post(client,'/api/market/refresh-due',{'mode':'Intraday'}).json()['job_id'] is None

@pytest.mark.parametrize('condition',['no_history','already_current','closed','cas'])
def test_auto_candles_skip_unsafe_or_unchanged(client,monkeypatch,condition):
    monkeypatch.setenv('UPSTOX_ACCESS_TOKEN','fixture-not-real');_clock(monkeypatch)
    inst=normalize_master(fixtures())[0];inst['simple_equity']=True
    if condition=='cas':inst['cas_eligible']=True
    monkeypatch.setattr(client.app_.state.universe,'watch',lambda:[inst])
    data=None if condition=='no_history' else {'bars':[{'t':'2026-11-03T'+('10:15' if condition=='already_current' else '10:00')+':00+05:30'}]}
    monkeypatch.setattr(client.app_.state.universe,'history',lambda key,tf:data)
    monkeypatch.setattr(client.app_.state.broker,'exchange_status',lambda ex:{'status':'NORMAL_CLOSE' if condition=='closed' else 'NORMAL_OPEN','cas_status':'CALL_AUCTION' if condition=='cas' else None})
    assert post(client,'/api/market/refresh-due',{'mode':'Intraday'}).json()['job_id'] is None

def test_auto_candles_refresh_once_and_cooldown(client,monkeypatch):
    import time
    monkeypatch.setenv('UPSTOX_ACCESS_TOKEN','fixture-not-real');_clock(monkeypatch)
    inst=next(x for x in normalize_master(fixtures()) if x['simple_equity'])
    monkeypatch.setattr(client.app_.state.universe,'watch',lambda:[inst])
    monkeypatch.setattr(client.app_.state.universe,'history',lambda key,tf:{'bars':[{'t':'2026-11-03T10:00:00+05:30'}]})
    monkeypatch.setattr(client.app_.state.broker,'exchange_status',lambda ex:{'status':'NORMAL_OPEN'})
    calls=[]
    def refresh(key,tf):calls.append((key,tf));return {'dataset_id':'fixture-only'}
    monkeypatch.setattr(client.app_.state.desk,'refresh_history',refresh)
    result=post(client,'/api/market/refresh-due',{'mode':'Intraday'}).json()
    assert result['job_id']
    for _ in range(100):
        job=client.get('/api/market/jobs/'+result['job_id']).json()
        if job['status']!='running':break
        time.sleep(.01)
    assert job['status']=='complete' and job['result']['successes']==1
    assert calls==[(inst['instrument_key'],'15m')]
    assert post(client,'/api/market/refresh-due',{'mode':'Intraday'}).json()['job_id'] is None

def test_auto_candles_requires_local_write_token(client):
    assert client.post('/api/market/refresh-due',json={'mode':'Intraday'}).status_code==403

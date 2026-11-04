"""Entry timing, gap/cost replay, local reminders and toolkit API regression tests."""
from datetime import datetime, timedelta
from email.utils import format_datetime
from unittest.mock import Mock
import os

os.environ['IQ_NO_DEFAULT_APP']='1'
import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.data import IST,demo_bars
from backend.entry_timing import entry_timing,exit_scenario
from backend.trade_replay import replay,resample,directional_events
from backend.market_news import parse_headlines
from backend.price_alerts import PriceAlerts
from backend.store import Store

NOW=datetime(2026,11,4,10,0,tzinfo=IST)
KEY='NSE_EQ|INEFIX000001'


def session_dataset(closes=(100,101,104)):
    start=NOW.replace(hour=9,minute=15)
    bars=[{'t':(start+timedelta(minutes=15*i)).isoformat(),'o':100,'h':max(c,102),'l':min(c,99),'c':c,'v':1000} for i,c in enumerate(closes)]
    return {'id':'fixture','sha':'hash','timeframe':'15m','source':'FICTIONAL TEST INPUT','synthetic':False,'bars':bars}


def test_entry_uses_only_completed_candles_and_strict_close():
    data=session_dataset((100,101,104))
    assert entry_timing(data,now=NOW-timedelta(minutes=1))['status']=='WAITING'
    result=entry_timing(data,now=NOW)
    assert result['status']=='TRIGGERED' and result['signal']['confirmed_at']==NOW.isoformat()
    data['bars'][-1]['c']=102
    assert entry_timing(data,now=NOW)['status']=='WAITING'


def test_entry_first_trigger_does_not_reset_and_missing_bars_block():
    data=session_dataset((100,101,104,105,106))
    later=NOW+timedelta(minutes=30)
    result=entry_timing(data,now=later)
    assert result['status']=='EXPIRED' and result['signal']['confirmed_at']==NOW.isoformat()
    data['bars'].pop(3)
    assert entry_timing(data,now=later)['status']=='MISSING_BARS'


def test_entry_short_and_session_boundaries():
    data=session_dataset((100,101,98))
    assert entry_timing(data,'sell',NOW)['status']=='TRIGGERED'
    assert entry_timing(data,now=NOW.replace(hour=9,minute=30))['status']=='FORMING_RANGE'
    assert entry_timing(data,now=NOW.replace(hour=16))['status']=='OUTSIDE_SESSION'
    data['synthetic']=True
    assert entry_timing(data,now=NOW)['status']=='DATA_REQUIRED'


def test_exit_scenario_is_cost_capped_and_not_option_lots():
    data={'timeframe':'1d','source':'FICTIONAL TEST INPUT','synthetic':False,'bars':demo_bars(2,'1d',300)}
    account={'settings':{'risk_pct':.5,'cost_bps':40,'exposure_pct':20},'equity_cost_basis':10000,'cash':10000}
    result=exit_scenario(data,{},account,now=datetime(2030,1,1,tzinfo=IST))
    assert result['stop']<result['entry']<result['target']
    assert result['planned_loss_with_costs']<=50 and result['cash_estimate']<=2000.01
    assert result['execution']=='SCENARIO_ONLY' and result['scope']=='CASH_OR_UNDERLYING_SCENARIO'
    with pytest.raises(ValueError):exit_scenario(data,{},account,stop_method='range_edge')


def test_replay_is_reproducible_and_never_uses_future_candles():
    data={'id':'fixture','sha':'fixture','source':'FICTIONAL TEST INPUT','synthetic':False,'timeframe':'1d','bars':demo_bars(2,'1d',800)}
    now=datetime(2027,1,1,tzinfo=IST)
    first=replay(data,'trend_pullback',paths=100,now=now)
    future={**data['bars'][-1],'t':'2028-01-01T09:15:00+05:30','c':1000000,'h':1000001}
    data['bars'].append(future)
    again=replay(data,'trend_pullback',paths=100,now=now)
    assert first['overall']==again['overall'] and first['curve']==again['curve']
    assert first['probability_of_next_trade'] is None and first['costs']['roundtrip_bps']>0
    assert first['recent_starts_at']<=first['last_bar']


def test_resampling_uses_real_outcomes_and_keeps_gap_losses():
    trades=[{'r_multiple':r} for r in [-2.,1.,-.8,1.8]*10]
    a=resample(trades,100,42);b=resample(trades,100,42)
    assert a==b and a['bands'][0]=={'trade':0,'low':0.,'median':0.,'high':0.}
    assert a['adverse_drawdown_r']>=a['median_drawdown_r']
    assert not resample(trades[:5])['available']


def test_direction_replay_gap_stops_are_worse_than_one_r():
    bars=[{'t':f'2026-01-{1+i%20:02d}T09:15:00+05:30','o':100,'h':101,'l':99,'c':100,
           'ema20':100,'ema50':100,'rsi':50,'atr':2,'rv':1,'v':1000} for i in range(76)]
    bars[70].update(ema20=97,ema50=95,rsi=60,o=99)
    bars[72].update(o=90,h=91,l=89,c=90)
    cfg={'horizon':3,'intraday':False,'index':False,'slippage_bps':5,'roundtrip_cost_bps':40}
    trades=directional_events(bars,cfg,'buy')
    assert trades[0]['reason']=='GAP_STOP' and trades[0]['r_multiple']<-3


def test_news_parser_filters_dates_links_and_tags():
    date=format_datetime(NOW)
    raw=f'<rss><channel><item><title>Fixture quarterly results and dividend</title><link>https://news.google.com/rss/articles/fixture</link><pubDate>{date}</pubDate><source>Fixture publisher</source></item><item><title>Bad link</title><link>javascript:alert(1)</link><pubDate>{date}</pubDate></item></channel></rss>'.encode()
    result=parse_headlines(raw,NOW)
    assert len(result)==1 and result[0]['tags']==['Results / earnings','Corporate action']
    with pytest.raises(ValueError):parse_headlines(b'<!DOCTYPE test><rss/>',NOW)


def test_alert_is_once_only_and_stale_or_wrong_prices_do_not_fire(tmp_path):
    store=Store(tmp_path/'alerts.db');alerts=PriceAlerts(store)
    item=alerts.add(KEY,'above',100);now=datetime.now(IST)
    q={'instrument_key':KEY,'last_price':101,'price_time':now.isoformat(),'received_at':now.isoformat(),'recent':True,'delayed':False}
    assert not alerts.check({KEY:{**q,'price_time':(now-timedelta(minutes=10)).isoformat()}},now)['fired']
    assert not alerts.check({KEY:{**q,'instrument_key':'WRONG'}},now)['fired']
    assert not alerts.check({KEY:{**q,'last_price':float('inf')}},now)['fired']
    result=alerts.check({KEY:q},now)
    assert len(result['fired'])==1 and result['fired'][0]['id']==item['id']
    assert not alerts.check({KEY:q},now)['fired']
    assert PriceAlerts(store).list()[0]['status']=='TRIGGERED'


@pytest.fixture
def tool_client(tmp_path,monkeypatch):
    monkeypatch.delenv('UPSTOX_ACCESS_TOKEN',raising=False)
    app=create_app(tmp_path,seed_demo=False,testing=True)
    rows=[{'segment':ex+'_EQ','instrument_key':ex+'_EQ|INEFIX000001','isin':'INEFIX000001',
           'trading_symbol':'FIXTURE','name':'FICTIONAL TEST COMPANY','instrument_type':'EQ','lot_size':1} for ex in ('NSE','BSE')]
    app.state.universe.replace(rows,[])
    for tf in ('1d','15m'):
        ident=app.state.store.add_dataset('NSE:FIXTURE',tf,'FICTIONAL TEST INPUT',False,demo_bars(2,tf,400))
        app.state.universe.link(KEY,tf,ident)
    client=TestClient(app);client.instance=app
    return client


def post(client,path,body):return client.post('/api'+path,json=body,headers={'X-Desk-Token':client.instance.state.token})


def test_tool_api_auth_budget_and_replay(tool_client):
    c=tool_client;body={'instrument_key':KEY}
    assert c.post('/api/tools/entry',json=body).status_code==403
    assert post(c,'/tools/entry',body).status_code==200
    assert post(c,'/tools/entry',{**body,'side':'anything'}).status_code==422
    assert post(c,'/tools/budget',{'capital':50000,'risk_pct':.5,'exposure_pct':20}).status_code==200
    assert c.get('/api/account').json()['settings']['capital']==50000
    replayed=post(c,'/tools/replay',{**body,'paths':100})
    assert replayed.status_code==200 and not replayed.json()['cached']
    assert post(c,'/tools/replay',{**body,'paths':100}).json()['cached']
    assert post(c,'/tools/replay',{**body,'paths':1000000}).status_code==422


def test_news_is_cached_and_alert_api_persists(tool_client,monkeypatch):
    news=Mock(return_value={'items':[],'fetched_at':NOW.isoformat()})
    monkeypatch.setattr('backend.trade_tools.fetch_news',news)
    c=tool_client
    assert not c.get('/api/tools/news',params={'instrument_key':KEY}).json()['cached']
    assert c.get('/api/tools/news',params={'instrument_key':KEY}).json()['cached'] and news.call_count==1
    created=post(c,'/tools/alerts',{'instrument_key':KEY,'condition':'below','level':50})
    assert created.status_code==200 and c.get('/api/tools/alerts').json()[0]['symbol']=='FIXTURE'
    assert post(c,'/tools/alerts/'+created.json()['id']+'/cancel',{}).status_code==200
    assert c.get('/api/tools/alerts').json()[0]['status']=='CANCELLED'


def test_practice_budget_cannot_rewrite_a_journal(tool_client):
    c=tool_client;store=c.instance.state.store
    ident=c.instance.state.universe.history(KEY,'1d')['id']
    store.open_position('fixture',ident,1,100,99,102)
    assert post(c,'/tools/budget',{'capital':50000}).status_code==400


@pytest.mark.parametrize('body',[{'capital':0},{'capital':10000,'risk_pct':5},{'capital':10000,'exposure_pct':99}])
def test_invalid_practice_limits_are_rejected(tool_client,body):
    assert post(tool_client,'/tools/budget',body).status_code==422


def test_practice_budget_clears_saved_scans(tool_client):
    c=tool_client
    with c.instance.state.store.db() as db:
        db.execute('INSERT INTO recommendation_cache VALUES(?,?)',('Delivery|nifty500|Intraday','{"rows":[],"mode":"Delivery"}'))
    assert c.get('/api/recommendations/latest').json()['cached']
    assert post(c,'/tools/budget',{'capital':20000}).status_code==200
    assert c.get('/api/recommendations/latest').json() is None


def test_alert_expiry_dedup_and_capacity(tmp_path):
    store=Store(tmp_path/'alerts.db');alerts=PriceAlerts(store)
    a=alerts.add(KEY,'above',100)
    assert alerts.add(KEY,'above',100)['id']==a['id']
    with store.db() as db:db.execute('UPDATE price_alerts SET expires=?',('2000-01-01T00:00:00+05:30',))
    assert alerts.list()[0]['status']=='EXPIRED'
    for i in range(20):alerts.add(KEY,'below',i+1)
    assert alerts.add(KEY,'below',1)['level']==1
    with pytest.raises(ValueError):alerts.add(KEY,'above',200)


def test_active_alert_is_not_hidden_by_a_large_trigger_history(tmp_path):
    store=Store(tmp_path/'alerts.db');alerts=PriceAlerts(store)
    active=alerts.add(KEY,'above',100)
    with store.db() as db:
        for i in range(110):
            db.execute('INSERT INTO price_alerts VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (str(i),KEY,'above',1,'TRIGGERED','2099-01-01','2099-01-02','2099-01-01',2,'2099-01-01'))
    assert alerts.list()[0]['id']==active['id']


def test_replay_cache_keeps_listing_identity_even_with_identical_bars(tool_client):
    c=tool_client;u=c.instance.state.universe
    rows=[u.get(KEY),u.get(KEY.replace('NSE_EQ','BSE_EQ'))]
    # Reuse the provider representation, adding a distinct NSE listing.
    provider=[{'segment':r['segment'],'instrument_key':r['instrument_key'],'isin':r['isin'],
               'trading_symbol':r['symbol'],'name':r['name'],'lot_size':1,'instrument_type':'EQ'} for r in rows]
    second={**provider[0],'instrument_key':'NSE_EQ|INEFIX000002','isin':'INEFIX000002','trading_symbol':'SECOND'}
    u.replace(provider+[second],[])
    u.link(second['instrument_key'],'1d',u.history(KEY,'1d')['id'])
    first=post(c,'/tools/replay',{'instrument_key':KEY,'paths':100}).json()
    other=post(c,'/tools/replay',{'instrument_key':second['instrument_key'],'paths':100}).json()
    assert first['instrument']['instrument_key']==KEY and other['instrument']['instrument_key']==second['instrument_key']
    assert not other['cached']

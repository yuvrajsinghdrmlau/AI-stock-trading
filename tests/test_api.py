import os, time
os.environ['IQ_NO_DEFAULT_APP']='1'
import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.data import demo_bars

@pytest.fixture
def client(tmp_path):
    app=create_app(tmp_path,seed_demo=False,testing=True)
    ident=app.state.store.add_dataset('SIM-TEST','1d','test',True,demo_bars(1,'1d',300))
    c=TestClient(app);c.token=app.state.token;c.ident=ident;c.store=app.state.store
    return c

def post(c,path,body):return c.post(path,json=body,headers={'X-Desk-Token':c.token})
def order(c,**kw):return {'request_id':'one','dataset_id':c.ident,'quantity':5,'entry':100.,'stop':95.,'target':110.,'acknowledged_manual':True,**kw}

def test_bootstrap(client):
    r=client.get('/api/bootstrap');assert r.status_code==200 and not r.json()['providers']['live']
def test_no_token_cannot_write(client):assert client.post('/api/kill-switch',json={'enabled':True}).status_code==403
def test_host_check(client):assert client.get('/api/health',headers={'Host':'evil.test'}).status_code==403
def test_origin_check(client):assert client.post('/api/kill-switch',headers={'X-Desk-Token':client.token,'Origin':'https://evil.test'},json={'enabled':True}).status_code==403
def test_real_orders_disabled(client):assert post(client,'/api/live/orders',{}).status_code==403
def test_security_headers(client):
    r=client.get('/api/health');assert "frame-ancestors 'none'" in r.headers['content-security-policy']
def test_paper_open(client):
    r=post(client,'/api/paper/open',order(client));assert r.status_code==200
    a=client.get('/api/account').json();assert len(a['open_positions'])==1 and a['cash']==9499

def test_duplicate_idempotent(client):
    a=post(client,'/api/paper/open',order(client));b=post(client,'/api/paper/open',order(client))
    assert a.json()['id']==b.json()['id'] and len(client.get('/api/account').json()['open_positions'])==1

def test_idempotency_conflict(client):
    post(client,'/api/paper/open',order(client));assert post(client,'/api/paper/open',order(client,entry=101.)).status_code==400

def test_ack_required(client):assert post(client,'/api/paper/open',order(client,acknowledged_manual=False)).status_code==400

def test_risk_limit(client):assert post(client,'/api/paper/open',order(client,quantity=20,stop=90)).status_code==400

def test_cash_exposure_limit(client):assert post(client,'/api/paper/open',order(client,quantity=21,stop=99.9)).status_code==400

def test_kill_blocks_entries_not_closes(client):
    r=post(client,'/api/paper/open',order(client)).json();post(client,'/api/kill-switch',{'enabled':True})
    assert post(client,'/api/paper/open',order(client,request_id='two')).status_code==400
    assert post(client,'/api/paper/'+r['id']+'/close',{'price':110}).status_code==200

def test_close_costs(client):
    r=post(client,'/api/paper/open',order(client)).json();c=post(client,'/api/paper/'+r['id']+'/close',{'price':110}).json()
    assert c['pnl']==pytest.approx(47.9)
    a=client.get('/api/account').json();assert a['cash']==pytest.approx(10047.9)

def test_close_duplicate(client):
    r=post(client,'/api/paper/open',order(client)).json()
    assert post(client,'/api/paper/'+r['id']+'/close',{'price':110}).json()==post(client,'/api/paper/'+r['id']+'/close',{'price':110}).json()

def test_noninteger_quantity(client):assert post(client,'/api/paper/open',order(client,quantity=1.5)).status_code==422

def test_inverted_plan(client):assert post(client,'/api/paper/open',order(client,stop=105.)).status_code==400

def test_api_scanner(client):
    r=client.get('/api/scanner');assert r.status_code==200 and r.json()[0]['synthetic']
def test_mismatch(client):assert client.get('/api/analysis/'+client.ident+'?strategy=opening_range').status_code==400

def test_backtest_job_and_cache(client):
    body={'dataset_id':client.ident,'strategy':'trend_pullback','config':{}}
    r=post(client,'/api/studies',body).json()
    for _ in range(100):
        j=client.get('/api/jobs/'+r['job_id']).json()
        if j['status']!='running':break
        time.sleep(.03)
    assert j['status']=='complete'
    result=client.get('/api/experiments/'+j['result_id']).json()
    assert result['current_probability'] is None
    assert post(client,'/api/studies',body).json()['cached']

def test_payoff_api(client):
    r=post(client,'/api/options/payoff',{'kind':'bull_call','long_strike':100,'short_strike':110,'net_debit':4,'lot_size':10,'lots':1,'charges':2})
    assert r.json()['max_loss']==42

def test_missing_broker_token(client,monkeypatch):
    monkeypatch.delenv('UPSTOX_ACCESS_TOKEN',raising=False)
    r=post(client,'/api/import/upstox',{'symbol':'TEST','timeframe':'1d','instrument_key':'NSE_EQ|TEST','start':'2020-01-01','end':'2026-01-01'})
    assert r.status_code==400 and 'token' in r.json()['error'].lower()

def test_audit_created(client):
    post(client,'/api/paper/open',order(client));assert any(e['action']=='PAPER_POSITION_OPENED' for e in client.get('/api/audit').json())

def test_daily_realized_loss_halts_new_entries(client):
    p=post(client,'/api/paper/open',order(client,quantity=10,stop=99)).json()
    assert post(client,'/api/paper/'+p['id']+'/close',{'price':80}).status_code==200
    r=post(client,'/api/paper/open',order(client,request_id='after-loss'))
    assert r.status_code==400 and 'Daily realized-loss' in r.json()['error']

def test_cumulative_loss_review_halts_entries(client):
    p=post(client,'/api/paper/open',order(client,quantity=10,stop=99)).json()
    post(client,'/api/paper/'+p['id']+'/close',{'price':30})
    with client.store.db() as c:
        c.execute('UPDATE positions SET closed=? WHERE id=?',('2000-01-01T12:00:00+05:30',p['id']))
    r=post(client,'/api/paper/open',order(client,request_id='after-drawdown'))
    assert r.status_code==400 and 'cumulative loss' in r.json()['error']

def test_maximum_open_positions(client):
    second=client.store.add_dataset('SIM-TWO','1d','test',True,demo_bars(2,'1d',300))
    third=client.store.add_dataset('SIM-THREE','1d','test',True,demo_bars(3,'1d',300))
    assert post(client,'/api/paper/open',order(client)).status_code==200
    assert post(client,'/api/paper/open',order(client,request_id='two',dataset_id=second)).status_code==200
    r=post(client,'/api/paper/open',order(client,request_id='three',dataset_id=third))
    assert r.status_code==400 and 'Maximum simultaneous' in r.json()['error']

def test_synthetic_and_imported_positions_cannot_mix(client):
    other=client.store.add_dataset('IMPORTED','1d','user file',False,demo_bars(2,'1d',300))
    post(client,'/api/paper/open',order(client))
    r=post(client,'/api/paper/open',order(client,request_id='two',dataset_id=other))
    assert r.status_code==400 and 'mix synthetic' in r.json()['error']

def test_malformed_content_length_rejected(client):
    assert client.get('/api/health',headers={'Content-Length':'not-a-number'}).status_code==400

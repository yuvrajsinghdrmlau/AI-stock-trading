from __future__ import annotations
import hashlib, json, os, secrets, threading, uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from .data import csv_bars, demo_bars, symbol_ok, freshness
from .store import Store
from .strategies import STRATEGIES, CATALOG, analyse
from .research import run_study, config_for, walkforward_study
from .providers import upstox_history
from .options import debit_spread
from .universe import Universe
from .market import BrokerData
from .model_registry import Models
from .desk import Desk
from .v2_api import register_v2

ROOT=Path(__file__).resolve().parents[1]

def load_env():
    p=ROOT/'.env'
    if p.exists():
        for line in p.read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.strip().startswith('#'):
                k,v=line.split('=',1);k=k.strip()
                if k in ('UPSTOX_ACCESS_TOKEN','INDIA_QUANT_DATA_DIR'):os.environ.setdefault(k,v.strip().strip('"').strip("'"))

class CSVImport(BaseModel):
    model_config=ConfigDict(extra='forbid')
    symbol:str=Field(max_length=24)
    timeframe:str
    csv_text:str=Field(max_length=4_000_000)
    source:str=Field(default='User-provided CSV',max_length=120)
class HistoryImport(BaseModel):
    model_config=ConfigDict(extra='forbid')
    symbol:str=Field(max_length=24)
    timeframe:str
    instrument_key:str=Field(max_length=100)
    start:str=Field(max_length=10)
    end:str=Field(max_length=10)
class Study(BaseModel):
    model_config=ConfigDict(extra='forbid')
    dataset_id:str
    strategy:str
    config:dict=Field(default_factory=dict)
    walkforward:bool=False
class PaperOpen(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id:str=Field(max_length=80)
    dataset_id:str
    quantity:int=Field(strict=True,ge=1,le=1000000)
    entry:float=Field(gt=0,allow_inf_nan=False)
    stop:float=Field(gt=0,allow_inf_nan=False)
    target:float=Field(gt=0,allow_inf_nan=False)
    acknowledged_manual:bool=False
class PaperClose(BaseModel):
    price:float=Field(gt=0,allow_inf_nan=False)
class OptionScenario(BaseModel):
    model_config=ConfigDict(extra="forbid")
    kind:str
    long_strike:float=Field(gt=0,allow_inf_nan=False)
    short_strike:float=Field(gt=0,allow_inf_nan=False)
    net_debit:float=Field(gt=0,allow_inf_nan=False)
    lot_size:int=Field(strict=True,ge=1,le=100000)
    lots:int=Field(strict=True,ge=1,le=1000)
    charges:float=Field(ge=0,allow_inf_nan=False)

class Kill(BaseModel):
    enabled:bool

def create_app(data_dir=None,seed_demo=True,testing=False):
    load_env()
    directory=Path(data_dir or os.getenv('INDIA_QUANT_DATA_DIR',ROOT/'data'))
    store=Store(directory/'desk.sqlite3')
    if seed_demo and not store.datasets():
        for seed in range(1,7):
            name=['ALPHA','BETA','GAMMA','DELTA','EPSILON','ZETA'][seed-1]
            store.add_dataset('SIM-'+name,'1d','Generated synthetic fixture',True,demo_bars(seed,'1d',3200),['Entire dataset is fictional. Dates are not an exchange calendar.'])
        for seed,name in ((2,'BETA'),(4,'DELTA'),(6,'ZETA')):
            store.add_dataset('SIM-'+name,'15m','Generated synthetic fixture',True,demo_bars(seed,'15m',5000),['Entire dataset is fictional.'])
    app=FastAPI(title='India Quant research API',version='2.1.0',docs_url=None,redoc_url=None,openapi_url='/api/schema')
    app.state.store=store;token=secrets.token_urlsafe(32);jobs={};guard=threading.Lock();executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='research')
    app.state.token=token
    universe=Universe(store); broker=BrokerData(); models=Models(store,universe); desk=Desk(store,universe,broker,models)
    app.state.universe=universe; app.state.broker=broker; app.state.models=models; app.state.desk=desk
    register_v2(app,store,universe,broker,models,desk)
    @app.middleware('http')
    async def safety(request:Request,call_next):
        host=request.headers.get('host','').split(':')[0].lower()
        allowed={'localhost','127.0.0.1'}|({'testserver'} if testing else set())
        if host not in allowed:return JSONResponse({'error':'Local-only build. Public multi-user deployment is not enabled.'},status_code=403)
        try:
            content_length=int(request.headers.get('content-length','0') or 0)
        except ValueError:
            return JSONResponse({'error':'Invalid Content-Length.'},status_code=400)
        if content_length<0:return JSONResponse({'error':'Invalid Content-Length.'},status_code=400)
        if content_length>5_000_000:return JSONResponse({'error':'Request too large.'},status_code=413)
        origin=request.headers.get('origin')
        if origin and origin not in (f'http://{request.headers.get("host")}',f'https://{request.headers.get("host")}'):
            return JSONResponse({'error':'Cross-origin requests are blocked.'},status_code=403)
        if request.method in ('POST','PUT','PATCH','DELETE'):
            if not secrets.compare_digest(request.headers.get('x-desk-token',''),token):return JSONResponse({'error':'Missing/expired local session token. Reload the application.'},status_code=403)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Cache-Control']='no-store'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        return response
    @app.exception_handler(ValueError)
    async def value_error(request,exc):return JSONResponse({'error':str(exc)},status_code=400)
    @app.get('/api/bootstrap')
    def bootstrap():
        return {'token':token,'version':'2.1.0','name':'India Quant','datasets':store.datasets(),'strategies':STRATEGIES,'account':store.account(),
          'providers':{'upstox_configured':bool(os.getenv('UPSTOX_ACCESS_TOKEN')),'live':False,'order_execution':False,'quote_adapter':True},'catalogue':universe.status(),'watchlist':universe.watch(),'experiments':store.experiments()}
    @app.get('/api/health')
    def health():return {'status':'ok','mode':'local_research_and_manual_paper','live_orders':False,'database':'sqlite','workers':1}
    @app.get('/api/datasets')
    def datasets():return store.datasets()
    @app.get('/api/analysis/{ident}')
    def analysis(ident:str,strategy:str='trend_pullback'):
        if strategy not in CATALOG:raise ValueError('Unknown strategy.')
        d=store.dataset(ident)
        if d['timeframe']!=CATALOG[strategy]['timeframe']:raise ValueError('Timeframe mismatch.')
        return {**analyse(d['bars'],d['timeframe'],strategy),'dataset':{k:v for k,v in d.items() if k!='bars'},'freshness':freshness(d)}
    @app.get('/api/scanner')
    def scanner(strategy:str='trend_pullback'):
        if strategy not in CATALOG:raise ValueError('Unknown strategy.')
        result=[]
        for d in store.datasets():
            if d['timeframe']!=CATALOG[strategy]['timeframe']:continue
            full=store.dataset(d['id']);a=analyse(full['bars'],full['timeframe'],strategy)
            result.append({**d,'regime':a['last']['regime'],'rsi':a['last']['rsi'],'relative_volume':a['last']['rv'],'setup_score':a['setup_score'],'rule_pass':a['rule_pass']})
        return sorted(result,key=lambda r:(r['rule_pass'],r['setup_score']),reverse=True)
    @app.post('/api/import/csv')
    def import_csv(body:CSVImport):
        if len(store.datasets())>=80:raise ValueError('Local workspace limit: 80 datasets.')
        bars,warnings=csv_bars(body.csv_text,body.timeframe)
        ident=store.add_dataset(symbol_ok(body.symbol),body.timeframe,body.source,False,bars,warnings)
        return {'id':ident,'warnings':warnings,'bars':len(bars)}
    @app.post('/api/import/upstox')
    def import_upstox(body:HistoryImport):
        if len(store.datasets())>=80:raise ValueError('Local workspace limit: 80 datasets.')
        bars,warnings=upstox_history(body.instrument_key,body.timeframe,body.start,body.end)
        ident=store.add_dataset(symbol_ok(body.symbol),body.timeframe,'Upstox V3 historical',False,bars,warnings)
        return {'id':ident,'warnings':warnings,'bars':len(bars)}
    @app.post('/api/studies')
    def study(body:Study):
        d=store.dataset(body.dataset_id);cfg=config_for(body.strategy,body.config)
        if CATALOG[body.strategy]['timeframe']!=d['timeframe']:raise ValueError('Strategy/timeframe mismatch.')
        key=hashlib.sha256(json.dumps({'dataset_id':d['id'],'sha':d['sha'],'strategy':body.strategy,'config':cfg,'engine':'iq-2.0.0','walkforward':body.walkforward},sort_keys=True).encode()).hexdigest()
        old=store.experiment_by_key(key)
        if old:return {'cached':True,'result_id':old['id']}
        with guard:
            active=next((j for j in jobs.values() if j['status']=='running'),None)
            if active:raise HTTPException(429,'A research run is already active. One local CPU worker is allowed.')
            jid=uuid.uuid4().hex[:16];jobs[jid]={'id':jid,'status':'running','progress':0,'message':'Preparing research'}
        def work():
            def update(progress,message):
                with guard:jobs[jid].update(progress=progress,message=message)
            try:
                result=run_study(d,body.strategy,cfg,lambda p,m:update(int(p*.55) if body.walkforward else p,m),artifact_callback=models.save)
                if body.walkforward:
                    result['walkforward']=walkforward_study(d,body.strategy,cfg,lambda p,m:update(55+int(p*.44),m))
                saved=store.save_experiment(key,result)
                with guard:jobs[jid].update(status='complete',progress=100,result_id=saved['id'],message='Research saved')
            except Exception as exc:
                with guard:jobs[jid].update(status='failed',error=str(exc)[:500],message='Run failed; no results fabricated')
        executor.submit(work)
        return {'job_id':jid,'cached':False}
    @app.get('/api/jobs/{jid}')
    def job(jid:str):
        with guard:
            if jid not in jobs:raise ValueError('Job not found. A server restart does not resume unfinished jobs.')
            return dict(jobs[jid])
    @app.get('/api/experiments')
    def experiments():return store.experiments()
    @app.get('/api/experiments/{ident}')
    def experiment(ident:str):return store.experiment(ident)
    @app.get('/api/experiments/{ident}/download')
    def download(ident:str):return Response(json.dumps(store.experiment(ident),indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="research_{ident}.json"'})
    @app.post('/api/options/payoff')
    def options_payoff(body:OptionScenario):
        s=store.settings()
        return debit_spread(**body.model_dump(),risk_budget=s['capital']*s['risk_pct']/100)
    @app.get('/api/account')
    def account():return store.account()
    @app.post('/api/paper/open')
    def paper_open(body:PaperOpen):
        if not body.acknowledged_manual:raise ValueError('Acknowledge that this is a manual paper journal, not a broker order.')
        return store.open_position(body.request_id,body.dataset_id,body.quantity,body.entry,body.stop,body.target)
    @app.post('/api/paper/{ident}/close')
    def paper_close(ident:str,body:PaperClose):return store.close_position(ident,body.price)
    @app.post('/api/kill-switch')
    def kill(body:Kill):return store.toggle_kill(body.enabled)
    @app.get('/api/audit')
    def audit():return store.audits()
    @app.post('/api/live/orders')
    def blocked():raise HTTPException(403,'Live execution is deliberately not implemented in this release.')
    @app.get('/')
    def index():return FileResponse(ROOT/'frontend'/'index.html')
    app.mount('/static',StaticFiles(directory=ROOT/'frontend'),name='static')
    return app

app=create_app() if os.getenv('IQ_NO_DEFAULT_APP')!='1' else None

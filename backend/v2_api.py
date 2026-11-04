"""Discovery, snapshot boards, incremental history and read-only option-chain APIs."""
from __future__ import annotations
import threading
import time
from datetime import datetime, timedelta
import uuid
import json
from concurrent.futures import ThreadPoolExecutor
from fastapi import HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from .desk import MODE_STRATEGIES, DEFAULT_FILTERS, filters_config
from .strategies import CATALOG, analyse
from .data import IST, parse_time, csv_bars
from .trade_plans import BROKER_PLATFORMS, DATA_OPTIONS
from .recommendations import select_universe, history_due, SCOPES
from .derivative_ideas import build_derivative_idea

class WatchChange(BaseModel):
    model_config=ConfigDict(extra='forbid')
    instrument_key:str=Field(min_length=5,max_length=110)
    enabled:bool=True

class RefreshHistory(BaseModel):
    model_config=ConfigDict(extra='forbid')
    instrument_keys:list[str]=Field(min_length=1,max_length=25)
    timeframe:str
    source:str='auto'

class MarketCSV(BaseModel):
    model_config=ConfigDict(extra='forbid')
    instrument_key:str=Field(min_length=5,max_length=110)
    timeframe:str
    csv_text:str=Field(max_length=4_000_000)

class BoardRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    mode:str='Swing'
    filters:dict=Field(default_factory=dict)

class PlanReview(BaseModel):
    model_config=ConfigDict(extra='forbid')
    instrument_key:str=Field(min_length=5,max_length=110)
    strategy:str
    filters:dict=Field(default_factory=dict)
    latest_price:bool=False

class RecommendationScan(BoardRequest):
    refresh:bool=False
    source:str='auto'
    scope:str='nifty500'
    holding:str='Intraday'

class DerivativeReview(BaseModel):
    model_config=ConfigDict(extra='forbid')
    instrument_key:str=Field(min_length=5,max_length=110)
    product:str='Options'
    holding:str='Intraday'


def register_v2(app,store,universe,broker,models,desk):
    worker=ThreadPoolExecutor(max_workers=1,thread_name_prefix='provider-read')
    jobs={}; lock=threading.Lock(); attempts={}
    def job_running():
        with lock:return any(j['status']=='running' for j in jobs.values())
    from .trade_tools import register_tools
    register_tools(app,store,universe,broker,desk,job_running)
    with store.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS recommendation_cache(id TEXT PRIMARY KEY,body TEXT)')

    def launch(task):
        with lock:
            if any(j['status']=='running' for j in jobs.values()):
                raise HTTPException(429,'A catalogue/history refresh is already running. Check its progress first.')
            if len(jobs)>60:
                for key in list(jobs)[:30]:
                    if jobs[key]['status']!='running': del jobs[key]
            jid=uuid.uuid4().hex[:16];jobs[jid]={'id':jid,'status':'running','progress':0,'message':'Starting data request'}
        def update(progress,message,partial=None):
            with lock:
                jobs[jid].update(progress=progress,message=message)
                if partial is not None: jobs[jid]['result']=partial
        def cancelled():
            with lock: return jobs[jid].get('cancel_requested',False)
        update.cancelled=cancelled
        def work():
            try:
                result=task(update)
                with lock: jobs[jid].update(status='complete',progress=100,result=result,message='Completed')
            except Exception as exc:
                with lock: jobs[jid].update(status='failed',error=str(exc)[:400],message='Data unavailable; no prices fabricated')
        worker.submit(work)
        return {'job_id':jid}

    @app.get('/api/universe/status')
    def universe_status(): return universe.status()

    @app.get('/api/universe/search')
    def search(q:str=Query(default='',max_length=100),exchange:str='ALL',kind:str='CASH',offset:int=0,limit:int=50):
        return universe.search(q,exchange,kind,offset,limit)

    @app.post('/api/universe/sync')
    def sync():
        def work(update):
            update(10,'Downloading provider catalogue and suspension records')
            return universe.sync()
        return launch(work)

    @app.get('/api/watchlist')
    def watchlist(): return universe.watch()

    @app.post('/api/watchlist')
    def change(body:WatchChange): return universe.set_watch(body.instrument_key,body.enabled)

    @app.get('/api/market/config')
    def market_config():
        return {'upstox_configured':broker.configured,'catalogue':universe.status(),'watchlist':universe.watch(),
            'filters':DEFAULT_FILTERS,'live_orders':False,'poll_seconds':20,'max_watched':25,
            'brokers':BROKER_PLATFORMS,'data_options':DATA_OPTIONS,
            'notes':['Catalogue search is not restricted to the live watchlist.', 'A REST snapshot is not a tick-by-tick stream.','Authenticated data requests are subject to your provider entitlements.']}

    @app.post('/api/market/history')
    def history(body:RefreshHistory):
        if body.timeframe not in ('1d','15m'): raise ValueError('Timeframe must be 1d or 15m.')
        if body.source not in ('auto','broker','public'): raise ValueError('History source must be auto, broker or public.')
        keys=list(dict.fromkeys(body.instrument_keys))
        for key in keys: universe.get(key)
        def work(update):
            result=[]
            for i,key in enumerate(keys):
                update(int(i/len(keys)*95),'Loading '+universe.get(key)['symbol']+' '+body.timeframe+' completed candles')
                try: result.append({'instrument_key':key,**desk.refresh_history(key,body.timeframe,body.source),'ok':True})
                except ValueError as exc: result.append({'instrument_key':key,'ok':False,'error':str(exc)})
            return {'items':result,'successes':sum(r['ok'] for r in result)}
        return launch(work)

    @app.post('/api/market/import-csv')
    def market_csv(body:MarketCSV):
        instrument=universe.get(body.instrument_key)
        bars,warnings=csv_bars(body.csv_text,body.timeframe)
        ident=store.add_dataset(instrument['exchange']+':'+instrument['symbol'],body.timeframe,
            'User-provided CSV | '+body.instrument_key,False,bars,warnings)
        universe.link(body.instrument_key,body.timeframe,ident)
        return {'dataset_id':ident,'bars':len(bars),'last_bar':bars[-1]['t'],'warnings':warnings}

    @app.post('/api/market/refresh-due')
    def refresh_due(body:BoardRequest):
        # Called only while the user has opted into the open-page polling loop.
        # There is no overnight daemon or promised scheduled delivery.
        if body.mode!='Intraday' or not broker.configured:
            return {'job_id':None,'reason':'Only connected intraday boards auto-refresh completed candles.'}
        now=datetime.now(IST);minute=now.hour*60+now.minute
        if now.weekday()>4 or not 570<=minute<885:
            return {'job_id':None,'reason':'Outside supported regular intraday entry window.'}
        target=now.replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(minutes=555+((minute-555)//15-1)*15)
        with lock:
            if any(j['status']=='running' for j in jobs.values()):
                return {'job_id':None,'reason':'A data refresh is already running.'}
        keys=[]
        statuses={}
        for inst in universe.watch():
            if not inst.get('simple_equity') or inst.get('suspended'): continue
            key=inst['instrument_key']; data=universe.history(key,'15m')
            if not data or parse_time(data['bars'][-1]['t'],'15m')>=target: continue
            if time.monotonic()-attempts.get(key,-1000)<60: continue
            if inst['exchange'] not in statuses:
                try: statuses[inst['exchange']]=broker.exchange_status(inst['exchange'])
                except ValueError: statuses[inst['exchange']]={'status':'UNKNOWN'}
            status=statuses[inst['exchange']]
            if status.get('status')!='NORMAL_OPEN' or (inst.get('cas_eligible') and status.get('cas_status')): continue
            keys.append(key)
        if not keys: return {'job_id':None,'reason':'No loaded intraday instrument needs a completed-bar update.'}
        for key in keys: attempts[key]=time.monotonic()
        def work(update):
            result=[]
            for i,key in enumerate(keys):
                update(int(i/len(keys)*95),'Updating completed intraday candles: '+universe.get(key)['symbol'])
                try: result.append({'instrument_key':key,**desk.refresh_history(key,'15m'),'ok':True})
                except ValueError as exc: result.append({'instrument_key':key,'ok':False,'error':str(exc)})
            return {'items':result,'successes':sum(r['ok'] for r in result)}
        return launch(work)

    @app.get('/api/market/jobs/{ident}')
    def job(ident:str,after_processed:int=-1):
        with lock:
            if ident not in jobs: raise ValueError('Data job not found. Restarted servers do not resume unfinished refreshes.')
            result=dict(jobs[ident])
            if result['status']=='running' and result.get('result',{}).get('processed')==after_processed:
                result.pop('result',None)
            return result

    @app.post('/api/market/jobs/{ident}/cancel')
    def cancel_job(ident:str):
        with lock:
            if ident not in jobs: raise ValueError('Data job not found.')
            jobs[ident]['cancel_requested']=True
        return {'requested':True,'message':'Stopping after the current batch.'}

    @app.post('/api/desk/scan')
    def scan(body:BoardRequest): return desk.board(body.mode,body.filters)

    @app.post('/api/desk/review')
    def review(body:PlanReview): return desk.review(body.instrument_key,body.strategy,body.filters,body.latest_price)

    @app.get('/api/desk/log')
    def log(): return desk.signal_log()

    @app.post('/api/recommendations/scan')
    def recommendations(body:RecommendationScan):
        if body.mode not in (*MODE_STRATEGIES,'Options','Futures'): raise ValueError('Use Intraday, Swing, Delivery, Options or Futures.')
        if body.scope not in SCOPES: raise ValueError('Unknown stock universe.')
        if body.holding not in ('Intraday','Swing'): raise ValueError('Use Intraday or Swing holding for F&O.')
        if body.source not in ('auto','public','broker'): raise ValueError('Invalid history source.')
        cfg=filters_config(body.filters)
        def work(update):
            if universe.status().get('stale',True):
                update(1,'Refreshing stock catalogue before discovery')
                universe.sync()
            derivatives=body.mode in ('Options','Futures')
            instruments,missing,coverage=select_universe(universe,body.scope,derivatives)
            if not instruments: raise ValueError('No eligible listings found in this universe. Refresh the catalogue or choose All NSE stocks.')
            errors=list(coverage['warnings']); loaded=0; rows=[]; processed=0; with_history=0
            timeframe='15m' if body.mode=='Intraday' or (derivatives and body.holding=='Intraday') else '1d'
            paused=threading.Event()
            def history_one(inst):
                if paused.is_set(): return False, 'Provider rate limit reached; use cached data or retry later.'
                existing=universe.history(inst['instrument_key'],timeframe)
                if not body.refresh and not history_due(existing,timeframe): return False,None
                try:
                    desk.refresh_history(inst['instrument_key'],timeframe,body.source)
                    return True,None
                except ValueError as exc:
                    if '429' in str(exc): paused.set()
                    return False,str(exc)
            def snapshot():
                return {'mode':body.mode,'holding':body.holding,'scope':coverage['label'],'coverage':coverage,
                        'generated_at':store.now(),'rows':list(rows),'errors':sorted(set(errors)),
                        'basket_symbols':[i['symbol'] for i in instruments], 'missing_symbols':missing,
                        'refreshed':loaded,'evaluated':len(rows),'processed':processed,'total':len(instruments),
                        'with_history':with_history,'complete':processed==len(instruments),
                        'configured':broker.configured,'live_execution':False,'filters':cfg}
            # Publish batches as they finish; no 25-stock scan cap or watchlist mutation.
            workers=1 if broker.configured and body.source!='public' else 4
            with ThreadPoolExecutor(max_workers=workers,thread_name_prefix='scan-history') as readers:
                for start in range(0,len(instruments),10):
                    if update.cancelled(): break
                    batch=instruments[start:start+10]
                    update(3+int(95*start/len(instruments)),f'Checking {start+1}–{min(start+10,len(instruments))} of {len(instruments)} stocks',snapshot())
                    for inst,result in zip(batch,readers.map(history_one,batch)):
                        ok,error=result; loaded+=int(ok)
                        if error: errors.append(inst['symbol']+': '+error)
                    snapshots={}; quotes={}; statuses={}
                    if not broker.configured and not paused.is_set():
                        from .public_quotes import public_quote
                        with ThreadPoolExecutor(max_workers=3,thread_name_prefix='scan-price') as prices:
                            futures=[(inst,prices.submit(public_quote,inst)) for inst in batch]
                            for inst,future in futures:
                                try: snapshots[inst['instrument_key']]=future.result()
                                except ValueError as exc:
                                    errors.append(inst['symbol']+' price: '+str(exc))
                                    if '429' in str(exc): paused.set()
                    if derivatives:
                        if broker.configured:
                            try: quotes=broker.quotes([i['instrument_key'] for i in batch])
                            except ValueError as exc: errors.append(str(exc))
                            try: statuses=broker.exchange_status('NSE')
                            except ValueError as exc: errors.append(str(exc))
                        for inst in batch:
                            key=inst['instrument_key']; data=universe.history(key,timeframe)
                            rows.append(build_derivative_idea(inst,data,universe.contracts(key),body.mode,body.holding,
                                        universe.status(),store.account(),quotes.get(key) or snapshots.get(key),broker,statuses))
                    else:
                        board=desk.board(body.mode,cfg,instruments=batch,public_snapshots=snapshots)
                        # Discovery cards re-fetch full evidence on review. Avoid sending model
                        # metadata, long copy records and duplicate checklists on every batch.
                        for row in board['rows']:
                            compact={k:v for k,v in row.items() if k not in ('model','checks','market','advisory','event_risk')}
                            compact['trade_plan']={k:v for k,v in row.get('trade_plan',{}).items()
                                                   if k not in ('checks','copy_text','limitations')}
                            rows.append(compact)
                        errors.extend(board['errors'])
                    with_history+=sum(bool(universe.history(i['instrument_key'],timeframe)) for i in batch)
                    processed+=len(batch)
                    update(3+int(95*processed/len(instruments)),f'{processed} of {len(instruments)} stocks checked',snapshot())
            result=snapshot()
            result['cancelled']=update.cancelled()
            with store.db() as db:
                db.execute('INSERT OR REPLACE INTO recommendation_cache VALUES(?,?)',
                           ('|'.join((body.mode,body.scope,body.holding)),json.dumps(result,allow_nan=False)))
            return result
        return launch(work)

    @app.get('/api/recommendations/latest')
    def latest_recommendations(mode:str='Delivery',scope:str='nifty500',holding:str='Intraday'):
        if mode not in (*MODE_STRATEGIES,'Options','Futures') or scope not in SCOPES or holding not in ('Intraday','Swing'):
            raise ValueError('Invalid saved-scan selection.')
        with store.db() as db:
            row=db.execute('SELECT body FROM recommendation_cache WHERE id=?',('|'.join((mode,scope,holding)),)).fetchone()
        return {**json.loads(row['body']),'cached':True} if row else None

    @app.post('/api/recommendations/review-derivative')
    def review_derivative(body:DerivativeReview):
        if body.product not in ('Options','Futures') or body.holding not in ('Intraday','Swing'):
            raise ValueError('Invalid derivative product or holding period.')
        inst=universe.get(body.instrument_key); timeframe='15m' if body.holding=='Intraday' else '1d'
        contracts=universe.contracts(body.instrument_key)
        if not contracts: raise ValueError('No current derivative contracts are listed for this instrument.')
        data=universe.history(body.instrument_key,timeframe)
        if history_due(data,timeframe):
            desk.refresh_history(body.instrument_key,timeframe)
            data=universe.history(body.instrument_key,timeframe)
        quote=None; market=None; errors=[]
        try:
            if broker.configured:
                quote=broker.quotes([body.instrument_key]).get(body.instrument_key)
                market=broker.exchange_status(inst['exchange'])
            else:
                from .public_quotes import public_quote
                quote=public_quote(inst)
        except ValueError as exc: errors.append(str(exc))
        row=build_derivative_idea(inst,data,contracts,body.product,body.holding,universe.status(),store.account(),quote,broker,market)
        row['data_errors']=errors
        return row

    @app.get('/api/models')
    def model_list(): return models.list()

    @app.get('/api/market/chart')
    def chart(instrument_key:str,strategy:str='trend_pullback'):
        if strategy not in CATALOG: raise ValueError('Unknown strategy.')
        instrument=universe.get(instrument_key); tf=CATALOG[strategy]['timeframe']; data=universe.history(instrument_key,tf)
        if not data: return {'instrument':instrument,'data_required':True,'timeframe':tf,'configured':broker.configured}
        a=analyse(data['bars'],tf,strategy)
        # Chart rendering does not implicitly poll the broker on every filter change.
        return {**a,'instrument':instrument,'data_required':False,'dataset':{k:v for k,v in data.items() if k!='bars'},
            'model':models.infer(instrument_key,strategy,data),'source_kind':'COMPLETED_HISTORICAL_BARS','configured':broker.configured}

    @app.get('/api/market/quote')
    def quote(instrument_key:str):
        inst=universe.get(instrument_key)
        return {'quote':broker.quotes([instrument_key])[instrument_key],'market':broker.exchange_status(inst['exchange'])}

    @app.get('/api/market/expiries')
    def expiries(instrument_key:str):
        universe.get(instrument_key)
        return {'expiries':broker.expiries(instrument_key)}

    @app.get('/api/market/option-chain')
    def chain(instrument_key:str,expiry:str):
        universe.get(instrument_key)
        return broker.option_chain(instrument_key,expiry)

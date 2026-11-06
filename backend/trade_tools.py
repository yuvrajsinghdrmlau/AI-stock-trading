"""Manual decision tools: entry, exits, replay, news, practice budget and alerts."""
import threading
import time
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .entry_timing import entry_timing, exit_scenario
from .trade_replay import replay
from .market_news import fetch_news
from .price_alerts import PriceAlerts
from .strategies import CATALOG
from .recommendations import history_due
from .mode_data import mode_dataset, mode_data


class ToolRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    instrument_key:str=Field(min_length=5,max_length=110)
    strategy:str='trend_pullback'
    side:Literal['buy','sell']='buy'
    stop_method:Literal['atr','range_mid','range_edge']='atr'
    reward_r:float=Field(default=2,ge=1,le=4,allow_inf_nan=False)
    refresh:bool=False
    derivative:bool=False

class ReplayRequest(ToolRequest):
    paths:int=Field(default=1000,ge=100,le=5000,strict=True)
    seed:int=Field(default=42,ge=0,le=999999,strict=True)

class AlertRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    instrument_key:str=Field(min_length=5,max_length=110)
    condition:Literal['above','below']
    level:float=Field(gt=0,le=10000000,allow_inf_nan=False)

class BudgetRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    capital:float=Field(ge=1000,le=10000000,allow_inf_nan=False)
    risk_pct:float=Field(default=.5,ge=.1,le=1,allow_inf_nan=False)
    exposure_pct:float=Field(default=20,ge=1,le=25,allow_inf_nan=False)


def register_tools(app,store,universe,broker,desk,job_running=lambda:False):
    alerts=PriceAlerts(store);app.state.price_alerts=alerts
    news_cache={};replay_cache={};cache_lock=threading.Lock();alert_lock=threading.Lock()

    def resolve(body):
        if body.strategy not in CATALOG:raise ValueError('Unknown strategy.')
        inst=universe.get(body.instrument_key);tf=CATALOG[body.strategy]['timeframe']
        data=universe.history(body.instrument_key,tf)
        if body.refresh and history_due(data,tf):
            desk.refresh_history(body.instrument_key,tf);data=universe.history(body.instrument_key,tf)
        return inst,data,tf

    @app.post('/api/tools/entry')
    def entry(body:ToolRequest):
        inst,data,tf=resolve(body);intraday=universe.history(body.instrument_key,'15m')
        if body.refresh and tf!='15m' and history_due(intraday,'15m'):
            desk.refresh_history(body.instrument_key,'15m');intraday=universe.history(body.instrument_key,'15m')
        feed=getattr(app.state,'live_candles',None)
        intraday=mode_dataset('Intraday',body.instrument_key,intraday,feed)
        if tf=='15m': data=intraday
        timing=entry_timing(intraday,body.side)
        scenario=None;error=None
        if data:
            try:scenario=exit_scenario(data,timing if tf=='15m' else {},store.account(),body.side,body.stop_method,body.reward_r)
            except ValueError as exc:error=str(exc)
        return {'instrument':inst,'timing':timing,'scenario':scenario,'scenario_error':error,
                'data_status':mode_data('Intraday',body.instrument_key,dataset=intraday,feed=feed,broker_configured=broker.configured),
                'timeframe':tf,'data_loaded':bool(data),'source':data['source'] if data else None,
                'account':{k:store.settings()[k] for k in ('capital','risk_pct','exposure_pct')},
                'note':'Entry timing and exit scenarios support manual review. Existing trade-plan data, price and account checks still apply.'}

    @app.post('/api/tools/replay')
    def trade_replay(body:ReplayRequest):
        inst,data,tf=resolve(body)
        if not data:raise ValueError('Load candles before replaying this stock.')
        # A dataset hash and fixed scenario parameters identify a reproducible calculation.
        key=(inst['instrument_key'],data['id'],data['sha'],body.strategy,body.side,body.derivative,inst['kind']=='INDEX',body.paths,body.seed,store.now()[:10])
        with cache_lock:cached=replay_cache.get(key)
        if cached:return {**cached,'cached':True}
        result=replay(data,body.strategy,body.side,body.derivative or body.side=='sell',inst['kind']=='INDEX',body.paths,body.seed)
        result['instrument']=inst
        with cache_lock:
            if len(replay_cache)>=30:replay_cache.pop(next(iter(replay_cache)))
            replay_cache[key]=result
        return {**result,'cached':False}

    @app.get('/api/tools/news')
    def news(instrument_key:str):
        inst=universe.get(instrument_key)
        with cache_lock:cached=news_cache.get(instrument_key)
        if cached and time.monotonic()-cached[0]<600:return {**cached[1],'cached':True}
        result=fetch_news(inst)
        with cache_lock:
            if len(news_cache)>=100:news_cache.pop(next(iter(news_cache)))
            news_cache[instrument_key]=(time.monotonic(),result)
        return {**result,'cached':False}

    @app.post('/api/tools/budget')
    def budget(body:BudgetRequest):
        if job_running():raise HTTPException(409,'Stop the current scan or wait for it to finish before changing the practice budget.')
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT COUNT(*) FROM positions').fetchone()[0]:
                raise ValueError('This practice account already has journal trades. Its starting capital is locked to preserve the recorded results.')
            for key,value in body.model_dump().items():
                db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(value),key))
            store.log(db,'PRACTICE_BUDGET_UPDATED',body.model_dump())
            db.execute('DELETE FROM recommendation_cache')
        return store.account()

    @app.get('/api/tools/alerts')
    def alert_list():
        result=alerts.list()
        for item in result:
            try:item['symbol']=universe.get(item['instrument_key'])['symbol']
            except ValueError:item['symbol']=item['instrument_key']
        return result

    @app.post('/api/tools/alerts')
    def alert_add(body:AlertRequest):
        inst=universe.get(body.instrument_key)
        if inst.get('suspended'):raise ValueError('This instrument is suspended.')
        return alerts.add(body.instrument_key,body.condition,body.level)

    @app.post('/api/tools/alerts/{ident}/cancel')
    def alert_cancel(ident:str):return alerts.cancel(ident)

    @app.post('/api/tools/alerts/check')
    def alert_check():
        if not alert_lock.acquire(blocking=False):raise HTTPException(429,'An alert check is already running.')
        try:
            keys=list({a['instrument_key'] for a in alerts.list() if a['status']=='ACTIVE'})
            quotes={};errors=[]
            if broker.configured:
                try:quotes=broker.quotes(keys)
                except ValueError as exc:errors.append(str(exc))
            else:
                from .public_quotes import public_quote
                with ThreadPoolExecutor(max_workers=3,thread_name_prefix='alert-price') as pool:
                    pending=[]
                    for key in keys:
                        try:pending.append((key,pool.submit(public_quote,universe.get(key))))
                        except ValueError as exc:errors.append(str(exc))
                    for key,future in pending:
                        try:quotes[key]=future.result()
                        except ValueError as exc:errors.append(str(exc))
            result=alerts.check(quotes);result['errors']=sorted(set(errors))
            for item in result['fired']:
                try:item['symbol']=universe.get(item['instrument_key'])['symbol']
                except ValueError:item['symbol']=item['instrument_key']
            return result
        finally:alert_lock.release()

"""Research candidate boards. Risk/data vetoes are independent of model confidence."""
from __future__ import annotations
import hashlib
import json
import math
from datetime import datetime, timedelta
from .data import IST, parse_time
from .strategies import CATALOG, analyse
from .research import config_for
from .public_history import public_history
from .trade_plans import build_trade_plan, plan_text

MODE_STRATEGIES={'Swing':['trend_pullback','range_breakout'],'Intraday':['opening_range','vwap_pullback'],'Delivery':['position_trend']}

DEFAULT_FILTERS={'min_price':1.,'max_price':1000000.,'min_volume':0.,'min_relative_volume':.8,
    'rsi_min':35.,'rsi_max':80.,'max_spread_bps':25.,'min_checklist':60.,'min_probability':.60,
    'uptrend_only':True,'candidates_only':False}

def filters_config(values=None):
    values=values or {}
    if set(values)-set(DEFAULT_FILTERS): raise ValueError('Unknown scan filter.')
    cfg={**DEFAULT_FILTERS,**values}
    limits={'min_price':(0,1000000),'max_price':(1,10000000),'min_volume':(0,1e12),'min_relative_volume':(0,20),
            'rsi_min':(0,100),'rsi_max':(0,100),'max_spread_bps':(1,200),'min_checklist':(0,100),'min_probability':(.5,.95)}
    for k,(a,b) in limits.items():
        v=cfg[k]
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not a<=v<=b:
            raise ValueError(f'Invalid filter {k}.')
    for k in ('uptrend_only','candidates_only'):
        if not isinstance(cfg[k],bool): raise ValueError('Boolean filter expected.')
    if cfg['min_price']>cfg['max_price'] or cfg['rsi_min']>cfg['rsi_max']: raise ValueError('Filter range is reversed.')
    return cfg


def risk_plan(reference,atr,cfg,account):
    equity=max(0,float(account.get('equity_cost_basis',account.get('settings',{}).get('capital',10000))))
    settings=account.get('settings',{}); cash=max(0,float(account.get('cash',equity)))
    cfg=config_for('trend_pullback',cfg) if not cfg else cfg
    stop=reference-cfg['atr_multiple']*atr; target=reference+cfg['reward_r']*cfg['atr_multiple']*atr
    if min(reference,stop,atr)<=0: return {'quantity':0,'reason':'Invalid stop/price geometry.'}
    fee=cfg['roundtrip_cost_bps']/20000; slip=cfg['slippage_bps']/10000
    entry=reference*(1+slip); stop_fill=stop*(1-slip)
    loss_per_share=entry-stop_fill+fee*(entry+stop_fill)
    risk=equity*min(settings.get('risk_pct',.5),cfg['risk_pct'])/100
    position_cash=min(cash,equity*min(settings.get('exposure_pct',20),cfg['exposure_pct'])/100)
    qty=max(0,int(min(risk/max(loss_per_share,1e-9),position_cash/(entry*(1+fee)))))
    return {'reference_entry':reference,'stop':stop,'target':target,'quantity':qty,
            'planned_loss_with_estimated_costs':qty*loss_per_share,'cash_required_estimate':qty*entry*(1+fee),
            'risk_budget':risk,'reward_r':cfg['reward_r'],
            'note':'Conditional next-open plan based on the last completed candle, not an executable quote. Gaps and fills can exceed planned loss.'}


def evaluate_candidate(instrument,dataset,analysis,quote,market,model,account,catalogue,filters,now=None):
    now=now or datetime.now(IST); spec=CATALOG[analysis['strategy']]; timeframe=dataset['timeframe']; r=analysis['last']
    cfg=model.get('config') or config_for(spec['id'],{})
    reasons=[]; checks=[]
    def gate(label,passed,reason):
        checks.append({'name':label,'pass':bool(passed)})
        if not passed: reasons.append(reason)
    dt=parse_time(r['t'],timeframe)
    quote=quote or {}; market=market or {}; model=model or {}
    gate('Current catalogue',not catalogue.get('stale',True) and catalogue.get('suspension_checked',False),'Catalogue or suspension status is stale/unverified.')
    gate('Regular cash-equity scope',instrument.get('simple_equity') and not instrument.get('suspended'), 'Index, special-series, suspended, nonstandard lot or non-equity instrument: cash recommendation disabled.')
    gate('Genuine imported/broker history',not dataset['synthetic'],'Synthetic histories are never live candidates.')
    gate('Completed-bar setup',analysis['rule_pass'],'Strategy setup does not match the last completed candle.')
    gate('Fresh exchange quote',quote.get('fresh') is True,'Quote is stale, missing a source timestamp, or the last trade is old.')
    gate('Normal trading phase',market.get('status')=='NORMAL_OPEN','Exchange is closed or its current status is unverified.')
    if instrument.get('cas_eligible'):
        gate('Outside closing auction',not market.get('cas_status'),'Closing-auction phase: continuous-session candidate disabled.')
    if timeframe=='15m':
        age=(now-(dt+timedelta(minutes=15))).total_seconds()
        fresh=dt.date()==now.date() and -5<=age<=75
        gate('Intraday signal still valid',fresh,'Next-bar setup expired or candles have not been refreshed. Refresh completed candles.')
        gate('Intraday entry cutoff',now.hour*60+now.minute<14*60+45,'Intraday entry cutoff reached.')
    else:
        age=(now.date()-dt.date()).days
        gate('Recent completed daily candle',0<=age<=4,'Daily history is older than the local four-calendar-day limit.')
    gate('Two-sided acceptable spread',quote.get('spread_bps') is not None and 0<=quote.get('spread_bps',-1)<=filters['max_spread_bps'],'Missing/crossed depth or spread exceeds configured limit.')
    ltp=quote.get('last_price')
    gate('Price range',ltp is not None and filters['min_price']<=ltp<=filters['max_price'],'Live price is outside range or absent.')
    gate('Minimum completed-bar volume',r['v']>=filters['min_volume'],'Completed-bar volume below filter.')
    gate('Relative volume',r['rv']>=filters['min_relative_volume'],'Relative volume below filter.')
    gate('RSI range',filters['rsi_min']<=r['rsi']<=filters['rsi_max'],'RSI outside filter.')
    gate('Trend regime',not filters['uptrend_only'] or r['regime']=='UPTREND','Trend regime does not pass.')
    gate('Checklist threshold',analysis['setup_score']>=filters['min_checklist'],'Checklist below filter; checklist is not a probability.')
    gate('Frozen-model evidence',model.get('status')=='RESEARCH_ESTIMATE','Model missing, stale, out-of-distribution, or historically unvalidated.')
    probability=model.get('probability')
    gate('Target-hit threshold',probability is not None and probability>=max(filters['min_probability'],cfg['threshold']),'Conditional target-hit estimate absent or below frozen-model/user threshold.')
    gate('Price near setup',ltp is not None and abs(ltp-r['c'])<=cfg['max_gap_atr']*r['atr'],'Price moved beyond the setup gap tolerance.')
    gate('Not at circuit limits',ltp is not None and
         (quote.get('lower_circuit') is None or ltp>quote['lower_circuit']*1.001) and
         (quote.get('upper_circuit') is None or ltp<quote['upper_circuit']*.999),'Price near a circuit limit.')
    plan=risk_plan(r['c'],r['atr'],cfg,account)
    gate('Risk-capped position fits',plan['quantity']>=1,'No share fits the cash and planned-risk limits.')
    settings=account['settings']; equity=account.get('equity_cost_basis',settings.get('capital',10000))
    gate('Open position limit',len(account.get('open_positions',[]))<settings.get('max_positions',2),'Paper position limit reached.')
    gate('Total planned risk',account.get('open_planned_risk',0)+plan.get('planned_loss_with_estimated_costs',0)<=equity*settings.get('total_risk_pct',1)/100,'Combined planned risk exceeds account limit.')
    gate('Daily loss limit',account.get('daily_realized_pnl',0)>-settings.get('capital',10000)*settings.get('daily_loss_pct',1)/100,'Daily realized-loss limit reached.')
    gate('Loss review limit',account.get('realized_pnl',0)>-settings.get('capital',10000)*.05,'Cumulative loss-review limit reached.')
    gate('Paper entry control',not account['settings'].get('kill_switch',False),'Paper-entry kill switch is enabled.')
    # No price-only model can independently clear news, fundamentals, or suitability.
    status=('PAPER_RESEARCH_CANDIDATE' if timeframe=='15m' else 'NEXT_OPEN_RESEARCH_WATCH') if not reasons else 'NO_TRADE'
    return {'instrument':instrument,'dataset_id':dataset['id'],'strategy':spec['id'],'strategy_name':spec['name'],'mode':spec['mode'],
            'status':status,'probability':probability,'model':model,'quote':quote,'market':market,'checks':checks,'reasons':reasons,
            'setup_score':analysis['setup_score'],'last_bar':r['t'],'regime':r['regime'],'rsi':r['rsi'],'relative_volume':r['rv'],
            'plan':plan,'generated_at':now.isoformat(), 'expires_at':(now+timedelta(seconds=20)).isoformat(),
            'event_risk':'NOT_CHECKED','advisory':'Research watch only. News, earnings, corporate actions and suitability are not cleared. No guaranteed return or automatic execution.'}


class Desk:
    def __init__(self,store,universe,broker,models):
        self.store=store; self.universe=universe; self.broker=broker; self.models=models

    def refresh_history(self,key,timeframe,source='auto'):
        instrument=self.universe.get(key)
        if source not in ('auto','broker','public'): raise ValueError('Unknown history source.')
        use_broker = source == 'broker' or (source == 'auto' and self.broker.configured)
        if use_broker and not self.broker.configured: raise ValueError('Broker history needs an Upstox token. Select public history instead.')
        if use_broker and instrument['suspended']: raise ValueError('Suspended instrument: broker data-loading action blocked.')
        old=self.universe.history(key,timeframe)
        if use_broker:
            bars,warnings=self.broker.history(key,timeframe,old['bars'] if old and old['source'].startswith('Upstox V3 |') else None)
            label='Upstox V3 | '+key
        else:
            bars,warnings,ticker=public_history(instrument,timeframe)
            label='Yahoo Finance historical | '+ticker
        # Exchange-specific symbols avoid mixing NSE/BSE price histories.
        ident=self.store.add_dataset(instrument['exchange']+':'+instrument['symbol'],timeframe,label,False,bars,warnings)
        self.universe.link(key,timeframe,ident)
        return {'dataset_id':ident,'bars':len(bars),'last_bar':bars[-1]['t'],'warnings':warnings}

    def evaluate(self, inst, strategy, cfg, account, catalogue, quote=None, market=None, public_snapshot=None):
        spec=CATALOG[strategy]; data=self.universe.history(inst['instrument_key'],spec['timeframe'])
        if not data:
            return {'instrument':inst,'strategy':strategy,'strategy_name':spec['name'],'mode':spec['mode'],
                'status':'DATA_REQUIRED','reasons':['Load '+spec['timeframe']+' history for this stock.'],
                'probability':None,'quote':quote,'public_snapshot':public_snapshot,
                'trade_plan':{'decision':'DATA_REQUIRED','entry':None}}
        a={**analyse(data['bars'],data['timeframe'],strategy),'strategy':strategy}
        model=self.models.infer(inst['instrument_key'],strategy,data)
        row=evaluate_candidate(inst,data,a,quote,market,model,account,catalogue,cfg)
        row['public_snapshot']=public_snapshot
        row['trade_plan']=build_trade_plan(row,data,a,catalogue,cfg)
        if not self.broker.configured and row['trade_plan']['decision']=='CONDITIONAL_BUY':
            row['status']='PUBLIC_RESEARCH_SETUP' if data['timeframe']=='15m' else 'HISTORICAL_SETUP'
        row['trade_plan']['copy_text']=plan_text(row)
        self._audit(row)
        return row

    def review(self,key,strategy,filters=None,latest_price=False):
        if strategy not in CATALOG: raise ValueError('Unknown strategy.')
        inst=self.universe.get(key); quote=None; market=None; errors=[]; public_snapshot=None
        if self.broker.configured:
            try: quote=self.broker.quotes([key]).get(key)
            except ValueError as exc: errors.append(str(exc))
            try: market=self.broker.exchange_status(inst['exchange'])
            except ValueError as exc: errors.append(str(exc))
        elif latest_price:
            from .public_quotes import public_quote
            try: public_snapshot=public_quote(inst)
            except ValueError as exc: errors.append(str(exc))
        row=self.evaluate(inst,strategy,filters_config(filters),self.store.account(),self.universe.status(),quote,market,public_snapshot)
        row['data_errors']=errors
        return row

    def board(self,mode,filters=None,instruments=None,public_snapshots=None):
        if mode not in MODE_STRATEGIES: raise ValueError('Use Swing, Intraday or Delivery. F&O has a separate read-only chain.')
        cfg=filters_config(filters); watched=self.universe.watch() if instruments is None else instruments
        keys=[r['instrument_key'] for r in watched if not r.get('unavailable')]
        quotes={}; statuses={}; errors=[]
        if self.broker.configured and keys:
            try: quotes=self.broker.quotes(keys)
            except ValueError as exc: errors.append(str(exc))
            for ex in {r.get('exchange') for r in watched if r.get('exchange')}:
                try: statuses[ex]=self.broker.exchange_status(ex)
                except ValueError as exc: errors.append(str(exc))
        elif keys: errors.append('No broker token: daily conditional plans use completed history only. Live quotes, verified market status and live-qualified intraday plans are unavailable.')
        account=self.store.account(); catalogue=self.universe.status(); rows=[]
        for inst in watched:
            if inst.get('unavailable'):
                rows.append({'instrument':inst,'status':'UNAVAILABLE','reasons':['Instrument not in refreshed catalogue.'],'probability':None})
                continue
            for strategy in MODE_STRATEGIES[mode]:
                rows.append(self.evaluate(inst,strategy,cfg,account,catalogue,quotes.get(inst['instrument_key']),statuses.get(inst['exchange']),
                                          (public_snapshots or {}).get(inst['instrument_key'])))
        rows.sort(key=lambda r:(r.get('trade_plan',{}).get('decision')=='CONDITIONAL_BUY',
            r.get('trade_plan',{}).get('live_qualified',False),r.get('setup_score') or 0),reverse=True)
        total=len(rows)
        if cfg['candidates_only']: rows=[r for r in rows if r.get('trade_plan',{}).get('decision')=='CONDITIONAL_BUY']
        return {'mode':mode,'generated_at':self.store.now(),'rows':rows,'evaluated':total,'watchlist_size':len(watched),
            'configured':self.broker.configured,'catalogue':catalogue,'errors':sorted(set(errors)), 'filters':cfg,
            'live_execution':False,'feed_mode':'REST snapshots; no WebSocket or full-exchange live scanning',
            'next_refresh_seconds':20,'confidence_definition':'Estimated conditional target-hit probability from a saved model. It is not guaranteed profit.'}

    def _audit(self,row):
        # One immutable record per setup/model/status. Later refreshes never replace
        # the first forecast. This is local research provenance, not a tamper-proof ledger.
        key='|'.join([row['instrument']['instrument_key'],row['strategy'],row['last_bar'],row['model'].get('model_id','none'),row['status'],row['trade_plan']['id']])
        ident=hashlib.sha256(key.encode()).hexdigest()
        body={k:row.get(k) for k in ('strategy','last_bar','probability','status','generated_at','reasons','plan','trade_plan')}
        body.update(instrument_key=row['instrument']['instrument_key'],model_id=row['model'].get('model_id'),prospective=row['model'].get('prospective',False))
        with self.store.db() as db:
            db.execute('INSERT OR IGNORE INTO signal_audit VALUES(?,?,?)',(ident,self.store.now(),json.dumps(body,allow_nan=False)))

    def signal_log(self):
        with self.store.db() as db: rows=db.execute('SELECT body FROM signal_audit ORDER BY created DESC LIMIT 100').fetchall()
        return [json.loads(r['body']) for r in rows]

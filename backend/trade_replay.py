"""Cost-aware historical replay and reproducible trade-outcome resampling."""
from datetime import datetime, timedelta
import random
import statistics

from .data import IST, parse_time
from .entry_timing import completed_bars
from .strategies import CATALOG, indicators, events, nonoverlap
from .research import config_for, wilson


def directional_events(features, cfg, side):
    """Replay the F&O underlying direction rule; no option-premium modelling."""
    out=[];sign=1 if side=='buy' else -1
    for i,r in enumerate(features[:-1]):
        if i<70: continue
        match=(r['c']>r['ema20']>r['ema50'] and 52<=r['rsi']<=72 and r['c']>r['o']) if sign==1 else (
               r['c']<r['ema20']<r['ema50'] and 28<=r['rsi']<=48 and r['c']<r['o'])
        if not match or (not cfg.get('index') and (r['v']<=0 or r['rv']<.8)): continue
        intraday=cfg['intraday'];entry_i=i+1;end=min(i+cfg['horizon'],len(features)-1)
        if intraday and not 585<=parse_time(r['t'],'15m').hour*60+parse_time(r['t'],'15m').minute+15<885:continue
        if i+cfg['horizon']>=len(features): continue
        if intraday:
            day=r['t'][:10]
            if features[entry_i]['t'][:10]!=day: continue
            while end>=entry_i and features[end]['t'][:10]!=day:end-=1
            if end<entry_i:continue
            if end<i+cfg['horizon'] and parse_time(features[end]['t'],'15m').strftime('%H:%M')!='15:15':continue
            if any(parse_time(features[j]['t'],'15m')-parse_time(features[j-1]['t'],'15m')!=timedelta(minutes=15) for j in range(entry_i,end+1)):continue
        entry=features[entry_i]['o'];risk=1.5*r['atr']
        if risk<=0 or abs(entry-r['c'])>.75*r['atr']:continue
        stop=entry-sign*risk;target=entry+sign*2*risk
        if min(stop,target)<=0:continue
        reason='TIMEOUT';exit_i=end;raw_exit=features[end]['c']
        for j in range(entry_i,end+1):
            b=features[j]
            if (b['o']-stop)*sign<=0:raw_exit=b['o'];reason='GAP_STOP'
            elif (b['o']-target)*sign>=0:raw_exit=target;reason='TARGET'
            elif (b['l']<=stop if sign==1 else b['h']>=stop):raw_exit=stop;reason='STOP'
            elif (b['h']>=target if sign==1 else b['l']<=target):raw_exit=target;reason='TARGET'
            else:continue
            exit_i=j;break
        slip=cfg['slippage_bps']/10000;fee=cfg['roundtrip_cost_bps']/20000
        filled_entry=entry*(1+sign*slip);filled_exit=raw_exit*(1-sign*slip)
        net=sign*(filled_exit-filled_entry)-fee*(filled_entry+filled_exit)
        out.append({'i':i,'exit_i':exit_i,'entry_i':entry_i,'entry_time':features[entry_i]['t'],
                    'exit_time':features[exit_i]['t'],'entry':filled_entry,'exit':filled_exit,
                    'stop':stop,'target':target,'risk':risk,'r_multiple':net/risk,
                    'net_per_share':net,'reason':reason})
    return out


def summary(trades):
    n=len(trades);targets=sum(t['reason']=='TARGET' for t in trades);wins=sum(t['r_multiple']>0 for t in trades)
    return {'trades':n,'targets':targets,'stops':sum(t['reason'] in ('STOP','GAP_STOP') for t in trades),
            'timeouts':sum(t['reason']=='TIMEOUT' for t in trades),'gap_stops':sum(t['reason']=='GAP_STOP' for t in trades),
            'net_positive_rate':wins/n if n else None,'net_positive_interval':wilson(wins,n),
            'target_rate':targets/n if n else None,'average_net_r':statistics.fmean(t['r_multiple'] for t in trades) if n else None,
            'sample_quality':'SMALL_SAMPLE' if n<30 else 'HISTORICAL_SAMPLE'}


def percentile(values,p):
    v=sorted(values);x=(len(v)-1)*p;i=int(x);return v[i]+(v[min(i+1,len(v)-1)]-v[i])*(x-i)


def resample(trades,paths=1000,seed=42,length=20):
    if len(trades)<20:return {'available':False,'reason':'At least 20 non-overlapping historical trades are needed for resampling.'}
    values=[t['r_multiple'] for t in trades];rng=random.Random(seed);curves=[];drawdowns=[]
    for _ in range(paths):
        sample=[]
        while len(sample)<length:
            start=rng.randrange(max(1,len(values)-4))
            sample.extend(values[start:start+5])
        curve=[0.];peak=0.;drawdown=0.
        for value in sample[:length]:
            curve.append(curve[-1]+value);peak=max(peak,curve[-1]);drawdown=max(drawdown,peak-curve[-1])
        curves.append(curve);drawdowns.append(drawdown)
    bands=[{'trade':j,'low':round(percentile([c[j] for c in curves],.05),3),
            'median':round(percentile([c[j] for c in curves],.5),3),
            'high':round(percentile([c[j] for c in curves],.95),3)} for j in range(length+1)]
    return {'available':True,'paths':paths,'seed':seed,'block_trades':5,'horizon_trades':length,'bands':bands,
            'median_drawdown_r':round(percentile(drawdowns,.5),3),'adverse_drawdown_r':round(percentile(drawdowns,.95),3),
            'definition':'Resampled historical trade sequences in R, not a forecast of the next trade or of option premiums.'}


def replay(dataset,strategy,side='buy',derivative=False,index=False,paths=1000,seed=42,now=None):
    if not dataset or dataset['synthetic']:raise ValueError('Load genuine price history before running a historical replay.')
    if strategy not in CATALOG:raise ValueError('Unknown strategy.')
    now=now or datetime.now(IST);bars=completed_bars(dataset,now)[-3000:]
    if dataset['timeframe']!=CATALOG[strategy]['timeframe']:raise ValueError('History and strategy timeframes do not match.')
    if len(bars)<100:raise ValueError('At least 100 completed candles are needed for replay.')
    cfg=config_for(strategy,{});features=indicators(bars,dataset['timeframe'])
    if derivative:
        trades=directional_events(features,{**cfg,'intraday':dataset['timeframe']=='15m','index':index},side)
        method='Underlying trend and momentum · next-open proxy, not the live trigger or a contract backtest'
    else:
        trades=events(features,strategy,cfg)
        method=CATALOG[strategy]['name']+' · next completed open'
    trades=nonoverlap(trades)
    split=int(len(bars)*.7)
    holdout=[t for t in trades if t['i']>=split]
    # Trades crossing the time split are excluded from the earlier segment.
    earlier=[t for t in trades if t['exit_i']<split]
    curve=[];cumulative=0.
    for t in trades:
        cumulative+=t['r_multiple'];curve.append({'time':t['exit_time'],'net_r':round(cumulative,3)})
    return {'method':method,'scope':'UNDERLYING_ONLY' if derivative else 'CASH_RULE_REPLAY',
            'strategy':strategy,'side':side,'source':dataset['source'],'data_sha':dataset.get('sha'),
            'first_bar':bars[0]['t'],'last_bar':bars[-1]['t'],'generated_at':now.isoformat(),
            'overall':summary(trades),'earlier':summary(earlier),'recent':summary(holdout),'recent_starts_at':bars[split]['t'],
            'costs':{'roundtrip_bps':cfg['roundtrip_cost_bps'],'slippage_bps_per_side':cfg['slippage_bps']},
            'curve':curve[-250:],'examples':[{k:t[k] for k in ('entry_time','exit_time','entry','stop','target','exit','reason','r_multiple')} for t in trades[-20:]],
            'scenarios':resample(holdout,paths,seed),'probability_of_next_trade':None,
            'notes':['Signals use past candles, next-open fills, non-overlapping trades and stop-first handling when both levels touch.',
                     'This replays chart rules, not saved ML models, news checks, live spreads or every current scanner/account gate.',
                     'Gap stops use the bar open and can lose more than 1R. Estimated costs and slippage are deducted.',
                     'Recent results are the last 30% of the candle history with fixed rules; no parameters were tuned on this segment.',
                     'R means the initial stop distance. Resampling reuses historical outcomes; it is not new independent evidence.']}

"""Past-only technical features, setup rules and conservative OHLC event simulation."""
from __future__ import annotations
import math, statistics
from datetime import timedelta
from .data import parse_time

STRATEGIES = [
 {'id':'trend_pullback','name':'Trend pullback','mode':'Swing','timeframe':'1d','horizon':10,'description':'Uptrend with a pullback near EMA20 and a positive resumption candle.'},
 {'id':'range_breakout','name':'Range breakout','mode':'Swing','timeframe':'1d','horizon':10,'description':'Close above the prior 20-bar high with expanded relative volume.'},
 {'id':'position_trend','name':'Position trend','mode':'Delivery','timeframe':'1d','horizon':20,'description':'Price-only longer-horizon trend model. No fundamental or valuation claims.'},
 {'id':'opening_range','name':'Opening-range breakout','mode':'Intraday','timeframe':'15m','horizon':6,'description':'Break of the first 30-minute range after 09:45, before noon, with volume confirmation.'},
 {'id':'vwap_pullback','name':'VWAP continuation','mode':'Intraday','timeframe':'15m','horizon':6,'description':'Session uptrend pulls back toward VWAP then prints a positive candle.'},
]
CATALOG={s['id']:s for s in STRATEGIES}
FEATURES=['return_1','return_5','ema20_gap','ema50_gap','trend_atr','rsi','atr_pct','relative_volume','volatility_20','momentum_20','range_pct','body_atr','breakout_distance','vwap_gap','session_fraction']

def indicators(bars: list[dict], timeframe: str) -> list[dict]:
    result=[]; e9=e20=e50=e200=e12=e26=bars[0]['c']; macd_signal=0.0; ag=al=atr=0.0
    vols=[]; rets=[]; time_vols={}; pv=sv=0.0; day=None; session=[]
    for i,b in enumerate(bars):
        c,o,h,l,v=(b[k] for k in ('c','o','h','l','v'))
        prev=bars[i-1]['c'] if i else c
        change=c-prev
        ag=(ag*13+max(change,0))/14; al=(al*13+max(-change,0))/14
        rsi=50 if ag+al==0 else (100 if al==0 else 100-100/(1+ag/al))
        tr=max(h-l,abs(h-prev),abs(l-prev)); atr=tr if i==0 else (atr*13+tr)/14
        e9+=(c-e9)*2/10; e20+=(c-e20)*2/21; e50+=(c-e50)*2/51; e200+=(c-e200)*2/201
        e12+=(c-e12)*2/13; e26+=(c-e26)*2/27
        macd=e12-e26; macd_signal+=(macd-macd_signal)*2/10
        closes=[bb['c'] for bb in bars[max(0,i-19):i+1]]
        bb_mid=statistics.fmean(closes); bb_std=statistics.pstdev(closes)
        dt=parse_time(b['t'],timeframe); minute=dt.hour*60+dt.minute
        if day!=dt.date():
            day=dt.date(); pv=sv=0; session=[]
        session.append(b); pv+=(h+l+c)/3*v; sv+=v; vwap=pv/sv if sv>0 else c
        # Intraday relative volume uses prior sessions at the SAME time slot.
        history=time_vols.setdefault(minute,[]) if timeframe=='15m' else vols
        avg=statistics.fmean(history[-20:]) if history else 0
        rv=v/avg if avg>0 else 1
        history.append(v)
        ret=c/prev-1; rets.append(ret)
        prior=bars[max(0,i-20):i]
        resistance=max((x['h'] for x in prior),default=h)
        support=min((x['l'] for x in prior),default=l)
        r5=c/bars[max(0,i-5)]['c']-1
        mom=c/bars[max(0,i-20)]['c']-1
        trend=(e20-e50)/max(atr,1e-9)
        regime='UPTREND' if trend>.65 and c>e50 else ('DOWNTREND' if trend<-.65 and c<e50 else 'RANGE')
        volatility=statistics.pstdev(rets[-20:]) if i>0 else 0
        values=[ret,r5,c/e20-1,c/e50-1,trend,rsi/100,atr/c,min(rv,10),volatility,mom,(h-l)/c,(c-o)/max(atr,1e-9),c/resistance-1,c/vwap-1 if timeframe=='15m' else 0,(minute-555)/375 if timeframe=='15m' else 0]
        opening_complete = len(session)>2 and parse_time(session[0]['t'],timeframe).hour*60+parse_time(session[0]['t'],timeframe).minute==555 and parse_time(session[1]['t'],timeframe).hour*60+parse_time(session[1]['t'],timeframe).minute==570
        orhigh=max(x['h'] for x in session[:2]) if opening_complete else None
        result.append({**b,'ema9':e9,'ema20':e20,'ema50':e50,'ema200':e200,'macd':macd,'macd_signal':macd_signal,'macd_hist':macd-macd_signal,'bb_upper':bb_mid+2*bb_std,'bb_lower':bb_mid-2*bb_std,'atr':atr,'rsi':rsi,'rv':rv,'vwap':vwap,'support':support,'resistance':resistance,'regime':regime,'minute':minute,'session_n':len(session),'or_high':orhigh,'features':values,'momentum20':mom})
    return result

def rule(row: dict, prev: dict | None, strategy: str, index: int) -> bool:
    if index<70 or row['v']<=0: return False
    c=row['c']; trend=c>row['ema20']>row['ema50']
    if strategy=='trend_pullback':
        return trend and row['l']<=row['ema20']+.8*row['atr'] and row['c']>row['o'] and 43<row['rsi']<75
    if strategy=='range_breakout':
        return trend and c>row['resistance'] and row['rv']>=1.15 and row['rsi']<82
    if strategy=='position_trend':
        return index>=220 and c>row['ema50']>row['ema200'] and row['momentum20']>0 and 45<row['rsi']<72
    if strategy=='opening_range':
        return bool(prev and 585<=row['minute']<=720 and row['or_high'] and c>row['or_high'] and prev['c']<=row['or_high'] and c>row['vwap'] and row['rv']>=1.1)
    if strategy=='vwap_pullback':
        return bool(prev and 585<=row['minute']<=870 and row['ema9']>row['ema20'] and c>row['vwap'] and row['l']<=row['vwap']+.5*row['atr'] and c>prev['c'] and c>row['o'] and row['rv']>=.8)
    raise ValueError('Unknown strategy.')

def analyse(bars: list[dict], timeframe: str, strategy: str) -> dict:
    f=indicators(bars,timeframe); r=f[-1]
    eligible=rule(r,f[-2],strategy,len(f)-1)
    checks=[{'name':'Price above EMA20','pass':r['c']>r['ema20']},
            {'name':'EMA20 above EMA50','pass':r['ema20']>r['ema50']},
            {'name':'RSI between 45 and 72','pass':45<r['rsi']<72},
            {'name':'Volume above reference','pass':r['rv']>=1},
            {'name':'Strategy entry rule','pass':eligible}]
    return {'last':{k:v for k,v in r.items() if k!='features'},'rule_pass':eligible,'checks':checks,
            'setup_score':sum(x['pass'] for x in checks)*20,
            'score_definition':'Checklist score only, NOT a probability of profit.',
            'chart':[{k:r[k] for k in ('t','o','h','l','c','v','ema9','ema20','ema50','ema200','vwap','rsi','macd','macd_signal','macd_hist','bb_upper','bb_lower','support','resistance')} for r in f[-180:]]}

def simulate_event(f: list[dict], i: int, strategy: str, cfg: dict) -> dict | None:
    spec=CATALOG[strategy]; horizon=cfg['horizon']; intraday=spec['timeframe']=='15m'
    if i+1>=len(f): return None
    entry_index=i+1; end=min(i+horizon,len(f)-1)
    if not intraday and i+horizon>=len(f): return None
    day=f[i]['t'][:10]
    if intraday:
        if f[entry_index]['t'][:10]!=day: return None
        while end>=entry_index and f[end]['t'][:10]!=day: end-=1
        if end<entry_index: return None
        if end<i+horizon and parse_time(f[end]['t'],'15m').hour*60+parse_time(f[end]['t'],'15m').minute!=915:
            return None # incomplete observed session cannot be assumed closed
        for k in range(entry_index,end+1):
            if parse_time(f[k]['t'],'15m')-parse_time(f[k-1]['t'],'15m') != timedelta(minutes=15): return None
    ref=f[i]; raw_entry=f[entry_index]['o']; distance=ref['atr']*cfg['atr_multiple']
    if distance<=0 or abs(raw_entry-ref['c'])>cfg['max_gap_atr']*ref['atr']: return None
    stop=raw_entry-distance; target=raw_entry+cfg['reward_r']*distance
    if stop<=0: return None
    exit_index=end; raw_exit=f[end]['c']; reason='TIMEOUT'
    for j in range(entry_index,end+1):
        b=f[j]
        if b['o']<=stop:
            raw_exit=b['o']; reason='GAP_STOP'; exit_index=j; break
        if b['o']>=target:
            raw_exit=target; reason='TARGET'; exit_index=j; break # no optimistic improvement at target
        if b['l']<=stop:
            raw_exit=stop; reason='STOP'; exit_index=j; break # stop first if both touched
        if b['h']>=target:
            raw_exit=target; reason='TARGET'; exit_index=j; break
    slip=cfg['slippage_bps']/10000; fee=cfg['roundtrip_cost_bps']/20000
    entry=raw_entry*(1+slip); exit_price=raw_exit*(1-slip)
    net=exit_price-entry-fee*(entry+exit_price)
    return {'i':i,'entry_i':entry_index,'exit_i':exit_index,'signal_time':ref['t'],'entry_time':f[entry_index]['t'],'exit_time':f[exit_index]['t'],
            'entry':entry,'raw_entry':raw_entry,'exit':exit_price,'stop':stop,'target':target,'risk':distance,
            'net_per_share':net,'net_return':net/entry,'r_multiple':net/distance,'label':int(reason=='TARGET'),'reason':reason,'x':ref['features']}

def events(f: list[dict], strategy: str, cfg: dict) -> list[dict]:
    return [e for i in range(70,len(f)-1) if rule(f[i],f[i-1],strategy,i) and (e:=simulate_event(f,i,strategy,cfg)) is not None]

def nonoverlap(events: list[dict]) -> list[dict]:
    out=[]; last=-1
    for e in events:
        if e['i']>last:
            out.append(e); last=e['exit_i']
    return out

def portfolio(events: list[dict], cfg: dict, probabilities: list[float] | None=None) -> dict:
    """One position at a time; marked-to-market equity/drawdown is computed separately when bars are supplied."""
    capital=cfg['capital']; equity=capital; peak=capital; dd=0; last=-1; trades=[]; curve=[{'t':'START','equity':capital}]
    total_profit=total_loss=0.0; positive=0
    for k,e in enumerate(events):
        if e['i']<=last or (probabilities is not None and probabilities[k]<cfg['threshold']): continue
        fee=cfg['roundtrip_cost_bps']/20000
        risk_per=e['entry']-e['stop']*(1-cfg['slippage_bps']/10000)+fee*(e['entry']+e['stop'])
        q=max(0,math.floor(min(equity*cfg['risk_pct']/100/max(risk_per,1e-9),equity*cfg['exposure_pct']/100/(e['entry']*(1+fee)))))
        if q==0: continue
        pnl=q*e['net_per_share']; equity+=pnl; peak=max(peak,equity); dd=max(dd,(peak-equity)/peak)
        positive+=pnl>0; total_profit+=max(0,pnl); total_loss+=max(0,-pnl)
        t={k:v for k,v in e.items() if k!='x'}
        t.update(quantity=q,net_pnl=pnl,equity=equity,probability=None if probabilities is None else probabilities[k])
        trades.append(t); curve.append({'t':e['exit_time'],'equity':round(equity,2)}); last=e['exit_i']
    n=len(trades)
    return {'trades':trades,'curve':curve,'net_pnl':equity-capital,'return_pct':(equity/capital-1)*100,'closed_trade_drawdown_pct':dd*100,'n':n,
            'win_rate':positive/n if n else None,'profit_factor':total_profit/total_loss if total_loss>0 else None,
            'profit_factor_note':'Undefined with no losing trades; never interpreted as infinite evidence.',
            'average_pnl':(equity-capital)/n if n else None,'final_equity':equity}

"""Past-only Indian-session opening-range timing and manual exit scenarios."""
from datetime import datetime, timedelta, time
import math

from .data import IST, parse_time
from .strategies import indicators


def completed_bars(dataset, now):
    tf=dataset['timeframe']
    return [b for b in dataset['bars'] if (parse_time(b['t'],tf)+timedelta(minutes=15) if tf=='15m'
            else datetime.combine(parse_time(b['t'],tf).date(),time(16),IST))<=now]


def entry_timing(dataset, side='buy', now=None):
    now=now or datetime.now(IST)
    result={'status':'DATA_REQUIRED','side':side,'generated_at':now.isoformat(),'signal':None,
            'range':None,'last_close':None,'distance_to_trigger':None,'order_placed':False,
            'session_verified':False,'method':'First completed 15-minute close beyond the 09:15–09:45 opening range.'}
    if not dataset or dataset['timeframe']!='15m':
        result['message']='Load 15-minute candles to time an intraday entry.';return result
    if dataset['synthetic']:
        result['message']='Synthetic histories cannot confirm a market entry.';return result
    minute=now.hour*60+now.minute
    if now.weekday()>4 or minute<555 or minute>=930:
        result.update(status='OUTSIDE_SESSION',message='Outside the ordinary 09:15–15:30 IST session. Special sessions and holidays require broker confirmation.')
        return result
    bars=completed_bars(dataset,now)
    today=[b for b in bars if parse_time(b['t'],'15m').date()==now.date()]
    result['last_close']=today[-1]['c'] if today else None
    if minute<585:
        result.update(status='FORMING_RANGE',message='The opening range is forming. Wait for both 09:15 and 09:30 candles to finish.')
        return result
    expected=max(0,(minute-555)//15)
    start=now.replace(hour=9,minute=15,second=0,microsecond=0)
    if len(today)!=expected or any(parse_time(b['t'],'15m')!=start+timedelta(minutes=15*i) for i,b in enumerate(today)):
        result.update(status='MISSING_BARS',message='One or more completed session candles are missing. Refresh data before using the trigger.')
        return result
    high=max(b['h'] for b in today[:2]);low=min(b['l'] for b in today[:2])
    result['range']={'high':high,'low':low,'ends_at':(start+timedelta(minutes=30)).isoformat()}
    trigger=next((b for b in today[2:] if (b['c']>high if side=='buy' else b['c']<low)),None)
    level=high if side=='buy' else low
    result['distance_to_trigger']=round(max(0,level-today[-1]['c'] if side=='buy' else today[-1]['c']-level),4)
    if trigger:
        confirmed=parse_time(trigger['t'],'15m')+timedelta(minutes=15)
        result['signal']={'price':trigger['c'],'bar_time':trigger['t'],'confirmed_at':confirmed.isoformat(),
                          'expires_at':min(confirmed+timedelta(minutes=15),now.replace(hour=14,minute=45,second=0,microsecond=0)).isoformat()}
        status='EXPIRED' if (now-confirmed).total_seconds()>=900 or minute>=885 else 'TRIGGERED'
        result.update(status=status,message='First completed candle confirmed the breakout. Recheck the current price before any entry.' if status=='TRIGGERED'
                      else 'The first breakout is old or the entry cutoff passed. Later candles do not create a fresh first-entry signal.')
    else:
        result.update(status='EXPIRED' if minute>=885 else 'WAITING',message='Entry cutoff reached. Wait for another session.' if minute>=885
                      else 'Wait for a completed candle to close '+('above the range high.' if side=='buy' else 'below the range low.'))
    return result


def exit_scenario(dataset, timing, account, side='buy', stop_method='atr', reward_r=2., now=None):
    now=now or datetime.now(IST)
    if not dataset or dataset['synthetic']: raise ValueError('Genuine completed history is needed for an exit scenario.')
    bars=completed_bars(dataset,now)
    if len(bars)<70: raise ValueError('At least 70 completed candles are needed for an ATR scenario.')
    last=indicators(bars[-350:],dataset['timeframe'])[-1]
    entry=(timing.get('signal') or {}).get('price') or last['c'];atr=last['atr'];sign=1 if side=='buy' else -1
    if stop_method=='atr': stop=entry-sign*1.5*atr
    else:
        opening=timing.get('range')
        if not opening: raise ValueError('Opening-range stops require a complete current-session range.')
        stop=(opening['high']+opening['low'])/2 if stop_method=='range_mid' else opening['low' if side=='buy' else 'high']
    distance=(entry-stop)*sign;target=entry+sign*reward_r*distance
    if not all(math.isfinite(x) and x>0 for x in (entry,stop,target,distance)):
        raise ValueError('This stop method does not produce valid entry, stop and target geometry.')
    settings=account['settings'];equity=max(0,account['equity_cost_basis'])
    risk_budget=equity*settings['risk_pct']/100;fees=(entry+stop)*settings['cost_bps']/20000
    per_share=distance+fees+entry*.001
    cash=min(max(0,account['cash']),equity*settings['exposure_pct']/100)
    quantity=max(0,int(min(risk_budget/per_share,cash/(entry*(1+settings['cost_bps']/20000)))))
    return {'entry':round(entry,4),'stop':round(stop,4),'target':round(target,4),'reward_r':reward_r,
            'side':side,'stop_method':stop_method,'atr':round(atr,4),'quantity':quantity,
            'planned_loss_with_costs':round(quantity*per_share,2),'risk_budget':round(risk_budget,2),
            'cash_estimate':round(quantity*entry*(1+settings['cost_bps']/20000),2),
            'flat_by':now.replace(hour=15,minute=20,second=0,microsecond=0).isoformat() if dataset['timeframe']=='15m' else None,
            'scope':'CASH_OR_UNDERLYING_SCENARIO','execution':'SCENARIO_ONLY',
            'note':'Reference scenario, not an entry confirmation. Quantity is cash-equity practice sizing, never F&O lots. Stops can gap and fills can be worse.'}

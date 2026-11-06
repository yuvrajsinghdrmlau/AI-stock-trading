"""One source of truth for the data each trade mode can actually use.

The optional live feed is an injected, read-only candle builder. A REST quote
or a cached historical dataset never establishes that a tick feed is live.
"""
from __future__ import annotations

from datetime import datetime, timedelta, time
import math

from .data import IST, parse_time, fingerprint
from .market import timestamp


REQUIREMENTS = {
    'Delivery': {'timeframe': '1d', 'needs': ['Completed daily candles']},
    'Swing': {'timeframe': '1d', 'needs': ['Completed daily candles']},
    'Intraday': {'timeframe': '15m', 'needs': ['Completed 15-minute candles', 'Current trading session']},
    'Options': {'timeframe': '15m/1d', 'needs': ['Completed underlying candles', 'Listed option contract', 'Fresh premium, bid, ask and open interest']},
    'Futures': {'timeframe': '15m/1d', 'needs': ['Completed underlying candles', 'Listed futures contract', 'Fresh price, bid, ask and open interest']},
    'Scalper': {'timeframe': '1m/5m', 'needs': ['Live tick feed', 'Completed 1-minute and 5-minute candles', 'Cost filter and validated strategy']},
}


def _positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _feed_live(feed, symbol, now):
    if feed is None: return False
    try:
        state = feed.status(symbol)
    except (AttributeError, KeyError, ValueError):
        return False
    if not isinstance(state, dict) or state.get('status') != 'Live': return False
    stamp = timestamp(state.get('last_tick_at'))
    return bool(stamp and -5 <= (now-stamp).total_seconds() <= 20)


def _feed_bars(feed, symbol, timeframe, now):
    if feed is None: return []
    try: rows = feed.completed(symbol, timeframe)
    except (AttributeError, KeyError, ValueError): return []
    if not isinstance(rows, list): return []
    duration = timedelta(minutes=int(timeframe[:-1]))
    result = []
    for row in rows:
        if not isinstance(row, dict) or not all(_positive(row.get(k)) for k in ('o','h','l','c')): continue
        if not isinstance(row.get('v'), (int,float)) or row['v'] < 0: continue
        if row['h'] < max(row['o'],row['l'],row['c']) or row['l'] > min(row['o'],row['h'],row['c']): continue
        try: start = parse_time(row['t'], timeframe)
        except (KeyError, ValueError, TypeError): continue
        if start + duration <= now: result.append(row)
    return result


def mode_dataset(mode, symbol, dataset, feed=None, now=None):
    """Use completed, contiguous live 15m bars for intraday analysis when present."""
    if mode != 'Intraday' or not dataset or dataset.get('synthetic') or dataset.get('timeframe') != '15m':
        return dataset
    now = (now or datetime.now(IST)).astimezone(IST)
    if not _feed_live(feed, symbol, now): return dataset
    live_rows = _feed_bars(feed, symbol, '15m', now)
    today = sorted((r for r in live_rows if parse_time(r['t'], '15m').date() == now.date()),
                   key=lambda r:r['t'])
    start = now.replace(hour=9, minute=15, second=0, microsecond=0)
    if not today or any(parse_time(r['t'],'15m') != start+timedelta(minutes=15*i)
                        for i,r in enumerate(today)):
        return dataset
    old = [r for r in _completed(dataset,now) if parse_time(r['t'],'15m').date() < now.date()]
    bars = old + today
    if len(bars) < 70: return dataset
    return {**dataset, 'bars':bars, 'sha':fingerprint(bars),
            'source':'Live candle builder | '+symbol}


def _completed(dataset, now):
    if not dataset or dataset.get('synthetic') or dataset.get('timeframe') not in ('1d', '15m'): return []
    tf = dataset['timeframe']; rows = []
    for bar in dataset.get('bars') or []:
        if not isinstance(bar, dict) or not _positive(bar.get('c')): continue
        try: start = parse_time(bar['t'], tf)
        except (KeyError, ValueError, TypeError): continue
        finish = datetime.combine(start.date(), time(16), IST) if tf == '1d' else start + timedelta(minutes=15)
        if finish <= now: rows.append(bar)
    return rows


def _broker_quote_live(quote, symbol, now):
    if not isinstance(symbol,str) or not symbol or not isinstance(quote, dict) or quote.get('instrument_key') != symbol or quote.get('fresh') is not True:
        return False
    if not _positive(quote.get('last_price')) or quote.get('delayed') is True: return False
    feed = timestamp(quote.get('feed_time')); receipt = timestamp(quote.get('received_at'))
    trade = timestamp(quote.get('trade_time'))
    return bool(feed and receipt and trade and -5 <= (now-feed).total_seconds() < 60
                and -5 <= (now-receipt).total_seconds() < 20
                and -5 <= (now-trade).total_seconds() < 120)


def _contract_quote_live(quote, symbol, now):
    if not _broker_quote_live(quote, symbol, now): return False
    bid, ask = quote.get('bid'), quote.get('ask')
    oi = quote.get('open_interest', quote.get('oi'))
    return bool(_positive(bid) and _positive(ask) and bid <= ask
                and _positive(oi) and quote.get('spread_bps') is not None
                and 0 <= quote['spread_bps'] <= 200)


def mode_data(mode, symbol, *, dataset=None, feed=None, quote=None, contract=None,
              contract_quote=None, broker_configured=False, now=None):
    """Return requirements, usability, provenance and a safe reference price.

    ``available`` means the mode can show its data-based idea. ``actionable``
    additionally needs a fresh contract quote for derivatives. Scalper has no
    validated strategy in this product, so its data readiness never enables a tip.
    """
    if mode not in REQUIREMENTS: raise ValueError('Unknown trade mode.')
    now = (now or datetime.now(IST)).astimezone(IST)
    spec = REQUIREMENTS[mode]
    result = {'mode': mode, 'symbol': symbol, 'timeframe': spec['timeframe'],
              'needs': list(spec['needs']), 'status': 'Unavailable', 'available': False,
              'actionable': False, 'reason': 'Not available right now: required data is missing.',
              'source': None, 'last_bar': None, 'price': None, 'session_state': None}
    minute = now.hour * 60 + now.minute
    session_open = now.weekday() < 5 and 555 <= minute < 930
    live = _feed_live(feed, symbol, now)
    if mode == 'Scalper':
        one = _feed_bars(feed, symbol, '1m', now) if live else []
        five = _feed_bars(feed, symbol, '5m', now) if live else []
        ready = bool(session_open and one and five and
                     parse_time(one[-1]['t'], '1m').date() == now.date() and
                     parse_time(five[-1]['t'], '5m').date() == now.date())
        if ready:
            result.update(status='Partial', reason='Live 1m/5m candles are ready; no validated scalper strategy or cost filter is connected.',
                          source='Live candle builder', last_bar=one[-1]['t'], price=one[-1]['c'])
        else:
            result.update(reason='Scalper unavailable: live data not connected' if not live
                          else 'Scalper unavailable: completed 1m/5m candles are missing or the session is closed.')
        return result

    tf = '15m' if mode == 'Intraday' else dataset.get('timeframe') if dataset else spec['timeframe']
    rows = _completed(dataset, now) if dataset and dataset.get('timeframe') == tf else []
    if live and tf == '15m':
        combined = mode_dataset('Intraday',symbol,dataset,feed,now)
        if combined is not dataset: rows = combined['bars']
    if not rows:
        result.update(status='Unavailable', reason='Not available right now: completed '+str(tf)+' candles are missing.')
        if mode == 'Intraday' and not session_open: result['session_state'] = 'SESSION_CLOSED'
        return result
    last = rows[-1]; start = parse_time(last['t'], tf)
    result.update(last_bar=last['t'], price=last['c'], source=(dataset or {}).get('source') or 'Live candle builder')
    if mode == 'Intraday':
        result['session_state'] = ('SESSION_CLOSED' if not session_open else
                                   'EXPIRED' if minute >= 885 else
                                   'WAITING' if start.date() != now.date() else 'CURRENT')
        if not session_open:
            result.update(status='Stale', reason='Session closed. Intraday entry waits for the next session.')
        elif start.date() != now.date() or (now - (start+timedelta(minutes=15))).total_seconds() >= 900:
            result.update(status='Stale', reason='Completed 15-minute candles are old. Refresh before an intraday entry.')
        elif live and mode_dataset('Intraday',symbol,dataset,feed,now) is not dataset:
            result.update(status='Live', available=True, reason='Completed current-session candles from the live feed.', source='Live candle builder')
        else:
            result.update(status='Delayed', available=True, reason='Completed historical candles only; no verified live candle feed. Recheck entry on your broker.')
        return result
    if tf == '1d':
        age = (now.date()-start.date()).days
        if age > 4:
            result.update(status='Stale', reason='Daily candles are older than four calendar days. Refresh history.')
        elif (dataset or {}).get('source','').startswith('Upstox V3 |'):
            verified = broker_configured and _broker_quote_live(quote, symbol, now)
            result.update(status='Live' if verified else 'Delayed', available=True,
                          reason='Broker daily history with fresh broker quote.' if verified else 'Saved broker daily candles; current price is not verified live.')
        else:
            result.update(status='Delayed', available=True, reason='Public or imported daily history; prices may be delayed or revised.')
    elif tf == '15m':
        result['session_state'] = 'SESSION_CLOSED' if not session_open else 'CURRENT'
        if not session_open:
            result.update(status='Stale', reason='Session closed. Recheck the underlying and contract next session.')
        elif start.date()!=now.date() or (now-(start+timedelta(minutes=15))).total_seconds() >= 900:
            result.update(status='Stale', reason='Underlying 15-minute candle is old. Refresh before a contract entry.')
        else:
            result.update(status='Live' if live and mode_dataset('Intraday',symbol,dataset,feed,now) is not dataset else 'Delayed',
                          available=True, reason='Underlying completed candles; a contract quote is required for an F&O entry.')
    if mode in ('Options', 'Futures'):
        if not result['available']:
            result['reason'] += ' Needs live quote after fresh underlying candles load.'
        elif not contract:
            result.update(status='Partial', actionable=False, reason='Underlying direction only: no listed contract is available.')
        elif broker_configured and _contract_quote_live(contract_quote, contract.get('instrument_key'), now):
            result.update(status='Live', actionable=True, reason='Fresh broker contract price, bid/ask and open interest verified.')
        else:
            result.update(status='Partial', actionable=False, reason='Needs live quote: fresh contract price, bid/ask and open interest are required.')
    return result


def mode_availability(feed=None, now=None):
    """Readiness for mode navigation; scans may still find missing symbols."""
    return {mode: {'enabled': mode != 'Scalper',
                   'status': 'Unavailable' if mode == 'Scalper' else 'Partial',
                   'reason': (('Scalper unavailable: live data not connected' if feed is None else
                               'Scalper unavailable: completed live candles and a validated strategy are required.') if mode == 'Scalper' else
                              'Ideas available after completed candles load; contract entries need a live quote.' if mode in ('Options','Futures') else
                              'Historical candles can be loaded; each card shows its data status.')}
            for mode in REQUIREMENTS}


def age_cached_row(row, now=None):
    """Saved scans keep their history but cannot keep a live quote badge."""
    now=(now or datetime.now(IST)).astimezone(IST)
    data=row.get('data_status')
    if not isinstance(data,dict): return row
    data=dict(data); row={**row,'data_status':data}
    made=timestamp(row.get('generated_at'))
    mode=row.get('mode')
    if data.get('status')=='Live' and (not made or (now-made).total_seconds()>=20):
        data.update(status='Delayed' if mode in ('Delivery','Swing') else 'Partial' if mode in ('Options','Futures') else 'Stale',
                    actionable=False,reason='The live snapshot expired. Recheck for current data.')
    if mode=='Intraday' or mode in ('Options','Futures') and row.get('holding')=='Intraday':
        stamp=timestamp(data.get('last_bar'))
        if not stamp or stamp.date()!=now.date() or now.weekday()>4 or not 555<=now.hour*60+now.minute<930:
            data.update(status='Stale',available=False,actionable=False,
                        reason='The intraday session or its last completed candle is no longer current.')
    if mode in ('Delivery','Swing') or mode in ('Options','Futures') and row.get('holding')=='Swing':
        stamp=timestamp(data.get('last_bar'))
        if stamp and (now.date()-stamp.date()).days>4:
            data.update(status='Stale',available=False,actionable=False,reason='Daily candles need a refresh.')
    if data.get('status')=='Unavailable': data['price']=None
    if mode in ('Options','Futures') and not data.get('actionable'):
        idea=dict(row.get('idea') or {})
        idea['contract_levels']=None
        if idea.get('decision')=='REVIEW_TRADE':
            idea.update(decision='QUOTE_EXPIRED',reasons=['The contract quote expired. Recheck it before manual review.'])
        row['idea']=idea
    return row


def redact_unavailable(row):
    """Do not send a price-bearing tip when required mode data is unavailable."""
    if (row.get('data_status') or {}).get('status')!='Unavailable': return row
    row['quote']=None
    row['public_snapshot']=None
    row['spark']=[]
    row['last_close']=None
    row['plan']=None
    plan=row.get('trade_plan')
    if isinstance(plan,dict):
        row['trade_plan']={**plan,'decision':'DATA_REQUIRED','entry':None,
                           'copy_text':None,'reasons':[row['data_status']['reason']]}
    idea=row.get('idea')
    if isinstance(idea,dict):
        row['idea']={**idea,'contract_quote':None,'contract_levels':None,
                     'underlying_levels':None,'action':None,'decision':'DATA_REQUIRED',
                     'reasons':[row['data_status']['reason']]}
    return row

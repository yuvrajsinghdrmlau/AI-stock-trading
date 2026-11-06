"""Directional F&O ideas with real contract identities and optional broker quotes."""
from datetime import datetime, timedelta, time
import math

from .data import IST, parse_time
from .market import timestamp
from .strategies import indicators


def recent_price(quote, key, now):
    q = quote or {}
    stamp = timestamp(q.get('price_time') or q.get('feed_time'))
    receipt = timestamp(q.get('received_at'))
    price = q.get('last_price')
    trade = timestamp(q.get('trade_time'))
    trade_ok = bool(q.get('price_time') or (trade and -5 <= (now-trade).total_seconds() < 120))
    valid = (isinstance(price, (int, float)) and not isinstance(price, bool) and math.isfinite(price)
             and price > 0 and q.get('instrument_key') == key and stamp and receipt
             and -5 <= (now-stamp).total_seconds() < 60 and -5 <= (now-receipt).total_seconds() < 20
             and (q.get('fresh') is True or (q.get('price_time') and q.get('recent') is True))
             and q.get('delayed') is not True)
    return bool(valid and trade_ok), stamp, receipt


def build_derivative_idea(instrument, dataset, contracts, product, holding, catalogue,
                          account, quote=None, broker=None, market=None, now=None):
    fixed_now = now
    now = now or datetime.now(IST)
    base = {'instrument': instrument, 'mode': product, 'holding': holding,
            'strategy': 'vwap_pullback' if holding == 'Intraday' else 'trend_pullback',
            'strategy_name': 'Trend, momentum and candle confirmation', 'generated_at': now.isoformat(),
            'public_snapshot': quote if (quote or {}).get('price_time') else None,
            'quote': quote if (quote or {}).get('feed_time') else None,
            'dataset_id': dataset['id'] if dataset else None, 'setup_score': 0}
    idea = {'decision': 'WAIT', 'action': None, 'direction': None, 'reasons': [], 'contract': None,
            'underlying_levels': None, 'contract_levels': None, 'expires_at': None,
            'order_placed': False, 'basis': 'RULES_ONLY_UNVALIDATED', 'probability': None}
    base['idea'] = idea
    if not dataset:
        idea.update(decision='DATA_REQUIRED', reasons=['Price history is not available yet.'])
        return base
    base['spark']=[bar['c'] for bar in dataset['bars'][-30:] if 'c' in bar]
    base['last_close']=dataset['bars'][-1].get('c') if dataset['bars'] else None
    tf = dataset['timeframe']; bars = dataset['bars']
    if len(bars) < 71 or dataset['synthetic'] or catalogue.get('stale', True) or not catalogue.get('suspension_checked'):
        idea.update(decision='DATA_REQUIRED', reasons=['Refresh genuine history and the instrument catalogue.'])
        return base
    last = indicators(bars[-350:], tf)[-1]; base['last_bar'] = last['t']
    dt = parse_time(last['t'], tf); intraday = tf == '15m'
    complete = dt + timedelta(minutes=15) if intraday else datetime.combine(dt.date(), time(16), IST)
    next_day=dt.date()+timedelta(days=1)
    while next_day.weekday()>4: next_day+=timedelta(days=1)
    daily_deadline=datetime.combine(next_day,time(15),IST)
    fresh_history = (0 <= (now-complete).total_seconds() < 900 if intraday
                     else 0 <= (now.date()-dt.date()).days <= 4)
    if complete > now or not fresh_history or (not intraday and now>=daily_deadline):
        idea.update(decision='WAIT_FOR_DATA', reasons=['The signal candle is old or still forming. Refresh prices.'])
        return base
    bull = last['c'] > last['ema20'] > last['ema50'] and 52 <= last['rsi'] <= 72 and last['c'] > last['o']
    bear = last['c'] < last['ema20'] < last['ema50'] and 28 <= last['rsi'] <= 48 and last['c'] < last['o']
    volume_ok = instrument['kind'] == 'INDEX' or (last['v'] > 0 and last['rv'] >= .8)
    base['setup_score'] = sum([bull or bear, volume_ok, fresh_history]) * 100 / 3
    if not (bull or bear) or not volume_ok or not math.isfinite(last['atr']) or last['atr'] <= 0:
        idea['reasons'] = ['Wait for trend, momentum, candle direction and volume to agree.']
        return base
    sign = 1 if bull else -1
    # These are underlying levels, never an estimated option premium.
    trigger = last['h'] + .05 if bull else last['l'] - .05
    distance = 1.5 * last['atr']
    if trigger - distance <= 0:
        idea['reasons'] = ['Price and stop geometry do not support a trade.']
        return base
    idea.update(direction='UP' if bull else 'DOWN', action=('BUY_CALL' if bull else 'BUY_PUT') if product == 'Options'
                else ('BUY_FUTURE' if bull else 'SELL_FUTURE'),
                underlying_levels={'trigger': round(trigger, 4), 'stop': round(trigger-sign*distance, 4),
                                   'target': round(trigger+sign*2*distance, 4), 'side': 'ABOVE' if bull else 'BELOW'})
    candidates = [c for c in contracts if c['instrument_type'] == ('CE' if bull else 'PE')]
    if product == 'Futures': candidates = [c for c in contracts if c['instrument_type'] == 'FUT']
    # Avoid recommending contracts about to expire to a beginner. Never guess expiry or lot size.
    candidates = [c for c in candidates if (datetime.fromisoformat(c['expiry']).date()-now.date()).days >= 7]
    if not candidates:
        idea.update(decision='CONTRACT_DATA_REQUIRED', reasons=['No eligible listed contract with at least seven days to expiry is available.'])
        return base
    expiry = min(c['expiry'] for c in candidates)
    candidates = [c for c in candidates if c['expiry'] == expiry]
    candidates.sort(key=lambda c: (abs((c.get('strike') or last['c'])-last['c']), c['instrument_key']))
    idea['contract'] = candidates[0]
    idea.update(decision='CONTRACT_DATA_REQUIRED', reasons=['Underlying setup found. Check this contract’s current premium or futures price on your broker.'])
    # Daily ideas are watch ideas; an active F&O entry requires current-session candles and quotes.
    if not intraday:
        idea['expires_at']=daily_deadline.isoformat()
        idea['reasons'] = ['Trend idea for the next session. Use Today mode to recheck an entry with current candles and contract prices.']
        return base
    valid, source_time, receipt = recent_price(quote, instrument['instrument_key'], now)
    session_ok = now.weekday() < 5 and 585 <= now.hour*60+now.minute < 885
    if not valid or not session_ok:
        idea['reasons'] = ['Underlying setup found. A recent price during the intraday entry session is needed before entering.']
        return base
    expiry_time = min(source_time+timedelta(seconds=60), receipt+timedelta(seconds=20), complete+timedelta(minutes=15))
    idea['expires_at'] = expiry_time.isoformat()
    price = quote['last_price']
    if (price-trigger)*sign < 0 or (price-trigger)*sign > .5*last['atr']:
        idea.update(decision='WAIT_FOR_TRIGGER', reasons=['Wait for the underlying to cross the trigger without chasing more than half an ATR beyond it.'])
        return base
    if not broker or not broker.configured:
        return base
    market_time = timestamp((market or {}).get('checked_at'))
    if (not market or market.get('status') != 'NORMAL_OPEN' or not market_time
            or not -5 <= (now-market_time).total_seconds() < 20
            or (instrument.get('cas_eligible') and market.get('cas_status'))):
        idea['reasons'] = ['The broker has not confirmed an open trading session.']
        return base
    try:
        quotes = broker.quotes([c['instrument_key'] for c in candidates[:3]])
    except ValueError as exc:
        idea['reasons'] = [str(exc)]
        return base
    now = fixed_now or datetime.now(IST)
    underlying_valid,_,_=recent_price(quote,instrument['instrument_key'],now)
    if not underlying_valid or expiry_time <= now or market_time+timedelta(seconds=20) <= now:
        idea['reasons'] = ['The underlying or session snapshot expired while contract quotes were loading. Recheck the idea.']
        return base
    for c in candidates[:3]:
        q = quotes.get(c['instrument_key']) or {}
        verified, stamp, received = recent_price(q, c['instrument_key'], now)
        spread = q.get('spread_bps'); bid = q.get('bid'); ask = q.get('ask')
        oi = q.get('open_interest', q.get('oi'))
        if (not verified or spread is None or not 0<=spread<=200 or not bid or not ask
                or bid > ask or (q.get('volume') or 0)<=0 or not isinstance(oi,(int,float))
                or isinstance(oi,bool) or not math.isfinite(oi) or oi<=0):
            continue
        entry = ask if product == 'Options' or bull else bid
        # Premium stop is a fixed rule, not inferred from the stock's ATR.
        stop_distance = entry*.25 if product == 'Options' else distance
        side = 1 if product == 'Options' else sign
        stop = entry-side*stop_distance; target = entry+side*stop_distance*2
        if min(stop, target) <= 0: continue
        settings = account['settings']; capital = max(0, account.get('equity_cost_basis', 0))
        risk_per_lot = (stop_distance + entry*.004) * c['lot_size']
        budget = capital*min(settings.get('risk_pct', .5), .5)/100
        max_lots = int(budget/risk_per_lot) if risk_per_lot else 0
        premium = entry*c['lot_size'] if product == 'Options' else None
        if premium:
            max_lots = min(max_lots, int(min(account['cash'], capital*.2)/premium))
        limits_ok = (max_lots >= 1 and not settings.get('kill_switch')
                     and len(account.get('open_positions', [])) < settings.get('max_positions', 2)
                     and account.get('open_planned_risk', 0)+risk_per_lot <= capital*settings.get('total_risk_pct', 1)/100
                     and account.get('daily_realized_pnl', 0) > -settings.get('capital', 10000)*settings.get('daily_loss_pct', 1)/100
                     and account.get('realized_pnl', 0) > -settings.get('capital', 10000)*.05)
        idea['contract'] = c
        idea['contract_quote'] = q
        idea['contract_levels'] = {'entry': round(entry, 4), 'stop': round(stop, 4), 'target': round(target, 4),
                                   'quantity': c['lot_size'], 'lots': 1, 'planned_risk': round(risk_per_lot, 2),
                                   'premium_cost': round(premium, 2) if premium else None,
                                   'maximum_premium_loss': round(premium, 2) if premium else None,
                                   'margin': 'Confirm current margin on broker' if product == 'Futures' else None,
                                   'basis': '25% premium stop / 50% target' if product == 'Options' else '1.5 underlying ATR distance; futures basis can change'}
        trade_time=timestamp(q.get('trade_time'))
        idea['expires_at'] = min(expiry_time, stamp+timedelta(seconds=60), received+timedelta(seconds=20),
                                  trade_time+timedelta(seconds=120),market_time+timedelta(seconds=20)).isoformat()
        idea.update(decision='REVIEW_TRADE' if limits_ok else 'BUDGET_TOO_SMALL', reasons=[
            'Price and signal checks passed. Recheck spread and available funds before a manual order.' if limits_ok
            else 'One lot does not fit the local account’s position, loss or risk limits. Practise this setup instead.'])
        return base
    idea['reasons'] = ['Needs live quote: fresh contract price, bid/ask and open interest are required. Recheck on your broker.']
    return base

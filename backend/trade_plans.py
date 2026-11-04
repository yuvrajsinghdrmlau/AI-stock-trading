"""Versioned conditional trade plans for manual review outside this application."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, time

from .data import IST, parse_time
from .market import timestamp
from .research import config_for
from .strategies import CATALOG

PLAN_VERSION = 1
BROKER_PLATFORMS = [
    {'name': 'Zerodha Kite', 'url': 'https://kite.zerodha.com/'},
    {'name': 'Upstox', 'url': 'https://pro.upstox.com/'},
    {'name': 'Dhan', 'url': 'https://web.dhan.co/'},
]
DATA_OPTIONS = [
    {'name': 'Public history / your CSV', 'available': True,
     'description': 'No broker token needed. Completed candles for conditional research; no verified live quote or commercial data licence is supplied.'},
    {'name': 'Your Upstox connection', 'available': True,
     'description': 'The implemented live snapshot adapter needs your authorized token. A personal token does not establish redistribution rights.'},
    {'name': 'Licensed exchange or vendor feed', 'available': False,
     'description': 'An alternative to a personal broker API for a commercial product. Purchase the required display, derived-data and redistribution rights, then integrate that vendor.',
     'url': 'https://www.nseindia.com/static/market-data/real-time-data-subscription'},
]


def build_trade_plan(row, dataset, analysis, catalogue, filters, now=None):
    now = now or datetime.now(IST)
    inst = row['instrument']; spec = CATALOG[row['strategy']]; last = analysis['last']
    model = row.get('model') or {}; cfg = model.get('config') or config_for(spec['id'], {})
    dt = parse_time(last['t'], dataset['timeframe'])
    daily = dataset['timeframe'] == '1d'
    if daily:
        next_date = dt.date() + timedelta(days=1)
        while next_date.weekday() > 4: next_date += timedelta(days=1)
        window = datetime.combine(next_date, time(9, 15), IST)
    else:
        window = dt + timedelta(minutes=15)
    window_end = window + timedelta(seconds=75)
    expiry = window_end
    close, atr = last['c'], last['atr']
    geometry = all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in (close, atr))
    distance = cfg['atr_multiple'] * atr if geometry else 0
    gap = cfg['max_gap_atr'] * atr if geometry else 0
    geometry = geometry and close - gap - distance > 0
    checks = [
        ('Genuine history', not dataset['synthetic'], 'Synthetic history cannot generate a buy plan.'),
        ('Current catalogue', not catalogue.get('stale', True) and catalogue.get('suspension_checked', False), 'Refresh the catalogue and suspension records.'),
        ('Eligible listing', inst.get('simple_equity') and not inst.get('suspended'), 'This listing is suspended or outside regular cash-equity scope.'),
        ('Completed candle', dt + timedelta(minutes=15) <= now if not daily else datetime.combine(dt.date(), time(16), IST) <= now, 'The signal candle is not complete.'),
        ('Price geometry', geometry, 'Entry, ATR and stop geometry are invalid.'),
        ('Price filter', filters['min_price'] <= close <= filters['max_price'], 'The completed close is outside the price filter.'),
        ('Volume filter', last['v'] >= filters['min_volume'] and last['rv'] >= filters['min_relative_volume'], 'Volume does not pass your filters.'),
        ('RSI filter', filters['rsi_min'] <= last['rsi'] <= filters['rsi_max'], 'RSI does not pass your filters.'),
        ('Trend filter', not filters['uptrend_only'] or last['regime'] == 'UPTREND', 'Trend does not pass your filter.'),
        ('Checklist filter', analysis['setup_score'] >= filters['min_checklist'], 'Checklist does not pass your filter.'),
        ('Entry rule', analysis['rule_pass'], 'The strategy has no entry setup on the last completed candle.'),
    ]
    if model.get('status') == 'RESEARCH_ESTIMATE':
        probability = model.get('probability')
        probability_ok = (isinstance(probability, (int, float)) and math.isfinite(probability)
                          and max(filters['min_probability'], cfg['threshold']) <= probability <= 1)
        checks.append(('Target-hit threshold', probability_ok,
                       'The validated model estimate is absent or below the frozen-model/user threshold.'))
    risk_names = {'Risk-capped position fits', 'Open position limit', 'Total planned risk',
                  'Daily loss limit', 'Loss review limit', 'Paper entry control'}
    risk_checks = [c for c in row['checks'] if c['name'] in risk_names]
    risk_ok = len(risk_checks) == len(risk_names) and all(c['pass'] for c in risk_checks)
    checks.append(('Paper risk limits', risk_ok, 'The local paper account cannot fit this plan within its risk limits.'))
    failed = [reason for _, passed, reason in checks if not passed]
    fatal_names = {'Genuine history', 'Current catalogue', 'Eligible listing', 'Completed candle', 'Price geometry', 'Paper risk limits'}
    fatal = any(not passed for name, passed, _ in checks if name in fatal_names)
    qualified = row['status'] in ('PAPER_RESEARCH_CANDIDATE', 'NEXT_OPEN_RESEARCH_WATCH')
    snapshot_end = None
    if qualified:
        quote = row.get('quote') or {}; market = row.get('market') or {}
        deadlines = [(row.get('expires_at'), 0), (quote.get('feed_time'), 60),
                     (quote.get('trade_time'), 120), (market.get('checked_at'), 20)]
        parsed = [(timestamp(value), seconds) for value, seconds in deadlines]
        snapshot_end = min(t + timedelta(seconds=s) for t, s in parsed) if all(t for t, _ in parsed) else now
        qualified = snapshot_end > now
        if qualified: expiry = min(expiry, snapshot_end)
    if fatal:
        decision = 'BLOCKED'
    elif now >= window_end or (not daily and (window.date() != dt.date() or window.hour * 60 + window.minute >= 885)):
        decision = 'EXPIRED'
        failed.insert(0, 'The next-open entry window has passed. Wait for a new completed-bar setup.')
    elif failed:
        decision = 'WAIT'
    elif not daily and not qualified:
        decision = 'WAIT_FOR_LIVE_DATA'
        failed.insert(0, 'Intraday plans require fresh broker quotes, normal market status and validated model evidence.')
    else:
        decision = 'CONDITIONAL_BUY'
    ready = decision == 'CONDITIONAL_BUY'
    entry = None if not ready else {
        'rule': 'NEXT_SESSION_OPEN' if daily else 'NEXT_BAR_OPEN',
        'min': round(close - gap, 4), 'max': round(close + gap, 4),
        'reference': round(close, 4), 'stop_distance': round(distance, 4),
        'target_distance': round(distance * cfg['reward_r'], 4),
        'stop_at_reference': round(close - distance, 4),
        'target_at_reference': round(close + distance * cfg['reward_r'], 4),
        'reward_r': cfg['reward_r'], 'horizon_bars': cfg['horizon'],
        'session_exit_at': None if daily else datetime.combine(dt.date(), time(15, 30), IST).isoformat(),
        'instruction': 'Use the next opening price only if it is inside the range. Recalculate stop and target from the actual fill; do not chase a later price.'}
    identity = {'version': PLAN_VERSION, 'instrument': inst['instrument_key'], 'strategy': spec['id'],
                'dataset_sha': dataset.get('sha'), 'last_bar': last['t'], 'config': cfg, 'filters': filters,
                'model_id': model.get('model_id'), 'decision': decision, 'entry': entry}
    plan = {
        'id': hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20],
        'version': PLAN_VERSION, 'decision': decision, 'side': 'BUY' if ready else None,
        'entry': entry, 'data_source': dataset['source'], 'last_bar': last['t'],
        'generated_at': now.isoformat(), 'entry_window': window.isoformat(), 'expires_at': expiry.isoformat(),
        'entry_window_ends_at': window_end.isoformat(),
        'snapshot_expires_at': snapshot_end.isoformat() if snapshot_end else None,
        'calendar_verified': False, 'live_qualified': qualified and ready,
        'basis': 'VALIDATED_MODEL_AND_RULES' if model.get('status') == 'RESEARCH_ESTIMATE' else 'RULES_ONLY_UNVALIDATED',
        'probability': model.get('probability') if model.get('status') == 'RESEARCH_ESTIMATE' else None,
        'reasons': failed, 'checks': [{'name': name, 'pass': bool(passed)} for name, passed, _ in checks],
        'execution': 'MANUAL_ON_YOUR_BROKER', 'order_placed': False,
        'limitations': ['Confirm the actual trading session, stock identity, current price, spread and company events on your broker before any order.',
                        'Dates assume ordinary weekdays; exchange holidays and special sessions are not verified. Expired plans are not rolled forward.',
                        'Risk checks use the local paper account. Your actual broker balance, positions and limits are not connected; check them and the permitted price tick size yourself.',
                        'Reference levels are hypothetical. Gaps, slippage, taxes and costs affect outcomes. A rules match is not a profit probability.'],
        'official_market_url': 'https://www.nseindia.com/market-data/live-equity-market' if inst['exchange'] == 'NSE' else 'https://www.bseindia.com/',
    }
    return plan


def plan_text(row):
    p = row['trade_plan']; inst = row['instrument']
    lines = ['India Quant - conditional research plan',
             f"{inst['exchange']} / {inst['symbol']} / ISIN {inst.get('isin', 'unknown')}",
             f"Strategy: {row['strategy_name']}", f"Decision: {p['decision']}",
             f"Plan: {p['id']} | version {p['version']}",
             f"Source: {p['data_source']} | completed bar: {p['last_bar']}",
             f"Evidence: {p['basis']} | live qualified: {p['live_qualified']}",
             f"Entry window (IST): {p['entry_window']} to {p['entry_window_ends_at']}",
             f"Plan expires / recheck by (IST): {p['expires_at']}"]
    if p['entry']:
        e = p['entry']
        lines += [f"BUY only at the next open within Rs {e['min']:.2f} - {e['max']:.2f}.",
                  f"Stop = actual fill minus Rs {e['stop_distance']:.2f}; target = actual fill plus Rs {e['target_distance']:.2f}.",
                  f"At reference Rs {e['reference']:.2f}: stop Rs {e['stop_at_reference']:.2f}, target Rs {e['target_at_reference']:.2f}.",
                  f"Review horizon: {e['horizon_bars']} bars. {e['instruction']}"]
        if e['session_exit_at']:
            lines.append(f"Intraday exit is due at the earlier of the horizon or {e['session_exit_at']} (ordinary session close; verify special sessions). Do not carry this intraday plan overnight.")
    lines += p['reasons'] + p['limitations'] + ['No order has been placed. Open your own broker and decide independently.']
    return '\n'.join(lines)

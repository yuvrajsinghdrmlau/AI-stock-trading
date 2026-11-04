"""Conditional plans use fictional fixtures; they do not establish profitability."""
import copy
import os
from datetime import datetime, timedelta

import pytest

os.environ['IQ_NO_DEFAULT_APP'] = '1'
from fastapi.testclient import TestClient
from backend.data import IST, demo_bars
from backend.desk import evaluate_candidate, filters_config
from backend.main import create_app
from backend.trade_plans import build_trade_plan, plan_text
from backend.universe import normalize_master

NOW = datetime(2026, 11, 3, 18, 0, tzinfo=IST)


def inputs():
    inst = {'instrument_key': 'NSE_EQ|INEFIXTURE01', 'exchange': 'NSE', 'symbol': 'FIXTURE',
            'isin': 'INEFIXTURE01', 'simple_equity': True, 'suspended': False}
    data = {'id': 'fixture', 'sha': 'fixture-hash', 'synthetic': False, 'timeframe': '1d', 'source': 'TEST FIXTURE'}
    a = {'strategy': 'trend_pullback', 'rule_pass': True, 'setup_score': 100,
         'last': {'t': '2026-11-03T09:15:00+05:30', 'c': 100., 'atr': 2., 'v': 100000., 'rv': 1.5,
                  'rsi': 60., 'regime': 'UPTREND'}}
    model = {'status': 'NOT_TRAINED', 'probability': None}
    account = {'settings': {'capital': 10000., 'risk_pct': .5, 'exposure_pct': 20., 'max_positions': 2,
                           'total_risk_pct': 1., 'daily_loss_pct': 1., 'kill_switch': False},
               'cash': 10000., 'equity_cost_basis': 10000., 'open_positions': [], 'open_planned_risk': 0.,
               'daily_realized_pnl': 0., 'realized_pnl': 0.}
    return [inst, data, a, None, None, model, account, {'stale': False, 'suspension_checked': True}, filters_config()]


def plan(args=None, now=NOW):
    args = args or inputs()
    row = evaluate_candidate(*args, now=now)
    result = build_trade_plan(row, args[1], args[2], args[7], args[8], now=now)
    row['trade_plan'] = result
    return row, result


def test_no_api_daily_plan_is_conditional_and_unvalidated():
    row, p = plan()
    assert p['decision'] == 'CONDITIONAL_BUY' and not p['live_qualified']
    assert p['basis'] == 'RULES_ONLY_UNVALIDATED' and p['probability'] is None
    assert not p['order_placed'] and not p['calendar_verified']
    assert p['entry']['min'] == 98.5 and p['entry']['max'] == 101.5
    assert p['entry']['stop_at_reference'] == 97 and p['entry']['target_at_reference'] == 106
    assert 'actual fill' in plan_text(row) and 'TEST FIXTURE' in plan_text(row)


@pytest.mark.parametrize('case', ['synthetic', 'suspended', 'special', 'catalogue', 'future', 'risk', 'geometry'])
def test_unsafe_inputs_never_emit_buy(case):
    args = inputs()
    if case == 'synthetic': args[1]['synthetic'] = True
    if case == 'suspended': args[0]['suspended'] = True
    if case == 'special': args[0]['simple_equity'] = False
    if case == 'catalogue': args[7]['stale'] = True
    if case == 'future': args[2]['last']['t'] = '2026-11-04T09:15:00+05:30'
    if case == 'risk': args[6]['settings']['kill_switch'] = True
    if case == 'geometry': args[2]['last']['atr'] = 100
    _, p = plan(args)
    assert p['decision'] == 'BLOCKED' and p['entry'] is None and p['side'] is None


def test_no_setup_and_price_filter_withhold_buy():
    args = inputs(); args[2]['rule_pass'] = False
    assert plan(args)[1]['decision'] == 'WAIT'
    args = inputs(); args[8]['min_price'] = 110
    assert plan(args)[1]['decision'] == 'WAIT'


def test_next_open_deadline_does_not_roll_forward():
    _, p = plan(now=NOW + timedelta(hours=16))
    assert p['decision'] == 'EXPIRED' and p['entry'] is None
    assert p['entry_window'].startswith('2026-11-04T09:15')


def test_weekend_window_is_explicitly_unverified():
    args = inputs(); args[2]['last']['t'] = '2026-11-06T09:15:00+05:30'
    _, p = plan(args, datetime(2026, 11, 6, 18, tzinfo=IST))
    assert p['entry_window'].startswith('2026-11-09T09:15') and not p['calendar_verified']


def test_unvalidated_model_does_not_supply_probability():
    args = inputs(); args[5] = {'status': 'UNVALIDATED', 'probability': .99}
    _, p = plan(args)
    assert p['probability'] is None and p['basis'] == 'RULES_ONLY_UNVALIDATED'


@pytest.mark.parametrize('probability', [None, .55, .79])
def test_validated_daily_model_respects_probability_filter(probability):
    args = inputs(); args[8]['min_probability'] = .8
    args[5] = {'status': 'RESEARCH_ESTIMATE', 'probability': probability}
    _, p = plan(args)
    assert p['decision'] == 'WAIT' and p['entry'] is None
    assert any(c['name'] == 'Target-hit threshold' and not c['pass'] for c in p['checks'])


def test_no_api_intraday_does_not_emit_buy():
    args = inputs(); args[1]['timeframe'] = '15m'; args[2]['strategy'] = 'vwap_pullback'
    args[2]['last']['t'] = '2026-11-03T10:15:00+05:30'
    _, p = plan(args, datetime(2026, 11, 3, 10, 30, 20, tzinfo=IST))
    assert p['decision'] == 'WAIT_FOR_LIVE_DATA' and p['entry'] is None


@pytest.mark.parametrize('feed_age,trade_age,status_age,remaining', [(59, 0, 0, 1), (0, 119, 0, 1), (0, 0, 19, 1), (0, 0, 0, 20)])
def test_live_plan_expires_with_earliest_source_check(feed_age, trade_age, status_age, remaining):
    now = datetime(2026, 11, 3, 10, 30, 20, tzinfo=IST)
    args = inputs(); args[1]['timeframe'] = '15m'; args[2]['strategy'] = 'vwap_pullback'
    args[2]['last']['t'] = '2026-11-03T10:15:00+05:30'
    args[3] = {'fresh': True, 'last_price': 100., 'spread_bps': 1.,
               'feed_time': (now - timedelta(seconds=feed_age)).isoformat(),
               'trade_time': (now - timedelta(seconds=trade_age)).isoformat()}
    args[4] = {'status': 'NORMAL_OPEN', 'checked_at': (now - timedelta(seconds=status_age)).isoformat()}
    args[5] = {'status': 'RESEARCH_ESTIMATE', 'probability': .9}
    row, p = plan(args, now)
    assert p['decision'] == 'CONDITIONAL_BUY' and p['live_qualified']
    assert datetime.fromisoformat(p['expires_at']) == now + timedelta(seconds=remaining)
    assert p['entry_window_ends_at'].endswith('10:31:15+05:30')
    assert p['entry']['session_exit_at'].endswith('15:30:00+05:30')
    assert 'Do not carry this intraday plan overnight' in plan_text(row)
    stale = build_trade_plan(row, args[1], args[2], args[7], args[8], now + timedelta(seconds=remaining))
    assert stale['decision'] == 'WAIT_FOR_LIVE_DATA' and stale['entry'] is None


def test_plan_identity_tracks_filters_and_dataset_revision():
    _, a = plan(); args = inputs(); args[8]['min_volume'] = 1
    assert plan(args)[1]['id'] != a['id']
    args = inputs(); args[1]['sha'] = 'revised'
    assert plan(args)[1]['id'] != a['id']
    assert plan()[1]['id'] == a['id']


def master_rows():
    return [{'segment': ex + '_EQ', 'instrument_key': ex + '_EQ|INEFIXTURE01', 'trading_symbol': 'FIXTURE',
             'name': 'FICTIONAL TEST COMPANY', 'isin': 'INEFIXTURE01', 'instrument_type': typ,
             'exchange_token': token, 'lot_size': 1} for ex, typ, token in [('NSE', 'EQ', '100'), ('BSE', 'A', '500000')]]


def test_suspended_special_series_does_not_suspend_active_equity():
    rows = master_rows(); suspended = [{**rows[0], 'instrument_type': 'BL', 'exchange_token': '200'}]
    inst = next(r for r in normalize_master(rows, suspended) if r['exchange'] == 'NSE')
    assert not inst['suspended'] and inst['instrument_type'] == 'EQ' and inst['exchange_token'] == '100'


def test_matching_suspended_series_is_blocked():
    rows = master_rows()
    inst = next(r for r in normalize_master(rows, [rows[0]]) if r['exchange'] == 'NSE')
    assert inst['suspended']


def test_regular_active_series_is_selected_regardless_of_order():
    rows = master_rows(); special = {**rows[0], 'instrument_type': 'BL', 'exchange_token': '200'}
    for active in (rows + [special], [special] + rows):
        inst = next(r for r in normalize_master(active, []) if r['exchange'] == 'NSE')
        assert inst['instrument_type'] == 'EQ'


def test_review_api_rechecks_and_audits_without_order(tmp_path, monkeypatch):
    monkeypatch.delenv('UPSTOX_ACCESS_TOKEN', raising=False)
    app = create_app(tmp_path, seed_demo=False, testing=True)
    app.state.universe.replace(master_rows(), [])
    data = demo_bars(1, '1d', 300)
    ident = app.state.store.add_dataset('NSE:FIXTURE', '1d', 'TEST FIXTURE', False, data)
    key = 'NSE_EQ|INEFIXTURE01'; app.state.universe.link(key, '1d', ident)
    monkeypatch.setattr('backend.desk.analyse', lambda *args: copy.deepcopy(inputs()[2]))
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None): return NOW
    monkeypatch.setattr('backend.trade_plans.datetime', Frozen)
    with TestClient(app) as c:
        body = {'instrument_key': key, 'strategy': 'trend_pullback'}
        assert c.post('/api/desk/review', json=body).status_code == 403
        headers = {'X-Desk-Token': app.state.token}
        r = c.post('/api/desk/review', json=body, headers=headers)
        assert r.status_code == 200 and r.json()['trade_plan']['decision'] == 'CONDITIONAL_BUY'
        c.post('/api/desk/review', json=body, headers=headers)
        assert len(app.state.desk.signal_log()) == 1
        assert c.post('/api/live/orders', json={}, headers=headers).status_code == 403
        cfg = c.get('/api/market/config').json()
        assert len(cfg['brokers']) >= 3 and not cfg['live_orders']


def test_csv_import_links_only_selected_listing(tmp_path, monkeypatch):
    monkeypatch.delenv('UPSTOX_ACCESS_TOKEN', raising=False)
    app = create_app(tmp_path, seed_demo=False, testing=True)
    app.state.universe.replace(master_rows(), [])
    bars = demo_bars(1, '1d', 100)
    csv = 'timestamp,open,high,low,close,volume\n' + '\n'.join(
        ','.join(str(b[k]) for k in ('t', 'o', 'h', 'l', 'c', 'v')) for b in bars)
    with TestClient(app) as c:
        body = {'instrument_key': 'NSE_EQ|INEFIXTURE01', 'timeframe': '1d', 'csv_text': csv}
        assert c.post('/api/market/import-csv', json=body).status_code == 403
        r = c.post('/api/market/import-csv', json=body, headers={'X-Desk-Token': app.state.token})
        assert r.status_code == 200 and r.json()['bars'] == 100
        assert app.state.universe.history('NSE_EQ|INEFIXTURE01', '1d')
        assert app.state.universe.history('BSE_EQ|INEFIXTURE01', '1d') is None

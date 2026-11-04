"""Discovery and public-price research checks use controlled fictional inputs."""
import copy
import os
import time
from datetime import datetime, timedelta

import pytest

os.environ['IQ_NO_DEFAULT_APP'] = '1'
from fastapi.testclient import TestClient
from backend.data import IST, demo_bars
from backend.desk import evaluate_candidate, filters_config
from backend.main import create_app
from backend.recommendations import discovery_basket
from backend.trade_plans import build_trade_plan

NOW = datetime(2026, 11, 4, 10, 30, 20, tzinfo=IST)
KEY = 'NSE_EQ|INEFIX000001'


def master(symbol, number=1, exchange='NSE', series='EQ'):
    isin = f'INEFIX{number:06d}'
    return {'segment': exchange + '_EQ', 'instrument_key': exchange + '_EQ|' + isin,
            'trading_symbol': symbol, 'name': 'FICTIONAL TEST LISTING', 'isin': isin,
            'instrument_type': series, 'exchange_token': str(number), 'lot_size': 1}


def intraday_inputs():
    instrument = {'instrument_key': KEY, 'exchange': 'NSE', 'symbol': 'FIXTURE',
                  'simple_equity': True, 'suspended': False}
    dataset = {'id': 'fixture', 'sha': 'fixture-hash', 'synthetic': False,
               'timeframe': '15m', 'source': 'FICTIONAL TEST INPUT'}
    analysis = {'strategy': 'vwap_pullback', 'rule_pass': True, 'setup_score': 100,
                'last': {'t': '2026-11-04T10:15:00+05:30', 'c': 100., 'atr': 2.,
                         'v': 100000., 'rv': 1.5, 'rsi': 60., 'regime': 'UPTREND'}}
    model = {'status': 'NOT_TRAINED', 'probability': None}
    account = {'settings': {'capital': 10000., 'risk_pct': .5, 'exposure_pct': 20.,
                           'max_positions': 2, 'total_risk_pct': 1., 'daily_loss_pct': 1.,
                           'kill_switch': False}, 'cash': 10000., 'equity_cost_basis': 10000.,
               'open_positions': [], 'open_planned_risk': 0., 'daily_realized_pnl': 0.,
               'realized_pnl': 0.}
    return [instrument, dataset, analysis, None, None, model, account,
            {'stale': False, 'suspension_checked': True}, filters_config()]


def public_snapshot(now=NOW):
    return {'instrument_key': KEY, 'last_price': 100.5,
            'price_time': (now - timedelta(seconds=5)).isoformat(),
            'received_at': now.isoformat(), 'delayed': False,
            'source': 'FICTIONAL PUBLIC QUOTE', 'fresh': True}


def make_plan(snapshot, args=None, now=NOW):
    args = args or intraday_inputs()
    row = evaluate_candidate(*args, now=now)
    row['public_snapshot'] = snapshot
    return build_trade_plan(row, args[1], args[2], args[7], args[8], now=now)


def test_public_intraday_plan_is_rules_only_and_never_broker_qualified():
    plan = make_plan(public_snapshot())
    assert plan['decision'] == 'CONDITIONAL_BUY'
    assert plan['public_research_ready'] and not plan['live_qualified']
    assert plan['basis'] == 'RULES_ONLY_UNVALIDATED' and plan['probability'] is None
    assert not plan['calendar_verified'] and not plan['order_placed']
    assert plan['entry']['min'] == 98.5 and plan['entry']['max'] == 101.5
    assert plan['entry']['stop_distance'] == 3 and plan['entry']['target_distance'] == 6
    assert datetime.fromisoformat(plan['expires_at']) == NOW + timedelta(seconds=20)
    assert plan['entry']['session_exit_at'].endswith('15:30:00+05:30')


@pytest.mark.parametrize('case', ['absent', 'missing_time', 'stale', 'future', 'old_receipt',
                                 'future_receipt', 'previous_window', 'wrong_listing',
                                 'delayed', 'unknown_delay', 'outside_range', 'boolean_price'])
def test_public_snapshot_failures_never_issue_intraday_buy(case):
    snapshot = public_snapshot()
    if case == 'absent': snapshot = None
    elif case == 'missing_time': snapshot.pop('price_time')
    elif case == 'stale': snapshot['price_time'] = (NOW - timedelta(seconds=61)).isoformat()
    elif case == 'future': snapshot['price_time'] = (NOW + timedelta(seconds=6)).isoformat()
    elif case == 'old_receipt': snapshot['received_at'] = (NOW - timedelta(seconds=20)).isoformat()
    elif case == 'future_receipt': snapshot['received_at'] = (NOW + timedelta(seconds=6)).isoformat()
    elif case == 'previous_window': snapshot['price_time'] = NOW.replace(minute=29, second=59).isoformat()
    elif case == 'wrong_listing': snapshot['instrument_key'] = 'BSE_EQ|INEFIX000001'
    elif case == 'delayed': snapshot['delayed'] = True
    elif case == 'unknown_delay': snapshot.pop('delayed')
    elif case == 'outside_range': snapshot['last_price'] = 102.
    elif case == 'boolean_price': snapshot['last_price'] = True
    plan = make_plan(snapshot)
    assert plan['decision'] == 'WAIT_FOR_LIVE_DATA'
    assert plan['entry'] is None and not plan['public_research_ready'] and not plan['live_qualified']


def test_public_plan_source_timestamp_can_expire_before_receipt():
    now = NOW.replace(minute=31, second=5)
    snapshot = public_snapshot(now)
    snapshot['price_time'] = (now - timedelta(seconds=59)).isoformat()
    plan = make_plan(snapshot, now=now)
    assert plan['decision'] == 'CONDITIONAL_BUY'
    assert datetime.fromisoformat(plan['expires_at']) == now + timedelta(seconds=1)
    assert make_plan(snapshot, now=now + timedelta(seconds=1))['decision'] == 'WAIT_FOR_LIVE_DATA'


@pytest.mark.parametrize('case', ['no_rule', 'risk', 'model_threshold'])
def test_recent_public_price_does_not_override_existing_gates(case):
    args = intraday_inputs()
    if case == 'no_rule': args[2]['rule_pass'] = False
    elif case == 'risk': args[6]['settings']['kill_switch'] = True
    else: args[5] = {'status': 'RESEARCH_ESTIMATE', 'probability': .5}
    plan = make_plan(public_snapshot(), args=args)
    assert plan['decision'] in ('WAIT', 'BLOCKED') and plan['entry'] is None


def test_public_intraday_cutoff_and_entry_deadline_are_enforced():
    args = intraday_inputs()
    args[2]['last']['t'] = '2026-11-04T14:30:00+05:30'
    now = NOW.replace(hour=14, minute=45)
    assert make_plan(public_snapshot(now), args, now)['decision'] == 'EXPIRED'
    now = NOW.replace(minute=31, second=15)
    assert make_plan(public_snapshot(now), now=now)['decision'] == 'EXPIRED'


@pytest.fixture
def application(tmp_path, monkeypatch):
    monkeypatch.delenv('UPSTOX_ACCESS_TOKEN', raising=False)
    return create_app(tmp_path, seed_demo=False, testing=True)


def test_discovery_resolves_exact_eligible_nse_listings_without_watch_changes(application):
    rows = [master('RELIANCE'), master('RELIANCE-ALT', 2), master('TCS', 3, series='BL'),
            master('INFY', 4), master('BEL', 5, exchange='BSE', series='A')]
    universe = application.state.universe
    universe.replace(rows, [rows[3]])
    universe.set_watch(rows[4]['instrument_key'])
    before = copy.deepcopy(universe.watch())
    selected, missing = discovery_basket(universe)
    assert [r['symbol'] for r in selected] == ['RELIANCE']
    assert {'TCS', 'INFY', 'BEL'} <= set(missing)
    assert universe.watch() == before


def poll_job(client, ident):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        response = client.get('/api/market/jobs/' + ident)
        assert response.status_code == 200
        job = response.json()
        if job['status'] != 'running': return job
        time.sleep(.02)
    pytest.fail('Discovery fixture job did not finish')


def test_recommendation_api_auth_and_invalid_inputs(application):
    with TestClient(application) as client:
        assert client.post('/api/recommendations/scan', json={}).status_code == 403
        headers = {'X-Desk-Token': application.state.token}
        for body in ({'mode': 'F&O'}, {'source': 'invented'}, {'filters': {'min_price': -1}}):
            assert client.post('/api/recommendations/scan', json=body, headers=headers).status_code == 400


def test_recommendation_job_keeps_partial_results_and_reports_missing_data(application, monkeypatch):
    universe = application.state.universe
    rows = [master('RELIANCE'), master('TCS', 2)]
    universe.replace(rows, [])
    instruments = [universe.get(r['instrument_key']) for r in rows]
    monkeypatch.setattr('backend.v2_api.discovery_basket', lambda _: (instruments, ['MISSING']))
    calls = []

    def refresh(key, timeframe, source):
        calls.append((key, timeframe, source))
        if key == rows[1]['instrument_key']: raise ValueError('Fixture candle source unavailable')
        ident = application.state.store.add_dataset('NSE:RELIANCE', timeframe, 'FICTIONAL TEST INPUT',
                                                    False, demo_bars(1, timeframe, 120))
        universe.link(key, timeframe, ident)
        return {'dataset_id': ident}

    def quote(inst):
        if inst['instrument_key'] == rows[1]['instrument_key']: raise ValueError('Fixture quote unavailable')
        return {**public_snapshot(), 'instrument_key': inst['instrument_key']}

    monkeypatch.setattr(application.state.desk, 'refresh_history', refresh)
    monkeypatch.setattr('backend.public_quotes.public_quote', quote)
    with TestClient(application) as client:
        response = client.post('/api/recommendations/scan', json={'mode': 'Swing'},
                               headers={'X-Desk-Token': application.state.token})
        assert response.status_code == 200
        job = poll_job(client, response.json()['job_id'])
    assert job['status'] == 'complete'
    result = job['result']
    assert result['basket_symbols'] == ['RELIANCE', 'TCS'] and result['missing_symbols'] == ['MISSING']
    assert result['refreshed'] == 1 and result['evaluated'] == 4
    assert any('Fixture candle source unavailable' in error for error in result['errors'])
    assert any('Fixture quote unavailable' in error for error in result['errors'])
    tcs = [r for r in result['rows'] if r['instrument']['symbol'] == 'TCS']
    assert len(tcs) == 2 and all(r['trade_plan']['decision'] == 'DATA_REQUIRED' for r in tcs)
    assert all(timeframe == '1d' for _, timeframe, _ in calls)
    assert universe.watch() == []


def test_review_latest_price_is_opt_in_and_preserves_source_errors(application, monkeypatch):
    application.state.universe.replace([master('RELIANCE')], [])
    calls = []

    def quote(inst):
        calls.append(inst['instrument_key'])
        raise ValueError('Fixture quote unavailable')

    monkeypatch.setattr('backend.public_quotes.public_quote', quote)
    with TestClient(application) as client:
        headers = {'X-Desk-Token': application.state.token}
        body = {'instrument_key': KEY, 'strategy': 'trend_pullback'}
        assert client.post('/api/desk/review', json=body, headers=headers).status_code == 200
        assert calls == []
        response = client.post('/api/desk/review', json={**body, 'latest_price': True}, headers=headers)
    assert response.status_code == 200 and calls == [KEY]
    assert response.json()['data_errors'] == ['Fixture quote unavailable']
    assert response.json()['trade_plan']['entry'] is None

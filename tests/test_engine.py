import copy, json, math
from datetime import datetime, timedelta
import pytest
from backend.data import demo_bars,validate_bars,csv_bars,fingerprint,symbol_ok,IST
from backend.strategies import indicators,simulate_event,events,portfolio,nonoverlap,rule
from backend.research import config_for,partition,run_study,wilson
from backend.options import debit_spread

@pytest.fixture
def daily():return demo_bars(1,'1d',300)

def test_deterministic_data(daily):assert daily==demo_bars(1,'1d',300)
def test_valid_data(daily):assert len(validate_bars(daily,'1d')[0])==300
@pytest.mark.parametrize('key,value',[('c',float('nan')),('h',float('inf')),('o',0),('v',-1)])
def test_bad_numbers(daily,key,value):
    daily[15][key]=value
    with pytest.raises(ValueError):validate_bars(daily,'1d')
def test_invalid_high(daily):
    daily[0]['h']=daily[0]['l']/2
    with pytest.raises(ValueError):validate_bars(daily,'1d')
def test_duplicate(daily):
    daily.append(daily[-1])
    with pytest.raises(ValueError,match='Duplicate'):validate_bars(daily,'1d')
def test_future_bar_excluded(daily):
    daily[-1]['t']='2099-01-01T09:15:00+05:30'
    bars,w=validate_bars(daily,'1d');assert len(bars)==299 and any('withheld' in x for x in w)
def test_sorting_is_visible(daily):
    rows,w=validate_bars(list(reversed(daily)),'1d');assert rows==daily and any('reordered' in x for x in w)
def test_csv_header():
    with pytest.raises(ValueError,match='Columns'):csv_bars('x,y\n1,2','1d')
def test_symbol_injection():
    with pytest.raises(ValueError):symbol_ok('<script>alert(1)</script>')
def test_empty_csv():
    with pytest.raises(ValueError):csv_bars('','1d')
def test_features_past_only(daily):
    old=indicators(daily,'1d');new=copy.deepcopy(daily)
    for b in new[150:]:
        for key in ('o','h','l','c'):b[key]*=2
    other=indicators(new,'1d')
    assert old[:150]==other[:150]
def event_fixture():
    rows=[{'t':f'2026-10-{12+i:02d}T09:15:00+05:30','o':100.,'h':101.,'l':99.,'c':100.,'v':1000.,'atr':2.,'features':[0]*15} for i in range(7)]
    return rows

def test_stop_first_ambiguous_candle():
    f=event_fixture();f[1].update(h=108.,l=94.)
    e=simulate_event(f,0,'trend_pullback',config_for('trend_pullback',{'horizon':3,'roundtrip_cost_bps':0,'slippage_bps':0}))
    assert e['reason']=='STOP' and e['exit']==97

def test_gap_stop_fills_adversely():
    f=event_fixture();f[2].update(o=92.,h=94.,l=90.,c=93.)
    e=simulate_event(f,0,'trend_pullback',config_for('trend_pullback',{'horizon':3,'roundtrip_cost_bps':0,'slippage_bps':0}))
    assert e['reason']=='GAP_STOP' and e['exit']==92

def test_entry_uses_next_open_not_signal_close():
    f=event_fixture();f[1].update(o=100.5,h=102,l=99,c=101)
    e=simulate_event(f,0,'trend_pullback',config_for('trend_pullback',{'horizon':3,'slippage_bps':0}))
    assert e['raw_entry']==100.5

def test_entry_gap_rejected():
    f=event_fixture();f[1]['o']=110
    assert simulate_event(f,0,'trend_pullback',config_for('trend_pullback',{'horizon':3})) is None

def test_costs_reduce_return():
    f=event_fixture();a=simulate_event(f,0,'trend_pullback',config_for('trend_pullback',{'horizon':3,'roundtrip_cost_bps':0,'slippage_bps':0}))
    b=simulate_event(f,0,'trend_pullback',config_for('trend_pullback',{'horizon':3,'roundtrip_cost_bps':40,'slippage_bps':5}))
    assert b['net_per_share']<a['net_per_share']

def test_timeout_positive_is_not_target_hit():
    f=event_fixture();f[3].update(c=101.,h=102.)
    e=simulate_event(f,0,'trend_pullback',config_for('trend_pullback',{'horizon':3,'roundtrip_cost_bps':0,'slippage_bps':0}))
    assert e['label']==0 and e['net_per_share']>0

def test_nonoverlap():
    es=[{'i':0,'exit_i':4},{'i':3,'exit_i':6},{'i':5,'exit_i':7}]
    assert [x['i'] for x in nonoverlap(es)]==[0,5]

def test_split_purge():
    es=[{'i':40,'exit_i':49},{'i':48,'exit_i':51},{'i':50,'exit_i':60},{'i':67,'exit_i':69},{'i':70,'exit_i':72},{'i':84,'exit_i':88}]
    parts,cut=partition(es,100)
    assert cut==[50,68,83] and [len(p) for p in parts]==[1,1,1,1]
    assert all(e['exit_i']<cut[0] for e in parts[0])

@pytest.mark.parametrize('changes',[{'threshold':1.2},{'horizon':1.5},{'roundtrip_cost_bps':-2},{'risk_pct':10},{'horizon':True}])
def test_bad_config(changes):
    with pytest.raises(ValueError):config_for('trend_pullback',changes)

def test_intraday_no_overnight():
    bars=demo_bars(1,'15m',150);f=indicators(bars,'15m');idx=next(i for i in range(70,len(f)-1) if f[i]['t'][:10]!=f[i+1]['t'][:10])
    assert simulate_event(f,idx,'vwap_pullback',config_for('vwap_pullback',{})) is None

def test_opening_range_needs_real_first_two_bars():
    bars=demo_bars(1,'15m',150)
    rows=[b for b in bars if b['t'][11:16] not in ('09:15','09:30')]
    assert all(r['or_high'] is None for r in indicators(rows,'15m'))

def test_intraday_gap_rejected():
    bars=demo_bars(1,'15m',150);f=indicators(bars,'15m');f.pop(78)
    assert simulate_event(f,76,'vwap_pullback',config_for('vwap_pullback',{})) is None

def test_size_capped():
    cfg=config_for('trend_pullback',{});e=simulate_event(event_fixture(),0,'trend_pullback',{**cfg,'horizon':3})
    p=portfolio([e],cfg)
    assert p['trades'][0]['quantity']*e['entry']<=2000

def test_zero_size_no_trade():
    cfg=config_for('trend_pullback',{});e=simulate_event(event_fixture(),0,'trend_pullback',{**cfg,'horizon':3});e['entry']=5000
    assert portfolio([e],cfg)['n']==0

def test_uncertainty_bounds():
    lo,hi=wilson(5,10);assert 0<lo<.5<hi<1

def test_insufficient_data_has_no_probability(daily):
    r=run_study({'id':'x','symbol':'SIM-X','timeframe':'1d','bars':daily,'synthetic':True,'sha':fingerprint(daily),'source':'test'},'trend_pullback',{})
    assert r['current_probability'] is None and r['evidence_status']=='INSUFFICIENT_EVIDENCE'

def test_real_model_comparison_runs():
    bars=demo_bars(1,'1d',3200)
    r=run_study({'id':'x','symbol':'SIM-X','timeframe':'1d','bars':bars,'synthetic':True,'sha':fingerprint(bars),'source':'test'},'trend_pullback',{})
    assert len(r['leaderboard'])==5 and 0<=r['diagnostic_last_bar_probability']<=1
    assert r['selected_model']==min(r['leaderboard'],key=lambda v:v['selection_brier'])['model']
    assert all('test_brier' not in x for x in r['leaderboard'])
    json.dumps(r,allow_nan=False)

def test_spread_math():
    r=debit_spread('bull_call',100,110,4,10,1,2)
    assert r['max_loss']==42 and r['max_gain']==58 and r['break_even']==104.2
    assert min(x['pnl'] for x in r['payoff'])==-42 and max(x['pnl'] for x in r['payoff'])==58

def test_put_spread_math():
    r=debit_spread('bear_put',110,100,4,10,1,2);assert r['break_even']==105.8 and r['prediction'] is None

def test_spread_no_guessed_contract_size():
    with pytest.raises(ValueError):debit_spread('bull_call',100,110,4,1.5,1,0)

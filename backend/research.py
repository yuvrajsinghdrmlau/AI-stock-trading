"""Chronological strategy research. No claims of live performance or model superiority."""
from __future__ import annotations
import math, statistics
from .strategies import CATALOG, FEATURES, indicators, events, nonoverlap, portfolio, rule

DEFAULTS={'horizon':10,'atr_multiple':1.5,'reward_r':2.0,'max_gap_atr':.75,
 'roundtrip_cost_bps':40.0,'slippage_bps':5.0,'threshold':.60,'capital':10000.0,
 'risk_pct':.5,'exposure_pct':20.0,'seed':42}

def config_for(strategy: str, supplied: dict) -> dict:
    if strategy not in CATALOG: raise ValueError('Unknown strategy.')
    c={**DEFAULTS,'horizon':CATALOG[strategy]['horizon']}
    if set(supplied)-set(c): raise ValueError('Unknown experiment setting.')
    c.update(supplied)
    limits={'horizon':(1,40),'atr_multiple':(.5,5),'reward_r':(.5,5),'max_gap_atr':(.1,3),
            'roundtrip_cost_bps':(0,500),'slippage_bps':(0,100),'threshold':(.5,.95),
            'capital':(1000,10000000),'risk_pct':(.05,1),'exposure_pct':(1,100),'seed':(0,999999)}
    for key,(low,high) in limits.items():
        val=c[key]
        if isinstance(val,bool) or not isinstance(val,(int,float)) or not math.isfinite(val) or not low<=val<=high:
            raise ValueError(f'{key} must be between {low} and {high}.')
    if c['horizon']!=int(c['horizon']) or c['seed']!=int(c['seed']): raise ValueError('Horizon and seed must be integers.')
    c['horizon']=int(c['horizon']); c['seed']=int(c['seed'])
    if CATALOG[strategy]['timeframe']=='15m' and c['horizon']>24: raise ValueError('Intraday horizon cannot exceed 24 bars.')
    return c

def wilson(successes: int,n: int) -> list[float] | None:
    if not n: return None
    p=successes/n; z=1.959963984540054; den=1+z*z/n
    mid=(p+z*z/(2*n))/den; rad=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [max(0,mid-rad),min(1,mid+rad)]

def partition(es: list[dict], n_bars: int, boundaries=None):
    a,b,c=boundaries or [int(n_bars*x) for x in (.50,.68,.83)]
    if not 0<a<b<c<n_bars: raise ValueError("Invalid chronological split boundaries.")
    sets=[[],[],[],[]]
    for e in es:
        i,j=e['i'],e['exit_i']
        if j<a: sets[0].append(e)
        elif i>=a and j<b: sets[1].append(e)
        elif i>=b and j<c: sets[2].append(e)
        elif i>=c: sets[3].append(e)
    return sets,[a,b,c]

def mark_curve(result: dict, f: list[dict], start: int, cfg: dict):
    trades=result['trades']; equity=cfg['capital']; peak=equity; drawdown=0; curve=[]; k=0
    for i in range(start,len(f)):
        while k<len(trades) and trades[k]['exit_i']<i:
            equity+=trades[k]['net_pnl']; k+=1
        mark=equity
        if k<len(trades) and trades[k]['entry_i']<=i<=trades[k]['exit_i']:
            t=trades[k]
            if i==t['exit_i']: mark+=t['net_pnl']
            else:
                sell=f[i]['c']*(1-cfg['slippage_bps']/10000)
                fees=cfg['roundtrip_cost_bps']/20000*(t['entry']+sell)
                mark+=t['quantity']*(sell-t['entry']-fees)
        peak=max(peak,mark); drawdown=max(drawdown,(peak-mark)/peak)
        curve.append({'t':f[i]['t'],'equity':round(mark,2)})
    result['curve']=curve; result['bar_close_drawdown_pct']=drawdown*100
    result['drawdown_definition']='Bar-close hypothetical liquidation equity, not tick-level or intrabar maximum drawdown.'
    return result

def run_study(dataset: dict, strategy: str, supplied: dict, update=lambda p,m:None, artifact_callback=None, split_boundaries=None) -> dict:
    cfg=config_for(strategy,supplied)
    if dataset['timeframe']!=CATALOG[strategy]['timeframe']: raise ValueError('Dataset timeframe does not match the strategy.')
    update(10,'Building past-only features and conditional trade outcomes')
    f=indicators(dataset['bars'],dataset['timeframe']); es=events(f,strategy,cfg)
    sets,boundaries=partition(es,len(f),split_boundaries); train,cal0,select0,test0=sets
    cal,selection,test=[nonoverlap(s) for s in (cal0,select0,test0)]
    descriptions=['Train','Calibrate','Select champion','Final test']
    intervals=[(0,boundaries[0]),(boundaries[0],boundaries[1]),(boundaries[1],boundaries[2]),(boundaries[2],len(f))]
    result={'engine_version':'iq-2.0.0','strategy':strategy,'strategy_name':CATALOG[strategy]['name'],'dataset_id':dataset['id'],
     'symbol':dataset['symbol'],'synthetic':dataset['synthetic'],'data_sha256':dataset['sha'],'source':dataset['source'],
     'timeframe':dataset['timeframe'],'config':cfg,'target_definition':'Target hit before stop within the holding horizon, conditional on the next-open entry/gap filter. A timeout is label 0 even if profitable.',
     'splits':[{'name':name,'from':f[a]['t'],'to':f[b-1]['t'],'events':len(ev)} for name,(a,b),ev in zip(descriptions,intervals,[train,cal,selection,test])],
     'purged_boundary_events':len(es)-sum(map(len,sets)),'total_events':len(es),'leaderboard':[], 'calibration':[],
     'importance':[],'current_probability':None,'selected_model':None,'evidence_status':'INSUFFICIENT_EVIDENCE','warnings':[],
     'experiment_policy':'Fixed model recipes, calibration on later disjoint data, champion chosen on selection Brier score only. Final test is not used to select the champion. Repeated manual experiments still risk data snooping.',
     'latest_rule_pass':rule(f[-1],f[-2],strategy,len(f)-1)}
    result['rules_test']=mark_curve(portfolio(test0,cfg),f,boundaries[2],cfg)
    result['ml_test']=mark_curve(portfolio([],cfg),f,boundaries[2],cfg)
    # Simple equal-exposure buy/hold comparator over the same final time window.
    fee=cfg['roundtrip_cost_bps']/20000; slip=cfg['slippage_bps']/10000
    b_entry=f[boundaries[2]]['o']*(1+slip); b_exit=f[-1]['c']*(1-slip)
    qty=int(cfg['capital']*cfg['exposure_pct']/100/(b_entry*(1+fee)))
    result['buy_hold']={'quantity':qty,'net_pnl':qty*(b_exit-b_entry-fee*(b_entry+b_exit)),
                        'label':'Same-exposure buy and hold; risk profile is different.'}
    minimums=[60,16,15,15]
    counts=[len(train),len(cal),len(selection),len(test)]
    if any(n<m for n,m in zip(counts,minimums)):
        result['warnings'].append('Not enough strategy events for independent stages. Required train/calibrate/select/test: 60/16/15/15; observed: '+ '/'.join(map(str,counts))+'. Import more history; do not weaken evidence thresholds to force calls.')
        result['model_available']=False
        return result
    if min(sum(e['label'] for e in train),len(train)-sum(e['label'] for e in train))<8 or min(sum(e['label'] for e in cal),len(cal)-sum(e['label'] for e in cal))<4:
        result['warnings'].append('Both outcomes need sufficient representation in training and calibration.')
        result['model_available']=False
        return result
    try:
        import numpy as np
        from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        from sklearn.pipeline import make_pipeline
        from threadpoolctl import threadpool_limits
    except (ImportError,OSError) as exc:
        result['warnings'].append('ML dependencies could not load. Rules research remains available. Run INSTALL_ML.bat; a Windows policy block needs administrator review. '+str(exc)[:180])
        result['model_available']=False
        return result
    result['model_available']=True
    x=lambda ss:np.array([e['x'] for e in ss],dtype=float)
    y=lambda ss:np.array([e['label'] for e in ss],dtype=int)
    Xtr,Xca,Xse,Xte=x(train),x(cal),x(selection),x(test)
    Ytr,Yca,Yse,Yte=y(train),y(cal),y(selection),y(test)
    baseline=float((Yca.sum()+1)/(len(Yca)+2))
    result['base_rate']=baseline
    candidates=[('Prior baseline',None),
      ('Logistic regression',make_pipeline(StandardScaler(),LogisticRegression(C=.3,max_iter=1000,random_state=cfg['seed']))),
      ('Extra Trees',ExtraTreesClassifier(n_estimators=120,max_depth=5,min_samples_leaf=12,max_features=.8,n_jobs=1,random_state=cfg['seed'])),
      ('Histogram gradient boosting',HistGradientBoostingClassifier(max_iter=100,max_leaf_nodes=7,max_depth=3,learning_rate=.05,l2_regularization=3,min_samples_leaf=20,early_stopping=False,random_state=cfg['seed']))]
    fitted={}; predict={}
    def logit(p):
        p=np.clip(p,1e-5,1-1e-5); return np.log(p/(1-p)).reshape(-1,1)
    for num,(name,model) in enumerate(candidates):
        update(25+num*15,'Comparing '+name)
        if model is None:
            pred=lambda a:np.full(len(a),baseline)
        else:
            with threadpool_limits(limits=1):
                model.fit(Xtr,Ytr)
                calibrator=LogisticRegression(C=1,max_iter=500,random_state=cfg['seed']).fit(logit(model.predict_proba(Xca)[:,1]),Yca)
            def pred(a,m=model,c=calibrator):
                with threadpool_limits(limits=1):
                    return c.predict_proba(logit(m.predict_proba(a)[:,1]))[:,1]
            fitted[name]=(model,calibrator)
        predict[name]=pred
        p=pred(Xse); brier=float(np.mean((p-Yse)**2))
        pp=np.clip(p,1e-8,1-1e-8); loss=float(np.mean(-Yse*np.log(pp)-(1-Yse)*np.log(1-pp)))
        result['leaderboard'].append({'model':name,'selection_brier':brier,'selection_log_loss':loss,'selection_events':len(selection),'selected':False})
    # Fixed equal-weight soft vote of independently calibrated members. Its weights
    # are not tuned on selection or final-test outcomes. The average is still checked
    # empirically; do not assume that averaging ensures calibration.
    member_names=list(fitted)
    def blended(a):
        return np.mean(np.vstack([predict[n](a) for n in member_names]),axis=0)
    predict['Calibrated soft-vote']=blended
    p=blended(Xse); pp=np.clip(p,1e-8,1-1e-8)
    result['leaderboard'].append({'model':'Calibrated soft-vote','selection_brier':float(np.mean((p-Yse)**2)),
        'selection_log_loss':float(np.mean(-Yse*np.log(pp)-(1-Yse)*np.log(1-pp))),
        'selection_events':len(selection),'selected':False})
    chosen=min(result['leaderboard'],key=lambda row:row['selection_brier'])
    chosen['selected']=True; name=chosen['model']; result['selected_model']=name
    forecast=predict[name]; pte=forecast(Xte); pfull=forecast(x(test0))
    result['diagnostic_last_bar_probability']=float(forecast(np.array([f[-1]['features']]))[0])
    result['current_probability']=result['diagnostic_last_bar_probability'] if result['latest_rule_pass'] else None
    member_scores=[float(predict[n](np.array([f[-1]['features']]))[0]) for n in member_names]
    result['model_disagreement']={'minimum':min(member_scores),'maximum':max(member_scores),
        'definition':'Range across calibrated members, NOT a confidence interval.'}
    result['ml_test']=mark_curve(portfolio(test0,cfg,pfull.tolist()),f,boundaries[2],cfg)
    result['test_brier']=float(np.mean((pte-Yte)**2)); result['test_baseline_brier']=float(np.mean((baseline-Yte)**2))
    result['test_events']=len(test)
    for low in (0,.2,.4,.6,.8):
        ix=(pte>=low)&(pte<low+.2000001 if low==.8 else pte<low+.2)
        n=int(ix.sum())
        if n:
            successes=int(Yte[ix].sum())
            result['calibration'].append({'from':low,'to':min(1,low+.2),'n':n,'predicted':float(pte[ix].mean()),'observed':successes/n,'observed_wilson_95':wilson(successes,n)})
    if name!='Prior baseline':
        # Descriptive selection-set permutation sensitivity, not causal attribution or SHAP.
        rng=np.random.default_rng(cfg['seed']); base=float(np.mean((forecast(Xse)-Yse)**2))
        for j,feature in enumerate(FEATURES):
            vals=[]
            for _ in range(3):
                xp=Xse.copy(); xp[:,j]=rng.permutation(xp[:,j]); vals.append(float(np.mean((forecast(xp)-Yse)**2))-base)
            result['importance'].append({'feature':feature,'selection_brier_increase':float(np.mean(vals))})
        result['importance'].sort(key=lambda z:z['selection_brier_increase'],reverse=True)
    mt=result['ml_test']
    gates=[{'name':'ML beats prior baseline during selection','pass':name!='Prior baseline'},
           {'name':'Final-test Brier beats prior baseline','pass':result['test_brier']<result['test_baseline_brier']},
           {'name':'At least 30 non-overlapping filtered test trades','pass':mt['n']>=30},
           {'name':'Positive net test outcome after estimated costs','pass':mt['net_pnl']>0},
           {'name':'Final-test profit factor above 1.10','pass':mt['profit_factor'] is not None and mt['profit_factor']>1.1}]
    result['gates']=gates
    result['evidence_status']='RESEARCH_GATES_PASSED' if all(g['pass'] for g in gates) else 'NOT_VALIDATED'
    if dataset['synthetic']: result['warnings'].append('All results are on SYNTHETIC data. Passing any numerical gate provides NO evidence of real-market profitability.')
    result['warnings']+=['A single final period is not multi-regime forward validation. Manual reruns on the same final period compromise independence.',
                        'Costs are configurable estimates, not broker-accurate Indian taxes, DP fees or exchange charges.',
                        'No news, earnings, spread/order-book, corporate-action or exchange-calendar service is connected.',
                        'Study data is historical; a quote snapshot does not turn a historical score into an executable recommendation. Real orders are disabled.']
    if artifact_callback is not None:
        artifact_callback({'selected_model':name,'fitted':fitted,'baseline':baseline,
            'features':FEATURES,'feature_low':np.quantile(Xtr,.01,axis=0).tolist(),
            'feature_high':np.quantile(Xtr,.99,axis=0).tolist()},result)
    update(95,'Saving evidence, provenance and risk checks')
    return result


def walkforward_study(dataset: dict, strategy: str, supplied: dict, update=lambda p,m:None):
    """Three disjoint prospective test blocks; each fold trains/selects on its past.

    Presets are fixed. This is NOT a license to tune on the aggregated fold scores.
    Later folds legitimately learn from earlier history, including previous tests.
    """
    from .data import fingerprint
    n=len(dataset['bars']); starts=[int(n*x) for x in (.55,.70,.85)]; ends=[int(n*x) for x in (.70,.85,1.0)]
    folds=[]
    for j,(start,end) in enumerate(zip(starts,ends)):
        update(8+j*28,f'Walk-forward fold {j+1}/3: training strictly before its test block')
        sub={**dataset,'bars':dataset['bars'][:end],'sha':fingerprint(dataset['bars'][:end])}
        boundaries=[int(start*.64),int(start*.82),start]
        r=run_study(sub,strategy,supplied,split_boundaries=boundaries)
        folds.append({'fold':j+1,'test_start_index':start,'test_end_index':end,
            'splits':r['splits'],'selected_model':r['selected_model'],'evidence_status':r['evidence_status'],
            'test_events':r.get('test_events',0),'test_brier':r.get('test_brier'),
            'baseline_brier':r.get('test_baseline_brier'),'net_pnl':r['ml_test']['net_pnl'],
            'trades':r['ml_test']['n'],'drawdown_pct':r['ml_test'].get('bar_close_drawdown_pct'),
            'profit_factor':r['ml_test']['profit_factor'],'warnings':r['warnings']})
    counts=sum(f['test_events'] for f in folds)
    measured=[f for f in folds if f['test_brier'] is not None]
    return {'folds':folds,'disjoint_test_windows':True,'synthetic':dataset['synthetic'],
        'total_test_events':counts,'all_folds_evaluable':len(measured)==3,
        'weighted_brier':sum(f['test_brier']*f['test_events'] for f in measured)/counts if counts else None,
        'weighted_baseline_brier':sum(f['baseline_brier']*f['test_events'] for f in measured)/counts if counts else None,
        'aggregate_net_pnl':sum(f['net_pnl'] for f in folds),
        'all_folds_positive':len(measured)==3 and all(f['net_pnl']>0 for f in folds),
        'definition':'Fixed-policy expanding-history tests with nonoverlapping test dates. Each fold starts with the same virtual capital; summed P&L is NOT a continuous compounded account. Repeated tuning consumes independence.'}

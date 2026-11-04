"""Locally generated model artifacts only. Never deserialize uploaded models.

Artifact hashes detect accidental corruption, not an adversary with write access.
The data directory is trusted local storage and must not be exposed publicly.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from .data import IST, fingerprint, parse_time
from .strategies import indicators, rule, FEATURES

class Models:
    def __init__(self, store, universe):
        self.store=store; self.universe=universe
        self.directory=store.path.parent/'models'; self.directory.mkdir(exist_ok=True)
        with store.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS models(id TEXT PRIMARY KEY,instrument_key TEXT,strategy TEXT,dataset_id TEXT,created TEXT,body TEXT)')

    def save(self, bundle, result):
        import joblib
        key=self.universe.instrument_for_dataset(result['dataset_id'])
        data=self.store.dataset(result['dataset_id'])
        ident=uuid.uuid4().hex; path=self.directory/(ident+'.joblib')
        tmp=self.directory/(ident+'.tmp')
        joblib.dump(bundle,tmp,compress=3); os.replace(tmp,path)
        import sklearn
        meta={'id':ident,'instrument_key':key,'strategy':result['strategy'],'dataset_id':data['id'],
              'data_sha':data['sha'],'data_end':data['bars'][-1]['t'],'data_start':data['bars'][0]['t'],
              'timeframe':data['timeframe'],'synthetic':data['synthetic'],'selected_model':result['selected_model'],
              'evidence_status':result['evidence_status'],'config':result['config'],'created':self.store.now(),
              'artifact_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'sklearn_version':sklearn.__version__,
              'test_events':result.get('test_events',0),'calibration':result.get('calibration',[]),
              'test_brier':result.get('test_brier'),'test_baseline_brier':result.get('test_baseline_brier'),
              'test_trades':result['ml_test']['n'],'net_pnl':result['ml_test']['net_pnl'],
              'drawdown_pct':result['ml_test'].get('bar_close_drawdown_pct'),'profit_factor':result['ml_test'].get('profit_factor'),
              'target_definition':result['target_definition']}
        with self.store.db() as db:
            db.execute('INSERT INTO models VALUES(?,?,?,?,?,?)',(ident,key,result['strategy'],data['id'],meta['created'],json.dumps(meta,allow_nan=False)))
            self.store.log(db,'MODEL_SAVED',{'id':ident,'instrument_key':key,'evidence_status':meta['evidence_status']})
        result['model_id']=ident
        return meta

    def list(self):
        with self.store.db() as db: rows=db.execute('SELECT body FROM models ORDER BY created DESC LIMIT 100').fetchall()
        return [json.loads(r['body']) for r in rows]

    def latest(self,key,strategy):
        with self.store.db() as db:
            r=db.execute('SELECT body FROM models WHERE instrument_key=? AND strategy=? ORDER BY created DESC LIMIT 1',(key,strategy)).fetchone()
        return json.loads(r['body']) if r else None

    def infer(self,key,strategy,dataset):
        meta=self.latest(key,strategy)
        unavailable={'probability':None,'status':'NOT_TRAINED','reasons':['Train and save a model on this instrument and strategy in AI strategy lab.']}
        if not meta: return unavailable
        answer={**unavailable,'model_id':meta['id'],'selected_model':meta['selected_model'],'evidence_status':meta['evidence_status'],
                'test_events':meta['test_events'],'test_trades':meta['test_trades'],'net_pnl':meta['net_pnl'],
                'config':meta['config'],'target_definition':meta['target_definition'],'reasons':[]}
        old=self.store.dataset(meta['dataset_id'])
        current=dataset['bars']
        # A frozen model may only evaluate the same symbol/source lineage. Ensure the
        # complete prior window is unchanged; splits/dividends/revisions force a retrain.
        prefix=[r for r in current if r['t']<=meta['data_end']]
        if fingerprint(prefix)!=old['sha'] or dataset['synthetic']!=meta['synthetic']:
            return {**answer,'status':'DATA_REVISED','reasons':['Training-history prefix changed or is missing. Retrain; do not reuse this model.']}
        if not re.fullmatch(r'[a-f0-9]{32}',meta['id']): raise ValueError('Invalid local artifact identifier.')
        path=self.directory/(meta['id']+'.joblib')
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=meta['artifact_sha256']:
            return {**answer,'status':'ARTIFACT_INVALID','reasons':['Saved artifact missing or hash changed. Retrain.']}
        try:
            import numpy as np
            import sklearn
            import joblib
            from threadpoolctl import threadpool_limits
            if sklearn.__version__!=meta['sklearn_version']:
                return {**answer,'status':'VERSION_MISMATCH','reasons':['scikit-learn version differs from the training version. Retrain.']}
            bundle=joblib.load(path)
            if bundle.get('features')!=FEATURES: raise ValueError('Feature schema changed; retrain.')
            rows=indicators(current,dataset['timeframe']); x=np.array([rows[-1]['features']],dtype=float)
            checks=rule(rows[-1],rows[-2],strategy,len(rows)-1)
            if not checks:
                return {**answer,'status':'NO_SETUP','reasons':['Current completed bar does not satisfy the model training setup. Probability withheld.']}
            def logit(p):
                p=np.clip(p,1e-5,1-1e-5); return np.log(p/(1-p)).reshape(-1,1)
            with threadpool_limits(limits=1):
                scores={name:float(c.predict_proba(logit(m.predict_proba(x)[:,1]))[0,1]) for name,(m,c) in bundle['fitted'].items()}
            selected=bundle['selected_model']
            prob=(bundle['baseline'] if selected=='Prior baseline' else
                  (float(np.mean(list(scores.values()))) if selected=='Calibrated soft-vote' else scores[selected]))
            outside=sum(v<lo or v>hi for v,lo,hi in zip(x[0],bundle['feature_low'],bundle['feature_high']))
        except (ImportError,OSError,ValueError,EOFError,KeyError) as exc:
            return {**answer,'status':'MODEL_UNAVAILABLE','reasons':['Local model could not load: '+str(exc)[:180]]}
        age=(datetime.now(IST)-parse_time(meta['data_end'],meta['timeframe'])).total_seconds()/86400
        maximum_age=30 if meta['timeframe']=='1d' else 7
        reasons=[]
        if meta['synthetic']: reasons.append('Synthetic model: not market evidence.')
        if meta['evidence_status']!='RESEARCH_GATES_PASSED': reasons.append('Saved model failed historical evidence checks.')
        if age>maximum_age or age<0: reasons.append('Model evaluation window is stale or in the future.')
        if outside>=4: reasons.append('At least four features lie outside the training 1st-99th percentile range.')
        answer.update(probability=prob,status='RESEARCH_ESTIMATE' if not reasons else 'UNVALIDATED',reasons=reasons,
            feature_range_violations=outside,model_age_days=max(0,age),members=scores,
            cohort=next((b for b in meta['calibration'] if b['from']<=prob<=b['to']),None),
            definition='Estimated conditional target-hit probability, not net-profit probability or assured return.',
            prospective=current[-1]['t']>meta['data_end'])
        return answer

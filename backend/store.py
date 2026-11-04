"""Local SQLite persistence; transactions protect the single-user paper journal."""
from __future__ import annotations
import json, math, sqlite3, uuid
from pathlib import Path
from datetime import datetime
from .data import IST, fingerprint

class Store:
    def __init__(self,path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as c:
            c.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS datasets(id TEXT PRIMARY KEY,symbol TEXT,timeframe TEXT,source TEXT,synthetic INTEGER,sha TEXT,bars TEXT,warnings TEXT,created TEXT);
            CREATE TABLE IF NOT EXISTS experiments(id TEXT PRIMARY KEY,run_key TEXT UNIQUE,dataset_id TEXT,created TEXT,body TEXT);
            CREATE TABLE IF NOT EXISTS positions(id TEXT PRIMARY KEY,request_id TEXT UNIQUE,dataset_id TEXT,symbol TEXT,quantity INTEGER,entry REAL,stop REAL,target REAL,entry_fee REAL,opened TEXT,closed TEXT,exit REAL,exit_fee REAL,pnl REAL,synthetic INTEGER);
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,at TEXT,action TEXT,detail TEXT);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
            ''')
            for key,val in {'capital':10000.,'risk_pct':.5,'exposure_pct':20.,'total_risk_pct':1.,'daily_loss_pct':1.,'max_positions':2,'cost_bps':40.,'kill_switch':False}.items():
                c.execute('INSERT OR IGNORE INTO settings VALUES (?,?)',(key,json.dumps(val)))
    def db(self):
        c=sqlite3.connect(self.path,timeout=15)
        c.row_factory=sqlite3.Row
        return c
    def now(self): return datetime.now(IST).isoformat()
    def log(self,c,action,detail): c.execute('INSERT INTO audit(at,action,detail) VALUES (?,?,?)',(self.now(),action,json.dumps(detail)))
    def add_dataset(self,symbol,timeframe,source,synthetic,bars,warnings=None):
        sha=fingerprint(bars)
        with self.db() as c:
            row=c.execute('SELECT id FROM datasets WHERE symbol=? AND timeframe=? AND sha=? AND source=?',(symbol,timeframe,sha,source)).fetchone()
            if row:return row['id']
            ident=uuid.uuid4().hex[:16]
            c.execute('INSERT INTO datasets VALUES (?,?,?,?,?,?,?,?,?)',(ident,symbol,timeframe,source,int(synthetic),sha,json.dumps(bars),json.dumps(warnings or []),self.now()))
            self.log(c,'DATASET_IMPORTED',{'id':ident,'symbol':symbol,'sha':sha,'synthetic':synthetic})
            return ident
    def dataset(self,ident):
        with self.db() as c:r=c.execute('SELECT * FROM datasets WHERE id=?',(ident,)).fetchone()
        if not r:raise ValueError('Dataset not found.')
        d=dict(r);d['bars']=json.loads(d['bars']);d['warnings']=json.loads(d['warnings']);d['synthetic']=bool(d['synthetic']);return d
    def datasets(self):
        with self.db() as c:ids=[r['id'] for r in c.execute('SELECT id FROM datasets ORDER BY synthetic DESC,symbol,timeframe')]
        out=[]
        for ident in ids:
            d=self.dataset(ident); bars=d.pop('bars');d.update(count=len(bars),first=bars[0]['t'],last=bars[-1]['t'],close=bars[-1]['c'],change_pct=(bars[-1]['c']/bars[-2]['c']-1)*100,spark=[r['c'] for r in bars[-35:]])
            out.append(d)
        return out
    def settings(self):
        with self.db() as c:return {r['key']:json.loads(r['value']) for r in c.execute('SELECT * FROM settings')}
    def toggle_kill(self,enabled):
        with self.db() as c:
            c.execute('UPDATE settings SET value=? WHERE key="kill_switch"',(json.dumps(bool(enabled)),)); self.log(c,'PAPER_KILL_SWITCH',{'enabled':bool(enabled)})
        return self.settings()
    def experiment_by_key(self,key):
        with self.db() as c:r=c.execute('SELECT body FROM experiments WHERE run_key=?',(key,)).fetchone()
        return json.loads(r['body']) if r else None
    def experiment(self,ident):
        with self.db() as c:r=c.execute('SELECT body FROM experiments WHERE id=?',(ident,)).fetchone()
        if not r:raise ValueError('Experiment not found.')
        return json.loads(r['body'])
    def save_experiment(self,key,result):
        ident=uuid.uuid4().hex[:16];result.update(id=ident,created=self.now())
        with self.db() as c:
            c.execute('INSERT INTO experiments VALUES (?,?,?,?,?)',(ident,key,result['dataset_id'],result['created'],json.dumps(result,allow_nan=False)))
            self.log(c,'EXPERIMENT_COMPLETED',{'id':ident,'data_sha256':result['data_sha256'],'strategy':result['strategy']})
        return result
    def experiments(self):
        with self.db() as c:rs=c.execute('SELECT body FROM experiments ORDER BY created DESC LIMIT 60').fetchall()
        return [{k:r.get(k) for k in ('id','created','symbol','strategy_name','selected_model','evidence_status','synthetic','data_sha256','dataset_id','current_probability')} for r in (json.loads(row['body']) for row in rs)]
    def account(self):
        settings=self.settings()
        with self.db() as c:positions=[dict(r) for r in c.execute('SELECT * FROM positions ORDER BY opened DESC')]
        closed=[p for p in positions if p['closed']];opened=[p for p in positions if not p['closed']]
        pnl=sum(p['pnl'] for p in closed);cash=settings['capital']+pnl-sum(p['quantity']*p['entry']+p['entry_fee'] for p in opened)
        eq=settings['capital']+pnl-sum(p['entry_fee'] for p in opened) # cost basis only, no invented live MTM
        today=self.now()[:10];daily=sum(p['pnl'] for p in closed if p['closed'][:10]==today)
        fees=settings['cost_bps']/20000
        risk=sum(p['quantity']*(p['entry']-p['stop'])+p['entry_fee']+p['stop']*p['quantity']*fees for p in opened)
        return {'settings':settings,'cash':cash,'equity_cost_basis':eq,'realized_pnl':pnl,'daily_realized_pnl':daily,'open_planned_risk':risk,'open_positions':opened,'closed_positions':closed,
                'valuation_note':'Manual paper fills. Equity uses entry cost basis for open positions, NOT live mark-to-market. Stop prices are journal fields, NOT automatic orders.'}
    def open_position(self,request_id,dataset_id,quantity,entry,stop,target):
        if not request_id or len(request_id)>80:raise ValueError('Idempotency key is required.')
        if isinstance(quantity,bool) or not isinstance(quantity,int) or quantity<1:raise ValueError('Quantity must be a positive integer.')
        if not all(math.isfinite(x) and x>0 for x in (entry,stop,target)) or not stop<entry<target:raise ValueError('For a long position require 0 < stop < entry < target.')
        d=self.dataset(dataset_id)
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT * FROM positions WHERE request_id=?',(request_id,)).fetchone()
            if old:
                if (old['dataset_id'],old['quantity'],old['entry'],old['stop'],old['target'])!=(dataset_id,quantity,entry,stop,target):raise ValueError('Idempotency key reused with different order details.')
                return dict(old)
            s={r['key']:json.loads(r['value']) for r in c.execute('SELECT * FROM settings')}
            if s['kill_switch']:raise ValueError('Paper kill switch is on. Closing existing positions is still allowed.')
            rows=[dict(r) for r in c.execute('SELECT * FROM positions')];op=[p for p in rows if not p['closed']];cl=[p for p in rows if p['closed']]
            if len(op)>=s['max_positions']:raise ValueError('Maximum simultaneous paper positions reached.')
            if any(p['dataset_id']==dataset_id for p in op):raise ValueError('An open paper position already exists for this dataset.')
            if op and any(bool(p['synthetic'])!=bool(d['synthetic']) for p in op):raise ValueError('Do not mix synthetic and imported-data open positions in this journal.')
            daily=sum(p['pnl'] for p in cl if p['closed'][:10]==self.now()[:10])
            if daily<=-s['capital']*s['daily_loss_pct']/100:raise ValueError('Daily realized-loss limit reached.')
            realized=sum(p['pnl'] for p in cl);equity=s['capital']+realized
            if equity<s['capital']*.95:raise ValueError('5% cumulative loss review threshold reached; new paper entries blocked.')
            cash=equity-sum(p['quantity']*p['entry']+p['entry_fee'] for p in op)
            fee=entry*quantity*s['cost_bps']/20000
            risk=quantity*(entry-stop)+fee+stop*quantity*s['cost_bps']/20000
            open_risk=sum(p['quantity']*(p['entry']-p['stop'])+p['entry_fee']+p['stop']*p['quantity']*s['cost_bps']/20000 for p in op)
            if risk>equity*s['risk_pct']/100+1e-9:raise ValueError('Planned loss including estimated fees exceeds the per-trade limit.')
            if risk+open_risk>equity*s['total_risk_pct']/100+1e-9:raise ValueError('Combined planned open risk exceeds the account limit.')
            if quantity*entry+fee>min(cash,equity*s['exposure_pct']/100)+1e-9:raise ValueError('Insufficient cash or single-position exposure limit exceeded.')
            ident=uuid.uuid4().hex[:16];now=self.now()
            c.execute('INSERT INTO positions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(ident,request_id,dataset_id,d['symbol'],quantity,entry,stop,target,fee,now,None,None,None,None,int(d['synthetic'])))
            self.log(c,'PAPER_POSITION_OPENED',{'id':ident,'symbol':d['symbol'],'quantity':quantity,'entry':entry,'synthetic':d['synthetic']})
            return dict(c.execute('SELECT * FROM positions WHERE id=?',(ident,)).fetchone())
    def close_position(self,ident,price):
        if not math.isfinite(price) or price<=0:raise ValueError('Exit price must be finite and positive.')
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE');p=c.execute('SELECT * FROM positions WHERE id=?',(ident,)).fetchone()
            if not p:raise ValueError('Position not found.')
            if p['closed']:
                if p['exit']!=price:raise ValueError('Position already closed at a different price.')
                return dict(p)
            cost=json.loads(c.execute('SELECT value FROM settings WHERE key="cost_bps"').fetchone()[0])
            fee=price*p['quantity']*cost/20000;pnl=p['quantity']*(price-p['entry'])-fee-p['entry_fee']
            c.execute('UPDATE positions SET closed=?,exit=?,exit_fee=?,pnl=? WHERE id=?',(self.now(),price,fee,pnl,ident))
            self.log(c,'PAPER_POSITION_CLOSED',{'id':ident,'exit':price,'net_pnl':pnl})
            return dict(c.execute('SELECT * FROM positions WHERE id=?',(ident,)).fetchone())
    def audits(self):
        with self.db() as c:return [dict(r) for r in c.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 100')]

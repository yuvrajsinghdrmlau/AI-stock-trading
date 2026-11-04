"""Persisted local price reminders. Checks are requested by the open browser."""
import uuid
import math
from datetime import datetime, timedelta
from .data import IST
from .market import timestamp


class PriceAlerts:
    def __init__(self,store):
        self.store=store
        with store.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS price_alerts(id TEXT PRIMARY KEY,instrument_key TEXT,condition TEXT,level REAL,status TEXT,created TEXT,expires TEXT,triggered TEXT,price REAL,price_time TEXT)')

    def list(self):
        now=self.store.now()
        with self.store.db() as db:
            db.execute("UPDATE price_alerts SET status='EXPIRED' WHERE status='ACTIVE' AND expires<=?",(now,))
            return [dict(r) for r in db.execute("SELECT * FROM price_alerts ORDER BY CASE WHEN status='ACTIVE' THEN 0 ELSE 1 END,created DESC LIMIT 100")]

    def add(self,key,condition,level):
        self.list()
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            existing=db.execute("SELECT * FROM price_alerts WHERE instrument_key=? AND condition=? AND level=? AND status='ACTIVE'",(key,condition,level)).fetchone()
            if existing:return dict(existing)
            if db.execute("SELECT COUNT(*) FROM price_alerts WHERE status='ACTIVE'").fetchone()[0]>=20:
                raise ValueError('Keep up to 20 active local alerts. Cancel an old alert first.')
            ident=uuid.uuid4().hex[:16];now=datetime.now(IST)
            db.execute('INSERT INTO price_alerts VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (ident,key,condition,level,'ACTIVE',now.isoformat(),(now+timedelta(days=7)).isoformat(),None,None,None))
            self.store.log(db,'PRICE_ALERT_ADDED',{'id':ident,'instrument_key':key,'condition':condition,'level':level})
            return dict(db.execute('SELECT * FROM price_alerts WHERE id=?',(ident,)).fetchone())

    def cancel(self,ident):
        with self.store.db() as db:
            db.execute("UPDATE price_alerts SET status='CANCELLED' WHERE id=? AND status='ACTIVE'",(ident,))
        return self.list()

    def check(self,quotes,now=None):
        now=now or datetime.now(IST);fired=[];unavailable=[]
        for alert in self.list():
            if alert['status']!='ACTIVE':continue
            q=quotes.get(alert['instrument_key']) or {};stamp=timestamp(q.get('price_time') or q.get('feed_time'))
            receipt=timestamp(q.get('received_at'));price=q.get('last_price')
            verified=(q.get('instrument_key')==alert['instrument_key'] and isinstance(price,(int,float))
                      and not isinstance(price,bool) and math.isfinite(price) and price>0 and stamp and receipt
                      and -5<=(now-stamp).total_seconds()<=120 and -5<=(now-receipt).total_seconds()<=30
                      and (q.get('fresh') is True or (q.get('recent') is True and q.get('delayed') is False)))
            if not verified:unavailable.append(alert['instrument_key']);continue
            hit=price>=alert['level'] if alert['condition']=='above' else price<=alert['level']
            if not hit:continue
            with self.store.db() as db:
                updated=db.execute("UPDATE price_alerts SET status='TRIGGERED',triggered=?,price=?,price_time=? WHERE id=? AND status='ACTIVE' AND expires>?",
                                  (now.isoformat(),price,stamp.isoformat(),alert['id'],now.isoformat()))
                if updated.rowcount:
                    item={**alert,'status':'TRIGGERED','triggered':now.isoformat(),'price':price,'price_time':stamp.isoformat()}
                    fired.append(item);self.store.log(db,'PRICE_ALERT_TRIGGERED',item)
        return {'fired':fired,'unavailable_keys':sorted(set(unavailable)),'checked_at':now.isoformat(),
                'alerts':self.list(),'note':'Checks run only when requested or while the open page has auto-check enabled. No orders are sent.'}

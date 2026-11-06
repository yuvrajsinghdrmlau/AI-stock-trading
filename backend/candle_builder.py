"""Read-only, in-memory candles built from authenticated, timestamped feed ticks.

An authorised feed adapter may call ``ingest``. REST snapshots and historical
bars must not be fed into this builder or described as a streaming source.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import math
import threading

from .data import IST
from .market import timestamp


class LiveCandleBuilder:
    def __init__(self, max_completed=15000):
        self.lock=threading.Lock()
        self.rows={}
        self.last={}
        self.max_completed=max_completed

    def ingest(self, symbol, price, volume, source_time, *, received_at=None):
        """Add one real feed event. ``volume`` is this event's traded quantity."""
        now=received_at or datetime.now(IST)
        if not isinstance(now,datetime) or now.tzinfo is None: raise ValueError('Receipt needs a timezone.')
        now=now.astimezone(IST)
        stamp=timestamp(source_time)
        if (not isinstance(symbol,str) or not symbol or not isinstance(price,(int,float))
                or isinstance(price,bool) or not math.isfinite(price) or price<=0
                or not isinstance(volume,(int,float)) or isinstance(volume,bool)
                or not math.isfinite(volume) or volume<0 or not stamp
                or not -5 <= (now-stamp).total_seconds() <= 20):
            raise ValueError('A recent authenticated tick with valid price, quantity and source time is required.')
        minute=stamp.hour*60+stamp.minute
        if stamp.weekday()>4 or not 555<=minute<930:
            raise ValueError('Ticks outside the ordinary NSE continuous session are not used.')
        with self.lock:
            previous=self.last.get(symbol)
            if previous and stamp<=previous: raise ValueError('Out-of-order or duplicate feed tick.')
            self.last[symbol]=stamp
            for width in (1,5,15):
                minute_start=555+((minute-555)//width)*width
                start=stamp.replace(hour=minute_start//60,minute=minute_start%60,second=0,microsecond=0)
                tf=str(width)+'m';key=(symbol,tf)
                bars=self.rows.setdefault(key,[])
                if bars and bars[-1]['t']==start.isoformat():
                    bar=bars[-1];bar['h']=max(bar['h'],price);bar['l']=min(bar['l'],price)
                    bar['c']=price;bar['v']+=volume
                else:
                    bars.append({'t':start.isoformat(),'o':price,'h':price,'l':price,'c':price,'v':volume})
                    if len(bars)>self.max_completed+1: del bars[:len(bars)-self.max_completed-1]

    def status(self,symbol,now=None):
        now=(now or datetime.now(IST)).astimezone(IST)
        with self.lock: stamp=self.last.get(symbol)
        age=(now-stamp).total_seconds() if stamp else None
        return {'status':'Live' if age is not None and -5<=age<=20 else 'Stale' if stamp else 'Unavailable',
                'last_tick_at':stamp.isoformat() if stamp else None}

    def completed(self,symbol,timeframe,now=None):
        if timeframe not in ('1m','5m','15m'): raise ValueError('Candle builder supports 1m, 5m and 15m.')
        now=(now or datetime.now(IST)).astimezone(IST)
        with self.lock: bars=list(self.rows.get((symbol,timeframe),[]))
        duration=timedelta(minutes=int(timeframe[:-1]))
        return [dict(bar) for bar in bars if datetime.fromisoformat(bar['t'])+duration<=now]

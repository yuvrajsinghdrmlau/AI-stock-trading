"""Validated OHLCV input and explicitly synthetic offline fixtures. No pandas/Arrow."""
from __future__ import annotations
import csv, hashlib, io, json, math, random, re
from datetime import datetime, date, time, timedelta, timezone
from typing import Any

IST = timezone(timedelta(hours=5, minutes=30))
MAX_BARS = 15000

def symbol_ok(value: str) -> str:
    value = value.strip().upper()
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9&._-]{0,23}', value):
        raise ValueError('Symbol: use 1-24 letters, digits, &, dot, underscore or hyphen.')
    return value

def parse_time(value: str, timeframe: str) -> datetime:
    s = str(value).strip().replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise ValueError('Use ISO dates/timestamps, e.g. 2026-10-30 or 2026-10-30T09:15:00+05:30.') from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(IST)

def validate_bars(rows: list[dict], timeframe: str, now: datetime | None = None) -> tuple[list[dict], list[str]]:
    if timeframe not in ('1d', '15m'):
        raise ValueError('Supported timeframes are 1d and regular-session 15m.')
    if not 70 <= len(rows) <= MAX_BARS:
        raise ValueError(f'Provide 70 to {MAX_BARS:,} candles. Longer history improves evidence availability.')
    now = (now or datetime.now(IST)).astimezone(IST)
    result, seen, dropped = [], set(), 0
    for k, r in enumerate(rows):
        try:
            dt = parse_time(r['t'], timeframe)
            vals = {key: float(r[key]) for key in ('o','h','l','c','v')}
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f'Invalid row {k+1}: {exc}') from exc
        if not all(math.isfinite(x) for x in vals.values()):
            raise ValueError(f'Row {k+1}: OHLCV must be finite.')
        if min(vals[x] for x in ('o','h','l','c')) <= 0 or vals['v'] < 0:
            raise ValueError(f'Row {k+1}: prices must be positive; volume must not be negative.')
        if vals['h'] < max(vals['o'],vals['c'],vals['l']) or vals['l'] > min(vals['o'],vals['c'],vals['h']):
            raise ValueError(f'Row {k+1}: high and low must enclose open and close.')
        key = dt.date().isoformat() if timeframe == '1d' else dt.isoformat()
        if key in seen:
            raise ValueError(f'Duplicate candle at {key}. Duplicates are not silently discarded.')
        seen.add(key)
        if timeframe == '15m':
            minute = dt.hour * 60 + dt.minute
            if dt.weekday() > 4 or not 555 <= minute <= 915 or (minute-555) % 15 or dt.second or dt.microsecond:
                raise ValueError('15m timestamps must be bar OPEN times, weekdays 09:15 through 15:15 IST. Special sessions are unsupported.')
            complete = dt + timedelta(minutes=15)
        else:
            complete = datetime.combine(dt.date(), time(16,0), IST)
        if complete > now:
            dropped += 1
            continue
        result.append({'t': dt.isoformat(), **vals})
    warnings = []
    if dropped:
        warnings.append(f'{dropped} future/incomplete bars withheld.')
    if result != sorted(result, key=lambda b:b['t']):
        warnings.append('Input reordered chronologically.')
    result.sort(key=lambda b:b['t'])
    if len(result) < 70:
        raise ValueError('Fewer than 70 completed bars remain.')
    if timeframe == '15m':
        gaps = 0
        for a,b in zip(result,result[1:]):
            da,db = parse_time(a['t'],timeframe), parse_time(b['t'],timeframe)
            if da.date()==db.date() and db-da != timedelta(minutes=15):
                gaps += 1
        if gaps:
            warnings.append(f'{gaps} within-session gaps. Backtests reject affected events.')
        warnings.append('Regular-session assumptions only; no exchange holiday/special-session calendar validation.')
    warnings.append('Corporate actions, data rights and vendor accuracy are not independently verified.')
    return result, warnings

def csv_bars(text: str, timeframe: str) -> tuple[list[dict],list[str]]:
    if len(text.encode('utf-8')) > 4_000_000:
        raise ValueError('CSV limit is 4 MB.')
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    if not reader.fieldnames:
        raise ValueError('CSV needs a header.')
    names = {n.strip().lower(): n for n in reader.fieldnames}
    t = next((names[x] for x in ('timestamp','datetime','date','time') if x in names), None)
    if not t or not all(x in names for x in ('open','high','low','close','volume')):
        raise ValueError('Columns required: timestamp,open,high,low,close,volume.')
    rows = []
    for row in reader:
        if len(rows) >= MAX_BARS:
            raise ValueError('Too many candles.')
        rows.append({'t':row[t], **{a:row[names[b]] for a,b in zip(('o','h','l','c','v'),('open','high','low','close','volume'))}})
    return validate_bars(rows,timeframe)

def fingerprint(rows: list[dict]) -> str:
    return hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def demo_bars(seed: int, timeframe: str='1d', count: int=2600) -> list[dict]:
    """Synthetic, reproducible regimes. Not real prices, tickers, or evidence of an edge."""
    rng = random.Random(seed)
    end = date(2026,10,30)
    n_days = count if timeframe=='1d' else math.ceil(count/25)
    dates=[]; d=end
    while len(dates)<n_days:
        if d.weekday()<5: dates.append(d)
        d-=timedelta(days=1)
    dates.reverse()
    stamps=[]
    for d in dates:
        if timeframe=='1d': stamps.append(datetime.combine(d,time(9,15),IST))
        else:
            stamps.extend(datetime.combine(d,time(9,15),IST)+timedelta(minutes=15*k) for k in range(25))
    stamps=stamps[-count:]
    prev = 140 + seed*12
    out=[]
    for i,dt in enumerate(stamps):
        regime = (i//90+seed)%5
        vol = .006 if timeframe=='1d' else .0018
        drift = [0.0008,-0.00065,0.0001,0.00035,-0.00015][regime]
        if timeframe=='15m': drift*=.35
        gap = rng.gauss(0,vol*.24)
        op = prev*math.exp(gap)
        ret = drift + rng.gauss(0,vol) + .0012*math.sin(i/8+seed)*(1 if timeframe=='1d' else .3)
        close = op*math.exp(ret)
        spread = abs(rng.gauss(vol*.55,vol*.2))
        high=max(op,close)*(1+spread)
        low=min(op,close)*(1-spread)
        v=int((350000 if timeframe=='1d' else 48000)*(1+abs(ret)/vol)*rng.uniform(.6,1.5))
        out.append({'t':dt.isoformat(),'o':round(op,4),'h':round(high,4),'l':round(low,4),'c':round(close,4),'v':v})
        prev=close
    return out

def freshness(dataset: dict) -> dict:
    dt=parse_time(dataset['bars'][-1]['t'],dataset['timeframe'])
    age_hours=max(0,(datetime.now(IST)-dt).total_seconds()/3600)
    return {'last_bar':dt.isoformat(),'age_hours':round(age_hours,1),'live':False,
            'label':'SYNTHETIC DEMO' if dataset['synthetic'] else 'HISTORICAL / NOT LIVE'}

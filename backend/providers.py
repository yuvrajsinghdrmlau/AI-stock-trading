"""Read-only Upstox V3 history. No order endpoints, token uploads or arbitrary URLs."""
import json, os, re
from datetime import date, timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from .data import validate_bars

def upstox_history(instrument_key: str, timeframe: str, start: str, end: str):
    token=os.getenv('UPSTOX_ACCESS_TOKEN','').strip()
    if not token:raise ValueError('Set UPSTOX_ACCESS_TOKEN in the server .env, then restart. Never paste credentials into screenshots or public chat.')
    if not re.fullmatch(r'[A-Z_]+\|[A-Za-z0-9 ._-]{1,80}',instrument_key):raise ValueError('Supply the exact instrument_key from the broker instrument master.')
    if timeframe not in ('1d','15m'):raise ValueError('Unsupported timeframe.')
    a,b=date.fromisoformat(start),date.fromisoformat(end)
    if a>b or b>date.today():raise ValueError('Date range must be chronological and not in the future.')
    cap=365*8 if timeframe=='1d' else 365
    if (b-a).days>cap:raise ValueError(f'This local adapter limits history to {cap} calendar days per request.')
    step=timedelta(days=365*8 if timeframe=='1d' else 27)
    unit,interval=('days','1') if timeframe=='1d' else ('minutes','15')
    rows=[];cursor=a
    while cursor<=b:
        stop=min(b,cursor+step)
        url=f'https://api.upstox.com/v3/historical-candle/{quote(instrument_key,safe="")}/{unit}/{interval}/{stop.isoformat()}/{cursor.isoformat()}'
        req=Request(url,headers={'Authorization':'Bearer '+token,'Accept':'application/json','User-Agent':'IndiaQuantResearch/1.0'})
        try:
            with urlopen(req,timeout=20) as response:
                raw=response.read(8_000_001)
                if len(raw)>8_000_000:raise ValueError('Broker response too large.')
                data=json.loads(raw)
        except HTTPError as exc:raise ValueError(f'Broker returned HTTP {exc.code}. Verify token, instrument key and account permissions.') from None
        except (URLError,TimeoutError) as exc:raise ValueError('Broker data request failed or timed out. No live data was substituted.') from None
        if data.get('status')!='success':raise ValueError('Broker did not report a successful data request.')
        for x in data.get('data',{}).get('candles',[]):
            if len(x)<6:raise ValueError('Malformed broker candle.')
            rows.append(dict(zip(('t','o','h','l','c','v'),x[:6])))
        cursor=stop+timedelta(days=1)
    return validate_bars(rows,timeframe)

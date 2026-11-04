"""On-demand India-focused RSS headlines; links and keyword tags, no trade scoring."""
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from urllib.error import URLError
import xml.etree.ElementTree as ET
import re

from .data import IST

TAGS={'Results / earnings':r'earnings|quarterly|results|profit|loss',
      'Corporate action':r'dividend|split|bonus|buyback|demerger|merger',
      'Company announcement':r'order win|contract|acquisition|board|fundrais',
      'Regulatory / legal':r'sebi|rbi|penalty|fraud|court|investigation'}


def parse_headlines(raw,now=None):
    now=now or datetime.now(IST)
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('Unsupported RSS document.')
    try:root=ET.fromstring(raw)
    except ET.ParseError:raise ValueError('News source returned invalid RSS.') from None
    if root.tag!='rss':raise ValueError('News source did not return an RSS feed.')
    out=[];seen=set()
    for item in root.findall('.//item')[:80]:
        title=(item.findtext('title') or '').strip()[:400];link=(item.findtext('link') or '').strip()
        if re.search(r'stock price,? news,? quote and history',title,re.I):continue
        url=urlsplit(link)
        if not title or url.scheme!='https' or url.netloc!='news.google.com' or url.username or url.password:continue
        try:
            dt=parsedate_to_datetime(item.findtext('pubDate') or '')
            if not dt.tzinfo:continue
            dt=dt.astimezone(IST)
        except (ValueError,TypeError,OverflowError):continue
        if not -300<=(now-dt).total_seconds()<=3*86400 or link in seen:continue
        seen.add(link)
        out.append({'title':title,'url':link,'published_at':dt.isoformat(),
                    'publisher':(item.findtext('source') or 'News publisher')[:120],
                    'tags':[label for label,pattern in TAGS.items() if re.search(pattern,title,re.I)]})
    return sorted(out,key=lambda row:row['published_at'],reverse=True)[:12]


def fetch_news(instrument,now=None):
    now=now or datetime.now(IST)
    name=str(instrument.get('name') or instrument['symbol'])[:100]
    query='"'+name.replace('"','')+'" NSE stock when:3d'
    url='https://news.google.com/rss/search?'+urlencode({'q':query,'hl':'en-IN','gl':'IN','ceid':'IN:en'})
    try:
        with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0 IndiaQuant/2.1','Accept':'application/rss+xml'}),timeout=12) as response:
            if not response.geturl().startswith('https://news.google.com/rss/'):raise ValueError('Unexpected news redirect.')
            raw=response.read(1_000_001)
        if len(raw)>1_000_000:raise ValueError('News response too large.')
        items=parse_headlines(raw,now)
    except (URLError,OSError,ET.ParseError) as exc:raise ValueError('Headlines are unavailable. Check the official announcements link or retry later.') from None
    return {'instrument_key':instrument['instrument_key'],'items':items,'fetched_at':now.isoformat(),
            'source':'Google News RSS · Indian search results','query':query,
            'coverage':'Search matches can be incomplete or refer to similarly named companies. No headlines is not an all-clear.',
            'official_url':'https://www.nseindia.com/companies-listing/corporate-filings-announcements'}

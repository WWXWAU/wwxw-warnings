"""Probe 33: the shires' road report pages in detail (map data feeds, tables, PDFs)."""
import sys, re, urllib.parse, urllib.request
sys.path.insert(0, 'rivers'); import rivers as RV
BUA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36', 'Accept': 'text/html,application/xhtml+xml,*/*'}
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=BUA), timeout=60).read().decode('utf-8', 'replace')
URLS = ['https://www.swek.wa.gov.au/roadreport/', 'https://eastpilbara.wa.gov.au/roadreport/', 'https://www.sdwk.wa.gov.au/services/roads/road-conditions.aspx',
        'https://www.ashburton.wa.gov.au/services/emergency-safety/road-report.aspx', 'https://www.hallscreek.wa.gov.au/services/road-conditions',
        'https://www.broome.wa.gov.au/Shire-Services/Infrastructure/Road-Condition-Report-and-Planned-Maintenance']
for u in URLS:
    try: t = get(u)
    except Exception as e: print('\n##', u, 'ERR', str(e)[:100]); continue
    print('\n##', u, len(t))
    srcs = re.findall(r'(?:src|href)="([^"]+)"', t)
    print(' scripts/data:', [s for s in srcs if re.search(r'(?i)roadreport|json|api|\.pdf|map|arcgis|road', s) and not re.search(r'(?i)facebook|twitter|favicon|\.css|\.png|\.jpg|\.svg', s)][:30])
    print(' inline urls:', sorted(set(re.findall(r'["\'](/?[\w/.\-]*(?:api|json|ajax|roadreport|getroads|data)[\w/.\-?=&]*)["\']', t)))[:30])
    body = RV.clean(re.sub(r'(?is)<(script|style|nav|header|footer).*?</\1>', ' ', t))
    for kw in ('Closed', 'closed', 'Open', 'Updated', 'updated'):
        i = body.find(kw)
        if i >= 0: print(' text@%s:' % kw, body[max(0, i - 300):i + 1500]); break
    js = re.findall(r'(?is)<script[^>]*>(.*?)</script>', t)
    for s in js:
        if re.search(r'(?i)road|marker|lat', s) and len(s) > 200: print(' js:', re.sub(r'\s+', ' ', s)[:1500]); break

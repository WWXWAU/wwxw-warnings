"""Probe 14: which DWER gauges publish discharge (te4) and stage (te2) tables; catchment sources."""
import re, sys, json, concurrent.futures as cf, urllib.request
sys.path.insert(0, 'rivers'); import rivers as RV
G = RV.read_dwer()
P = 'https://kumina.water.wa.gov.au/waterinformation/wir/reports/publish/%s/%s'
def one(g):
    out = {}
    for p in ('te4.htm', 'te2.htm'):
        try: c = RV.get(P % (g['id'], p), 40, 1); out[p] = c
        except Exception as e: out[p] = None
    return g, out
n4 = n2 = 0; ex = None
with cf.ThreadPoolExecutor(8) as X:
    for g, o in X.map(one, G):
        if o['te4']: n4 += 1; ex = ex or (g, o['te4'])
        if o['te2']: n2 += 1
print('gauges', len(G), 'with te4', n4, 'with te2', n2)
g, c = ex; pre = re.search(r'(?s)<pre>(.*?)</pre>', c).group(1); print(g['id'], re.sub(r'<[^>]+>', '', pre)[:3000])
def J(u):
    try: return json.loads(RV.get(u, 90, 1))
    except Exception as e: print('FAILED', u, e); return {}
for u in ['https://public-services.slip.wa.gov.au/public/rest/services/SLIP_Public_Services/Water/MapServer?f=json',
          'https://services.slip.wa.gov.au/public/rest/services/SLIP_Public_Services/Water/MapServer?f=json']:
    j = J(u); print(u, [(l['id'], l['name']) for l in j.get('layers', [])][:80])
for u in ['https://data.hydrosheds.org/file/HydroBASINS/standard/hybas_au_lev12_v1c.zip']:
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, method='HEAD', headers=RV.UA), timeout=60); print(u, r.status, r.headers.get('Content-Length'))
    except Exception as e: print('HEAD fail', u, e)

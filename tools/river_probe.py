"""Probe 6: why some Bureau gauge pages give no readings; Water Data Online names for them."""
import re, sys, json, urllib.parse
sys.path.insert(0, 'rivers'); import rivers as RV
t = RV.ftp_get('IDW60402.html')
for r in re.findall(r'<tr>(.*?)</tr>', t, re.S):
    if 'Eradu' in r or 'Mingenew' in r: print('ROW:', RV.clean(r)[:300], re.findall(r'href="([^"]+)"', r))
for prod, bid in [('IDW62402', None)]:
    pass
m = re.search(r'(IDW624\d\d)\.(\d+)\.tbl[^"]*"[^<]*</a>[^<]*', t)
ids = re.findall(r'(IDW624\d\d)\.(\d+)\.tbl', t)
for prod, bid in ids:
    if bid in t[t.find('Eradu') - 2000:t.find('Eradu') + 2000]:
        u = 'http://www.bom.gov.au/fwo/%s/%s.%s.tbl.shtml' % (prod, prod, bid); x = RV.get(u)
        i = x.find('Data from'); print(u, len(x)); print(x[i - 200:i + 2500]); break
K = RV.KIWIS
for term in ['*Eradu*', '*Mingenew*', '*Barrack*', '*Doyle*', '*Donnybrook*', '*Cross Farm*', '*Rosa*']:
    q = K + urllib.parse.urlencode({'request': 'getStationList', 'station_name': term, 'returnfields': 'station_name,station_no,station_latitude,station_longitude'})
    print(term, RV.get(q)[:400])

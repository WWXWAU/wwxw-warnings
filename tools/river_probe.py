"""Probe 22: what the Bureau's WA rain products hold."""
import ftplib, io, re, sys, json, urllib.parse
sys.path.insert(0, 'rivers'); import rivers as RV
f = ftplib.FTP('ftp.bom.gov.au', timeout=60); f.login()
def raw(p):
    b = io.BytesIO(); f.retrbinary('RETR /anon/gen/fwo/' + p, b.write); return b.getvalue().decode('latin-1')
def txt(t): return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' | ', re.sub(r'(?s)<(style|script)[^>]*>.*?</\1>', '', t)))
names = sorted(n.split('/')[-1] for n in f.nlst('/anon/gen/fwo'))
for pat in ('IDW65900_', 'IDW65901_', 'IDW65902_', 'IDW65910_'):
    L = [n for n in names if n.startswith(pat) and n.endswith('.hcs')]
    if not L: continue
    t = raw(L[-1]); lines = t.splitlines()
    print('\n==', L[-1], len(lines), 'lines'); print('\n'.join(lines[:12])); print('...'); print('\n'.join(lines[-4:]))
for p in ('IDW60201.html', 'IDW60215.html', 'IDW62305.html', 'IDW62320.html', 'IDW60028.html', 'IDW60042.txt', 'IDW60115.html', 'IDW62412.html', 'IDW60015.txt'):
    try: t = raw(p)
    except Exception as e: print('\n==', p, 'FAIL', e); continue
    s = txt(t); print('\n==', p, len(t)); print(s[:1500])
K = 'http://www.bom.gov.au/waterdata/services?service=kisters&type=queryServices&datasource=0&format=json&'
q = K + urllib.parse.urlencode({'request': 'getTimeseriesList', 'parametertype_name': 'Rainfall', 'ts_name': 'Received.Provisional.AsStored.1', 'returnfields': 'station_no,station_name,station_latitude,station_longitude,coverage'})
j = json.loads(RV.get(q, 240, 2))
wa = [r for r in j[1:] if r[2] and r[3] and -36 < float(r[2]) < -13 and 112 < float(r[3]) < 129.1]
rec = [r for r in wa if r[5] and r[5][:10] >= '2026-11-09']
import collections
print('\nWDO rainfall (live) in WA:', len(wa), 'reporting since 9 Nov:', len(rec))
print('station number styles:', collections.Counter(re.sub(r'\d', '9', r[0])[:6] for r in rec).most_common(10))
print('sample:', rec[:8])

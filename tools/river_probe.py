"""Probe 21: Bureau rainfall products for WA — FTP listings and titles, and Water Data Online rainfall stations."""
import ftplib, io, re, sys, json, urllib.request, urllib.parse
sys.path.insert(0, 'rivers'); import rivers as RV
f = ftplib.FTP('ftp.bom.gov.au', timeout=60); f.login()
for d in ('/anon/gen/fwo', '/anon/gen/clim_data'):
    try:
        names = f.nlst(d)
    except Exception as e: print('list fail', d, e); continue
    W = sorted(n.split('/')[-1] for n in names if re.search(r'IDW', n))
    print(d, len(names), 'IDW files:', len(W)); print(' '.join(W)[:6000])
def grab(path, n=1200):
    b = io.BytesIO()
    try: f.retrbinary('RETR ' + path, b.write)
    except Exception as e: return 'FAIL %s' % e
    t = b.getvalue().decode('latin-1')
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', t))[:n]
for p in ['IDW60150.html', 'IDW60151.html', 'IDW60152.html', 'IDW60153.html', 'IDW60160.html', 'IDW60300.html', 'IDW60301.html', 'IDW60920.xml', 'IDW60910.xml', 'IDW60201.html', 'IDW13010.txt', 'IDW60140.html', 'IDW60170.html', 'IDW10500.html']:
    print('\n==', p, grab('/anon/gen/fwo/' + p, 700))
# Water Data Online: rainfall stations in WA
K = 'http://www.bom.gov.au/waterdata/services?service=kisters&type=queryServices&datasource=0&format=json&'
try:
    q = K + urllib.parse.urlencode({'request': 'getTimeseriesList', 'parametertype_name': 'Rainfall', 'ts_name': 'DMQaQc.Merged.DailyTotal.09HR', 'returnfields': 'station_no,station_name,station_latitude,station_longitude,coverage', 'station_latitude': '', 'bbox': '112,-36,129.1,-13'})
    j = json.loads(RV.get(q, 180, 2))
    print('\nWDO rainfall daily series (bbox WA):', len(j) - 1, j[1:6])
    q = K + urllib.parse.urlencode({'request': 'getTimeseriesList', 'parametertype_name': 'Rainfall', 'ts_name': 'Received.Provisional.AsStored.1', 'returnfields': 'station_no,station_name,station_latitude,station_longitude,coverage', 'bbox': '112,-36,129.1,-13'})
    j = json.loads(RV.get(q, 180, 2))
    print('WDO rainfall live series (bbox WA):', len(j) - 1, j[1:6])
    recent = [r for r in j[1:] if r[-1] and r[-1][:10] >= '2026-11-09']
    print('  reporting since 9 Nov:', len(recent))
except Exception as e: print('WDO fail', e)

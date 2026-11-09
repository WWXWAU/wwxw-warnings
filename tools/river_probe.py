"""Probe 3: BoM flood classifications for WA river gauges."""
import re, urllib.request, ftplib, io
UA = {'User-Agent': 'Mozilla/5.0 (WWXW river probe)'}
def get(u):
    try: return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read().decode('utf-8', 'replace')
    except Exception as e: print('FAILED', u, e); return ''
f = ftplib.FTP('ftp.bom.gov.au', timeout=60); f.login(); f.cwd('/anon/gen/fwo')
for n in ['IDW60200.html', 'IDW60215.html', 'IDW60400.html', 'IDW60920.xml']:
    bio = io.BytesIO(); f.retrbinary('RETR ' + n, bio.write); t = bio.getvalue().decode('utf-8', 'replace')
    print('\n=== FTP', n, len(t)); print(t[:3000])
for u in ['http://www.bom.gov.au/wa/flood/swan_avon.shtml', 'http://www.bom.gov.au/wa/flood/rain_river.shtml', 'http://www.bom.gov.au/wa/flood/kimberley.shtml']:
    t = get(u)
    if not t: continue
    print('\n=== ', u); print('links:', sorted(set(re.findall(r'href="([^"]*)"', t)))[:120])
    i = t.find('<table'); print(re.sub(r'\s+', ' ', t[i:i + 4000]))

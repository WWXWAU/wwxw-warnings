"""Probe 4: a BoM river-height station table/plot page (flood class levels?) and the full IDW60404 rows."""
import re, urllib.request, ftplib, io
UA = {'User-Agent': 'Mozilla/5.0 (WWXW river probe)'}
def get(u):
    try: return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read().decode('utf-8', 'replace')
    except Exception as e: print('FAILED', u, e); return ''
tx = lambda t: re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', t.replace('&nbsp;', ' ')))
for u in ['http://www.bom.gov.au/fwo/IDW62404/IDW62404.509376.tbl.shtml', 'http://www.bom.gov.au/fwo/IDW62404/IDW62404.509376.plt.shtml', 'http://www.bom.gov.au/fwo/IDW62400/IDW62400.502024.tbl.shtml']:
    t = get(u); i = t.find('<div id="content'); print('\n===', u, len(t)); print(tx(t[i:i + 9000])[:2500])
    print([x for x in re.findall(r'(?:src|href)="([^"]+)"', t) if 'IDW6' in x][:10])
f = ftplib.FTP('ftp.bom.gov.au', timeout=60); f.login(); f.cwd('/anon/gen/fwo')
for n in ['IDW60404.html']:
    bio = io.BytesIO(); f.retrbinary('RETR ' + n, bio.write); t = bio.getvalue().decode('utf-8', 'replace')
    rows = re.findall(r'<tr>(.*?)</tr>', t, re.S)
    for r in rows[:40]: print([tx(c).strip() for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, re.S)], re.findall(r'IDW624\d\d\.(\d+)', r)[:1])

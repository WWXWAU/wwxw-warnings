"""Probe river-level sources for WA (run on GitHub: the sandbox can't reach them)."""
import re, urllib.request, ftplib, io
UA = {'User-Agent': 'Mozilla/5.0 (WWXW river probe)'}
def get(u, n=1500):
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60); b = r.read()
        t = b.decode('utf-8', 'replace'); print('\n=== %s  [%s, %d bytes]' % (u, r.status, len(b)))
        return t
    except Exception as e:
        print('\n=== %s  FAILED %s' % (u, e)); return ''
B = 'https://kumina.water.wa.gov.au/waterinformation'
for u in [B + '/telem/', B + '/telem/index.cfm', B + '/telem/river.cfm', B + '/telem/level.cfm', B + '/telem/stage.cfm', B + '/telem/flow.cfm', B + '/telem/rain.cfm']:
    t = get(u)
    if t:
        print('links:', sorted(set(re.findall(r'href="([^"]+)"', t)))[:60])
        txt = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', t)); print('text:', txt[:1500])
# BoM latest river heights pages (flood warning network)
for u in ['http://www.bom.gov.au/wa/flood/', 'http://www.bom.gov.au/cgi-bin/wrap_fwo.pl?IDW60140.html', 'http://www.bom.gov.au/fwo/IDW60140.html', 'http://www.bom.gov.au/fwo/IDW60150.html']:
    t = get(u)
    if t: txt = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', t)); print('text:', txt[:2500]); print('links:', sorted(set(re.findall(r'href="([^"]*(?:IDW6|fwo|flood)[^"]*)"', t)))[:80])
# BoM FTP: river-height products
try:
    f = ftplib.FTP('ftp.bom.gov.au', timeout=60); f.login(); f.cwd('/anon/gen/fwo')
    names = f.nlst(); w = [n for n in names if n.startswith('IDW6') or n.startswith('IDW3')]
    print('\n=== FTP fwo IDW6*/IDW3*:', w[:200])
    for n in [x for x in w if x.endswith('.xml') or x.endswith('.txt') or x.endswith('.html')][:6]:
        bio = io.BytesIO(); f.retrbinary('RETR ' + n, bio.write); print('\n--- %s (%d bytes)\n%s' % (n, len(bio.getvalue()), bio.getvalue()[:1200].decode('utf-8', 'replace')))
except Exception as e:
    print('FTP failed', e)
# BoM Water Data Online (Kisters KiWIS)
K = 'http://www.bom.gov.au/waterdata/services?service=kisters&type=queryServices&datasource=0&format=json'
t = get(K + '&request=getStationList&parametertype_name=Water%20Course%20Level&station_no=616011&returnfields=station_name,station_no,station_latitude,station_longitude', 1500); print(t[:1500])
t = get(K + '&request=getTimeseriesList&station_no=616011&returnfields=ts_id,ts_name,parametertype_name,coverage', 1500); print(t[:2500])

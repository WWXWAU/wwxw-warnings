"""Probe 5: flood class thresholds on a BoM station page; flow (discharge) sources."""
import re, json, urllib.request, urllib.parse
UA = {'User-Agent': 'Mozilla/5.0 (WWXW river probe)'}
def get(u, t=90):
    try: return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=t).read().decode('utf-8', 'replace')
    except Exception as e: print('FAILED', u, e); return ''
tx = lambda t: re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', t.replace('&nbsp;', ' ')))
t = get('http://www.bom.gov.au/fwo/IDW62404/IDW62404.509438.tbl.shtml')
for m in re.finditer(r'(?i)(minor|moderate|major|flood class)', t):
    print('...', tx(t[max(0, m.start() - 300):m.end() + 300])[:400]); 
print('TBL head:', tx(t)[:1500])
t = get('http://www.bom.gov.au/fwo/IDW62404/IDW62404.509438.plt.shtml')
for m in list(re.finditer(r'(?i)(minor|moderate|major)', t))[:6]: print('PLT...', tx(t[max(0, m.start() - 300):m.end() + 300])[:400])
# flow: DWER other parameters page, and a gauge's tel page text
o = get('https://kumina.water.wa.gov.au/waterinformation/telem/ops.cfm'); print('OPS:', tx(o)[:2500])
s = get('https://kumina.water.wa.gov.au/waterinformation/wir/reports/publish/616011/616011.htm'); print('SITE:', tx(s)[:2000]); print([x for x in re.findall(r'(?:src|href)="([^"]+)"', s)][:40])
# Water Data Online discharge for all DWER gauges: which have it, and how far behind it is
K = 'http://www.bom.gov.au/waterdata/services?service=kisters&type=queryServices&datasource=0&format=json&'
ids = sorted(set(re.findall(r'/publish/(\d{6})/', get('https://kumina.water.wa.gov.au/waterinformation/telem/stage.cfm'))))
q = K + urllib.parse.urlencode({'request': 'getTimeseriesList', 'station_no': ','.join(ids), 'parametertype_name': 'Water Course Discharge', 'returnfields': 'station_no,ts_id,ts_name,coverage'})
j = json.loads(get(q, 180)); names = {}
for r in j[1:]: names[r[2]] = names.get(r[2], 0) + 1
print('DISCHARGE series:', len(j) - 1, names)
recv = [r for r in j[1:] if r[2] == 'Received.Provisional.AsStored.1']; print('received:', len(recv), recv[:5])
if recv:
    q = K + urllib.parse.urlencode({'request': 'getTimeseriesValues', 'ts_id': recv[0][1], 'period': 'P2D', 'returnfields': 'Timestamp,Value'})
    print(get(q)[:800])

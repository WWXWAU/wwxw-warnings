"""Probe 2: the DWER stage table's raw rows, explanatory notes, and Water Data Online level history."""
import re, json, urllib.request, urllib.parse
UA = {'User-Agent': 'Mozilla/5.0 (WWXW river probe)'}
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=90).read().decode('utf-8', 'replace')
B = 'https://kumina.water.wa.gov.au/waterinformation'
t = get(B + '/telem/stage.cfm')
i = t.find('601001'); print('RAW ROWS:\n', t[i - 1500:i + 3500])
rows = re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S); print('rows:', len(rows))
cells = lambda r: [re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', c)).replace('&nbsp;', ' ').strip() for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, re.S)]
for r in rows[:6] + rows[100:104] + rows[-4:]: print(cells(r))
ids = sorted(set(re.findall(r'/publish/(\d{6})/', t))); print('sites:', len(ids), ids[:10])
try:
    e = get(B + '/telem/explanatory.cfm'); print('EXPLANATORY:', re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', e))[:3000])
except Exception as ex: print('expl failed', ex)
try:
    s = get(B + '/wir/reports/publish/616011/tel.htm'); print('TEL PAGE:', re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', s))[:1500]); print(sorted(set(re.findall(r'(?:src|href)="([^"]+)"', s)))[:30])
except Exception as ex: print('tel failed', ex)
K = 'http://www.bom.gov.au/waterdata/services?service=kisters&type=queryServices&datasource=0&format=json&'
q = K + urllib.parse.urlencode({'request': 'getStationList', 'station_no': ','.join(ids[:400]), 'returnfields': 'station_name,station_no,station_latitude,station_longitude'})
try:
    j = json.loads(get(q)); print('KiWIS stations found:', len(j) - 1, j[1:4])
except Exception as ex: print('kiwis list failed', ex)
q = K + urllib.parse.urlencode({'request': 'getTimeseriesList', 'station_no': '616011', 'parametertype_name': 'Water Course Level', 'returnfields': 'ts_id,ts_name,coverage'})
j = json.loads(get(q)); print('LEVEL TS:', j)
for row in j[1:]:
    if 'AsStored' in row[1] or 'Provisional' in row[1]:
        q = K + urllib.parse.urlencode({'request': 'getTimeseriesValues', 'ts_id': row[0], 'period': 'P3D', 'returnfields': 'Timestamp,Value'})
        try: v = json.loads(get(q)); print(row[1], str(v)[:600])
        except Exception as ex: print(row[1], 'failed', ex)

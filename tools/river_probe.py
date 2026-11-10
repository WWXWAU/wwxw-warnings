"""Probe 20: Orion readings for one approved sensor of each kind (values only)."""
import json, os, sys, urllib.request, urllib.parse, datetime as dt
K = os.environ['ORION_API_KEY'].strip(); B = 'https://api.oriondata.io/api/'
def J(path, tok=None):
    h = {'User-Agent': 'Mozilla/5.0 (West WX Watchers)'}
    if tok: h['Authorization'] = 'Bearer ' + tok
    return json.loads(urllib.request.urlopen(urllib.request.Request(B + path, headers=h), timeout=120).read())
tok = J('token?' + urllib.parse.urlencode({'apiKey': K}))['token']
S = json.load(open('rivers/orion-sites.json'))
now = dt.datetime.utcnow() + dt.timedelta(hours=8)
done = set()
for s in S:
    for k, (kind, sid, u) in s['sensors'].items():
        if k in done and k != 'rain': continue
        if k == 'rain' and len([x for x in done if x.startswith('rain')]) >= 3: continue
        done.add(k if k != 'rain' else 'rain%d' % len(done))
        p = {'version': '1.3', 'startDate': (now - dt.timedelta(hours=26)).strftime('%Y-%m-%dT%H:%M:%S'), 'endDate': now.strftime('%Y-%m-%dT%H:%M:%S'), 'offset': 0}
        p['sensorIds' if kind == 's' else 'softSensorIds'] = sid
        v = J('SensorData?' + urllib.parse.urlencode(p), tok)
        vals = [x['sensorValue'] for x in v]
        print(k, u, 'n', len(v), 'first', v[0]['readingDate'] if v else None, 'last', v[-1]['readingDate'] if v else None,
              'min', min(vals) if vals else None, 'max', max(vals) if vals else None, 'sample', vals[:6], vals[-6:], 'sum', round(sum(vals), 1) if vals else None)

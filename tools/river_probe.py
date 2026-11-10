"""Probe 17: Orion Data API (EWS) — what the account holds. Counts only: the repo's logs are public."""
import json, os, sys, collections, urllib.request, urllib.parse, datetime as dt
K = os.environ.get('ORION_API_KEY', '').strip()
if not K: sys.exit('No ORION_API_KEY secret')
B = 'https://api.oriondata.io/api/'
def J(path, tok=None):
    h = {'User-Agent': 'Mozilla/5.0 (West WX Watchers)'}
    if tok: h['Authorization'] = 'Bearer ' + tok
    return json.loads(urllib.request.urlopen(urllib.request.Request(B + path, headers=h), timeout=90).read())
try: tok = J('token?' + urllib.parse.urlencode({'apiKey': K}))['token']
except Exception as e: sys.exit('Token failed: %s' % e)
print('token ok')
D = J('userDevices', tok)
print('devices', len(D), 'status', collections.Counter(d.get('status') for d in D))
print('with position', sum(1 for d in D if d.get('latitude')), 'in WA (lng<129)', sum(1 for d in D if d.get('latitude') and d.get('longitude') and d['longitude'] < 129 and d['latitude'] < -13 and d['longitude'] > 112))
st = collections.Counter((s.get('sensorType') or '').strip() + ' [' + (s.get('uom') or '') + ']' for d in D for s in d.get('sensors', []))
ss = collections.Counter((s.get('sensorType') or '').strip() + ' [' + (s.get('uom') or '') + ']' for d in D for s in d.get('softSensors', []))
print('sensor types', st.most_common(30)); print('soft sensor types', ss.most_common(30))
recent = sum(1 for d in D if d.get('lastUpload') and d['lastUpload'] >= (dt.datetime.utcnow() - dt.timedelta(hours=6)).isoformat())
print('uploaded in last 6 h', recent)
# one water-level sensor: how often it reads, value range
wl = [(d, s) for d in D for s in d.get('sensors', []) if 'level' in (s.get('sensorType') or '').lower()]
if wl:
    d, s = wl[0]; now = dt.datetime.utcnow() + dt.timedelta(hours=8)
    v = J('SensorData?' + urllib.parse.urlencode({'version': '1.3', 'startDate': (now - dt.timedelta(hours=6)).strftime('%Y-%m-%dT%H:%M:%S'), 'endDate': now.strftime('%Y-%m-%dT%H:%M:%S'), 'offset': 0, 'sensorIds': s['sensorId']}), tok)
    print('sample level sensor: readings in 6 h', len(v), 'interval', (v[1]['readingDate'], v[0]['readingDate']) if len(v) > 1 else None)

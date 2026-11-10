"""Probe 19: Orion (EWS) WA devices with rain, weather or water-level sensors, for a private review.
The list is encrypted with tools/review-key.pub (only the private key holder can read it); the log shows counts only."""
import json, os, sys, collections, urllib.request, urllib.parse, subprocess
K = os.environ.get('ORION_API_KEY', '').strip()
if not K: sys.exit('No ORION_API_KEY secret')
B = 'https://api.oriondata.io/api/'
def J(path, tok=None):
    h = {'User-Agent': 'Mozilla/5.0 (West WX Watchers)'}
    if tok: h['Authorization'] = 'Bearer ' + tok
    return json.loads(urllib.request.urlopen(urllib.request.Request(B + path, headers=h), timeout=120).read())
tok = J('token?' + urllib.parse.urlencode({'apiKey': K}))['token']
D = J('userDevices?version=1.3', tok)
want = lambda t: any(w in (t or '').lower() for w in ('rain', 'water level', 'air temp', 'wind', 'humid', 'stage', 'mahd', 'flow'))
out = []
for d in D:
    la, lo = d.get('latitude'), d.get('longitude')
    if la is None or lo is None or not (-36 < la < -13 and 112 < lo < 129.1): continue
    S = [{'id': s.get('sensorId'), 't': (s.get('sensorType') or '').strip(), 'u': s.get('uom'), 'n': s.get('customName')} for s in d.get('sensors', []) if want(s.get('sensorType'))]
    SS = [{'id': s.get('softSensorId'), 't': (s.get('sensorType') or '').strip(), 'u': s.get('uom'), 'n': s.get('customName')} for s in d.get('softSensors', []) if want(s.get('sensorType'))]
    if not S and not SS: continue
    out.append({'id': d.get('deviceId'), 'name': d.get('deviceName'), 'ref': d.get('reference'), 'lat': la, 'lng': lo, 'status': d.get('status'), 'last': d.get('lastUpload'), 's': S, 'ss': SS})
print('WA devices with rain/weather/level sensors:', len(out), collections.Counter(o['status'] for o in out))
os.makedirs('review', exist_ok=True)
open('review/list.json', 'w').write(json.dumps(out))
subprocess.run('openssl rand -hex 32 > review/k && openssl enc -aes-256-cbc -pbkdf2 -salt -in review/list.json -out review/list.enc -pass file:review/k '
               '&& openssl pkeyutl -encrypt -pubin -inkey tools/review-key.pub -in review/k -out review/k.enc && rm review/k review/list.json', shell=True, check=True)
print('encrypted bytes', os.path.getsize('review/list.enc'))

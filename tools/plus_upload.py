"""
WWXW Plus: keep the full farm forecast for members (run by ripper.yml after the forecast is made).

1. Sends out/ag.json and out/ag-fine.json (gzip, base64) to the Plus server (the rainfall web app, Plus.gs),
   with the PLUS_UPLOAD_KEY secret. No secret: nothing is sent.
2. If Plus is switched on (the site's app-config.json "plusLock": true), trims the public copies to today only,
   so the full week is only on the Plus server.
"""
import base64, gzip, json, os, sys, urllib.request

API = 'https://script.google.com/macros/s/AKfycbyoxJApPxqA86gVVXen0USujHH7OAz3_nEwonfV-8j1G4pWAyKU7aIBRCRxsYZ5DcdJ/exec'
out = sys.argv[1] if len(sys.argv) > 1 else 'out'
key = os.environ.get('PLUS_UPLOAD_KEY', '')

for f in ('ag', 'ag-fine'):
    p = os.path.join(out, f + '.json')
    if not os.path.exists(p):
        continue
    if key:
        b64 = base64.b64encode(gzip.compress(open(p, 'rb').read())).decode()
        req = urllib.request.Request(API, data=json.dumps({'plusupload': key, 'f': f, 'b64': b64}).encode(),
                                     headers={'Content-Type': 'text/plain;charset=utf-8'})
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=120).read())
            print('Plus copy of %s: %s' % (f, 'kept (%d KB)' % (len(b64) // 1024) if r.get('ok') else 'refused (check PLUS_UPLOAD_KEY)'))
        except Exception as e:  # noqa: BLE001
            print('Plus copy of %s failed: %s' % (f, e))
    else:
        print('No PLUS_UPLOAD_KEY secret: %s not kept for Plus' % f)

try:
    cfg = json.loads(urllib.request.urlopen('https://westweatherwatchers.com/app-config.json', timeout=30).read())
except Exception as e:  # noqa: BLE001
    print('app-config.json not read (%s): public farm data left as it is' % e); cfg = {}
if cfg.get('plusLock'):
    for f in ('ag', 'ag-fine'):
        p = os.path.join(out, f + '.json')
        if not os.path.exists(p):
            continue
        A = json.load(open(p))
        A['days'] = A.get('days', [])[:1]
        A['plus'] = 'The other days are for WWXW Plus members.'
        json.dump(A, open(p, 'w'), separators=(',', ':'))
        print('Plus is on: public %s trimmed to today' % f)

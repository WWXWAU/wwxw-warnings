"""Kimberley rain wrap data: the Rainfall page's own gauges (DPIRD, BoM, DWER) with since-9am totals and 1/3-hour peaks."""
import json, re, sys, urllib.request, datetime as dt
URL = 'https://script.google.com/macros/s/AKfycbyoxJApPxqA86gVVXen0USujHH7OAz3_nEwonfV-8j1G4pWAyKU7aIBRCRxsYZ5DcdJ/exec'
t = urllib.request.urlopen(urllib.request.Request(URL, headers={'User-Agent': 'Mozilla/5.0'}), timeout=120).read().decode('utf-8', 'replace')
print('page bytes', len(t))
i = t.find('m60_daily'); print('m60_daily at', i)
# the points: find JSON objects holding m60_daily
objs = []
for m in re.finditer(r'\{[^{}]*?"m60_daily"[^{}]*\}', t.replace('\\"', '"')):
    try: objs.append(json.loads(m.group(0)))
    except Exception: pass
print('points parsed', len(objs))
if objs: print('fields', sorted(objs[0].keys()))
if i >= 0 and not objs: print(t[i - 1500:i + 500])
K = [o for o in objs if (o.get('lat') or 0) > -19.6 and (o.get('lng') or o.get('lon') or 0) > 121.3]
print('kimberley', len(K))
f = lambda v: -1 if v is None else v
for k in ['daily', 'm60_daily', 'm180_daily']:
    print('\nTOP', k)
    for o in sorted(K, key=lambda o: -f(o.get(k)))[:15]:
        t60 = o.get('m60t_daily'); t60 = dt.datetime.fromtimestamp(t60 / 1000, dt.timezone(dt.timedelta(hours=8))).strftime('%H:%M') if t60 else ''
        print('  %-35s %-6s daily %s  1h %s (%s)  3h %s  12h %s 24h %s' % (o.get('name'), o.get('source') or o.get('src'), o.get('daily'), o.get('m60_daily'), t60, o.get('m180_daily'), o.get('h12'), o.get('h24')))

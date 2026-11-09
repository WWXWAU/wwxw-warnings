"""Kimberley rain wrap data: the Rainfall page's own gauges (DPIRD, BoM, DWER) with since-9am totals and 1/3-hour peaks."""
import json, re, sys, urllib.request, datetime as dt
URL = 'https://script.google.com/macros/s/AKfycbyoxJApPxqA86gVVXen0USujHH7OAz3_nEwonfV-8j1G4pWAyKU7aIBRCRxsYZ5DcdJ/exec'
t = urllib.request.urlopen(urllib.request.Request(URL, headers={'User-Agent': 'Mozilla/5.0'}), timeout=120).read().decode('utf-8', 'replace')
print('page bytes', len(t))
for _ in range(3):   # the page arrives as an escaped JavaScript string inside Google's wrapper: undo the escaping
    t = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), t)
    t = t.replace('\\\\', '\\').replace('\\/', '/').replace('\\"', '"')
i = t.find('m60_daily'); print('m60_daily at', i); print(t[i - 700:i + 300])
# the points: find JSON objects holding m60_daily
objs = []
for m in re.finditer(r'\{[^{}]*?"m60_daily"[^{}]*\}', t):
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

# Vaisala (Xweather) 24-hour lightning: strike counts within 100 km of points 2 degrees apart (the Rainfall page's LT24)
m = re.search(r'var LT24=(\{.*?\});', t)
if m:
    L = json.loads(m.group(1)); tz = dt.timezone(dt.timedelta(hours=8))
    made = dt.datetime.fromtimestamp(L['t'] / 1000, tz).strftime('%a %H:%M')
    kim = [p for p in L['pts'] if p[0] >= -19 and p[1] >= 121]
    print('\nLIGHTNING (Xweather 24 h, read %s): Kimberley points %d, total %d strikes' % (made, len(kim), sum(p[2] for p in kim)))
    for p in sorted(kim, key=lambda p: -p[2]):
        a = dt.datetime.fromtimestamp(p[3] / 1000, tz).strftime('%a %H:%M') if p[3] else '-'; b = dt.datetime.fromtimestamp(p[4] / 1000, tz).strftime('%a %H:%M') if p[4] else '-'
        print('   %6.1f %6.1f  %6d strikes  (%s to %s)' % (p[0], p[1], p[2], a, b))
    print('WA total %d strikes' % sum(p[2] for p in L['pts']))
else:
    print('no LT24 in page')

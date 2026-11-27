"""
The weather balloon library: every WA flight kept (Nov 2026).

  python grid1/sondes_archive.py nc/sondes.json lib

Adds any new flight in sondes.json to <lib>/<year>/<station>-<YYYYMMDDHH>.json (UTC launch hour) and lists it in
<lib>/index.json ({station: {name, lat, lng, flights: ["YYYYMMDDHH", ...] newest first}}). The nowcast workflow
pushes <lib> to the sondes-archive branch, which the weather balloons page reads.
"""
import json, os, sys

src, lib = sys.argv[1], sys.argv[2]
S = json.load(open(src)).get('st', {})
ip = os.path.join(lib, 'index.json')
idx = json.load(open(ip)) if os.path.exists(ip) else {}
new = 0
for sid, s in S.items():
    key = s['utc'][:13].replace('-', '').replace('T', '')          # YYYYMMDDHH
    d = os.path.join(lib, key[:4]); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, '%s-%s.json' % (sid, key))
    e = idx.setdefault(sid, {'name': s['name'], 'lat': s['lat'], 'lng': s['lng'], 'flights': []})
    if key in e['flights'] and os.path.exists(p):
        continue
    json.dump({'id': sid, 'name': s['name'], 'lat': s['lat'], 'lng': s['lng'], 'utc': s['utc'], 'awst': s['awst'], 'rows': s['rows']},
              open(p, 'w'), separators=(',', ':'))
    if key not in e['flights']:
        e['flights'].append(key); e['flights'].sort(reverse=True)
    new += 1
json.dump(idx, open(ip, 'w'), separators=(',', ':'))
print('Balloon library: %d new flight(s); %d in all' % (new, sum(len(v['flights']) for v in idx.values())))

"""Probe 38: Rainfall page doubles - pairs of gauges close together with the same rain."""
import sys, re, json, math
sys.path.insert(0, 'rivers'); import rivers as RV
t = RV.get('https://script.google.com/macros/s/AKfycbyoxJApPxqA86gVVXen0USujHH7OAz3_nEwonfV-8j1G4pWAyKU7aIBRCRxsYZ5DcdJ/exec', 150, 2)
for _ in range(3): t = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), t).replace('\\\\', '\\').replace('\\/', '/').replace('\\"', '"')
P = [json.loads(m.group(0)) for m in re.finditer(r'\{[^{}]*?"m60_daily"[^{}]*\}', t)]
import collections; print('points', len(P), collections.Counter(p['source'] for p in P))
B = json.loads(RV.get('https://raw.githubusercontent.com/WWXWAU/wwxw-warnings/river-data/bom-rain.json', 60, 2))
bn = {g[1]: g for g in B['gauges']}
km = lambda a, b: math.hypot((a['lat'] - b['lat']) * 111.2, (a['lng'] - b['lng']) * 111.2 * math.cos(math.radians(a['lat'])))
pairs = []
for i, a in enumerate(P):
    for b in P[i + 1:]:
        d = km(a, b)
        if d <= 25 and (a['source'] != b['source'] or a['name'] in bn or b['name'] in bn):
            same = sum(1 for k in ('h24', 'd2', 'd3', 'weekly') if a.get(k) is not None and a.get(k) == b.get(k) and a.get(k) > 0)
            if same >= 2: pairs.append((round(d, 1), a['source'], a['name'], b['source'], b['name'], a.get('h24'), b.get('h24'), a.get('weekly'), b.get('weekly')))
pairs.sort()
print('pairs with the same rain (2+ periods) within 25 km:', len(pairs))
for p in pairs: print(p)

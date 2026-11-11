"""Probe 24: match IDW65900/65901/65902 site ids to the Bureau metadata and the Rainfall page."""
import ftplib, io, re, sys, json, csv, math, collections
sys.path.insert(0, 'rivers'); import rivers as RV
M = {r['BOM_STATION_NUMBER']: r for r in csv.DictReader(open('data/bom-rain-sites.csv'))}
f = ftplib.FTP('ftp.bom.gov.au', timeout=60); f.login()
def raw(p):
    b = io.BytesIO(); f.retrbinary('RETR ' + p, b.write); return b.getvalue().decode('latin-1')
names = sorted(n.split('/')[-1] for n in f.nlst('/anon/gen/fwo'))
S = {}
for pre in ('IDW65900_', 'IDW65901_', 'IDW65902_'):
    fl = [n for n in names if n.startswith(pre) and n.endswith('.hcs')]
    print(pre, len(fl), 'files', fl[-1] if fl else '-')
    if not fl: continue
    rows = [l.split(',') for l in raw('/anon/gen/fwo/' + fl[-1]).splitlines() if l and l[0].isdigit()]
    ids = collections.defaultdict(list)
    for r in rows: ids[r[4].strip('"')].append((r[5].strip('"'), r[6]))
    S[pre] = ids
    sp = [r[5] for r in rows[:3]]; print('  sites', len(ids), 'example', rows[0][:9])
    print('  in metadata:', sum(k in M for k in ids), 'types', collections.Counter(M[k]['TYPE'] for k in ids if k in M))
all_ids = set().union(*[set(v) for v in S.values()])
print('union of sites:', len(all_ids), 'metadata WA sites:', len(M))
t = RV.get('https://script.google.com/macros/s/AKfycbyoxJApPxqA86gVVXen0USujHH7OAz3_nEwonfV-8j1G4pWAyKU7aIBRCRxsYZ5DcdJ/exec', 150, 2)
for _ in range(3): t = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), t).replace('\\\\', '\\').replace('\\/', '/').replace('\\"', '"')
pts = [json.loads(m.group(0)) for m in re.finditer(r'\{[^{}]*?"m60_daily"[^{}]*\}', t)]
print('rainfall page point keys', list(pts[0].keys()))
def near(la, lo):
    best = 9e9
    for p in pts:
        try: d = math.hypot(float(p['lat']) - la, (float(p['lng']) - lo) * math.cos(math.radians(la))) * 111
        except Exception: continue
        best = min(best, d)
    return best
new = []
for k in sorted(all_ids):
    m = M.get(k)
    if not m: continue
    d = near(float(m['LATITUDE']), float(m['LONGITUDE']))
    if d > 2: new.append((k, m['SHORT_NAME'], m['TYPE'], m['RIVER_BASIN_NAME'], round(d, 1)))
print('NEW sites (>2 km from any Rainfall page gauge):', len(new))
print(collections.Counter(n[3] for n in new).most_common(40))
for n in new: print(n)
print('not in metadata:', sorted(k for k in all_ids if k not in M)[:60])

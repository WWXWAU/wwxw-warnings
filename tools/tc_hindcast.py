"""Hindcast: how Google's AI cyclone models and ECMWF did on past Southern Hemisphere cyclones.

Forecasts: Google DeepMind Weather Lab 'paired' ATCF a-decks (CC BY 4.0 for past data), which carry the AI model's
ensemble mean alongside ECMWF's for the same storms. Best tracks: IBTrACS v04r01 (South Indian + South Pacific), using
the Bureau of Meteorology's positions where it tracked the storm, else JTWC's, else the WMO agency's.
Errors: great-circle distance from each forecast position to the best-track position at the same time, at 24-120 h,
by region (WA 90-135E, northern Australia east 135-160E, South Pacific 160E+, south-west Indian Ocean <90E).
Output: verify/tc-hindcast.json and verify/tc-hindcast.md (committed to the 'verification' branch by the workflow).
"""
import csv, io, json, math, os, sys, time, urllib.request, datetime as dt
from collections import defaultdict

OUT = sys.argv[1] if len(sys.argv) > 1 else 'verify'
os.makedirs(OUT, exist_ok=True)
G = 'https://deepmind.google.com/science/weatherlab/download/cyclones/{m}/ensemble_mean/paired/atcf/{m}_{d}_atcf_a_deck.txt'
MODELS = ['FNV3', 'FNV2', 'GENC']
SEASONS = [(2023, 11), (2024, 11), (2025, 11)]   # Nov to May
LEADS = [24, 48, 72, 96, 120]
UA = {'User-Agent': 'Mozilla/5.0 (WWXW verification)'}

def get(u, tries=3):
    for k in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=90).read()
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
        except Exception:
            pass
        time.sleep(2 + 3 * k)
    return None

def ll(s):
    s = s.strip()
    if not s or s[-1] not in 'NSEW': return None
    v = int(s[:-1]) / 10.0
    return -v if s[-1] in 'SW' else v

def km(a, b, c, d):
    p1, p2, dl = math.radians(a), math.radians(c), math.radians(d - b)
    x = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl)
    return 6371.0 * math.acos(max(-1, min(1, x)))

def region(lat, lon):
    L = lon % 360
    if lat >= 0: return None
    return 'SWIO' if L < 90 else 'WA' if L < 135 else 'NAUS' if L < 160 else 'SP' if L < 300 else 'SWIO'

# ---- best tracks
def ibtracs():
    bt = defaultdict(dict)   # ATCF id -> {datetime: (lat, lon, src)}
    for basin in ['SI', 'SP']:
        raw = get('https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/ibtracs.%s.list.v04r01.csv' % basin)
        if not raw: print('IBTrACS', basin, 'not read'); continue
        rd = csv.DictReader(io.StringIO(raw.decode('utf-8', 'replace')))
        n = 0
        for r in rd:
            if r.get('SEASON', '').strip() in ('', 'Year') or int(r['SEASON']) < 2023: continue
            aid = (r.get('USA_ATCF_ID') or '').strip().upper()
            if not aid: continue
            t = dt.datetime.strptime(r['ISO_TIME'][:16], '%Y-%m-%d %H:%M')
            for la, lo, src in (('BOM_LAT', 'BOM_LON', 'BoM'), ('USA_LAT', 'USA_LON', 'JTWC'), ('LAT', 'LON', 'WMO')):
                try:
                    a, b = float(r[la]), float(r[lo]); bt[aid][t] = (a, b, src); n += 1; break
                except (ValueError, KeyError, TypeError):
                    continue
        print('IBTrACS', basin, n, 'positions')
    return bt

def bt_at(track, t):
    if t in track: return track[t]
    ks = sorted(track)
    for i in range(len(ks) - 1):
        if ks[i] < t < ks[i + 1] and (ks[i + 1] - ks[i]).total_seconds() <= 6 * 3600:
            f = (t - ks[i]).total_seconds() / (ks[i + 1] - ks[i]).total_seconds()
            a, b = track[ks[i]], track[ks[i + 1]]
            return (a[0] + f * (b[0] - a[0]), a[1] + f * (((b[1] - a[1] + 180) % 360) - 180), a[2])
    return None

def main():
    bt = ibtracs()
    fc = {}      # (storm, init, tech) -> {tau: (lat, lon)}
    techs = defaultdict(int)
    for (y0, m0) in SEASONS:
        d = dt.datetime(y0, m0, 1)
        end = dt.datetime(y0 + 1, 6, 1)
        while d < end and d < dt.datetime.utcnow() - dt.timedelta(days=6):
            for m in MODELS:
                raw = get(G.format(m=m, d=d.strftime('%Y_%m_%dT%H_00')))
                if not raw: continue
                for line in raw.decode('utf-8', 'replace').splitlines():
                    if line.startswith('#') or line.count(',') < 8: continue
                    f = [x.strip() for x in line.split(',')]
                    basin, cy, init, tech, tau = f[0].upper(), f[1], f[2], f[4].upper(), f[5]
                    if basin not in ('SH', 'SP', 'SI'): continue
                    lat, lon = ll(f[6]), ll(f[7])
                    if lat is None or lon is None: continue
                    sid = 'SH' + cy.zfill(2) + init[:4]
                    # season year: SH storms after July belong to the next year's ATCF number
                    if int(init[4:6]) >= 7: sid = 'SH' + cy.zfill(2) + str(int(init[:4]) + 1)
                    techs[tech] += 1
                    fc.setdefault((sid, init, tech), {})[int(tau)] = (lat, lon)
            d += dt.timedelta(hours=12)
        print('season', y0, 'done:', len(fc), 'forecasts so far'); sys.stdout.flush()
    print('Forecast models in the files:', dict(techs))
    # score
    err = defaultdict(lambda: defaultdict(list))   # (region, tech) -> lead -> [km]
    pairs = defaultdict(lambda: defaultdict(list)) # (region, tech, 'EC') -> lead -> [(e_ai, e_ec)]
    by_si = defaultdict(lambda: defaultdict(dict)) # (storm, init) -> tech -> {lead: km}
    unmatched = set()
    for (sid, init, tech), P in fc.items():
        trk = bt.get(sid)
        if not trk: unmatched.add(sid); continue
        t0 = dt.datetime.strptime(init[:10], '%Y%m%d%H')
        p0 = bt_at(trk, t0)
        if not p0: continue
        rg = region(p0[0], p0[1])
        if not rg: continue
        for L in LEADS:
            if L not in P: continue
            b = bt_at(trk, t0 + dt.timedelta(hours=L))
            if not b: continue
            e = km(P[L][0], P[L][1], b[0], b[1])
            err[(rg, tech)][L].append(e)
            by_si[(sid, init, rg)][tech][L] = e
    # head-to-head: same storm, same start time, same lead
    h2h = defaultdict(lambda: defaultdict(list))   # (region, a, b) -> lead -> [(ea, eb)]
    tl = sorted(techs)
    for (sid, init, rg), T in by_si.items():
        for a in tl:
            for b in tl:
                if a >= b or a not in T or b not in T: continue
                for L in LEADS:
                    if L in T[a] and L in T[b]: h2h[(rg, a, b)][L].append((T[a][L], T[b][L]))
    res = {'made': dt.datetime.utcnow().isoformat() + 'Z', 'seasons': ['%d-%02d' % (y, (y + 1) % 100) for y, _ in SEASONS],
           'techs': dict(techs), 'unmatched': sorted(unmatched)[:50], 'err': {}, 'h2h': {}}
    for (rg, tech), D in err.items():
        res['err'].setdefault(rg, {})[tech] = {str(L): [len(v), round(sum(v) / len(v))] for L, v in D.items() if v}
    for (rg, a, b), D in h2h.items():
        res['h2h'].setdefault(rg, {})[a + ' vs ' + b] = {str(L): [len(v), round(sum(x[0] for x in v) / len(v)), round(sum(x[1] for x in v) / len(v))] for L, v in D.items() if v}
    json.dump(res, open(os.path.join(OUT, 'tc-hindcast.json'), 'w'), indent=1)
    names = {'WA': 'WA (90-135°E)', 'NAUS': 'Northern Australia east (135-160°E)', 'SP': 'South Pacific (160°E+)', 'SWIO': 'South-west Indian Ocean (<90°E)'}
    md = ['# Cyclone track hindcast: AI vs ECMWF, Southern Hemisphere ' + ', '.join(res['seasons']), '',
          'Mean track error (km) and number of forecasts, against IBTrACS best tracks (BoM positions where available).', '']
    for rg in ['WA', 'NAUS', 'SP', 'SWIO']:
        if rg not in res['err']: continue
        md += ['## ' + names[rg], '', '| Model | 24 h | 48 h | 72 h | 96 h | 120 h |', '|---|---|---|---|---|---|']
        for tech, D in sorted(res['err'][rg].items(), key=lambda x: (x[1].get('72', [0, 9e9])[1])):
            md.append('| ' + tech + ' | ' + ' | '.join(('%d (%d)' % (D[str(L)][1], D[str(L)][0])) if str(L) in D else '-' for L in LEADS) + ' |')
        md += ['', 'Head to head (same storms, same start times): mean error A / B km', '']
        for k, D in sorted(res['h2h'].get(rg, {}).items()):
            md.append('- **' + k + '**: ' + ', '.join('%d h %d / %d (%d)' % (L, D[str(L)][1], D[str(L)][2], D[str(L)][0]) for L in LEADS if str(L) in D))
        md.append('')
    open(os.path.join(OUT, 'tc-hindcast.md'), 'w').write('\n'.join(md))
    print('\n'.join(md))

if __name__ == '__main__':
    main()

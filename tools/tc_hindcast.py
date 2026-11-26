"""Hindcast: how every cyclone model did on past Southern Hemisphere cyclones, scored the same way as the live
verification in Cyclones.gs, so the result can seed the live model weights.

Forecasts:
  - UCAR/NCAR open a-decks (the same files the live page reads): JTWC's official forecast and every model JTWC
    receives (GFS, GEFS, UKMO, Canadian, NAVGEM, their ensembles, consensus aids...). ECMWF is not in the open files.
  - Google DeepMind Weather Lab archive (CC BY 4.0): FNV3 (WeatherNext) and GenCast ensemble means.
Best tracks: IBTrACS v04r01 (South Indian + South Pacific): BoM positions where BoM tracked the storm, else JTWC, else WMO.
Scoring (as Cyclones.gs cyVerifyScore_): great-circle error at 24-120 h; ensemble suites (XX01..XX30) as their mean
when at least 5 members; JTWC's official forecast as OFF; region from the storm's first best-track position.
Output: cy-skill-seed.json in the live record's layout { region: { key: { lead: [n, sum km] } } } and tc-hindcast.md.
Strength (Nov 2026): each forecast's maximum wind (kt, 1-minute, a-deck column 9) against JTWC's best-track wind
(IBTrACS USA_WIND) at the same lead, into cy-int-seed.json { region: { key: { lead: [n, sum |error|, sum error] } } }
(error = forecast minus actual: below zero = too weak). Only where the storm was 35 kt+ or the forecast had it so.
"""
import csv, io, json, math, os, re, sys, time, urllib.request, datetime as dt
from collections import defaultdict, Counter

OUT = sys.argv[1] if len(sys.argv) > 1 else 'verify'
os.makedirs(OUT, exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0 (WWXW verification)'}
LEADS = [24, 48, 72, 96, 120]
WL = 'https://deepmind.google.com/science/weatherlab/download/cyclones/{m}/ensemble_mean/paired/atcf/{m}_{d}_atcf_a_deck.txt'
WL_MODELS = ['FNV3', 'GENC']
SEASONS = [2024, 2025, 2026]           # SH season year (2024 = Jul 2023 - Jun 2024)
UCAR = 'https://hurricanes.ral.ucar.edu/repository/data/adecks_open/{Y}/'
stat = Counter()

def get(u, tries=3):
    for k in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=120).read()
        except urllib.error.HTTPError as e:
            if e.code == 404: stat['404'] += 1; return None
            stat['http%d' % e.code] += 1
        except Exception:
            stat['err'] += 1
        time.sleep(3 + 5 * k)
    return None

def ll(s):
    s = s.strip()
    if not s or s[-1] not in 'NSEW': return None
    v = int(s[:-1]) / 10.0
    return -v if s[-1] in 'SW' else v

def km(a, b, c, d):
    p1, p2, dl = math.radians(a), math.radians(c), math.radians(d - b)
    return 6371.0 * math.acos(max(-1, min(1, math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl))))

def region(lat, lon):   # as Cyclones.gs cyRegion_
    L = lon % 360
    if lat >= 0: return 'NIO' if L < 100 else 'WPAC' if L < 180 else 'NHE'
    return 'SWIO' if L < 90 else 'WA' if L < 135 else 'NAUS' if L < 160 else 'SP' if L < 300 else 'SWIO'

def season_of(t):
    return t.year + 1 if t.month >= 7 else t.year

# ---------------- best tracks
BTW = defaultdict(dict)   # best-track 1-minute wind (kt): BTW[sid][time]

def ibtracs():
    bt = defaultdict(dict)
    for basin in ['SI', 'SP']:
        raw = get('https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/ibtracs.%s.list.v04r01.csv' % basin)
        if not raw: print('IBTrACS', basin, 'not read'); continue
        for r in csv.DictReader(io.StringIO(raw.decode('utf-8', 'replace'))):
            try:
                if int(r['SEASON']) < SEASONS[0]: continue
            except ValueError:
                continue
            aid = (r.get('USA_ATCF_ID') or '').strip().upper()
            if not aid: continue
            t = dt.datetime.strptime(r['ISO_TIME'][:16], '%Y-%m-%d %H:%M')
            try: BTW[aid][t] = float(r['USA_WIND'])
            except (ValueError, KeyError, TypeError): pass
            for la, lo in (('BOM_LAT', 'BOM_LON'), ('USA_LAT', 'USA_LON'), ('LAT', 'LON')):
                try:
                    bt[aid][t] = (float(r[la]), float(r[lo])); break
                except (ValueError, KeyError, TypeError):
                    continue
    print('IBTrACS storms since', SEASONS[0], ':', len(bt))
    return bt

def bw_at(sid, t):
    w = BTW.get(sid) or {}
    if t in w: return w[t]
    ks = sorted(w)
    for i in range(len(ks) - 1):
        if ks[i] < t < ks[i + 1] and (ks[i + 1] - ks[i]).total_seconds() <= 12 * 3600:
            f = (t - ks[i]).total_seconds() / (ks[i + 1] - ks[i]).total_seconds()
            return w[ks[i]] + f * (w[ks[i + 1]] - w[ks[i]])
    return None

def bt_at(track, t):
    if t in track: return track[t]
    ks = sorted(track)
    for i in range(len(ks) - 1):
        if ks[i] < t < ks[i + 1] and (ks[i + 1] - ks[i]).total_seconds() <= 12 * 3600:
            f = (t - ks[i]).total_seconds() / (ks[i + 1] - ks[i]).total_seconds()
            a, b = track[ks[i]], track[ks[i + 1]]
            return (a[0] + f * (b[0] - a[0]), a[1] + f * (((b[1] - a[1] + 180) % 360) - 180))
    return None

# ---------------- forecasts: fc[(sid, init)][tech][tau] = (lat, lon)
fc = defaultdict(lambda: defaultdict(dict))
techs = Counter()

def take(text, source):
    for line in text.splitlines():
        if line.startswith('#') or line.count(',') < 8: continue
        f = [x.strip() for x in line.split(',')]
        basin, cy, init, tech = f[0].upper(), f[1].zfill(2), f[2], f[4].upper()
        try: tau = int(f[5])
        except ValueError: continue
        if tau not in LEADS: continue
        lat, lon = ll(f[6]), ll(f[7])
        if lat is None or lon is None or lat >= 0: continue
        lon = lon % 360   # 0-360, as the live page: ensemble means stay right across the dateline
        if basin not in ('SH', 'IO', 'SP', 'SI', 'S'): continue
        if not re.match(r'^\d{10}$', init) or int(cy) >= 80: continue      # no invests
        t0 = dt.datetime.strptime(init, '%Y%m%d%H')
        sid = 'SH' + cy + str(season_of(t0))
        if tech in ('CARQ', 'WRNG', 'BEST', 'TCVT', 'XTRP', 'CLIP', 'CLP5'): continue
        try: vmax = float(f[8])
        except (ValueError, IndexError): vmax = 0
        fc[(sid, init)][tech][tau] = (lat, lon, vmax if vmax > 0 else None)
        techs[(source, tech)] += 1

def main():
    bt = ibtracs()
    # UCAR a-decks
    for Y in SEASONS:
        base = UCAR.format(Y=Y)
        idx = get(base)
        names = sorted(set(re.findall(r'ash(\d\d)%d\.dat' % Y, idx.decode('utf-8', 'replace')))) if idx else []
        if not names:   # the current year's files sit in the top folder until the year is archived
            base = UCAR.replace('{Y}/', ''); idx = get(base)
            names = sorted(set(re.findall(r'ash(\d\d)%d\.dat' % Y, idx.decode('utf-8', 'replace')))) if idx else []
        names = [n for n in names if int(n) < 80]
        print('UCAR', Y, len(names), 'storms'); sys.stdout.flush()
        for n in names:
            raw = get(base + 'ash%s%d.dat' % (n, Y))
            if raw: take(raw.decode('utf-8', 'replace'), 'adeck')
    # Weather Lab, every 6 h
    for Y in SEASONS:
        d, end = dt.datetime(Y - 1, 10, 1), dt.datetime(Y, 6, 1)
        while d < end and d < dt.datetime.now() - dt.timedelta(days=6):
            for m in WL_MODELS:
                raw = get(WL.format(m=m, d=d.strftime('%Y_%m_%dT%H_00')))
                if raw: stat['wl_ok'] += 1; take(raw.decode('utf-8', 'replace'), 'weatherlab')
            d += dt.timedelta(hours=6)
        print('Weather Lab season', Y, 'done', dict(stat)); sys.stdout.flush()
    print('Models:', sorted(((s, t), n) for (s, t), n in techs.items() if n >= 50))
    # score
    K = {}; KI = {}
    first = {}
    for sid, tr in bt.items():
        if tr: k0 = min(tr); first[sid] = region(*tr[k0])
    for (sid, init), T in fc.items():
        trk = bt.get(sid)
        if not trk or sid not in first: stat['no_best_track'] += 1; continue
        rg = first[sid]; R = K.setdefault(rg, {}); RI = KI.setdefault(rg, {})
        t0 = dt.datetime.strptime(init, '%Y%m%d%H')
        keys = {}
        suites = defaultdict(lambda: defaultdict(list))
        for tech, P in T.items():
            if re.match(r'^[A-Z]{2}\d\d$', tech) and tech[2:] != '00':
                for L, q in P.items(): suites[tech[:2]][L].append(q)
                continue
            keys['OFF' if tech == 'JTWC' else tech] = P
        for s, D in suites.items():
            P = {}
            for L, qs in D.items():
                if len(qs) >= 5:
                    vv = [q[2] for q in qs if q[2]]
                    P[L] = (sum(q[0] for q in qs) / len(qs), sum(q[1] for q in qs) / len(qs), sum(vv) / len(vv) if len(vv) >= 5 else None)   # SH: no dateline issue for these
            if P: keys[s + '##'] = P
        for key, P in keys.items():
            for L, q in P.items():
                tL = t0 + dt.timedelta(hours=L)
                w = bw_at(sid, tL)
                if q[2] and w and (w >= 35 or q[2] >= 35):   # strength
                    ci = RI.setdefault(key, {}).setdefault(str(L), [0, 0, 0])
                    ci[0] += 1; ci[1] += round(abs(q[2] - w)); ci[2] += round(q[2] - w)
                if re.match(r'^CHP\d$', key): continue   # CHIPS runs 2-7 repeat CHIP's track
                b = bt_at(trk, tL)
                if not b: continue
                c = R.setdefault(key, {}).setdefault(str(L), [0, 0])
                c[0] += 1; c[1] += round(km(q[0], q[1], b[0], b[1]))
    json.dump(K, open(os.path.join(OUT, 'cy-skill-seed.json'), 'w'), separators=(',', ':'))
    json.dump(KI, open(os.path.join(OUT, 'cy-int-seed.json'), 'w'), separators=(',', ':'))
    # report
    names = {'WA': 'WA (90-135°E)', 'NAUS': 'Northern Australia east (135-160°E)', 'SP': 'South Pacific (160°E+)', 'SWIO': 'South-west Indian Ocean (<90°E)'}
    md = ['# Cyclone track errors, Southern Hemisphere seasons ' + ', '.join('%d-%02d' % (y - 1, y % 100) for y in SEASONS), '',
          'Mean track error in km (number of forecasts) against IBTrACS best tracks (BoM positions where available).',
          'Sources: UCAR/NCAR open a-decks (JTWC official and models received by JTWC), Google DeepMind Weather Lab (FNV3, GenCast; CC BY 4.0). ECMWF is not in the open archives.', '']
    for rg in ['WA', 'NAUS', 'SP', 'SWIO']:
        R = K.get(rg)
        if not R: continue
        rows = [(k, D) for k, D in R.items() if D.get('72', [0])[0] >= 10]
        rows.sort(key=lambda x: x[1]['72'][1] / x[1]['72'][0])
        md += ['## ' + names[rg], '', '| Model | 24 h | 48 h | 72 h | 96 h | 120 h |', '|---|---|---|---|---|---|']
        for k, D in rows[:30]:
            md.append('| ' + k + ' | ' + ' | '.join(('%d (%d)' % (round(D[str(L)][1] / D[str(L)][0]), D[str(L)][0])) if str(L) in D else '-' for L in LEADS) + ' |')
        md.append('')
    md += ['# Strength: mean error in kt, |error| (bias, + too strong) (forecasts), 1-minute winds against JTWC best tracks', '']
    for rg in ['WA', 'NAUS', 'SP', 'SWIO']:
        R = KI.get(rg)
        if not R: continue
        rows = [(k, D) for k, D in R.items() if D.get('72', [0])[0] >= 10]
        rows.sort(key=lambda x: x[1]['72'][1] / x[1]['72'][0])
        md += ['## ' + names[rg], '', '| Model | 24 h | 48 h | 72 h | 96 h | 120 h |', '|---|---|---|---|---|---|']
        for k, D in rows[:40]:
            md.append('| ' + k + ' | ' + ' | '.join(('%d (%+d) (%d)' % (round(D[str(L)][1] / D[str(L)][0]), round(D[str(L)][2] / D[str(L)][0]), D[str(L)][0])) if str(L) in D else '-' for L in LEADS) + ' |')
        md.append('')
    md.append('Fetch stats: ' + json.dumps(dict(stat)))
    open(os.path.join(OUT, 'tc-hindcast.md'), 'w').write('\n'.join(md))
    print('\n'.join(md))

if __name__ == '__main__':
    main()

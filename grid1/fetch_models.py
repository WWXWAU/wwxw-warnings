"""
fetch_models.py - West WX Watchers: model data on a 1-degree grid over WA, straight from the source.

Builds the same raw rows the outlook's model sheets hold (rawHeaders_ in Code.gs), for:
  ECMWF  HRES (IFS 0.25) - ECMWF open data, CC BY 4.0
  AIFS   AIFS single     - ECMWF open data, CC BY 4.0
  GFS    GFS 0.25        - NOAA, public domain (AWS open data bucket)
Only the pieces of each file that are needed are downloaded (byte ranges from the index files).
Steps: 3-hourly to 48 h, then 6-hourly to 168 h (AIFS is 6-hourly throughout).
Times are written in AWST ('yyyy-MM-dd HH:mm'), like Open-Meteo's.

Output: data/grid1/raw_<MODEL>.json  ({model, run, rows, missing}), then indices.js turns them into the
outlook data file. Run:  python grid1/fetch_models.py [ECMWF AIFS GFS]
"""
import concurrent.futures as cf
import datetime as dt
import json
import math
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request

import numpy as np

OUT_DIR = 'data/grid1'
LATS = [float(x) for x in range(-14, -36, -1)]      # 22 rows, -14 to -35
LNGS = [float(x) for x in range(113, 130)]           # 17 columns, 113 to 129
PLEVELS = [1000, 925, 850, 700, 500, 300, 250, 200]  # same as Code.gs
STEPS = list(range(0, 49, 3)) + list(range(54, 169, 6))
STEPS_6H = list(range(0, 169, 6))
AWST = dt.timedelta(hours=8)
WORKERS = 8          # GFS (NOAA's bucket copes)
EC_WORKERS = 4       # ECMWF's bucket answers "503 Slow Down" when pushed
EC_GAP = 4000000     # join ECMWF pieces less than 4 MB apart into one request (fewer requests)

ECMWF_MIRRORS = ['https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com', 'https://data.ecmwf.int/forecasts']
GFS_ROOT = 'https://noaa-gfs-bdp-pds.s3.amazonaws.com'


def log(*a):
    print(*a, flush=True)


def get(url, rng=None, tries=8):
    """Download (part of) a file; busy replies (429/503 "Slow Down", 5xx) wait and retry with back-off."""
    last = None
    for k in range(tries):
        try:
            hdr = {'Range': 'bytes=%d-%d' % rng} if rng else {}
            with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 404:
                raise
            wait = e.headers.get('Retry-After') if e.headers else None
            time.sleep(float(wait) if wait and wait.isdigit() else min(60, 3 * 2 ** k) + 3 * random.random())
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1 + k + random.random())
    raise last


# ---------------------------------------------------------------- GRIB decoding (eccodes)
_grid_cache = {}


def sample(buf):
    """GRIB message -> (key info, values at the 1-degree WA points, as a LATS x LNGS array)."""
    import eccodes
    gid = eccodes.codes_new_from_message(buf)
    try:
        ni, nj = eccodes.codes_get(gid, 'Ni'), eccodes.codes_get(gid, 'Nj')
        la1 = eccodes.codes_get(gid, 'latitudeOfFirstGridPointInDegrees')
        lo1 = eccodes.codes_get(gid, 'longitudeOfFirstGridPointInDegrees')
        di = eccodes.codes_get(gid, 'iDirectionIncrementInDegrees')
        dj = eccodes.codes_get(gid, 'jDirectionIncrementInDegrees')
        scan_n = eccodes.codes_get(gid, 'jScansPositively')
        vals = eccodes.codes_get_values(gid).reshape(nj, ni)
    finally:
        eccodes.codes_release(gid)
    key = (ni, nj, la1, lo1, di, dj, scan_n)
    if key not in _grid_cache:
        rows = [int(round(((la - la1) if scan_n else (la1 - la)) / dj)) for la in LATS]
        cols = [int(round(((lo - lo1) % 360.0) / di)) % ni for lo in LNGS]
        _grid_cache[key] = (np.array(rows), np.array(cols))
    r, c = _grid_cache[key]
    return vals[np.ix_(r, c)]


def merge_ranges(items, gap=0):
    """items: [(name, offset, length)] -> [(start, end, [(name, offset, length)])] for contiguous runs."""
    items = sorted(items, key=lambda x: x[1])
    out = []
    for it in items:
        if out and it[1] <= out[-1][1] + 1 + gap:
            out[-1][1] = max(out[-1][1], it[1] + it[2] - 1)
            out[-1][2].append(it)
        else:
            out.append([it[1], it[1] + it[2] - 1, [it]])
    return out


def fetch_fields(url, items, gap=0, alt_urls=()):
    """Download the wanted messages of one file and decode them -> {name: array}.
    A piece that still fails after the retries is tried on the other mirror, then skipped (the rest carries on)."""
    res = {}
    for start, end, group in merge_ranges(items, gap):
        buf = None
        for u in (url,) + tuple(alt_urls):
            try:
                buf = get(u, (start, end))
                break
            except Exception as e:  # noqa: BLE001
                log('  %s bytes %d-%d: %s' % (u.rsplit('/', 1)[-1], start, end, e))
        if buf is None:
            continue
        for name, off, ln in group:
            try:
                res[name] = sample(buf[off - start: off - start + ln])
            except Exception as e:  # noqa: BLE001
                log('  could not decode %s in %s: %s' % (name, url.rsplit('/', 1)[-1], e))
    return res


# ---------------------------------------------------------------- ECMWF HRES and AIFS (open data)
def ec_paths(kind, run):
    ymd, hh = run.strftime('%Y%m%d'), run.strftime('%H')
    if kind == 'ECMWF':
        stream = 'oper' if hh in ('00', '12') else 'scda'
        return '%s/%sz/ifs/0p25/%s/%s%s0000-{s}h-%s-fc' % (ymd, hh, stream, ymd, hh, stream)
    return '%s/%sz/aifs-single/0p25/oper/%s%s0000-{s}h-oper-fc' % (ymd, hh, ymd, hh)


def ec_wanted(kind):
    pl = ['t', 'u', 'v'] + (['r'] if kind == 'ECMWF' else ['q'])
    want = {(p, lv) for p in pl for lv in PLEVELS}
    want |= {('w', 700), ('gh', 500)}
    sfc = ['2t', '2d', '10u', '10v', 'sp', 'tp'] + (['mucape', '10fg', 'tcwv'] if kind == 'ECMWF' else ['tcw'])
    return want, set(sfc)


def ec_index(base, step):
    txt = get(base.replace('{s}', str(step)) + '.index').decode()
    out = []
    for line in txt.splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def find_run(kind, steps):
    """Newest run (last 2 days) whose last wanted step is published, and a mirror that has it."""
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    cycles = (0, 6, 12, 18)
    t = now.replace(minute=0, second=0, microsecond=0)
    cands = []
    for back in range(0, 60, 6):
        x = t - dt.timedelta(hours=back)
        run = x.replace(hour=max(c for c in cycles if c <= x.hour))
        if run not in cands:
            cands.append(run)
    for run in cands:
        if kind == 'GFS':
            try:
                get(gfs_url(run, steps[-1]) + '.idx')
                return run, None
            except Exception:  # noqa: BLE001
                continue
        for m in ECMWF_MIRRORS:
            try:
                get('%s/%s.index' % (m, ec_paths(kind, run).replace('{s}', str(steps[-1]))))
                return run, m
            except Exception:  # noqa: BLE001
                pass
    return None, None


def fetch_ecmwf(kind):
    steps = STEPS if kind == 'ECMWF' else STEPS_6H
    run, mirror = find_run(kind, steps)
    if not run:
        log('%s: no complete run found.' % kind)
        return None
    base = '%s/%s' % (mirror, ec_paths(kind, run))
    log('%s: run %s from %s' % (kind, run.strftime('%Y-%m-%d %Hz'), mirror))
    want, sfc = ec_wanted(kind)

    others = ['%s/%s' % (m, ec_paths(kind, run)) for m in ECMWF_MIRRORS if m != mirror]

    def one(step):
        try:
            idx = ec_index(base, step)
        except Exception as e:  # noqa: BLE001
            log('  step %d index: %s' % (step, e))
            return step, {}
        items = []
        for o in idx:
            p, lt = o.get('param'), o.get('levtype')
            if lt == 'pl' and (p, int(o.get('levelist', 0) or 0)) in want:
                items.append(('%s%s' % (p, o['levelist']), int(o['_offset']), int(o['_length'])))
            elif lt == 'sfc' and p in sfc:
                items.append((p, int(o['_offset']), int(o['_length'])))
        return step, fetch_fields(base.replace('{s}', str(step)) + '.grib2', items, EC_GAP,
                                  [o.replace('{s}', str(step)) + '.grib2' for o in others])

    fields = {}
    with cf.ThreadPoolExecutor(max_workers=EC_WORKERS) as ex:
        for step, f in ex.map(one, steps):
            fields[step] = f
    again = [s for s in steps if len(fields.get(s) or {}) < 10]
    if again:   # a second, slower pass for steps that came back empty or short
        log('%s: retrying %d step(s) one at a time: %s' % (kind, len(again), again))
        for s in again:
            time.sleep(5)
            st, f = one(s)
            if len(f) > len(fields.get(s) or {}):
                fields[s] = f
    return build_rows(kind, run, steps, fields, ecmwf_point)


def ecmwf_point(kind, f, prev, step, prev_step, i, j):
    """Raw-row values for one point from ECMWF/AIFS fields (SI units in, outlook units out)."""
    g = lambda k: float(f[k][i, j]) if k in f else math.nan  # noqa: E731
    lv = {}
    for p in PLEVELS:
        T = g('t%d' % p) - 273.15
        if kind == 'ECMWF':
            rh = g('r%d' % p)
            e = rh / 100.0 * sat_vap(T) if rh == rh else math.nan
        else:
            q = g('q%d' % p)
            e = q * p / (0.622 + 0.378 * q) if q == q else math.nan
            rh = 100.0 * e / sat_vap(T) if e == e else math.nan
        lv[p] = (T, dew(e), g('u%d' % p), g('v%d' % p), rh)
    tp_now = g('tp')
    tp_prev = float(prev['tp'][i, j]) if prev is not None and 'tp' in prev else math.nan
    rate = 0.0 if prev is None else max(0.0, (tp_now - tp_prev) * 1000.0 / max(1, step - prev_step))
    psfc = g('sp') / 100.0
    t700 = lv[700][0]
    return {
        'lv': lv, 'cape': g('mucape'), 'cin': math.nan, 'li': math.nan,
        'gust': g('10fg') * 3.6, 'precip': rate, 'psfc': psfc,
        't2': g('2t') - 273.15, 'td2': g('2d') - 273.15, 'u10': g('10u'), 'v10': g('10v'),
        'blh': math.nan, 'fzl': math.nan, 'w700': omega_to_w(g('w700'), 700, t700),
        'gh500': g('gh500'), 'tcwv': g('tcwv') if kind == 'ECMWF' else g('tcw'),
    }


# ---------------------------------------------------------------- GFS (NOAA open data on AWS)
def gfs_url(run, step):
    ymd, hh = run.strftime('%Y%m%d'), run.strftime('%H')
    return '%s/gfs.%s/%s/atmos/gfs.t%sz.pgrb2.0p25.f%03d' % (GFS_ROOT, ymd, hh, hh, step)


GFS_SFC = {('CAPE', 'surface'): 'cape', ('CIN', 'surface'): 'cin', ('LFTX', 'surface'): 'li',
           ('GUST', 'surface'): 'gust', ('APCP', 'surface'): 'apcp', ('PRES', 'surface'): 'sp',
           ('TMP', '2 m above ground'): 't2', ('DPT', '2 m above ground'): 'td2',
           ('UGRD', '10 m above ground'): 'u10', ('VGRD', '10 m above ground'): 'v10',
           ('HPBL', 'surface'): 'blh', ('HGT', '0C isotherm'): 'fzl', ('VVEL', '700 mb'): 'w700',
           ('HGT', '500 mb'): 'gh500', ('PWAT', 'entire atmosphere (considered as a single layer)'): 'pwat'}


def fetch_gfs():
    run, _ = find_run('GFS', STEPS)
    if not run:
        log('GFS: no complete run found.')
        return None
    log('GFS: run %s' % run.strftime('%Y-%m-%d %Hz'))

    def one(step):
        url = gfs_url(run, step)
        try:
            lines = get(url + '.idx').decode().splitlines()
        except Exception as e:  # noqa: BLE001
            log('  GFS step %d index: %s' % (step, e))
            return step, {}
        items, acc = [], None
        for n, line in enumerate(lines):
            parts = line.split(':')
            if len(parts) < 6:
                continue
            off = int(parts[1])
            nxt = int(lines[n + 1].split(':')[1]) if n + 1 < len(lines) else None
            ln = (nxt - off) if nxt else 4000000
            var, lev, fc = parts[3], parts[4], parts[5]
            name = None
            m = re.match(r'(\d+) mb$', lev)
            if m and int(m.group(1)) in PLEVELS and var in ('TMP', 'RH', 'UGRD', 'VGRD'):
                name = '%s%s' % (var, m.group(1))
            if (var, lev) in GFS_SFC and not (var == 'APCP' and 'acc' not in fc):
                name = GFS_SFC[(var, lev)]
                if name == 'apcp':
                    r = re.search(r'(\d+)-(\d+) hour acc', fc)
                    if not r or acc:
                        continue
                    acc = (int(r.group(1)), int(r.group(2)))
            if name and (name not in [x[0] for x in items]):
                items.append((name, off, ln))
        f = fetch_fields(url, items)
        f['_acc'] = acc
        return step, f

    fields = {}
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for step, f in ex.map(one, STEPS):
            fields[step] = f
    return build_rows('GFS', run, STEPS, fields, gfs_point)


def gfs_point(kind, f, prev, step, prev_step, i, j):
    g = lambda k: float(f[k][i, j]) if k in f else math.nan  # noqa: E731
    lv = {}
    for p in PLEVELS:
        T = g('TMP%d' % p) - 273.15
        rh = g('RH%d' % p)
        e = rh / 100.0 * sat_vap(T) if rh == rh else math.nan
        lv[p] = (T, dew(e), g('UGRD%d' % p), g('VGRD%d' % p), rh)
    # precipitation rate over the time since the previous step, from GFS's 3/6-hour buckets
    rate, acc = 0.0, f.get('_acc')
    if prev is not None and acc and 'apcp' in f:
        a, b = acc
        tot = g('apcp')
        if a >= prev_step:
            rate = tot / max(1, b - a)
        elif prev.get('_acc') and prev['_acc'][0] == a and 'apcp' in prev:
            rate = (tot - float(prev['apcp'][i, j])) / max(1, step - prev_step)
        else:
            rate = tot / max(1, b - a)
    return {
        'lv': lv, 'cape': g('cape'), 'cin': g('cin'), 'li': g('li'),
        'gust': g('gust') * 3.6, 'precip': max(0.0, rate), 'psfc': g('sp') / 100.0,
        't2': g('t2') - 273.15, 'td2': g('td2') - 273.15, 'u10': g('u10'), 'v10': g('v10'),
        'blh': g('blh'), 'fzl': g('fzl'), 'w700': omega_to_w(g('w700'), 700, lv[700][0]),
        'gh500': g('gh500'), 'tcwv': g('pwat'),
    }


# ---------------------------------------------------------------- shared
def sat_vap(t):
    return 6.112 * math.exp(17.67 * t / (t + 243.5))


def dew(e):
    if not (e == e) or e <= 0:
        return math.nan
    lg = math.log(e / 6.112)
    return 243.5 * lg / (17.67 - lg)


def omega_to_w(omega, p, t):
    """Pa/s (positive down) -> m/s (positive up), as the outlook's vertical velocity."""
    if not (omega == omega) or not (t == t):
        return math.nan
    rho = p * 100.0 / (287.04 * (t + 273.15))
    return -omega / (rho * 9.81)


def spd_dir(u, v):
    if not (u == u) or not (v == v):
        return '', ''
    return round(math.hypot(u, v) * 3.6, 1), round((math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0)


def cell(x, nd=1):
    return '' if x is None or not (x == x) else round(x, nd)


def build_rows(kind, run, steps, fields, point_fn):
    rows, missing = [], set()
    want_any = None
    for k, step in enumerate(steps):
        f = fields.get(step) or {}
        if not f:
            missing.add('step %d' % step)
            continue
        if want_any is None:
            want_any = set(f.keys())
        prev = fields.get(steps[k - 1]) if k else None
        prev_step = steps[k - 1] if k else 0
        when = (run + dt.timedelta(hours=step) + AWST).strftime('%Y-%m-%d %H:%M')
        for i, la in enumerate(LATS):
            for j, lo in enumerate(LNGS):
                v = point_fn(kind, f, prev, step, prev_step, i, j)
                lv = v['lv']
                ws10, wd10 = spd_dir(v['u10'], v['v10'])
                row = [la, lo, when]
                row += [cell(lv[p][0]) for p in PLEVELS]
                row += [cell(lv[p][1]) for p in PLEVELS]
                sd = [spd_dir(lv[p][2], lv[p][3]) for p in PLEVELS]
                row += [x[0] for x in sd] + [x[1] for x in sd]
                row += [cell(v['cape'], 0), cell(v['cin'], 0), cell(v['li']), cell(v['gust'], 0), cell(v['precip'], 2),
                        cell(v['psfc'], 1), cell(lv[850][4], 0), cell(lv[700][4], 0), cell(lv[500][4], 0), cell(lv[300][4], 0),
                        cell(v['t2']), cell(v['td2']), ws10, wd10, cell(v['blh'], 0), cell(v['fzl'], 0), cell(v['w700'], 3),
                        cell(v['gh500'], 0), '', '', '', cell(lv[1000][4], 0), cell(lv[925][4], 0), cell(v['tcwv'], 1)]
                rows.append(row)
    log('%s: %d rows (%d steps x %d points)%s' % (kind, len(rows), len(steps) - len([m for m in missing if m.startswith('step')]),
                                                 len(LATS) * len(LNGS), '; missing ' + ', '.join(sorted(missing)) if missing else ''))
    log('%s fields found at the first step: %s' % (kind, ', '.join(sorted(k for k in (want_any or []) if not k.startswith('_')))))
    return {'model': kind, 'run': run.strftime('%Y-%m-%d %Hz'), 'rows': rows, 'missing': sorted(missing)}


def main():
    which = [a for a in sys.argv[1:] if not a.startswith('-')] or ['ECMWF', 'AIFS', 'GFS']
    os.makedirs(OUT_DIR, exist_ok=True)
    ok = 0
    for kind in which:
        t0 = time.time()
        try:
            res = fetch_gfs() if kind == 'GFS' else fetch_ecmwf(kind)
        except Exception as e:  # noqa: BLE001
            log('%s failed: %s' % (kind, e))
            res = None
        if res and res['rows']:
            with open(os.path.join(OUT_DIR, 'raw_%s.json' % kind), 'w') as fh:
                json.dump(res, fh, separators=(',', ':'))
            ok += 1
        log('%s took %.0f s' % (kind, time.time() - t0))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())

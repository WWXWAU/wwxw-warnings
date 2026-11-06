"""
fetch_models.py - West WX Watchers: model data on a 1-degree grid over WA, straight from the source.

Builds the same raw rows the outlook's model sheets hold (rawHeaders_ in Code.gs), for:
  ECMWF  HRES (IFS 0.25) - ECMWF open data, CC BY 4.0
  AIFS   AIFS single     - ECMWF open data, CC BY 4.0
  GFS    GFS 0.25        - NOAA, public domain (AWS open data bucket)
  GEFS   GEFS mean 0.5   - NOAA, public domain (AWS open data bucket)
  ECENS  ECMWF ensemble mean - from Open-Meteo (ECMWF only publishes the mean for a few fields)
Only the pieces of each file that are needed are downloaded (byte ranges from the index files).
Steps: 3-hourly to 48 h, then 6-hourly to 168 h (AIFS is 6-hourly throughout).
Times are written in AWST ('yyyy-MM-dd HH:mm'), like Open-Meteo's.

Output: data/grid1/raw_<MODEL>.json  ({model, run, rows, missing}), then indices.js turns them into the
outlook data file. Run:  python grid1/fetch_models.py [GFS GEFS ECENS AIFS ECMWF]
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
CAPE_LEVELS = [600, 400, 150, 100]                   # extra ECMWF/AIFS levels, only for the CAPE we work out ourselves
# AIFS has no CAPE of its own. We lift a parcel through its temperature/humidity profile instead (derived_cape).
# 'check': worked out for AIFS and HRES and compared with HRES's own CAPE (data/grid1/cape_check.json), not used yet.
# 'on':    AIFS rows get the derived CAPE (times CAPE_SCALE, set from the check).
AIFS_CAPE = os.environ.get('AIFS_CAPE', 'on')          # on from 3 Nov 2026 (first check: corr 0.987, 1000 J/kg agreement 90%)
CAPE_SCALE = float(os.environ.get('CAPE_SCALE', '0.96'))  # HRES own CAPE / derived, from that check
CAPE_CHECK = os.environ.get('CAPE_CHECK', '') == '1'      # also fetch HRES's extra levels and compare (2 runs on 3 Nov: corr 0.98-0.99)
STEPS = list(range(0, 49, 3)) + list(range(54, 169, 6))
STEPS_6H = list(range(0, 169, 6))
AWST = dt.timedelta(hours=8)
WORKERS = 8          # GFS (NOAA's bucket copes)
EC_WORKERS = 6       # spread over the copies (ECMWF's own bucket answers "503 Slow Down" when pushed)
EC_GAP = 4000000     # join ECMWF pieces less than 4 MB apart into one request (fewer requests)

# Every copy of ECMWF's open data (same folder layout). Each step is downloaded from the next copy in turn, so no one
# server gets all the requests (ECMWF's own answers "503 busy" when pushed); a failed piece is tried on the others.
ECMWF_MIRRORS = ['https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com',   # AWS
                 'https://storage.googleapis.com/ecmwf-open-data',          # Google Cloud
                 'https://ai4edataeuwest.blob.core.windows.net/ecmwf',      # Azure
                 'https://data.ecmwf.int/forecasts']                        # ECMWF
GFS_ROOT = 'https://noaa-gfs-bdp-pds.s3.amazonaws.com'
GEFS_ROOT = 'https://noaa-gefs-pds.s3.amazonaws.com'
OPEN_METEO_ENS = 'https://ensemble-api.open-meteo.com/v1/ensemble'

# Time limits, so a slow or busy server can't stop the run publishing (GitHub cancels the job at 2 hours).
# A model that runs out of time keeps the steps it already has; one with too few steps is left out.
START = time.time()
JOB_BUDGET = int(os.environ.get('JOB_BUDGET_MIN', '95')) * 60   # stop downloading anything after this
MODEL_BUDGET = {'AIFS': 80 * 60, 'ECMWF': 95 * 60}     # per model: each runs in its own job now (grid1.yml), so they don't share time
MIN_STEP_SHARE = 0.75                                  # need at least 3/4 of the steps to use a model
DEADLINE = START + JOB_BUDGET


class OutOfTime(Exception):
    pass


def left():
    return DEADLINE - time.time()


def log(*a):
    print(*a, flush=True)


def get(url, rng=None, tries=8):
    """Download (part of) a file; busy replies (429/503 "Slow Down", 5xx) wait and retry with back-off."""
    last = None
    for k in range(tries):
        if left() <= 0:
            raise OutOfTime('out of time')
        try:
            hdr = {'Range': 'bytes=%d-%d' % rng} if rng else {}
            with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 404:
                raise
            wait = e.headers.get('Retry-After') if e.headers else None
            time.sleep(max(0, min(left(), float(wait) if wait and wait.isdigit() else min(60, 3 * 2 ** k) + 3 * random.random())))
        except OutOfTime:
            raise
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(max(0, min(left(), 1 + k + random.random())))
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
            if left() <= 0:
                break
            try:
                buf = get(u, (start, end), tries=3 if alt_urls else 8)   # with other copies to try, don't wait long on a busy one
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
EC_STREAM = {}   # run -> the stream name its HRES files use (found by find_run)


def ec_paths(kind, run, stream=None):
    """HRES 06z/18z files used to be 'scda'; ECMWF's open data now lists them as 'oper' like 00z/12z,
    so both names are tried (find_run remembers which one has the run)."""
    ymd, hh = run.strftime('%Y%m%d'), run.strftime('%H')
    if kind == 'ECMWF':
        stream = stream or EC_STREAM.get(run) or 'oper'
        return '%s/%sz/ifs/0p25/%s/%s%s0000-{s}h-%s-fc' % (ymd, hh, stream, ymd, hh, stream)
    return '%s/%sz/aifs-single/0p25/oper/%s%s0000-{s}h-oper-fc' % (ymd, hh, ymd, hh)


def ec_wanted(kind):
    pl = ['t', 'u', 'v'] + (['r'] if kind == 'ECMWF' else ['q'])
    want = {(p, lv) for p in pl for lv in PLEVELS}
    if kind == 'AIFS' or CAPE_CHECK:   # HRES has its own CAPE: its extra levels only for the check (slow server days)
        want |= {(p, lv) for p in ('t', 'r' if kind == 'ECMWF' else 'q') for lv in CAPE_LEVELS}
    want |= {('w', 700), ('gh', 500)}
    sfc = ['2t', '2d', '10u', '10v', 'sp', 'tp'] + (['mucape', '10fg', 'tcwv'] if kind == 'ECMWF' else ['tcw'])
    return want, set(sfc)


def ec_index(base, step, tries=3):
    txt = get(base.replace('{s}', str(step)) + '.index', tries=tries).decode()
    out = []
    for line in txt.splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def run_steps(kind, run):
    """The steps a run has: on ECMWF open data, HRES's 06z and 18z runs only go out 90 h (until 6 Nov this asked
    for 144 h, so they were never found and HRES sat on 00z/12z, up to ~19 h old); the rest of the week comes
    from the previous full run (see main). AIFS is 6-hourly to 360 h on every run."""
    if kind == 'ECMWF':
        return [s for s in STEPS if s <= 90] if run.hour in (6, 18) else STEPS
    return STEPS_6H if kind == 'AIFS' else STEPS


def find_run(kind, steps):
    """Newest run (last 2 days) whose last wanted step is published, and the copies (mirrors) that have it."""
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
        if kind in ('GFS', 'GEFS'):
            try:
                get(noaa_url(kind, run, steps[-1]) + '.idx')
                return run, None
            except Exception:  # noqa: BLE001
                continue
        last = run_steps(kind, run)[-1]
        streams = ['oper', 'scda'] if kind == 'ECMWF' and run.hour in (6, 18) else [None]
        for st in streams:
            have = []
            for m in ECMWF_MIRRORS:
                try:
                    get('%s/%s.index' % (m, ec_paths(kind, run, st).replace('{s}', str(last))), tries=2)
                    have.append(m)
                except Exception as e:  # noqa: BLE001
                    if '--newest' in sys.argv and kind == 'ECMWF':
                        log('  ECMWF %s %s step %d not on %s: %s' % (run.strftime('%d %Hz'), st or '', last,
                                                                      m.split('/')[2], str(e)[:80]))
            if have:
                if st:
                    EC_STREAM[run] = st
                return run, have
    return None, None


def fetch_ecmwf(kind):
    steps = STEPS if kind == 'ECMWF' else STEPS_6H
    run, mirrors = find_run(kind, steps)
    if not run:
        log('%s: no complete run found.' % kind)
        return None
    steps = run_steps(kind, run)
    bases = ['%s/%s' % (m, ec_paths(kind, run)) for m in mirrors]
    log('%s: run %s, from %d cop%s: %s' % (kind, run.strftime('%Y-%m-%d %Hz'), len(mirrors), 'y' if len(mirrors) == 1 else 'ies',
                                         ', '.join(m.split('/')[2] for m in mirrors)))
    want, sfc = ec_wanted(kind)

    pos = {st: k for k, st in enumerate(steps)}

    def one(step, shift=0):
        """One step: from the copies in turn (step k starts at copy k), the others as stand-ins."""
        k = (pos[step] + shift) % len(bases)
        order = bases[k:] + bases[:k]
        idx = None
        for b in order:
            try:
                idx = ec_index(b, step)
                break
            except OutOfTime:
                raise
            except Exception as e:  # noqa: BLE001
                log('  step %d index (%s): %s' % (step, b.split('/')[2], e))
        if idx is None:
            return step, {}
        items = []
        for o in idx:
            p, lt = o.get('param'), o.get('levtype')
            if lt == 'pl' and (p, int(o.get('levelist', 0) or 0)) in want:
                items.append(('%s%s' % (p, o['levelist']), int(o['_offset']), int(o['_length'])))
            elif lt == 'sfc' and p in sfc:
                items.append((p, int(o['_offset']), int(o['_length'])))
        return step, fetch_fields(order[0].replace('{s}', str(step)) + '.grib2', items, EC_GAP,
                                  [o.replace('{s}', str(step)) + '.grib2' for o in order[1:]])

    fields = {}
    with cf.ThreadPoolExecutor(max_workers=EC_WORKERS) as ex:
        for step, f in ex.map(one, steps):
            fields[step] = f
    again = [s for s in steps if len(fields.get(s) or {}) < 10]
    if again:   # a second, slower pass for steps that came back empty or short
        log('%s: retrying %d step(s) one at a time: %s' % (kind, len(again), again))
        for s in again:
            if left() <= 60:
                log('%s: out of time, %d step(s) left out.' % (kind, len([x for x in again if len(fields.get(x) or {}) < 10])))
                break
            time.sleep(3)
            st, f = one(s, 1)                     # starting from a different copy this time
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
    prof = []                                   # (p, T °C, Td °C), surface upwards, for the derived CAPE
    for p in sorted(PLEVELS + CAPE_LEVELS, reverse=True):
        T = g('t%d' % p) - 273.15
        if kind == 'ECMWF':
            rh = g('r%d' % p)
            e = rh / 100.0 * sat_vap(T) if rh == rh else math.nan
        else:
            q = g('q%d' % p)
            e = q * p / (0.622 + 0.378 * q) if q == q else math.nan
        prof.append((p, T, dew(e)))
    tp_now = g('tp')
    tp_prev = float(prev['tp'][i, j]) if prev is not None and 'tp' in prev else math.nan
    to_mm = 1000.0 if kind == 'ECMWF' else 1.0   # HRES tp is in metres; AIFS tp is already in mm (kg m-2)
    rate = 0.0 if prev is None else max(0.0, (tp_now - tp_prev) * to_mm / max(1, step - prev_step))
    psfc = g('sp') / 100.0
    t700 = lv[700][0]
    dcape = derived_cape(psfc, g('2t') - 273.15, g('2d') - 273.15, prof) if (kind == 'AIFS' or CAPE_CHECK) else math.nan
    cape = g('mucape')
    if kind == 'ECMWF':
        if CAPE_CHECK:
            CAPE_PAIRS.append((cape, dcape))
    else:
        CAPE_AIFS.append(dcape)
        if AIFS_CAPE == 'on' and dcape == dcape:
            cape = dcape * CAPE_SCALE
    return {
        'lv': lv, 'cape': cape, 'cin': math.nan, 'li': math.nan,
        'gust': g('10fg') * 3.6, 'precip': rate, 'psfc': psfc,
        't2': g('2t') - 273.15, 'td2': g('2d') - 273.15, 'u10': g('10u'), 'v10': g('10v'),
        'blh': math.nan, 'fzl': math.nan, 'w700': omega_to_w(g('w700'), 700, t700),
        'gh500': g('gh500'), 'tcwv': g('tcwv') if kind == 'ECMWF' else g('tcw'),
    }


# ---------------------------------------------------------------- GFS (NOAA open data on AWS)
def noaa_url(kind, run, step):
    ymd, hh = run.strftime('%Y%m%d'), run.strftime('%H')
    if kind == 'GEFS':   # GEFS ensemble mean (31 members), 0.5 degree
        return '%s/gefs.%s/%s/atmos/pgrb2ap5/geavg.t%sz.pgrb2a.0p50.f%03d' % (GEFS_ROOT, ymd, hh, hh, step)
    return '%s/gfs.%s/%s/atmos/gfs.t%sz.pgrb2.0p25.f%03d' % (GFS_ROOT, ymd, hh, hh, step)


GFS_SFC = {('CAPE', 'surface'): 'cape', ('CIN', 'surface'): 'cin', ('LFTX', 'surface'): 'li',
           ('GUST', 'surface'): 'gust', ('APCP', 'surface'): 'apcp', ('PRES', 'surface'): 'sp',
           ('TMP', '2 m above ground'): 't2', ('DPT', '2 m above ground'): 'td2',
           ('UGRD', '10 m above ground'): 'u10', ('VGRD', '10 m above ground'): 'v10',
           ('HPBL', 'surface'): 'blh', ('HGT', '0C isotherm'): 'fzl', ('VVEL', '700 mb'): 'w700',
           ('HGT', '500 mb'): 'gh500', ('PWAT', 'entire atmosphere (considered as a single layer)'): 'pwat'}
# GEFS's smaller file: CAPE/CIN may only be for the lowest 180 hPa, and 2 m humidity instead of dewpoint
GEFS_SFC = dict(GFS_SFC)
GEFS_SFC.update({('CAPE', '180-0 mb above ground'): 'cape', ('CIN', '180-0 mb above ground'): 'cin',
                 ('RH', '2 m above ground'): 'rh2'})


def fetch_gfs(kind='GFS'):
    run, _ = find_run(kind, STEPS)
    if not run:
        log('%s: no complete run found.' % kind)
        return None
    log('%s: run %s' % (kind, run.strftime('%Y-%m-%d %Hz')))
    sfc_map = GEFS_SFC if kind == 'GEFS' else GFS_SFC

    def one(step):
        url = noaa_url(kind, run, step)
        try:
            lines = get(url + '.idx').decode().splitlines()
        except Exception as e:  # noqa: BLE001
            log('  %s step %d index: %s' % (kind, step, e))
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
            if (var, lev) in sfc_map and not (var == 'APCP' and 'acc' not in fc):
                name = sfc_map[(var, lev)]
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
    return build_rows(kind, run, STEPS, fields, gfs_point)


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
        't2': g('t2') - 273.15, 'td2': td2_of(g('t2') - 273.15, g('td2') - 273.15, g('rh2')), 'u10': g('u10'), 'v10': g('v10'),
        'blh': g('blh'), 'fzl': g('fzl'), 'w700': omega_to_w(g('w700'), 700, lv[700][0]),
        'gh500': g('gh500'), 'tcwv': g('pwat'),
    }


def td2_of(t2, td2, rh2):
    """2 m dewpoint: the model's own, or from 2 m humidity (GEFS)."""
    if td2 == td2:
        return td2
    if rh2 == rh2 and t2 == t2:
        return dew(rh2 / 100.0 * sat_vap(t2))
    return math.nan


# ---------------------------------------------------------------- ECENS: ECMWF ensemble mean, via Open-Meteo
# ECMWF publishes the ensemble mean for only a few fields, and averaging the 51 members ourselves would mean
# ~50 GB of downloads a run. Open-Meteo already averages them, and with the other four models off Open-Meteo
# its free allowance has room for this one at 1 degree. Same variables and rows as Code.gs (fetchModelData).
ECENS_IDS = ['ecmwf_ifs025_ensemble_mean', 'ecmwf_ifs_ensemble_mean_seamless']
ECENS_VARS = ([('temperature_%dhPa' % p) for p in PLEVELS] + [('dew_point_%dhPa' % p) for p in PLEVELS]
              + [('wind_speed_%dhPa' % p) for p in PLEVELS] + [('wind_direction_%dhPa' % p) for p in PLEVELS]
              + ['relative_humidity_850hPa', 'relative_humidity_700hPa', 'relative_humidity_500hPa', 'relative_humidity_300hPa',
                 'cape', 'wind_gusts_10m', 'precipitation', 'surface_pressure', 'temperature_2m', 'dew_point_2m',
                 'wind_speed_10m', 'wind_direction_10m', 'freezing_level_height', 'geopotential_height_500hPa',
                 'vertical_velocity_700hPa', 'relative_humidity_1000hPa', 'relative_humidity_925hPa', 'convective_inhibition'])


def om_get(url):
    last = None
    for k in range(6):
        try:
            with urllib.request.urlopen(url, timeout=180) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            last = e
            body = ''
            try:
                body = e.read().decode()[:200]
            except Exception:  # noqa: BLE001
                pass
            if e.code == 400:
                raise RuntimeError('Open-Meteo refused the request: ' + body)
            time.sleep(min(90, 10 * 2 ** k))   # 429 (too many) or 5xx: wait and retry
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(5 + 5 * k)
    raise last


def near(arr, t):
    """Value at hour t, or the nearest within 2 hours (3/6-hourly ensemble output), as Code.gs safeGetNear."""
    if not arr:
        return ''
    for o in (0, 1, -1, 2, -2):
        if 0 <= t + o < len(arr) and arr[t + o] is not None:
            return arr[t + o]
    return ''


def fetch_ecens():
    pts = [(la, lo) for la in LATS for lo in LNGS]
    rows, used, done = [], None, 0
    for b in range(0, len(pts), 100):
        batch = pts[b:b + 100]
        data = None
        for mid in ([used] if used else ECENS_IDS):
            url = (OPEN_METEO_ENS + '?latitude=' + ','.join('%g' % p[0] for p in batch) + '&longitude=' + ','.join('%g' % p[1] for p in batch)
                   + '&hourly=' + ','.join(ECENS_VARS) + '&forecast_days=8&timezone=Australia%2FPerth&wind_speed_unit=kmh&models=' + mid)
            try:
                d = om_get(url)
            except Exception as e:  # noqa: BLE001
                log('ECENS (%s): %s' % (mid, e))
                continue
            d = d if isinstance(d, list) else [d]
            if any((x.get('hourly') or {}).get('temperature_850hPa') for x in d):
                data, used = d, mid
                break
        if not data:
            log('ECENS: points %d-%d not fetched.' % (b, b + len(batch) - 1))
            continue
        for (la, lo), d in zip(batch, data):
            h = d.get('hourly') or {}
            times = h.get('time') or []
            t = 2   # 02:00 AWST = 18 UTC, so the times line up with the other models (3-hourly to 48 h, then 6-hourly)
            while t < len(times):
                g = lambda k: near(h.get(k), t)  # noqa: E731
                row = [la, lo, str(times[t]).replace('T', ' ')]
                for k in ('temperature', 'dew_point', 'wind_speed', 'wind_direction'):
                    row += [g('%s_%dhPa' % (k, p)) for p in PLEVELS]
                row += [g('cape'), g('convective_inhibition'), '', g('wind_gusts_10m'), g('precipitation'), g('surface_pressure'),
                        g('relative_humidity_850hPa'), g('relative_humidity_700hPa'), g('relative_humidity_500hPa'), g('relative_humidity_300hPa'),
                        g('temperature_2m'), g('dew_point_2m'), g('wind_speed_10m'), g('wind_direction_10m'),
                        '', g('freezing_level_height'), g('vertical_velocity_700hPa'), g('geopotential_height_500hPa'),
                        '', '', '', g('relative_humidity_1000hPa'), g('relative_humidity_925hPa'), '']
                rows.append(row)
                t += 3 if t < 48 else 6
        done += len(batch)
        time.sleep(3)
    log('ECENS: %d rows for %d of %d points (Open-Meteo model %s)' % (len(rows), done, len(pts), used))
    if not rows:
        return None
    return {'model': 'ECENS', 'run': 'Open-Meteo ' + dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%MZ'), 'rows': rows, 'missing': []}


# ---------------------------------------------------------------- shared
def sat_vap(t):
    return 6.112 * math.exp(17.67 * t / (t + 243.5))


def dew(e):
    if not (e == e) or e <= 0:
        return math.nan
    lg = math.log(e / 6.112)
    return 243.5 * lg / (17.67 - lg)


# ---------------------------------------------------------------- CAPE from a profile (for AIFS)
CAPE_PAIRS = []      # (HRES's own MUCAPE, derived from HRES's profile), to check and scale the derived CAPE
CAPE_AIFS = []       # derived CAPE for AIFS
RD, CP, LV, EPS = 287.04, 1005.7, 2.501e6, 0.622


def _mix(e, p):
    return EPS * e / max(p - e, 1e-3)


def _tv(tk, r):
    return tk * (1 + r / EPS) / (1 + r)


def _env_at(prof, p):
    """Environment (T °C, Td °C) at pressure p, linear in ln p between profile levels."""
    for (p1, t1, d1), (p2, t2, d2) in zip(prof, prof[1:]):
        if p2 <= p <= p1:
            f = math.log(p1 / p) / math.log(p1 / p2) if p1 != p2 else 0
            return t1 + f * (t2 - t1), d1 + f * (d2 - d1)
    return math.nan, math.nan


def _moist_step(tk, p, dp):
    """Pseudo-adiabatic ascent from p to p - dp (hPa), RK2."""
    def rate(t, pp):
        es = sat_vap(t - 273.15)
        rs = _mix(es, pp)
        return (RD * t + LV * rs) / (pp * (CP + LV * LV * rs * EPS / (RD * t * t)))
    k1 = rate(tk, p)
    k2 = rate(tk - 0.5 * dp * k1, p - 0.5 * dp)
    return tk - dp * k2


def derived_cape(psfc, t2, td2, levels, dp=10.0):
    """Most-unstable CAPE (J/kg) from a coarse profile: the parcel with the highest theta-e in the lowest
    300 hPa (2 m or a pressure level above the ground) is lifted dry to its LCL, then pseudo-adiabatically
    to 100 hPa; positive buoyancy (virtual temperature) above the parcel's start is added up."""
    if not (psfc == psfc and t2 == t2 and td2 == td2):
        return math.nan
    prof = [(psfc, t2, min(td2, t2))] + [(p, t, min(d, t)) for p, t, d in levels if p < psfc - 1 and t == t and d == d]
    if len(prof) < 5 or prof[-1][0] > 200:
        return math.nan
    best, src = -1e9, None
    for p, t, d in prof:
        if p < psfc - 300:
            break
        e = sat_vap(d)
        r = _mix(e, p)
        tk = t + 273.15
        tl = 1.0 / (1.0 / (d + 273.15 - 56.0) + math.log(tk / (d + 273.15)) / 800.0) + 56.0
        the = tk * (1000.0 / p) ** (0.2854 * (1 - 0.28 * r)) * math.exp((3376.0 / tl - 2.54) * r * (1 + 0.81 * r))
        if the > best:
            best, src = the, (p, tk, r, tl)
    p0, tk0, r0, tl = src
    plcl = p0 * (tl / tk0) ** (1.0 / 0.2854)
    cape, p, tk = 0.0, p0, tk0
    top = prof[-1][0]
    while p - dp >= top:
        pn = p - dp
        if pn >= plcl:                                     # dry, mixing ratio kept
            tkn = tk0 * (pn / p0) ** 0.2854
            rp = r0
        else:
            if p > plcl:                                   # crossing the LCL: start from it
                tk, p = tl, plcl
                if p - pn <= 0:
                    p = pn
            tkn = _moist_step(tk, p, p - pn) if p > pn else tk
            rp = _mix(sat_vap(tkn - 273.15), pn)
        te, de = _env_at(prof, pn)
        if te == te:
            tve = _tv(te + 273.15, _mix(sat_vap(de), pn))
            b = _tv(tkn, rp) - tve
            if b > 0:
                cape += RD * b * math.log((pn + dp) / pn)
        p, tk = pn, tkn
    return cape


def cape_check():
    """How the derived CAPE compares with HRES's own (same profile levels) -> dict for cape_check.json."""
    pr = [(a, b) for a, b in CAPE_PAIRS if a == a and b == b]
    out = {'made': dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'aifs_mode': AIFS_CAPE, 'scale': CAPE_SCALE, 'n': len(pr)}
    if len(pr) < 50:
        return out
    a = np.array([x[0] for x in pr]); b = np.array([x[1] for x in pr])
    big = a >= 250
    out['corr'] = round(float(np.corrcoef(a, b)[0, 1]), 3)
    out['median_ratio_250plus'] = round(float(np.median(b[big] / a[big])), 3) if big.sum() >= 20 else None
    out['scale_suggested'] = round(float(np.sum(a[big]) / max(np.sum(b[big]), 1)), 3) if big.sum() >= 20 else None
    out['mean_hres'], out['mean_derived'] = round(float(a.mean()), 1), round(float(b.mean()), 1)
    for th in (250, 1000, 2500):   # does the derived CAPE put the same points over each threshold?
        x, y = a >= th, b >= th
        h, m, f = int((x & y).sum()), int((x & ~y).sum()), int((~x & y).sum())
        out['agree_%d' % th] = {'both': h, 'hres_only': m, 'derived_only': f, 'csi': round(h / max(h + m + f, 1), 3)}
    if CAPE_AIFS:
        c = np.array([x for x in CAPE_AIFS if x == x])
        out['aifs'] = {'n': int(c.size), 'mean': round(float(c.mean()), 1), 'p90': round(float(np.percentile(c, 90)), 0),
                       'share_250plus': round(float((c >= 250).mean()), 3)}
    return out


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


PREV_DIR = os.environ.get('PREV_DIR', 'prev')   # the last published raw files (grid1-data branch), for stand-ins
PREV_MAX_H = 36                                  # a stand-in run can be at most this old


def run_time(run):
    """'2026-11-03 12z' or 'Open-Meteo 2026-11-03 02:41Z' -> datetime (UTC), else None."""
    m = re.search(r'(\d{4}-\d\d-\d\d) (\d\d)(?::(\d\d))?[zZ]', run or '')
    if not m:
        return None
    return dt.datetime.strptime(m.group(1), '%Y-%m-%d') + dt.timedelta(hours=int(m.group(2)), minutes=int(m.group(3) or 0))


def prev_raw(kind):
    import gzip
    path = os.path.join(PREV_DIR, 'raw_%s.json.gz' % kind)
    if not os.path.exists(path):
        return None
    try:
        with gzip.open(path, 'rt') as fh:
            return json.load(fh)
    except Exception as e:  # noqa: BLE001
        log('%s: previous run not readable (%s)' % (kind, e))
        return None


def previous(kind):
    """The last published run of a model, if it isn't too old (used when this run's download fell short)."""
    res = prev_raw(kind)
    if not res:
        return None
    rt = run_time(res.get('run'))
    age = (dt.datetime.utcnow() - rt).total_seconds() / 3600 if rt else 999
    if age > PREV_MAX_H:
        log('%s: previous run %s is %.0f h old: too old to stand in.' % (kind, res.get('run'), age))
        return None
    res['fallback'] = True
    log('%s: using the previous run instead (%s, %.0f h old).' % (kind, res.get('run'), age))
    return res


def newest():
    """--newest: the newest run each model has out now (the hourly check compares it with what's published)."""
    out = {}
    for kind in ('GFS', 'GEFS', 'AIFS', 'ECMWF'):
        try:
            run, _ = find_run(kind, STEPS_6H if kind == 'AIFS' else STEPS)
            out[kind] = run.strftime('%Y-%m-%d %Hz') if run else None
        except Exception as e:  # noqa: BLE001
            log('%s: %s' % (kind, e))
            out[kind] = None
    print(json.dumps(out))
    return 0


def main():
    if '--newest' in sys.argv:
        return newest()
    which = [a for a in sys.argv[1:] if not a.startswith('-')] or ['GFS', 'GEFS', 'ECENS', 'AIFS', 'ECMWF']
    os.makedirs(OUT_DIR, exist_ok=True)
    global DEADLINE
    ok = 0
    for kind in which:
        t0 = time.time()
        DEADLINE = min(START + JOB_BUDGET, t0 + MODEL_BUDGET.get(kind, JOB_BUDGET))
        if left() <= 60:
            log('%s skipped: the run is out of time.' % kind)
            continue
        try:
            res = (fetch_gfs(kind) if kind in ('GFS', 'GEFS') else fetch_ecens() if kind == 'ECENS' else fetch_ecmwf(kind))
        except Exception as e:  # noqa: BLE001
            log('%s failed: %s' % (kind, e))
            res = None
        nsteps = (len(run_steps(kind, run_time(res['run']))) if res and run_time(res['run']) else len(STEPS if kind == 'ECMWF' else STEPS_6H)) if kind in ('ECMWF', 'AIFS') else 0
        if res and res['rows'] and nsteps:
            have = nsteps - len([m for m in res.get('missing', []) if m.startswith('step')])
            if have < MIN_STEP_SHARE * nsteps:
                log('%s left out: only %d of %d steps came through.' % (kind, have, nsteps))
                res = None
        if not (res and res['rows']):
            res = previous(kind)
        elif kind == 'ECMWF' and run_time(res['run']) and run_time(res['run']).hour in (6, 18):
            # a 90 h run: the rest of the week from the previous full run (its rows are in AWST times, so only later ones)
            pr = prev_raw(kind)
            if pr and pr.get('rows') and pr.get('run') != res['run']:
                last = max(r[2] for r in res['rows'])
                tail = [r for r in pr['rows'] if r[2] > last]
                res['rows'] += tail
                res['tail'] = pr['run']
                log('ECMWF: %d rows after %s from the previous run (%s) to finish the week.' % (len(tail), last, pr['run']))
        if res and res['rows']:
            res.setdefault('fallback', False)
            with open(os.path.join(OUT_DIR, 'raw_%s.json' % kind), 'w') as fh:
                json.dump(res, fh, separators=(',', ':'))
            ok += 1
        log('%s took %.0f s' % (kind, time.time() - t0))
    if CAPE_PAIRS or CAPE_AIFS:
        chk = cape_check()
        log('Derived CAPE check: ' + json.dumps(chk))
        with open(os.path.join(OUT_DIR, 'cape_check.json'), 'w') as fh:
            json.dump(chk, fh)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())

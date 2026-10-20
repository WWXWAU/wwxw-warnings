"""
ens_storms.py - West WX Watchers: ECMWF ensemble chance of storms over WA.

Free ECMWF open data (CC BY 4.0). For every member of the latest ensemble run (51 members) it downloads
just two fields - most-unstable CAPE (mucape) and total rain (tp) - every 6 hours out to 78 hours,
using the index files so only those pieces are fetched.

A member "has storms" in a 6-hour window when MUCAPE >= 250 J/kg (at either end of the window)
AND at least 1 mm of rain falls in the window. For each 1-degree point over WA and each 9am-to-9am day
(AWST), the chance of storms = the share of members with storms within about 80 km (+/-0.75 degrees),
the same "near this point" idea the West WX Watchers lightning check uses.

Output: data/ens_storms.json (small), read by the convective outlook.
"""
import concurrent.futures as cf
import datetime as dt
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request

import numpy as np

MIRRORS = ['https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com',   # ECMWF's AWS mirror (fast)
           'https://data.ecmwf.int/forecasts']
OUT = 'data/ens_storms.json'
STEPS = list(range(0, 79, 6))            # 0..78 h, 6-hourly
PARAMS = ('mucape', 'tp')
CAPE_MIN = 250.0                         # J/kg
RAIN_MIN_MM = 1.0                        # mm in 6 hours
RADIUS = 0.75                            # degrees either side (about 80 km)
LATS = [float(x) for x in range(-13, -36, -1)]      # output grid, 1 degree
LNGS = [float(x) for x in range(113, 130)]
BOX = (-10.0, -38.0, 110.0, 132.0)       # north, south, west, east: area kept from each field
AWST = dt.timedelta(hours=8)


WORKERS = 6                              # downloads at once (the mirror says "Slow Down" above about 10)
MIN_MEMBERS = 30                         # at least this many complete members, or no file is written


def get(url, rng=None, tries=6):
    """Download (part of) a file. Busy replies (429/5xx, e.g. "503 Slow Down") wait and retry with back-off."""
    last = None
    for k in range(tries):
        try:
            hdr = {'Range': 'bytes=%d-%d' % rng} if rng else {}
            with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=90) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 404:
                raise
            wait = e.headers.get('Retry-After') if e.headers else None
            time.sleep(float(wait) if wait and wait.isdigit() else min(30, 2 ** (k + 1)) + random.random())
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1 + k + random.random())
    raise last


def file_base(mirror, run):
    ymd, hh = run.strftime('%Y%m%d'), run.strftime('%H')
    return '%s/%s/%sz/ifs/0p25/enfo/%s%s0000-' % (mirror, ymd, hh, ymd, hh)


def find_run():
    """Newest run whose last step is published, and a mirror that has it."""
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    for back in range(4):
        t = now - dt.timedelta(hours=12 * back)
        run = t.replace(hour=12 if t.hour >= 12 else 0, minute=0, second=0, microsecond=0)
        for m in MIRRORS:
            try:
                get(file_base(m, run) + '%dh-enfo-ef.index' % STEPS[-1])
                return run, m
            except Exception:  # noqa: BLE001
                pass
    return None, None


def wanted(index_text):
    """(param, member, offset, length) for mucape and tp, control (0) and members 1-50."""
    out = []
    for line in index_text.splitlines():
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if o.get('param') in PARAMS and o.get('type') in ('cf', 'pf'):
            out.append((o['param'], int(o.get('number', 0) or 0), int(o['_offset']), int(o['_length'])))
    return out


def decode(buf):
    """GRIB message -> (2-D array over BOX, lats, lngs)."""
    import eccodes
    gid = eccodes.codes_new_from_message(buf)
    try:
        ni, nj = eccodes.codes_get(gid, 'Ni'), eccodes.codes_get(gid, 'Nj')
        la1 = eccodes.codes_get(gid, 'latitudeOfFirstGridPointInDegrees')
        lo1 = eccodes.codes_get(gid, 'longitudeOfFirstGridPointInDegrees')
        di = eccodes.codes_get(gid, 'iDirectionIncrementInDegrees')
        dj = eccodes.codes_get(gid, 'jDirectionIncrementInDegrees')
        vals = eccodes.codes_get_values(gid).reshape(nj, ni)
    finally:
        eccodes.codes_release(gid)
    lats = la1 - dj * np.arange(nj)
    lngs = (lo1 + di * np.arange(ni) + 180.0) % 360.0 - 180.0
    r = np.where((lats <= BOX[0]) & (lats >= BOX[1]))[0]
    c = np.where((lngs >= BOX[2]) & (lngs <= BOX[3]))[0]
    return vals[np.ix_(r, c)], lats[r], lngs[c]


def main():
    prev = None
    if os.path.exists(OUT):
        try:
            prev = json.load(open(OUT)).get('run')
        except ValueError:
            pass
    run, mirror = find_run()
    if not run:
        print('No complete ensemble run found yet.')
        return 0
    run_id = run.strftime('%Y-%m-%d %Hz')
    if prev == run_id and '--force' not in sys.argv:
        print('Already have run %s.' % run_id)
        return 0
    print('Run %s from %s' % (run_id, mirror))

    jobs = []                                   # (step, param, member, offset, length)
    for s in STEPS:
        idx = get(file_base(mirror, run) + '%dh-enfo-ef.index' % s).decode()
        for p, n, off, ln in wanted(idx):
            jobs.append((s, p, n, off, ln))
    print('%d fields to fetch' % len(jobs))

    fields, grid = {}, {}

    others = [m for m in MIRRORS if m != mirror]

    def fetch(job):
        s, p, n, off, ln = job
        for m in [mirror] + others:      # the same file has the same index on both servers
            try:
                buf = get(file_base(m, run) + '%dh-enfo-ef.grib2' % s, (off, off + ln - 1))
                a, la, lo = decode(buf)
                return job, a, la, lo
            except Exception as e:  # noqa: BLE001
                err = e
        print('  could not fetch %s step %d member %d: %s' % (p, s, n, err))
        return job, None, None, None

    failed = 0
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for job, a, la, lo in ex.map(fetch, jobs):
            if a is None:
                failed += 1
                continue
            fields[(job[0], job[1], job[2])] = a
            grid['lat'], grid['lng'] = la, lo
    if failed:
        print('%d of %d fields could not be fetched' % (failed, len(jobs)))

    # keep only members with every field (a member with a gap would undercount its storms)
    every = [(s, p) for s in STEPS for p in PARAMS]
    members = sorted(n for n in {k[2] for k in fields} if all((s, p, n) in fields for s, p in every))
    if len(members) < MIN_MEMBERS:
        print('Only %d complete members (need %d): keeping the previous file.' % (len(members), MIN_MEMBERS))
        return 1
    lat, lng = grid['lat'], grid['lng']
    storm = {}                                  # period date -> {member: bool grid}
    windows = {}                                # period date -> number of 6-hour windows covered
    for s in STEPS[1:]:
        mid = run + dt.timedelta(hours=s - 3) + AWST           # middle of the window, AWST
        period = (mid - dt.timedelta(hours=9)).date().isoformat()   # 9am-to-9am day it falls in
        windows[period] = windows.get(period, 0) + 1
        for n in members:
            cape0, cape1 = fields.get((s - 6, 'mucape', n)), fields.get((s, 'mucape', n))
            tp0 = fields.get((s - 6, 'tp', n)) if s - 6 > 0 else 0.0
            tp1 = fields.get((s, 'tp', n))
            if cape1 is None or tp1 is None:
                continue
            cape = cape1 if cape0 is None else np.maximum(cape0, cape1)
            rain = (tp1 - tp0) * 1000.0                         # metres -> mm
            hit = (cape >= CAPE_MIN) & (rain >= RAIN_MIN_MM)
            d = storm.setdefault(period, {})
            d[n] = hit if n not in d else (d[n] | hit)

    out = {'run': run_id, 'made': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
           'members': len(members), 'source': 'ECMWF ensemble (ENS) open data, CC BY 4.0',
           'rule': 'MUCAPE >= %d J/kg and >= %g mm rain in 6 h, within %g deg' % (CAPE_MIN, RAIN_MIN_MM, RADIUS),
           'lat': LATS, 'lng': LNGS, 'periods': [], 'p': {}}
    for period in sorted(storm):
        if windows[period] < 2:                 # barely covered by this run: leave out
            continue
        grid_p = []
        for la in LATS:
            row = []
            r = np.where(np.abs(lat - la) <= RADIUS + 1e-6)[0]
            for lo in LNGS:
                c = np.where(np.abs(lng - lo) <= RADIUS + 1e-6)[0]
                cnt = sum(1 for n in storm[period] if storm[period][n][np.ix_(r, c)].any())
                row.append(int(round(100.0 * cnt / len(members))))
            grid_p.append(row)
        out['periods'].append({'date': period, 'windows': windows[period]})
        out['p'][period] = grid_p
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        json.dump(out, f, separators=(',', ':'))
    print('Wrote %s: %d days, %d members.' % (OUT, len(out['periods']), len(members)))
    return 0


if __name__ == '__main__':
    sys.exit(main())

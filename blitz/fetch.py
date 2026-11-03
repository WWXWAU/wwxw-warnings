"""Blitzortung (Oceania, Strikes_2) -> the WA strikes for one 9am-9am AWST day, for the outlook's lightning check.

Participant data: https://data.blitzortung.org/Data/Protected/Strikes_2/ (login in the BLITZ_USER / BLITZ_PASS
secrets). The folders are walked from their index pages (year/month/day/hour/files), so the exact file naming
doesn't matter. Each file holds one strike per line (JSON): time (ns), lat, lon, mds (timing deviation, ns),
mcg (largest gap in degrees between the detecting stations around the strike) and sig (the stations).

Output: data/blitz/<period>.json, period = the date the 9am-9am day starts (same as the outlook's verification).
Only counts per grid point are saved (this repository is public, and Blitzortung's raw strikes are for participants):
  pts: {"lat,lng": [strikes within 75 km, of those with mcg <= 180, strikes within 100 km, of those with mcg <= 180]}
for every whole-degree point from 12-36S, 111-130E that had any (75 km = the 1-degree squares, 100 km = the 2-degree ones).
mcg <= 180 = detecting stations on more than one side of the strike (a better fix).

Usage: python blitz/fetch.py [YYYY-MM-DD[..YYYY-MM-DD]]   (default: yesterday's period, i.e. the day that ended at 9am today;
       a range backfills several days in one run)
"""
import base64, datetime as dt, gzip, json, math, os, re, sys, time, urllib.request, urllib.error

BASE = 'https://data.blitzortung.org/Data/Protected/Strikes_2/'
BOX = (-37.0, -12.0, 110.0, 131.0)          # lat min/max, lng min/max: WA and a margin
AWST = dt.timedelta(hours=8)
OUT = 'data/blitz'
AUTH = 'Basic ' + base64.b64encode(('%s:%s' % (os.environ.get('BLITZ_USER', ''), os.environ.get('BLITZ_PASS', ''))).encode()).decode()


def get(url, tries=4):
    last = None
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'Authorization': AUTH, 'User-Agent': 'wwxw-verify'}), timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                sys.exit('Login refused (HTTP %d): check the BLITZ_USER and BLITZ_PASS secrets.' % e.code)
            if e.code == 404:
                return None
            last = e
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(3 * (k + 1))
    print('  gave up on %s: %s' % (url, last), flush=True)
    return None


def links(url):
    b = get(url)
    if b is None:
        return []
    return [h for h in re.findall(r'href="([^"?/][^"]*)"', b.decode('utf-8', 'replace')) if not h.startswith('http') and h != '../']


def km(a1, o1, a2, o2):
    p1, p2 = math.radians(a1), math.radians(a2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(o2 - o1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def parse(raw):
    if raw[:2] == b'\x1f\x8b':
        raw = gzip.decompress(raw)
    for line in raw.decode('utf-8', 'replace').splitlines():
        line = line.strip()
        if not line.startswith('{'):
            continue
        try:
            yield json.loads(line)
        except ValueError:
            pass


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ''
    if arg:
        a, _, b = arg.partition('..')
        d0, d1 = dt.date.fromisoformat(a), dt.date.fromisoformat(b or a)
    else:
        now_awst = dt.datetime.utcnow() + AWST
        d0 = d1 = (now_awst - dt.timedelta(hours=9)).date() - dt.timedelta(days=1)
    ok = 0
    while d0 <= d1:
        ok += one_day(d0)
        d0 += dt.timedelta(days=1)
    if not ok:
        sys.exit('No files found: has the folder layout changed?')


def one_day(period):
    start = dt.datetime.combine(period, dt.time(9)) - AWST          # UTC
    end = start + dt.timedelta(days=1)
    print('Period %s: %s to %s UTC' % (period, start, end), flush=True)

    files, strikes, seen, hours = 0, [], set(), 0
    h = start.replace(minute=0)
    while h < end:
        hdir = BASE + h.strftime('%Y/%m/%d/%H/')
        names = sorted(n for n in links(hdir) if not n.endswith('/'))
        hours += 1 if names else 0
        for n in names:
            raw = get(hdir + n)
            if raw is None:
                continue
            files += 1
            for s in parse(raw):
                try:
                    t = s['time'] / 1e9
                    la, lo = float(s['lat']), float(s['lon'])
                except (KeyError, TypeError, ValueError):
                    continue
                if not (BOX[0] <= la <= BOX[1] and BOX[2] <= lo <= BOX[3]):
                    continue
                ts = dt.datetime.utcfromtimestamp(t)
                if not (start <= ts < end) or s['time'] in seen:
                    continue
                seen.add(s['time'])
                strikes.append([round((ts - start).total_seconds() / 60, 1), round(la, 3), round(lo, 3),
                                len(s.get('sig') or []), s.get('mcg'), round((s.get('mds') or 0) / 1000, 1)])
        h += dt.timedelta(hours=1)

    pts = {}
    for la0 in range(-36, -11):
        for lo0 in range(111, 131):
            c = [0, 0, 0, 0]
            for s in strikes:
                if abs(s[1] - la0) > 1 or abs(s[2] - lo0) > 1.2:
                    continue
                d = km(la0, lo0, s[1], s[2])
                q = (s[4] if s[4] is not None else 360) <= 180
                if d <= 75:
                    c[0] += 1; c[1] += q
                if d <= 100:
                    c[2] += 1; c[3] += q
            if c[2]:
                pts['%d,%d' % (la0, lo0)] = c
    if not files:
        print('%s: no files (not in the archive?)' % period)
        return 0
    os.makedirs(OUT, exist_ok=True)
    out = {'period': period.isoformat(), 'source': 'Blitzortung.org (Oceania, participant data)', 'made': dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'),
           'hours': hours, 'files': files, 'total': len(strikes), 'cols': ['n75', 'n75_mcg180', 'n100', 'n100_mcg180'], 'pts': pts}
    with open(os.path.join(OUT, '%s.json' % period), 'w') as fh:
        json.dump(out, fh, separators=(',', ':'))
    good = len([s for s in strikes if (s[4] or 360) <= 180])
    print('%s: %d hour folders, %d files, %d WA-area strikes (%d with mcg <= 180), %d grid points with any.' % (period, hours, files, len(strikes), good, len(pts)))
    return 1 if files else 0


if __name__ == '__main__':
    main()

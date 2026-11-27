"""
WA weather balloons (radiosondes) for the outlook nowcast and the Skew-T views (Nov 2026).

The Bureau launches balloons at about 7 am and 7 pm WST (23 and 11 UTC; some stations at 00/12 UTC). The same data
goes out on the international weather network, and the University of Wyoming upper-air archive republishes it as
text within an hour or two of launch. We read that (weather.uwyo.edu), not the Bureau's website.

  python grid1/sondes.py out/sondes.json

For each station, the newest flight in the last 15 hours: every level thinned to about 10 hPa (pressure, height,
temperature, dew point, wind direction and speed in km/h), and the values at the outlook's levels.
"""
import datetime as dt, json, re, sys, time, urllib.request

STATIONS = {   # WMO id: (name, lat, lng)
    '94610': ('Perth Airport', -31.93, 115.98), '94802': ('Albany', -34.94, 117.80), '94638': ('Esperance', -33.83, 121.89),
    '94403': ('Geraldton', -28.80, 114.70), '94302': ('Learmonth', -22.24, 114.10), '94312': ('Port Hedland', -20.37, 118.63),
    '94203': ('Broome', -17.95, 122.24), '94461': ('Giles', -25.03, 128.30), '94637': ('Kalgoorlie', -30.78, 121.45),
    '94212': ('Halls Creek', -18.23, 127.66), '94430': ('Meekatharra', -26.61, 118.54), '94300': ('Carnarvon', -24.89, 113.67),
    '94646': ('Forrest', -30.84, 128.11)}
LEVELS = [1000, 925, 850, 700, 500, 300, 250, 200]
URL = 'https://weather.uwyo.edu/wsgi/sounding?datetime=%s&id=%s&type=TEXT:LIST'


def log(*a): print(*a, flush=True)


def fetch(sid, when):
    url = URL % (when.strftime('%Y-%m-%d%%20%H:00:00'), sid)
    for k in range(3):
        try:
            return urllib.request.urlopen(url, timeout=60).read().decode('utf-8', 'replace')
        except Exception as e:  # noqa: BLE001
            if k == 2: log('  %s %s: %s' % (sid, when, e)); return ''
            time.sleep(5)


def parse(html, when):
    m = re.search(r'Observations for Station (\d+) at (\d+) UTC (\d+) (\w+) (\d{4})', html)
    if not m: return None
    got = dt.datetime.strptime('%s %s %s %s' % (m.group(3), m.group(4), m.group(5), m.group(2)), '%d %b %Y %H').replace(tzinfo=dt.timezone.utc)
    if abs((got - when).total_seconds()) > 3 * 3600: return None   # the site gives the nearest flight; only take this one
    pre = re.search(r'<PRE>(.*?)</PRE>', html, re.S | re.I)
    rows = []
    for ln in (pre.group(1) if pre else html).splitlines():
        if not re.match(r'^\s*\d{3,4}\.\d', ln): continue
        f = lambda a, b: (ln[a:b].strip() or None)
        try:
            p = float(f(0, 7)); z = f(7, 14); T = f(14, 21); Td = f(21, 28); d = f(42, 49); s = f(49, 56)
            rows.append([p, None if z is None else int(float(z)), None if T is None else float(T), None if Td is None else float(Td),
                         None if d is None else int(float(d)), None if s is None else round(float(s) * 3.6)])   # m/s -> km/h
        except ValueError:
            continue
    rows = [r for r in rows if r[2] is not None]
    if len(rows) < 20 or rows[-1][0] > 400: return None   # too short to use (burst early)
    return got, rows


def at(rows, p, i):
    """Value i (2 temp, 3 dew) at pressure p, interpolated in log-pressure."""
    import math
    for a, b in zip(rows, rows[1:]):
        if a[0] >= p >= b[0] and a[i] is not None and b[i] is not None:
            if a[0] == b[0]: return a[i]
            w = (math.log(a[0]) - math.log(p)) / (math.log(a[0]) - math.log(b[0]))
            return round(a[i] + w * (b[i] - a[i]), 1)
    return None


def thin(rows, step=10):
    out, last = [], None
    for r in rows:
        if last is None or last - r[0] >= step or r is rows[-1]:
            out.append(r); last = r[0]
    return out


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'sondes.json'
    now = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    tries = sorted({(now - dt.timedelta(hours=h)).replace(hour=hh) for h in (0, 12, 24) for hh in (0, 11, 12, 23)
                    if (now - dt.timedelta(hours=h)).replace(hour=hh) <= now - dt.timedelta(minutes=30)
                    and (now - dt.timedelta(hours=h)).replace(hour=hh) >= now - dt.timedelta(hours=15)}, reverse=True)
    out = {'made': now.strftime('%Y-%m-%dT%H:%MZ'), 'src': 'University of Wyoming upper-air archive (WMO radiosonde data, Bureau of Meteorology flights)', 'st': {}}
    for sid, (name, lat, lng) in STATIONS.items():
        for when in tries:
            r = parse(fetch(sid, when), when)
            if r:
                got, rows = r
                out['st'][sid] = {'name': name, 'lat': lat, 'lng': lng, 'utc': got.strftime('%Y-%m-%dT%H:00Z'),
                                  'awst': (got + dt.timedelta(hours=8)).strftime('%Y-%m-%d %H:00'),
                                  'lv': {str(p): [at(rows, p, 2), at(rows, p, 3)] for p in LEVELS},
                                  'rows': thin(rows)}
                log('%s %-14s %s: %d levels, top %.0f hPa' % (sid, name, got.strftime('%d %H UTC'), len(rows), rows[-1][0]))
                break
        else:
            log('%s %-14s no flight in the last 15 hours' % (sid, name))
    json.dump(out, open(path, 'w'), separators=(',', ':'))
    log('Saved %s: %d stations' % (path, len(out['st'])))


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
West WX Watchers — Today's Ripper Weather: how good is each day's weather across WA (today + 6 days).

Hourly forecast from Open-Meteo (best-match models, Australia/Perth times) for a 0.5° grid over WA and the
ranked towns. Each place and day gets a score 0-100 from the daytime hours (9 am-5 pm):

  temperature   best when the (effective) top is 25-29 °C (24-30 still 94+, "beach weather"); falls away either side
  the Doctor    coastal places within 60 km of the sea: if an onshore breeze of 15+ km/h arrives by 3 pm on a
                hot day and the heat stops climbing, the afternoon counts, not the morning peak
  humidity      sticky days (daytime dew point 16 °C+, e.g. a Broome build-up) lose points
  wind          mean daytime wind over 15 km/h, and gusts of 45 / 60 km/h+, lose points
  rain, storms  daytime rain of 0.3 mm+ loses points; thunderstorms lose more
  cloud         cloud over 40% loses a little, overcast up to 30%
  flies         a rough "fly factor": inland, warm (22-35 °C), light winds (<12 km/h), not too dry or humid

Bands: 0-29 Bit ordinary · 30-49 Not bad · 50-69 Decent · 70-84 Beaut · 85+ Bloody ripper.

    python ripper/ripper.py OUT.json
"""
import datetime as dt
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GRID_D = 0.5
LAT0, LAT1, LNG0, LNG1 = -35.5, -13.5, 112.5, 129.0
TOWNS = [('Perth', -31.95, 115.86), ('Mandurah', -32.53, 115.72), ('Bunbury', -33.33, 115.64),
         ('Busselton', -33.65, 115.35), ('Margaret River', -33.95, 115.07), ('Denmark', -34.96, 117.35),
         ('Albany', -34.94, 117.88), ('Esperance', -33.86, 121.89), ('Geraldton', -28.78, 114.61),
         ('Kalbarri', -27.71, 114.17), ('Carnarvon', -24.88, 113.66), ('Exmouth', -21.93, 114.12),
         ('Karratha', -20.74, 116.85), ('Port Hedland', -20.31, 118.6), ('Broome', -17.96, 122.24),
         ('Kununurra', -15.78, 128.74), ('Newman', -23.36, 119.73), ('Kalgoorlie', -30.75, 121.47),
         ('Northam', -31.65, 116.67), ('Merredin', -31.48, 118.28)]
HOURLY = ['temperature_2m', 'dew_point_2m', 'wind_speed_10m', 'wind_direction_10m', 'wind_gusts_10m',
          'cloud_cover', 'precipitation', 'weather_code']
DAY_H = range(9, 18)          # 9 am - 5 pm
BANDS = [(85, 'Bloody ripper'), (70, 'Beaut'), (50, 'Decent'), (30, 'Not bad'), (0, 'Bit ordinary')]


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- WA shape and coast
def wa_rings():
    g = json.load(open(os.path.join(ROOT, 'wxvideo', 'aus_states.json')))['Western Australia']
    polys = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
    return [p[0] for p in polys]


def inside(x, y, ring):
    c, j = False, len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]; xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            c = not c
        j = i
    return c


def km(la1, lo1, la2, lo2):
    return math.hypot((la1 - la2) * 111.2, (lo1 - lo2) * 111.2 * math.cos(math.radians((la1 + la2) / 2)))


def bearing(la1, lo1, la2, lo2):
    """Compass bearing (deg) from point 1 towards point 2."""
    y = (lo2 - lo1) * math.cos(math.radians((la1 + la2) / 2)); x = la2 - la1
    return (math.degrees(math.atan2(y, x)) + 360) % 360


# ---------------------------------------------------------------- forecast
def fetch(points):
    """Open-Meteo hourly forecast for [(lat, lng)], in batches. Returns a list (same order) of hourly dicts."""
    out = []
    for i in range(0, len(points), 50):
        chunk = points[i:i + 50]
        q = {'latitude': ','.join('%.2f' % p[0] for p in chunk), 'longitude': ','.join('%.2f' % p[1] for p in chunk),
             'hourly': ','.join(HOURLY), 'timezone': 'Australia/Perth', 'forecast_days': 7, 'wind_speed_unit': 'kmh'}
        url = 'https://api.open-meteo.com/v1/forecast?' + urllib.parse.urlencode(q)
        for attempt in range(4):
            try:
                d = json.loads(urllib.request.urlopen(url, timeout=90).read())
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 3: raise
                log('  retry batch %d: %s' % (i // 50, e)); time.sleep(5 * (attempt + 1))
        out += [x['hourly'] for x in (d if isinstance(d, list) else [d])]
        time.sleep(0.4)
    return out


# ---------------------------------------------------------------- the score
def band(s):
    return next(n for t, n in BANDS if s >= t)


def score_day(h, idx, coast_km, to_coast):
    """Score one place for one day. h = hourly dict, idx = the list indexes of that day's hours (0-23)."""
    g = lambda k, i: h[k][i] if h[k][i] is not None else None
    day = [i for i in idx if int(h['time'][i][11:13]) in DAY_H]
    if len(day) < 6: return None
    T = [g('temperature_2m', i) for i in day]; Dp = [g('dew_point_2m', i) for i in day]
    W = [g('wind_speed_10m', i) for i in day]; Wd = [g('wind_direction_10m', i) for i in day]
    G = [g('wind_gusts_10m', i) for i in day]; C = [g('cloud_cover', i) for i in day]
    P = [g('precipitation', i) for i in day]; Code = [g('weather_code', i) for i in day]
    if None in T: return None
    hrs = [int(h['time'][i][11:13]) for i in day]
    allT = [g('temperature_2m', i) for i in idx if g('temperature_2m', i) is not None]
    tmax, tmin = max(allT), min(allT)
    peak = max(T)
    # the Doctor: an onshore 15+ km/h breeze arriving 11 am-3 pm on a hot coastal day, after which it stops heating up
    doctor, eff = None, peak
    if coast_km is not None and coast_km <= 60 and peak >= 30:
        onshore = lambda k: (W[k] or 0) >= 15 and Wd[k] is not None and abs(((Wd[k] - to_coast) + 180) % 360 - 180) <= 75
        for k in range(1, len(day)):
            if 11 <= hrs[k] <= 15 and onshore(k) and not onshore(k - 1):
                before, after = max(T[:k + 1]), T[k:]
                if max(after) <= before + 1.0:
                    doctor = hrs[k]
                    eff = 0.35 * before + 0.65 * (sum(after) / len(after))
                break
    # temperature: 1 for 24-30 °C, falling away either side
    t = eff
    st = 1.0 if 25 <= t <= 29 else max(0.0, 1 - (25 - t) * 0.06) if t < 25 else max(0.0, 1 - (t - 29) * 0.09)   # 24-30 still scores 94+
    dp = sum(x for x in Dp if x is not None) / max(1, len([x for x in Dp if x is not None]))
    humid = 0.0 if dp < 16 else min(0.65, (dp - 16) * 0.075)   # dew point 24+ (a build-up day) loses most of it
    wmean = sum(x or 0 for x in W) / len(W); gmax = max(x or 0 for x in G)
    windp = min(0.5, max(0.0, (wmean - 15) * 0.02)) + (0.15 if gmax >= 60 else 0.05 if gmax >= 45 else 0)
    rain = sum(x or 0 for x in P)
    storm = any(c is not None and c >= 95 for c in Code)
    rainp = 0.0 if rain < 0.3 else 0.3 if rain < 1 else 0.45 if rain < 5 else 0.6
    rainp += 0.1 if storm else 0
    cmean = sum(x or 0 for x in C) / len(C)
    cloudp = max(0.0, (cmean - 40) / 60 * 0.3)
    flies = coast_km is not None and coast_km > 80 and 22 <= peak <= 35 and wmean < 12 and 2 <= dp <= 16 and rain < 1
    s = st * (1 - humid) * (1 - min(0.6, windp)) * (1 - min(0.7, rainp)) * (1 - cloudp) - (0.08 if flies else 0)
    s = int(round(max(0, min(1, s)) * 100))
    icon = 'storm' if storm else 'rain' if rain >= 1 else 'cloud' if cmean > 70 else 'partly' if cmean > 35 else 'sun'
    notes = []
    if doctor: notes.append('Doctor in about %s' % ('%d am' % doctor if doctor < 12 else '12 pm' if doctor == 12 else '%d pm' % (doctor - 12)))
    if humid >= 0.15: notes.append('Sticky')
    if windp >= 0.15: notes.append('Windy')
    if storm: notes.append('Storms')
    elif rain >= 1: notes.append('Showers')
    if flies: notes.append('Flies about')
    if eff >= 36: notes.append('Scorcher')
    elif eff < 18: notes.append('Cool')
    return {'s': s, 'tmax': round(tmax), 'tmin': round(tmin), 'dp': round(dp), 'wind': round(wmean), 'gust': round(gmax),
            'rain': round(rain, 1), 'icon': icon, 'doctor': doctor, 'notes': notes}


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else 'ripper.json'
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    rings = wa_rings()
    coast = [(p[1], p[0]) for r in rings for p in r[::3] if p[0] < 128.95]   # (lat, lng); the 129°E border is not coast
    def coast_info(la, lo):
        best = min(coast, key=lambda c: (c[0] - la) ** 2 + ((c[1] - lo) * math.cos(math.radians(la))) ** 2)
        return km(la, lo, *best), bearing(la, lo, *best)
    nx = int(round((LNG1 - LNG0) / GRID_D)) + 1; ny = int(round((LAT1 - LAT0) / GRID_D)) + 1
    grid = [(LAT0 + j * GRID_D, LNG0 + i * GRID_D) for j in range(ny) for i in range(nx)]
    inwa = [any(inside(lo, la, r) for r in rings) for la, lo in grid]
    pts = [p for p, w in zip(grid, inwa) if w]
    log('Grid %dx%d, %d points in WA, %d towns' % (nx, ny, len(pts), len(TOWNS)))
    t0 = time.time()
    hourly = fetch([(t[1], t[2]) for t in TOWNS] + pts)
    log('Forecast fetched in %.0f s' % (time.time() - t0))
    th, gh = hourly[:len(TOWNS)], hourly[len(TOWNS):]
    dates = sorted({x[:10] for x in th[0]['time']})[:7]
    by_date = {d: [i for i, x in enumerate(th[0]['time']) if x.startswith(d)] for d in dates}
    cinfo = [coast_info(la, lo) for la, lo in pts]
    days = []
    for d in dates:
        idx = by_date[d]; s = []; k = 0
        for w in inwa:
            if not w: s.append(-1); continue
            r = score_day(gh[k], idx, *cinfo[k]); k += 1
            s.append(r['s'] if r else -1)
        days.append({'date': d, 's': s})
    towns = []
    for (n, la, lo), h in zip(TOWNS, th):
        ck, cb = coast_info(la, lo)
        towns.append({'n': n, 'lat': la, 'lng': lo, 'days': [score_day(h, by_date[d], ck, cb) for d in dates]})
    for d_i, d in enumerate(dates):
        ranked = sorted([t for t in towns if t['days'][d_i]], key=lambda t: -t['days'][d_i]['s'])
        log('%s: ' % d + ', '.join('%s %d' % (t['n'], t['days'][d_i]['s']) for t in ranked[:6])
            + ' ... ' + ', '.join('%s %d' % (t['n'], t['days'][d_i]['s']) for t in ranked[-3:]))
    out = {'made': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), 'source': 'Open-Meteo (best-match models)',
           'grid': {'lat0': LAT0, 'lng0': LNG0, 'd': GRID_D, 'nx': nx, 'ny': ny},
           'bands': [[t, n] for t, n in BANDS], 'days': days, 'towns': towns}
    with open(out_path, 'w') as fh:
        json.dump(out, fh, separators=(',', ':'))
    log('Wrote %s (%.0f KB)' % (out_path, os.path.getsize(out_path) / 1024))


if __name__ == '__main__':
    main()

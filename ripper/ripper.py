#!/usr/bin/env python3
"""
West WX Watchers — Today's Ripper Weather: how good is each day's weather across WA (today + 6 days).

A mix of two forecasts (9 Nov 2026):
  BoM     the official town forecasts for 116 WA places (IDW14199, anonymous FTP): max, min, forecast words, icon,
          chance of rain and rain range. These are what the page shows, and they drive temperature, rain and cloud.
  model   Open-Meteo hourly forecasts (best-match models) at those places and on a 0.5° grid, for what BoM's file
          lacks: wind, humidity, sea-breeze timing (the Doctor) and the fly factor.
The map: the model grid's scores, nudged towards the BoM places' scores (inverse-distance, fading out by ~250 km).

Each place and day gets a score 0-100 from the daytime hours (9 am-5 pm):

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
import re
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
BOM_URL = 'ftp://ftp.bom.gov.au/anon/gen/fwo/IDW14199.xml'
# BoM's weather situation (synoptic) text: the WA overview (north), then the south-west coastal waters
BOM_SYN = ['ftp://ftp.bom.gov.au/anon/gen/fwo/IDW10100.xml', 'ftp://ftp.bom.gov.au/anon/gen/fwo/IDW11130.xml']
# Towns ranked on the page (shown if BoM forecasts them); every BoM place still shapes the map
RANK = ['Perth', 'Mandurah', 'Rockingham', 'Bunbury', 'Busselton', 'Margaret River', 'Collie', 'Denmark', 'Albany',
        'Esperance', 'Hopetoun', 'Geraldton', 'Jurien Bay', 'Kalbarri', 'Carnarvon', 'Exmouth', 'Onslow', 'Karratha',
        'Port Hedland', 'Broome', 'Derby', 'Kununurra', 'Halls Creek', 'Newman', 'Tom Price', 'Meekatharra',
        'Kalgoorlie', 'Northam', 'Merredin', 'Narrogin', 'Katanning', 'Norseman']
# BoM forecast icon codes
BOM_ICON = {1: 'sun', 2: 'sun', 14: 'sun', 3: 'partly', 6: 'partly', 9: 'partly', 13: 'partly', 4: 'cloud', 10: 'cloud',
            8: 'rain', 11: 'rain', 12: 'rain', 15: 'rain', 17: 'rain', 18: 'rain', 16: 'storm', 19: 'storm'}
BOM_CLOUD = {'sun': 10, 'partly': 40, 'cloud': 85, 'rain': 80, 'storm': 70}
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


# ---------------------------------------------------------------- BoM town forecasts
def norm(s):
    return re.sub(r'[^a-z0-9 ]', '', s.lower().replace('mt ', 'mount ').replace('&', 'and')).strip()


def fetch_bom():
    """{place name: {'date': {'tmax','tmin','precis','icon','pop','hi'}}} from BoM's WA town forecasts."""
    for attempt in range(3):
        try:
            x = urllib.request.urlopen(BOM_URL, timeout=90).read().decode('utf-8', 'replace'); break
        except Exception as e:  # noqa: BLE001
            if attempt == 2: raise
            log('  BoM retry: %s' % e); time.sleep(10)
    out = {}
    for m in re.finditer(r'<area aac="[^"]+" description="([^"]+)" type="location"[^>]*>(.*?)</area>', x, re.S):
        name, body, days = m.group(1), m.group(2), {}
        for f in re.finditer(r'<forecast-period[^>]*start-time-local="(\d{4}-\d\d-\d\d)[^"]*"[^>]*>(.*?)</forecast-period>', body, re.S):
            b = f.group(2)
            g = lambda pat: (re.search(pat, b) or [None, None])[1]
            tx, tn, ic, pop, rng = (g(r'air_temperature_maximum[^>]*>(-?\d+)'), g(r'air_temperature_minimum[^>]*>(-?\d+)'),
                                     g(r'forecast_icon_code">(\d+)'), g(r'probability_of_precipitation">(\d+)%'),
                                     g(r'precipitation_range">([^<]+)'))
            hi = re.findall(r'(\d+(?:\.\d+)?)', rng or '')
            days[f.group(1)] = {'tmax': int(tx) if tx else None, 'tmin': int(tn) if tn else None,
                                'precis': (g(r'type="precis">([^<]+)') or '').strip(), 'icon': BOM_ICON.get(int(ic), 'partly') if ic else None,
                                'pop': int(pop) if pop else 0, 'hi': float(hi[-1]) if hi else 0.0}
        out[name] = days
    return out


def bom_coords(names):
    """(lat, lng) for BoM place names from the GeoNames WA places list (TOWNS as a backup)."""
    P = json.load(open(os.path.join(ROOT, 'data', 'wa_places.json')))
    T = {n: (la, lo) for n, la, lo in TOWNS}
    out, miss = {}, []
    for n in names:
        k = norm(re.sub(r'\s+(MO|Airport|Aero|AWS|Mine)$', '', n))
        if n in T: out[n] = T[n]
        elif k in P: out[n] = (P[k][0], P[k][1])
        else: miss.append(n)
    if miss: log('BoM places not located (left out): ' + ', '.join(miss))
    return out


def fetch_synoptic():
    """BoM's weather situation sentences (deduplicated), or []."""
    out = []
    for u in BOM_SYN:
        try:
            x = urllib.request.urlopen(u, timeout=60).read().decode('utf-8', 'replace')
            m = re.search(r'<text type="synoptic_situation">(.*?)</text>', x, re.S)
            if m:
                t = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', m.group(1))).strip().replace('. while', ', while')
                if t and t not in out: out.append(t)
        except Exception as e:  # noqa: BLE001
            log('BoM situation not read (%s): %s' % (u.rsplit('/', 1)[-1], e))
    return out


# ---------------------------------------------------------------- the day in brief (for reports)
def wind_words(w):
    return 'light winds' if w < 12 else 'a gentle breeze' if w < 20 else 'a fresh breeze' if w < 30 else 'strong winds'


def day_name(d, i):
    return 'today' if i == 0 else 'tomorrow' if i == 1 else 'on ' + dt.date.fromisoformat(d).strftime('%A')


def setup_words(syn, south, d_i):
    """Our own plain-English take on the weather pattern (never quoting the source)."""
    low = syn.lower(); said = []
    sent = [x.strip() for x in re.split(r'(?<=\.)\s+', low) if x.strip()]
    def has(*w): return any(all(k in x for k in w) for x in sent)
    if has('cold front') or has('front'):
        said.append('a cold front brings cooler, showery weather to the south' + ('' if d_i == 0 else ' at some stage'))
    if has('ridge') or has('high'):
        said.append('high pressure is building over the south-west, which means settled, dry air and mostly light winds')
    if has('trough', 'eastern') or has('trough', 'interior') or has('trough', 'inland'):
        said.append('an inland trough sits further east, where it is hotter and more unsettled')
    if has('west coast trough'):
        said.append('a west coast trough is on the way, which usually means hotter days with easterly winds near the coast')
    if has('low pressure', 'pilbara') or has('low pressure', 'north') or has('low', 'kimberley'):
        said.append('low pressure over the north keeps it hot, humid and stormy up there')
    if not said: return []
    said = said[:3]
    txt = 'The set-up: ' + '; '.join(said) + '.'
    if south and 'high pressure' in txt:
        txt += ' That is exactly what makes the south the place to be.'
    elif not south and 'north' in txt:
        txt += ' The pick spots sit clear of the worst of it.'
    return [txt]


def brief(towns, d_i, d, synoptic):
    """A short write-up of the day: the best towns and why, BoM's weather situation, and where to avoid."""
    R = sorted([t for t in towns if t['days'][d_i]], key=lambda t: -t['days'][d_i]['s'])
    if len(R) < 5: return ''
    a, b = R[0], R[1]; ra, rb = a['days'][d_i], b['days'][d_i]
    sky = (ra['precis'] or 'fine').rstrip('.').lower()
    out = []
    if abs(ra['tmax'] - rb['tmax']) <= 2 and ra['s'] - rb['s'] <= 5:
        out.append('%s and %s lead the way %s: %s, around %d° with %s.' % (a['n'], b['n'], day_name(d, d_i), sky, ra['tmax'], wind_words(ra['wind'])))
        rest = R[2:5]
    else:
        out.append('%s is the pick of WA %s: %s, %d° with %s.' % (a['n'], day_name(d, d_i), sky, ra['tmax'], wind_words(ra['wind'])))
        rest = R[1:4]
    behind = '%s, %s and %s are not far behind.' % tuple(t['n'] for t in rest)
    if synoptic and d_i <= 2:
        out += setup_words(' '.join(synoptic), a.get('lat', -30) < -28, d_i)
    out.append(behind)
    doc = [t for t in R[:8] if t['days'][d_i]['doctor']]
    if doc:
        h = doc[0]['days'][d_i]['doctor']
        out.append('On the coast the sea breeze should reach %s by about %s, taking the edge off the afternoon.'
                   % (doc[0]['n'], '%d am' % h if h < 12 else '12 pm' if h == 12 else '%d pm' % (h - 12)))
    worst = R[-1]; rw = worst['days'][d_i]; why = []
    if rw['tmax'] >= 36: why.append('%d° heat' % rw['tmax'])
    if 'Sticky' in rw['notes']: why.append('sticky air')
    if rw['icon'] in ('storm', 'rain') and rw.get('precis'): why.append(rw['precis'].rstrip('.').lower())
    if 'Windy' in rw['notes']: why.append('strong winds')
    if rw['tmax'] < 18: why.append('a cool %d°' % rw['tmax'])
    if why:
        out.append('Least appealing: %s, with %s.' % (worst['n'], ' and '.join(why[:2])))
    return ' '.join(out)


# ---------------------------------------------------------------- the score
def band(s):
    return next(n for t, n in BANDS if s >= t)


def score_day(h, idx, coast_km, to_coast, bom=None):
    """Score one place for one day. h = hourly dict, idx = the list indexes of that day's hours (0-23).
    bom = BoM's forecast for that place and day, if any: its max, min, rain and sky replace the model's."""
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
    if bom and bom.get('tmax') is not None:   # BoM's max, lowered by the Doctor as much as the model's afternoon was
        eff = bom['tmax'] - (peak - eff); tmax = bom['tmax']; peak = bom['tmax']
    if bom and bom.get('tmin') is not None: tmin = bom['tmin']
    # temperature: 1 for 25-29 °C, falling away either side
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
    if bom and bom.get('icon'):   # BoM's chance of rain, rain range and sky instead of the model's
        pop = bom['pop']; storm = bom['icon'] == 'storm' or 'storm' in bom['precis'].lower()
        rainp = 0.0 if pop < 20 else 0.1 if pop < 40 else 0.25 if pop < 60 else 0.4 if pop < 80 else 0.55
        rainp += (0.05 if bom['hi'] >= 5 else 0) + (0.15 if storm else 0)
        rain = bom['hi'] if pop >= 40 else 0.0
        cmean = BOM_CLOUD[bom['icon']]
    cloudp = max(0.0, (cmean - 40) / 60 * 0.3)
    flies = coast_km is not None and coast_km > 80 and 22 <= peak <= 35 and wmean < 12 and 2 <= dp <= 16 and rain < 1
    s = st * (1 - humid) * (1 - min(0.6, windp)) * (1 - min(0.7, rainp)) * (1 - cloudp) - (0.08 if flies else 0)
    s = int(round(max(0, min(1, s)) * 100))
    icon = 'storm' if storm else 'rain' if rain >= 1 else 'cloud' if cmean > 70 else 'partly' if cmean > 35 else 'sun'
    if bom and bom.get('icon'): icon = bom['icon']
    notes = []
    if doctor: notes.append('Doctor in about %s' % ('%d am' % doctor if doctor < 12 else '12 pm' if doctor == 12 else '%d pm' % (doctor - 12)))
    if humid >= 0.15: notes.append('Sticky')
    if windp >= 0.15: notes.append('Windy')
    if not bom:
        if storm: notes.append('Storms')
        elif rain >= 1: notes.append('Showers')
    if flies: notes.append('Flies about')
    if eff >= 36: notes.append('Scorcher')
    elif eff < 18: notes.append('Cool')
    return {'s': s, 'tmax': round(tmax), 'tmin': round(tmin), 'dp': round(dp), 'wind': round(wmean), 'gust': round(gmax),
            'rain': round(rain, 1), 'icon': icon, 'doctor': doctor, 'notes': notes,
            'precis': (bom or {}).get('precis') or '', 'pop': (bom or {}).get('pop')}


def simplify(ring, tol):
    """Douglas-Peucker on a [lng, lat] ring (degrees)."""
    if len(ring) < 4: return ring
    keep = [False] * len(ring); keep[0] = keep[-1] = True; stack = [(0, len(ring) - 1)]
    while stack:
        a, b = stack.pop(); (x1, y1), (x2, y2) = ring[a], ring[b]; dmax, k = 0, -1
        L = math.hypot(x2 - x1, y2 - y1)
        for i in range(a + 1, b):
            x0, y0 = ring[i]
            d = (abs((y2 - y1) * x0 - (x2 - x1) * y0 + x2 * y1 - y2 * x1) / L) if L > 1e-9 else math.hypot(x0 - x1, y0 - y1)   # closed ring: first = last
            if d > dmax: dmax, k = d, i
        if dmax > tol: keep[k] = True; stack += [(a, k), (k, b)]
    return [[round(p[0], 3), round(p[1], 3)] for p, kk in zip(ring, keep) if kk]


def write_geo(path):
    """The page's map outlines: WA and the neighbouring states, simplified (drawn without map tiles)."""
    g = json.load(open(os.path.join(ROOT, 'wxvideo', 'aus_states.json')))
    out = {}
    for name in ('Western Australia', 'Northern Territory', 'South Australia'):
        gj = g[name]; polys = gj['coordinates'] if gj['type'] == 'MultiPolygon' else [gj['coordinates']]
        rings = [simplify(p[0], 0.02) for p in polys]
        out[name] = [r for r in rings if len(r) >= 4 and (max(x for x, _ in r) - min(x for x, _ in r)) > 0.08]
    # BoM forecast districts (as on the other pages): simplified boundaries and a label spot well inside each
    try:
        dd = json.load(open(os.path.join(ROOT, 'data', 'districts.json')))['districts']
        out['districts'] = []
        for d in dd:
            rings = [simplify(r, 0.03) for r in d['rings']]
            rings = [r for r in rings if len(r) >= 4]
            if not rings: continue
            big = max(rings, key=lambda r: (max(x for x, _ in r) - min(x for x, _ in r)) * (max(y for _, y in r) - min(y for _, y in r)))
            out['districts'].append({'n': d['name'], 'r': rings, 'at': label_spot(big)})
    except Exception as e:  # noqa: BLE001
        log('Districts not added: %s' % e)
    with open(path, 'w') as fh:
        json.dump(out, fh, separators=(',', ':'))


def label_spot(ring):
    """A point well inside a ring: of a 24 x 24 sample, the inside point furthest from the edge."""
    xs = [x for x, _ in ring]; ys = [y for _, y in ring]
    def inside(x, y):
        c = False
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1: c = not c
        return c
    def edge(x, y):
        best = 1e9
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            dx, dy = x2 - x1, y2 - y1; L = dx * dx + dy * dy
            t = 0 if L == 0 else max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / L))
            best = min(best, math.hypot(x - x1 - t * dx, y - y1 - t * dy))
        return best
    bx = None; bd = -1
    for i in range(24):
        for j in range(24):
            x = min(xs) + (i + 0.5) * (max(xs) - min(xs)) / 24; y = min(ys) + (j + 0.5) * (max(ys) - min(ys)) / 24
            if inside(x, y):
                d = edge(x, y)
                if d > bd: bd, bx = d, [round(x, 2), round(y, 2)]
    return bx or [round(sum(xs) / len(xs), 2), round(sum(ys) / len(ys), 2)]


def backfill(h, today):
    """Start the tally from 1 Jan: the same score from Open-Meteo's archived model forecasts (no BoM words for past days)."""
    rings = wa_rings()
    coast = [(p[1], p[0]) for r in rings for p in r[::3] if p[0] < 128.95]
    where = bom_coords(RANK)
    names = [n for n in RANK if n in where]
    start = today[:4] + '-01-01'
    end = (dt.date.fromisoformat(today) - dt.timedelta(days=1)).isoformat()
    if end < start: h['filled_to'] = end; return
    got = 0
    for i in range(0, len(names), 8):
        chunk = names[i:i + 8]
        q = {'latitude': ','.join('%.2f' % where[n][0] for n in chunk), 'longitude': ','.join('%.2f' % where[n][1] for n in chunk),
             'hourly': ','.join(HOURLY), 'timezone': 'Australia/Perth', 'start_date': start, 'end_date': end, 'wind_speed_unit': 'kmh'}
        url = 'https://historical-forecast-api.open-meteo.com/v1/forecast?' + urllib.parse.urlencode(q)
        for attempt in range(4):
            try:
                d = json.loads(urllib.request.urlopen(url, timeout=180).read()); break
            except Exception as e:  # noqa: BLE001
                if attempt == 3: raise
                log('  back-fill retry: %s' % e); time.sleep(10 * (attempt + 1))
        for n, x in zip(chunk, d if isinstance(d, list) else [d]):
            hh = x['hourly']; la, lo = where[n]
            best = min(coast, key=lambda c: (c[0] - la) ** 2 + ((c[1] - lo) * math.cos(math.radians(la))) ** 2)
            ck, cb = km(la, lo, *best), bearing(la, lo, *best)
            by = {}
            for k, t in enumerate(hh['time']): by.setdefault(t[:10], []).append(k)
            for day, idx in by.items():
                if day in h['days'] and n in h['days'][day]: continue
                try:
                    r = score_day(hh, idx, ck, cb)
                except Exception:  # noqa: BLE001
                    r = None
                if r: h['days'].setdefault(day, {})[n] = [r['s'], r['tmax']]; got += 1
        time.sleep(1)
    h['filled_to'] = end
    log('Tally: back-filled %d town-days, %s to %s' % (got, start, end))


def record_day(path, date, towns):
    """The tally: each town's score for the day, kept from the morning runs (before noon AWST), when the
    day's forecast is freshest and complete. ripper-history.json: {"days": {"2026-11-09": {"Northam": [score, top], ...}}}"""
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    try:
        h = json.load(open(path))
    except Exception:  # noqa: BLE001
        h = {'days': {}}
    if not h.get('filled_to'):
        try:
            backfill(h, date)
        except Exception as e:  # noqa: BLE001
            log('Tally: back-fill failed (%s); trying again next run' % e)
    if date != now.strftime('%Y-%m-%d') or (now.hour >= 12 and date in h['days']):
        log('Tally: %s kept as it was' % date)
    else:
        h['days'][date] = {t['n']: [t['days'][0]['s'], t['days'][0]['tmax']] for t in towns if t['days'] and t['days'][0]}
        log('Tally: recorded %s (%d towns, %d days kept)' % (date, len(h['days'][date]), len(h['days'])))
    with open(path, 'w') as fh:
        json.dump(h, fh, separators=(',', ':'), sort_keys=True)


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
    bom = fetch_bom()
    where = bom_coords(list(bom))
    places = [n for n in bom if n in where]
    log('Grid %dx%d, %d points in WA; BoM: %d places, %d located' % (nx, ny, len(pts), len(bom), len(places)))
    t0 = time.time()
    hourly = fetch([where[n] for n in places] + pts)
    log('Model forecast fetched in %.0f s' % (time.time() - t0))
    ph, gh = hourly[:len(places)], hourly[len(places):]
    dates = sorted({x[:10] for x in ph[0]['time']})[:7]
    by_date = {d: [i for i, x in enumerate(ph[0]['time']) if x.startswith(d)] for d in dates}
    cinfo = [coast_info(la, lo) for la, lo in pts]
    pinfo = {n: coast_info(*where[n]) for n in places}
    # every BoM place, every day: the model-only score and the mixed (BoM) score; their difference nudges the map
    pl = {n: [(score_day(h, by_date[d], *pinfo[n]), score_day(h, by_date[d], *pinfo[n], bom=bom[n].get(d))) for d in dates]
          for n, h in zip(places, ph)}
    days = []
    for d_i, d in enumerate(dates):
        idx = by_date[d]; s = []; k = 0
        resid = [(where[n][0], where[n][1], v[d_i][1]['s'] - v[d_i][0]['s']) for n, v in pl.items()
                 if v[d_i][0] and v[d_i][1] and bom[n].get(d)]
        for w, (la, lo) in zip(inwa, grid):
            if not w: s.append(-1); continue
            r = score_day(gh[k], idx, *cinfo[k]); k += 1
            if not r: s.append(-1); continue
            num = den = 0.0
            for rla, rlo, dv in resid:
                dk = km(la, lo, rla, rlo); wgt = 1.0 / (dk * dk + 400.0)
                num += wgt * dv; den += wgt
            den += 1.0 / (250.0 * 250.0)          # far from any BoM place the nudge fades to nothing
            s.append(int(max(0, min(100, round(r['s'] + num / den)))))
        days.append({'date': d, 's': s})
    towns = []
    for n in RANK:
        bn = next((b for b in places if norm(re.sub(r'\s+(MO|Airport|Aero|AWS|Mine)$', '', b)) == norm(n)), None)
        if not bn: log('Ranked town not in the BoM file: ' + n); continue
        towns.append({'n': n, 'lat': round(where[bn][0], 3), 'lng': round(where[bn][1], 3), 'days': [v[1] for v in pl[bn]]})
    syn = fetch_synoptic()
    log('BoM situation: ' + ' | '.join(syn))
    for d_i, d in enumerate(dates):
        days[d_i]['brief'] = brief(towns, d_i, d, syn)
    log('Brief, day 1: ' + days[0]['brief'])
    for d_i, d in enumerate(dates):
        ranked = sorted([t for t in towns if t['days'][d_i]], key=lambda t: -t['days'][d_i]['s'])
        log('%s: ' % d + ', '.join('%s %d (%s°)' % (t['n'], t['days'][d_i]['s'], t['days'][d_i]['tmax']) for t in ranked[:6])
            + ' ... ' + ', '.join('%s %d' % (t['n'], t['days'][d_i]['s']) for t in ranked[-3:]))
    out = {'made': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), 'source': 'BoM town forecasts + Open-Meteo',
           'grid': {'lat0': LAT0, 'lng0': LNG0, 'd': GRID_D, 'nx': nx, 'ny': ny},
           'bands': [[t, n] for t, n in BANDS], 'days': days, 'towns': towns}
    with open(out_path, 'w') as fh:
        json.dump(out, fh, separators=(',', ':'))
    write_geo(os.path.join(os.path.dirname(os.path.abspath(out_path)), 'ripper-geo.json'))
    record_day(os.path.join(os.path.dirname(os.path.abspath(out_path)), 'ripper-history.json'), dates[0], towns)
    log('Wrote %s (%.0f KB) and the map outlines' % (out_path, os.path.getsize(out_path) / 1024))


if __name__ == '__main__':
    main()

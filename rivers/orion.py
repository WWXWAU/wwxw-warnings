"""EWS Orion devices the site owner approved for publishing (rivers/orion-sites.json: public names only, positions
to about 1 km, sensor ids). Rain, weather and creek levels, read every run with only the new readings fetched
(the record so far is kept in orion-cache.json). The API key comes from the ORION_API_KEY secret; nothing here is
logged by device."""
import datetime as dt, json, os, time, urllib.parse, urllib.request

B = 'https://api.oriondata.io/api/'
AWST = dt.timezone(dt.timedelta(hours=8))
KEEP = {'rain': 4, 'level': 8, 'temp': 1, 'hum': 1, 'wind': 1, 'wdir': 1}   # days of record kept per kind


def _get(path, tok=None, tries=4):
    h = {'User-Agent': 'Mozilla/5.0 (West WX Watchers)'}
    if tok: h['Authorization'] = 'Bearer ' + tok
    for k in range(tries):
        try: return json.loads(urllib.request.urlopen(urllib.request.Request(B + path, headers=h), timeout=120).read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and k < tries - 1: time.sleep(20); continue
            raise
        except Exception:  # noqa: BLE001
            if k == tries - 1: raise
            time.sleep(5)


def fetch(out_dir, now, log=print):
    """Bring the record up to date: {'sites': [...], 'c': {sensor key: {'YYYY-MM-DDTHH:MM': value}}}."""
    key = os.environ.get('ORION_API_KEY', '').strip()
    S = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'orion-sites.json')))
    cp = os.path.join(out_dir, 'orion-cache.json')
    try: C = json.load(open(cp))
    except Exception: C = {}  # noqa: BLE001
    C.setdefault('c', {})
    if not key: log('Orion: no key; using the record so far'); return S, C
    tok = _get('token?' + urllib.parse.urlencode({'apiKey': key}))['token']
    loc = now.replace(tzinfo=None)                                           # devices read in local standard time (AWST)
    groups = {}                                                              # one request series per (sensor or soft sensor, start time)
    for s in S:
        for k, (kind, sid, u) in s['sensors'].items():
            sk = '%s%d' % (kind, sid); have = C['c'].get(sk) or {}
            start = max(have) if have else (loc - dt.timedelta(days=KEEP[k] if k in ('rain', 'level') else 0.1)).strftime('%Y-%m-%dT%H:%M')
            start = (dt.datetime.fromisoformat(start) - dt.timedelta(minutes=30)).strftime('%Y-%m-%dT%H:%M:00')
            groups.setdefault((kind, start[:13]), []).append(sid)
    n = 0
    for (kind, st), ids in groups.items():
        for i in range(0, len(ids), 25):
            chunk = ids[i:i + 25]
            for off in range(0, 200):
                p = {'version': '1.3', 'startDate': st + ':00:00', 'endDate': loc.strftime('%Y-%m-%dT%H:%M:%S'), 'offset': off}
                p['sensorIds' if kind == 's' else 'softSensorIds'] = ','.join(str(x) for x in chunk)
                page = _get('SensorData?' + urllib.parse.urlencode(p), tok); n += 1
                if not page: break
                for r in page:
                    sid = r.get('softSensorId') if kind == 'ss' else r.get('sensorId')
                    if sid is None or r.get('sensorValue') is None: continue
                    C['c'].setdefault('%s%d' % (kind, sid), {})[r['readingDate'][:16]] = r['sensorValue']
                time.sleep(1.05)                                             # 60 requests a minute on the free plan
    # trim
    kinds = {('%s%d' % (kind, sid)): k for s in S for k, (kind, sid, u) in s['sensors'].items()}
    for sk in list(C['c']):
        if sk not in kinds: del C['c'][sk]; continue
        cut = (loc - dt.timedelta(days=KEEP.get(kinds[sk], 1) + 0.5)).strftime('%Y-%m-%dT%H:%M')
        C['c'][sk] = {t: v for t, v in C['c'][sk].items() if t >= cut}
    C['made'] = now.isoformat(timespec='minutes')
    json.dump(C, open(cp, 'w'), separators=(',', ':'), sort_keys=True)
    log('Orion: %d requests, %d sensors with readings' % (n, sum(1 for v in C['c'].values() if v)))
    return S, C


def _ser(C, s, k):
    if k not in s['sensors']: return {}
    kind, sid, u = s['sensors'][k]
    return C['c'].get('%s%d' % (kind, sid)) or {}


def rain_totals(ser, now):
    """Since 9 am, the 24 hours to 9 am, and 3 days, from interval readings (or a running counter, differenced)."""
    if not ser: return None
    ks = sorted(ser); v = [ser[k] for k in ks]
    if len(v) > 4 and all(b >= a for a, b in zip(v, v[1:])) and v[-1] > 50:   # a running total: turn into amounts
        v = [0] + [max(0, b - a) for a, b in zip(v, v[1:])]
    nine = now.replace(hour=9, minute=0, second=0, microsecond=0, tzinfo=None)
    if now.replace(tzinfo=None) < nine: nine -= dt.timedelta(days=1)
    f = lambda a, b: round(sum(x for k, x in zip(ks, v) if a < dt.datetime.fromisoformat(k) <= b and 0 <= x < 200), 1)
    last = dt.datetime.fromisoformat(ks[-1])
    if now.replace(tzinfo=None) - last > dt.timedelta(hours=26): return None
    return {'s9': f(nine, nine + dt.timedelta(days=1)), 'to9': f(nine - dt.timedelta(days=1), nine), 'd3': f(nine - dt.timedelta(days=3), nine + dt.timedelta(days=1)),
            'at': ks[-1]}


def rain_gauges(S, C, now):
    """Approved rain gauges in the river job's rain format."""
    R = []
    for i, s in enumerate(S):
        t = rain_totals(_ser(C, s, 'rain'), now)
        if t: R.append({'id': 'O:%d' % i, 'n': s['name'], 'src': 'Partner', 'll': [s['lat'], s['lng']], 's9': t['s9'], 'to9': t['to9'], 'd3': t['d3']})
    return R


def level_gauges(S, C, now):
    """Approved creek and river level sensors as gauges for the River Levels page, with their hourly record."""
    G = []
    for i, s in enumerate(S):
        ser = _ser(C, s, 'level')
        if not ser: continue
        ks = sorted(ser); at = dt.datetime.fromisoformat(ks[-1]).replace(tzinfo=AWST)
        hist = {}
        for k in ks: hist[k[:13] + ':00'] = round(ser[k], 3)                  # the last reading in each hour
        h1 = [ser[k] for k in ks if dt.datetime.fromisoformat(k) <= dt.datetime.fromisoformat(ks[-1]) - dt.timedelta(minutes=55)]
        river, _, place = s['name'].partition(', ')
        age = (now - at).total_seconds() / 3600
        G.append({'id': 'O%d' % i, 'river': river, 'name': place or river, 'at': at.isoformat(), 'lvl': round(ser[ks[-1]], 3),
                  'rate': round(ser[ks[-1]] - h1[-1], 3) if h1 else None, 'trend': '', 'rec': None, 'recd': None, 'off': None, 'cls': 'rowNORM',
                  'note': '', 'src': 'ews', 'age': round(age, 1), 'off_air': age > 48, 'fl': None, 'hist': hist, 'll': [s['lat'], s['lng']]})
    return G


def obs(S, C, now):
    """The latest weather and rain from the approved stations: orion-obs.json for the Live Obs and Rainfall pages."""
    out = []
    for i, s in enumerate(S):
        o = {'name': s['name'], 'lat': s['lat'], 'lng': s['lng']}
        for k in ('temp', 'hum', 'wind', 'wdir'):
            ser = _ser(C, s, k)
            if not ser: continue
            t = max(ser)
            if now.replace(tzinfo=None) - dt.datetime.fromisoformat(t) > dt.timedelta(hours=3): continue
            v = ser[t]
            if k == 'wind' and s['sensors'][k][2] == 'm/s': v = v * 3.6
            if k == 'wind' and s['sensors'][k][2] == 'kts': v = v * 1.852
            o[k] = round(v, 1) if k != 'wdir' else round(v); o['at'] = max(o.get('at', ''), t)
        t = rain_totals(_ser(C, s, 'rain'), now)
        if t: o.update({'rain9': t['s9'], 'rain24to9': t['to9'], 'rain3d': t['d3']}); o['at'] = max(o.get('at', ''), t['at'])
        if len(o) > 3: out.append(o)
    return out

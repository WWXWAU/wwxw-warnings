"""WA river levels for the West WX Watchers River Levels page.

Every 15 minutes (GitHub Actions):
  * DWER's telemetered river gauges (kumina.water.wa.gov.au/waterinformation/telem/stage.cfm): level, hourly change,
    trend and record high for ~250 gauges (provisional, unaudited data).
  * Gauge positions from the Bureau's Water Data Online (KiWIS), cached in rivers-sites.json.
  * An hourly 8-day level record per gauge, kept in rivers-history.json: our own readings, with the gaps filled from
    Water Data Online's provisional level series (about a day behind, so it seeds the first week).
  * DWER's own hourly tables for each gauge (the station pages' 'Report of Discharge in m3/s' and 'Report of Stage
    Levels' for the last 6 days): flow as DWER publishes it, and the stage record that fills any gaps in ours.
  * Rain upstream: the rain gauges inside each river gauge's catchment, from DWER's hydrographic subcatchments
    (DWER-030, with their downstream links), cached weekly in rivers-upstream.json.
  * Peaks: each gauge's highest level and flow over the last 1 to 7 days and this month (daily maxima kept in
    rivers-daily.json).
Writes rivers.json (now) and rivers-history.json (the record) into the output folder.
"""
import concurrent.futures as cf, csv, datetime as dt, ftplib, io, json, math, os, re, sys, time, urllib.parse, urllib.request

UA = {'User-Agent': 'Mozilla/5.0 (West WX Watchers river levels; westweatherwatchers.com)'}
DWER = 'https://kumina.water.wa.gov.au/waterinformation'
KIWIS = 'http://www.bom.gov.au/waterdata/services?service=kisters&type=queryServices&datasource=0&format=json&'
AWST = dt.timezone(dt.timedelta(hours=8))
KEEP_H = 8 * 24
KNOWN_POS = {'B509440': [-31.9595, 115.8577]}   # Bureau gauges Water Data Online doesn't list (Barrack Street Jetty)
TIDAL = {'616004', '616094', 'B509440'}   # known tide-affected gauges (Swan estuary at Guildford; below Kent Street Weir; Barrack Street Jetty), on top of the test below


def log(*a):
    print(*a, flush=True)


def get(url, timeout=90, tries=3):
    for k in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read().decode('utf-8', 'replace')
        except Exception as e:  # noqa: BLE001
            if k == tries - 1: raise
            log('  retry %s: %s' % (url[:80], e)); time.sleep(5 * (k + 1))


def num(s):
    try: return float(s.replace('&nbsp;', '').strip())
    except Exception: return None  # noqa: BLE001


def clean(s):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', s).replace('&nbsp;', ' ')).strip()


def read_dwer():
    t = get(DWER + '/telem/stage.cfm')
    out = []
    for cls, row in re.findall(r'<tr class=(\w+)>(.*?)</tr>', t, re.S):
        td = re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)
        if len(td) < 10: continue
        sid = re.search(r'publish/(\d+)/', td[0])
        if not sid: continue
        note = re.search(r'Comments:<br>(.*?)</span>', td[0], re.S)
        note = clean(note.group(1)) if note else ''
        if note.lower().startswith('no additonal comments') or note.lower().startswith('no additional comments'): note = ''
        when = clean(td[3])
        try: at = dt.datetime.strptime(when, '%H:%M %d%b%Y').replace(tzinfo=AWST)
        except Exception: at = None  # noqa: BLE001
        stage, lvl, rate, mx = num(clean(td[4])), num(clean(td[5])), num(clean(td[6])), num(clean(td[8]))
        if lvl is None: continue
        off = (stage - lvl) if stage is not None else None          # gauge datum offset: level = stage - off
        rec = round(mx - off, 3) if (mx is not None and off is not None) else None   # record high, as a river level
        try: recd = dt.datetime.strptime(clean(td[9]), '%d%b%Y').strftime('%Y-%m-%d')
        except Exception: recd = None  # noqa: BLE001
        out.append({'id': sid.group(1), 'river': clean(td[1]), 'name': clean(td[2]).replace('Sw Hwy', 'SW Hwy'),
                    'at': at.isoformat() if at else None, 'lvl': round(lvl, 3), 'rate': rate, 'trend': clean(td[7]).title(),
                    'rec': rec, 'recd': recd, 'off': round(off, 3) if off is not None else None, 'cls': cls, 'note': note})
    log('DWER gauges read: %d (row classes: %s)' % (len(out), sorted(set(g['cls'] for g in out))))
    return out


def sites(ids, cache_path):
    try: C = json.load(open(cache_path))
    except Exception: C = {}  # noqa: BLE001
    need = [i for i in ids if i not in C]
    for k in range(0, len(need), 100):
        q = KIWIS + urllib.parse.urlencode({'request': 'getStationList', 'station_no': ','.join(need[k:k + 100]),
                                            'returnfields': 'station_no,station_latitude,station_longitude'})
        try:
            for no, la, lo in json.loads(get(q))[1:]:
                C[no] = [round(float(la), 5), round(float(lo), 5)]
        except Exception as e:  # noqa: BLE001
            log('Positions not read: %s' % e)
    if need: log('Positions: %d new, %d still missing' % (len(need), len([i for i in ids if i not in C])))
    return C


def kiwis_history(ids, days=8):
    """Hourly levels for the last days from Water Data Online's provisional series: {id: {hourISO: level}}."""
    out = {}
    q = KIWIS + urllib.parse.urlencode({'request': 'getTimeseriesList', 'station_no': ','.join(ids), 'parametertype_name': 'Water Course Level',
                                        'ts_name': 'Received.Provisional.AsStored.1', 'returnfields': 'station_no,ts_id'})
    try: rows = json.loads(get(q, timeout=180))[1:]
    except Exception as e:  # noqa: BLE001
        log('History list not read: %s' % e); return out
    tsid = {no: ts for no, ts in rows}
    todo = [i for i in ids if i in tsid]
    for k in range(0, len(todo), 25):
        chunk = todo[k:k + 25]
        q = KIWIS + urllib.parse.urlencode({'request': 'getTimeseriesValues', 'ts_id': ','.join(tsid[i] for i in chunk), 'period': 'P%dD' % days,
                                            'returnfields': 'Timestamp,Value', 'timezone': 'GMT+8'})
        try: res = json.loads(get(q, timeout=240))
        except Exception as e:  # noqa: BLE001
            log('History values not read (%d gauges): %s' % (len(chunk), e)); continue
        back = {v: kk for kk, v in tsid.items()}
        for r in res:
            sid = back.get(str(r.get('ts_id')))
            if not sid: continue
            h = out.setdefault(sid, {})
            for ts, v in r.get('data', []):
                if v is None: continue
                hk = ts[:13] + ':00'                                   # hourly: the reading on the hour (or the last before it)
                h[hk] = round(float(v), 3)
        time.sleep(0.5)
    log('History from Water Data Online: %d gauges' % len(out))
    return out


def tidal(v):
    """A tide gauge (estuary, weir pool below a weir): the level swings up and down twice a day. Count the swings of
    5 cm or more over the last three days (Perth tides are mostly once a day); three or more and the 'rising' is the tide, not a flood."""
    if len(v) < 36: return False
    swings, ext, up = 0, v[0], None
    for x in v[1:]:
        if up is None:
            if abs(x - ext) >= 0.05: up = x > ext; ext = x
            continue
        if (up and x > ext) or (not up and x < ext): ext = x
        elif abs(x - ext) >= 0.05: swings += 1; up = not up; ext = x
    # and the tide rises about as slowly as it falls; a flood jumps up in an hour or two and drains away for days
    ups = sum(1 for a, b in zip(v, v[1:]) if b - a >= 0.01); downs = sum(1 for a, b in zip(v, v[1:]) if a - b >= 0.01)
    return swings >= 3 and ups >= 6 and downs >= 6 and 0.4 <= ups / downs <= 2.5


# ---------------------------------------------------------------- the Bureau's flood levels
BOM_RH = ['IDW604%02d.html' % i for i in range(8)]   # Latest River Heights, by basin group
STOP = {'river', 'brook', 'creek', 'at', 'the', 'rd', 'road', 'bridge', 'br', 'of', 'and', 'downstream', 'upstream', 'd', 's', 'u', 'weir'}


def words(t):
    ab = {'mt': 'mount', 'st': 'street', 'ck': 'creek', 'hwy': 'highway', 'nth': 'north', 'sth': 'south'}
    return set(ab.get(w, w) for w in re.findall(r'[a-z]+', t.lower()) if ab.get(w, w) not in STOP and len(w) > 1)


def ftp_get(name):
    f = ftplib.FTP('ftp.bom.gov.au', timeout=60); f.login(); f.cwd('/anon/gen/fwo')
    b = io.BytesIO(); f.retrbinary('RETR ' + name, b.write); f.quit()
    return b.getvalue().decode('utf-8', 'replace')


def flood_levels(G, out_dir, now):
    """Match DWER gauges to the Bureau's flood-warning gauges, with their minor / moderate / major flood heights.
    The Bureau's current flood class comes from its river height tables every run; the heights (from each gauge's
    page) are kept in rivers-flood.json and re-read weekly."""
    path = os.path.join(out_dir, 'rivers-flood.json')
    try: F = json.load(open(path))
    except Exception: F = {}  # noqa: BLE001
    rows = []
    for name in BOM_RH:
        try: t = ftp_get(name)
        except Exception as e:  # noqa: BLE001
            log('BoM river heights %s not read: %s' % (name, e)); continue
        for r in re.findall(r'<tr>(.*?)</tr>', t, re.S):
            c = [clean(x) for x in re.findall(r'<td[^>]*>(.*?)</td>', r, re.S)]
            bid = re.search(r'IDW624\d\d\.(\d+)\.', r)
            if len(c) < 8 or not bid: continue
            rows.append({'bom': bid.group(1), 'prod': re.search(r'(IDW624\d\d)\.', r).group(1), 'name': c[0], 'h': num(c[3]) if c[3] else None, 'datum': c[4], 'cls': c[7]})
    log('BoM flood-warning gauges: %d' % len(rows))
    week = (now - dt.timedelta(days=7)).strftime('%Y-%m-%d')
    for r in rows:
        f = F.get(r['bom'])
        if f and f.get('read', '') >= week: continue
        try:
            t = get('http://www.bom.gov.au/fwo/%s/%s.%s.tbl.shtml' % (r['prod'], r['prod'], r['bom']), timeout=60, tries=2)
            x = clean(t)
            lv = {k: num(v) for k, v in re.findall(r'(Minor|Moderate|Major):\s*([\d.]+)\s*m', x)}
            F[r['bom']] = {'minor': lv.get('Minor'), 'moderate': lv.get('Moderate'), 'major': lv.get('Major'), 'read': now.strftime('%Y-%m-%d')}
        except Exception as e:  # noqa: BLE001
            log('  flood levels not read for %s: %s' % (r['name'], e))
        time.sleep(0.3)
    json.dump(F, open(path, 'w'), separators=(',', ':'), sort_keys=True)
    # match: the same river and place words, and (when both are reporting) the same height to within 5 cm
    for g in G: g['fl'] = None
    used = set()
    for r in rows:
        if r['datum'] != 'LGH': continue
        rw = words(r['name']); best, bs = None, 0
        for g in G:
            if g['id'] in used: continue
            gw = words(g['river'] + ' ' + g['name'])
            if not (rw & gw): continue
            sc = len(rw & gw) / len(rw | gw)
            if r['h'] is not None and not g['off_air']:
                if abs(r['h'] - g['lvl']) <= 0.05: sc += 0.5
                elif abs(r['h'] - g['lvl']) > 0.3: sc -= 0.5
            if sc > bs: best, bs = g, sc
        if best and bs >= 0.6:
            used.add(best['id']); f = F.get(r['bom'], {})
            mc = re.search(r'(Minor|Moderate|Major)', r['cls']); cls = mc.group(1).lower() if mc else 'below' if r['cls'].startswith('Below') else None
            best['fl'] = {'bom': r['bom'], 'bomname': r['name'], 'minor': f.get('minor'), 'moderate': f.get('moderate'), 'major': f.get('major'), 'bcls': cls}
    # the class from the live level and the heights (the Bureau's own class can lag the gauge)
    for g in G:
        f = g['fl']
        if not f: continue
        lvl = g['lvl']; c = 'below'
        for k in ('minor', 'moderate', 'major'):
            if f.get(k) is not None and lvl >= f[k]: c = k
        f['cls'] = c if not g['off_air'] else f.get('bcls')
    m = [g for g in G if g['fl']]
    for g in m: log('  match: %-45s -> %s / %s  (BoM %s, DWER %.2f; minor %s)' % (g['fl']['bomname'], g['river'], g['name'], next((r['h'] for r in rows if r['bom'] == g['fl']['bom']), None), g['lvl'], g['fl'].get('minor')))
    log('  BoM gauges not matched: %s' % ', '.join(r['name'] for r in rows if r['datum'] == 'LGH' and r['bom'] not in set(g['fl']['bom'] for g in m)))
    log('Matched to BoM flood gauges: %d (with heights: %d). Above minor now: %s' % (len(m), len([g for g in m if g['fl'].get('minor')]),
        ', '.join('%s %s (%s)' % (g['river'], g['name'], g['fl']['cls']) for g in m if g['fl'].get('cls') in ('minor', 'moderate', 'major')) or 'none'))
    return rows, F, set(g['fl']['bom'] for g in m)


def flood_class(lvl, f):
    c = 'below'
    for k in ('minor', 'moderate', 'major'):
        if f.get(k) is not None and lvl >= f[k]: c = k
    return c


def bom_gauges(rows, F, matched, pos, now):
    """The Bureau's flood-warning gauges that DWER doesn't run (shires, Water Corporation and others): level, trend
    and the last 7 days from each gauge's table page, every run; positions from Water Data Online by name."""
    out = []
    for r in rows:
        if r['bom'] in matched: continue
        sid = 'B' + r['bom']
        try: t = get('http://www.bom.gov.au/fwo/%s/%s.%s.tbl.shtml' % (r['prod'], r['prod'], r['bom']), timeout=60, tries=2)
        except Exception as e:  # noqa: BLE001
            log('  BoM gauge %s not read: %s' % (r['name'], e)); continue
        x = clean(t)
        ser = {}
        for d, v in re.findall(r'(\d\d/\d\d/\d{4} \d\d:\d\d)\s+(-?\d+\.\d+)', x):
            ser[dt.datetime.strptime(d, '%d/%m/%Y %H:%M').replace(tzinfo=AWST)] = float(v)
        lv = {k: num(v) for k, v in re.findall(r'(Minor|Moderate|Major):\s*([\d.]+)\s*m', x)}
        if lv: F[r['bom']] = {'minor': lv.get('Minor'), 'moderate': lv.get('Moderate'), 'major': lv.get('Major'), 'read': now.strftime('%Y-%m-%d')}
        if not ser: log('  BoM gauge %s: no readings' % r['name']); continue
        ts = sorted(ser); last = ts[-1]; lvl = ser[last]
        hr = [k for k in ts if k <= last - dt.timedelta(minutes=50)]
        rate = round(lvl - ser[hr[-1]], 3) if hr and (last - hr[-1]) <= dt.timedelta(hours=2) else None
        mm = re.match(r'(.*?) at (.*)', r['name']); river, place = (mm.group(1), mm.group(2)) if mm else (r['name'], '')
        if sid in KNOWN_POS: pos[sid] = KNOWN_POS[sid]
        if not pos.get(sid):
            pos[sid] = []
            for term in [place, place.split('(')[0].strip(), ' '.join(place.split()[:2])]:
                if not term: continue
                q = KIWIS + urllib.parse.urlencode({'request': 'getStationList', 'station_name': '*' + term + '*', 'returnfields': 'station_name,station_no,station_latitude,station_longitude'})
                try: res = json.loads(get(q, timeout=60, tries=2))[1:]
                except Exception: res = []  # noqa: BLE001
                res = [z for z in res if z[2] and -36 < float(z[2]) < -13 and 112 < float(z[3]) < 130]   # in WA
                exact = [z for z in res if z[0].strip().lower() == term.lower()]
                res = exact or [z for z in res if words(z[0]) & words(river)] or res[:1]
                if res:
                    pos[sid] = [round(float(res[0][2]), 5), round(float(res[0][3]), 5)]; break
        hourly = {}
        for k in ts: hourly[k.strftime('%Y-%m-%dT%H:00')] = ser[k]
        f = F.get(r['bom'], {})
        g = {'id': sid, 'river': river, 'name': place, 'at': last.isoformat(), 'lvl': round(lvl, 3), 'rate': rate,
             'trend': 'Rising' if (rate or 0) >= 0.005 else 'Falling' if (rate or 0) <= -0.005 else 'Steady',
             'rec': None, 'recd': None, 'off': None, 'cls': 'rowNORM', 'note': '', 'src': 'bom', 'prod': r['prod'], 'datum': r['datum'], 'hist': hourly,
             'fl': {'bom': r['bom'], 'bomname': r['name'], 'minor': f.get('minor'), 'moderate': f.get('moderate'), 'major': f.get('major'), 'bcls': None}}
        g['fl']['cls'] = flood_class(lvl, g['fl'])
        out.append(g); time.sleep(0.3)
    log('Bureau-only gauges added: %d (%s); no position: %s' % (len(out), ', '.join(g['river'] + ' at ' + g['name'] for g in out),
        ', '.join(g['river'] + ' at ' + g['name'] for g in out if not pos.get(g['id'])) or 'none'))
    return [g for g in out if pos.get(g['id'])]


LEVEL_SITES = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'bom-level-sites.csv')


def hcs_rows(prefix, files=None):
    """Records from the Bureau's HCS files on the FTP site (newest `files` of them): [site id, UTC time, value]."""
    f = ftplib.FTP('ftp.bom.gov.au', timeout=60); f.login(); f.cwd('/anon/gen/fwo')
    names = sorted(n for n in f.nlst() if n.startswith(prefix) and n.endswith('.hcs'))
    out = []
    for n in names[-files:] if files else names:
        b = io.BytesIO(); f.retrbinary('RETR ' + n, b.write)
        for l in b.getvalue().decode('latin-1').splitlines():
            c = [x.strip().strip('"') for x in l.split(',')]
            if len(c) > 6 and c[0].isdigit():
                try: out.append((c[4], dt.datetime.fromisoformat(c[5].replace('Z', '+00:00')), float(c[6])))
                except ValueError: pass
    f.quit()
    return out


def hcs_gauges(G, pos, now):
    """Bureau water-level sites (IDW65910) that neither DWER's table nor the Bureau's river height pages give us,
    with names, positions and flood levels from the Bureau's site list (data/bom-level-sites.csv)."""
    try: M = {r['BOM_STATION_NUMBER']: r for r in csv.DictReader(open(LEVEL_SITES))}
    except Exception as e:  # noqa: BLE001
        log('Bureau level site list not read: %s' % e); return []
    have = {g['id'] for g in G} | {(g.get('fl') or {}).get('bom') for g in G} | {g['id'][1:] for g in G if g['id'].startswith('B')}
    ser = {}
    for sid, t, v in hcs_rows('IDW65910_'):
        if sid in M and sid not in have and M[sid]['RIVER_SITEID'] not in have: ser.setdefault(sid, {})[t] = v
    num_ = lambda v: None if v in ('', 'NaN') else float(v)
    out = []
    for sid, s in ser.items():
        m = M[sid]; ts = sorted(s); last = ts[-1]
        if now - last > dt.timedelta(hours=48): continue
        la, lo = float(m['LATITUDE']), float(m['LONGITUDE'])
        if any(pos.get(g['id']) and abs(pos[g['id']][0] - la) < 0.003 and abs(pos[g['id']][1] - lo) < 0.003 for g in G): continue   # the same gauge under another name
        lvl = s[last]; back = [k for k in ts if k <= last - dt.timedelta(minutes=50)]
        rate = round(lvl - s[back[-1]], 3) if back and last - back[-1] <= dt.timedelta(hours=2) else None
        mm = re.match(r'(.*?) at (.*)', m['LONG_NAME']); river, place = (mm.group(1), mm.group(2)) if mm else (m['LONG_NAME'], '')
        gid = 'B' + sid; pos[gid] = [round(float(m['LATITUDE']), 5), round(float(m['LONGITUDE']), 5)]
        fl = {'bom': sid, 'bomname': m['LONG_NAME'], 'minor': num_(m['MINOR_FCL']), 'moderate': num_(m['MODERATE_FCL']), 'major': num_(m['MAJOR_FCL']), 'bcls': None}
        fl['cls'] = flood_class(lvl, fl)
        out.append({'id': gid, 'river': river, 'name': place, 'at': last.astimezone(AWST).isoformat(timespec='seconds'), 'lvl': round(lvl, 3), 'rate': rate,
                    'trend': 'Rising' if (rate or 0) >= 0.005 else 'Falling' if (rate or 0) <= -0.005 else 'Steady',
                    'rec': None, 'recd': None, 'off': None, 'cls': 'rowNORM', 'note': '', 'src': 'bom', 'prod': 'IDW65910', 'datum': m['GAUGE_DATUM'], 'fl': fl})
    log('Bureau water-level sites added: %d (%s)' % (len(out), ', '.join(g['river'] + ' at ' + g['name'] for g in out) or 'none'))
    return out


# ---------------------------------------------------------------- roads closed or affected by flooding (Main Roads WA)
MRWA_CLOSURES = 'https://services2.arcgis.com/cHGEnmsJ165IBJRM/arcgis/rest/services/WebEoc_RoadClosures/FeatureServer/4/query'


def flood_roads(out_dir):
    """Main Roads' road closures and warnings caused by flooding, as GeoJSON (CC BY 4.0, Commissioner of Main Roads)."""
    q = MRWA_CLOSURES + '?' + urllib.parse.urlencode({'where': "IncidentTy = 'Flooding' AND publishExt = 'Yes'", 'outFields': 'Id,Location,ClosureTyp,Road,Region,Suburb,TrafficImp,EntryDate,UpdateDate',
                                                     'outSR': 4326, 'f': 'geojson', 'maxAllowableOffset': 0.002, 'geometryPrecision': 4})
    fc = json.loads(get(q, timeout=90))
    feats = []
    for f in fc.get('features', []):
        p = f.get('properties', {})
        feats.append({'type': 'Feature', 'geometry': f.get('geometry'), 'properties': {
            'id': p.get('Id'), 'where': clean(p.get('Location') or ''), 'type': p.get('ClosureTyp') or '', 'road': p.get('Road') or '',
            'region': p.get('Region') or '', 'note': clean(p.get('TrafficImp') or ''), 'updated': p.get('UpdateDate') or ''}})
    for f in feats: f['properties']['src'] = 'mrwa'
    try: S = shire_roads(out_dir)
    except Exception as e:  # noqa: BLE001
        log('Shire road reports skipped: %s' % e); S = {'features': [], 'shires': []}
    out = {'type': 'FeatureCollection', 'features': feats + S['features'], 'shires': S['shires']}
    json.dump(out, open(os.path.join(out_dir, 'rivers-roads.json'), 'w'), separators=(',', ':'))
    log('Roads affected by flooding: %d (%s)' % (len(feats), '; '.join('%s: %s' % (f['properties']['type'], f['properties']['where'][:60]) for f in feats[:6])))


# ---------------------------------------------------------------- shire road reports
# Many WA shires publish their road report through the same council website system, which serves it as JSON
# (/api/roadreports/getReportItems): each road's status (Open, Open With Caution, Closed, Closed to Trucks...),
# its comments, when it was updated, and the road drawn as lines. Read every 30 minutes (rivers-shireroads.json).
SHIRE_API = [('www.swek.wa.gov.au', 'Wyndham–East Kimberley'), ('www.sdwk.wa.gov.au', 'Derby–West Kimberley'), ('eastpilbara.wa.gov.au', 'East Pilbara'),
             ('www.porthedland.wa.gov.au', 'Port Hedland'), ('www.ashburton.wa.gov.au', 'Ashburton'), ('www.exmouth.wa.gov.au', 'Exmouth'),
             ('www.carnarvon.wa.gov.au', 'Carnarvon'), ('www.uppergascoyne.wa.gov.au', 'Upper Gascoyne'), ('www.sharkbay.wa.gov.au', 'Shark Bay'),
             ('www.meekashire.wa.gov.au', 'Meekatharra'), ('www.wiluna.wa.gov.au', 'Wiluna'), ('www.ngaanyatjarraku.wa.gov.au', 'Ngaanyatjarraku'),
             ('www.murchison.wa.gov.au', 'Murchison'), ('www.cue.wa.gov.au', 'Cue'), ('www.yalgoo.wa.gov.au', 'Yalgoo'), ('www.northampton.wa.gov.au', 'Northampton'),
             ('www.chapmanvalley.wa.gov.au', 'Chapman Valley'), ('www.cgg.wa.gov.au', 'Greater Geraldton'), ('www.morawa.wa.gov.au', 'Morawa'),
             ('www.perenjori.wa.gov.au', 'Perenjori'), ('www.dalwallinu.wa.gov.au', 'Dalwallinu'), ('www.leonora.wa.gov.au', 'Leonora'), ('www.menzies.wa.gov.au', 'Menzies'),
             ('www.ckb.wa.gov.au', 'Kalgoorlie-Boulder'), ('www.coolgardie.wa.gov.au', 'Coolgardie'), ('www.dundas.wa.gov.au', 'Dundas'),
             ('www.esperance.wa.gov.au', 'Esperance'), ('www.ravensthorpe.wa.gov.au', 'Ravensthorpe'), ('www.jerramungup.wa.gov.au', 'Jerramungup')]
# Shires whose report is only a document or a page we can't read: listed with a link
SHIRE_LINKS = [('Broome', 'https://www.broome.wa.gov.au/Shire-Services/Infrastructure/Road-Condition-Report-and-Planned-Maintenance'),
               ('Halls Creek', 'https://www.hallscreek.wa.gov.au/services/road-conditions'),
               ('Derby–West Kimberley', 'https://www.sdwk.wa.gov.au/services/roads/road-conditions.aspx'),
               ('Ashburton', 'https://www.ashburton.wa.gov.au/services/emergency-safety/road-report.aspx')]
NOT_WEATHER = re.compile(r'(?i)road ?works|construction|reconstruct|resurfac|re-?sheet|bitumen|sealing|lane closure|stabilisation|asphalt|kerb|\bworks\b|maintenance|'
                         r'playground|beach access|stairs|intersection|temporary|event|parade|market')
BROWSER = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
           'Accept': 'application/json, */*', 'X-Requested-With': 'XMLHttpRequest'}


def thin_line(pts, tol=0.0015):
    """A road line with only the points needed to draw it within ~150 m (Douglas-Peucker), to 4 decimals."""
    if len(pts) < 3: return [[round(x, 4), round(y, 4)] for x, y in pts]
    keep = [False] * len(pts); keep[0] = keep[-1] = True; stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop(); (x1, y1), (x2, y2) = pts[a], pts[b]; dx, dy = x2 - x1, y2 - y1; L = math.hypot(dx, dy) or 1e-12; far, fi = 0, -1
        for i in range(a + 1, b):
            d = abs(dy * (pts[i][0] - x1) - dx * (pts[i][1] - y1)) / L
            if d > far: far, fi = d, i
        if far > tol: keep[fi] = True; stack += [(a, fi), (fi, b)]
    return [[round(x, 4), round(y, 4)] for (x, y), k in zip(pts, keep) if k]


def shire_status(name):
    """The shire's own status, sorted into closed / caution (None = open, or roadworks and the like)."""
    n = name.lower()
    if n == 'open' or 'roadwork' in n or 'lane' in n: return None
    if 'closed' in n and 'truck' not in n and '3t' not in n and 'heavy' not in n and 'high-clearance' not in n: return 'closed'
    return 'caution'


def shire_one(host, shire, now):
    d = json.loads(urllib.request.urlopen(urllib.request.Request('https://%s/api/roadreports/getReportItems?displayType=map' % host, headers=BROWSER), timeout=60).read())
    feats, latest = [], ''
    for m in d.get('mapData') or []:
        st = shire_status((m.get('Type') or {}).get('Name') or '')
        upd = m.get('LastUpdated') or ''
        try: when = dt.datetime.strptime(upd, '%A, %d %B %Y %I:%M %p').strftime('%Y-%m-%dT%H:%M')
        except ValueError: when = ''
        latest = max(latest, when)
        desc = clean(m.get('MarkerDescription') or m.get('Comments') or '')
        title, sub = clean(m.get('Title') or ''), clean(m.get('SubTitle') or '')
        if st is None or NOT_WEATHER.search(title + ' ' + sub + ' ' + desc): continue
        to = m.get('PublishTo') or ''
        try:
            if to and dt.datetime.strptime(to.split()[0], '%d/%m/%Y').date() < now.date(): continue      # finished
        except ValueError: pass
        geo = None
        try: md = json.loads(m.get('MappingData') or 'null')
        except ValueError: md = None
        if isinstance(md, list):
            lines = [thin_line([[p['lng'], p['lat']] for p in x.get('data') or [] if 'lat' in p and 'lng' in p]) for x in md if isinstance(x, dict)]
            lines = [l for l in lines if len(l) >= 2]
            if lines: geo = {'type': 'MultiLineString', 'coordinates': lines}
        elif isinstance(md, dict) and md.get('Latitude'):
            geo = {'type': 'Point', 'coordinates': [round(md['Longitude'], 4), round(md['Latitude'], 4)]}
        typ = (m.get('Type') or {}).get('Name') or ''
        feats.append({'type': 'Feature', 'geometry': geo, 'properties': {
            'id': 'S:%s:%s' % (host.replace('www.', '').split('.')[0], m.get('EntityId')), 'src': 'shire', 'shire': shire,
            'road': (lambda r: r.title() if r.isupper() else r)(re.split(r':| - | \(', title)[0].strip()),
            'where': title + (' · ' + sub if sub and sub.lower() not in title.lower() and sub.lower() not in ('road closure', 'road conditions') else ''),
            'type': typ, 'closed': 1 if st == 'closed' else 0, 'note': desc[:300],
            'updated': when, 'url': m.get('ShareUrl') or ''}})
    return feats, latest


def shire_roads(out_dir):
    """Every shire's closed and caution roads (cached for 30 minutes), and the list of shire reports."""
    path = os.path.join(out_dir, 'rivers-shireroads.json'); now = dt.datetime.now(AWST)
    try: C = json.load(open(path))
    except Exception: C = {}  # noqa: BLE001
    if C.get('at', '') < (now - dt.timedelta(minutes=30)).isoformat(timespec='minutes'):
        def one(hs):
            try: return hs, shire_one(hs[0], hs[1], now), None
            except Exception as e: return hs, None, str(e)[:80]  # noqa: BLE001
        old = {s['name']: s for s in C.get('shires', [])}
        feats, shires = [], []
        with cf.ThreadPoolExecutor(8) as X:
            for (host, name), res, err in X.map(one, SHIRE_API):
                if res is None:                                                        # keep the last good copy for this shire
                    feats += [f for f in C.get('features', []) if f['properties'].get('shire') == name]
                    if name in old: shires.append(dict(old[name], err=err))
                    log('  shire roads %s not read: %s' % (name, err)); continue
                f, latest = res; feats += f
                shires.append({'name': name, 'url': 'https://%s/roadreport/' % host, 'closed': sum(x['properties']['closed'] for x in f),
                               'caution': sum(1 - x['properties']['closed'] for x in f), 'updated': latest})
        have = {s['name'] for s in shires if s.get('updated')}
        for name, url in SHIRE_LINKS:
            if name not in have:
                shires = [s for s in shires if s['name'] != name] + [{'name': name, 'url': url, 'link': 1}]
        C = {'at': now.isoformat(timespec='minutes'), 'features': feats, 'shires': sorted(shires, key=lambda s: s['name'])}
        json.dump(C, open(path, 'w'), separators=(',', ':'))
        log('Shire road reports: %d closed or caution roads from %d shires (%s)' % (len(feats), len([s for s in shires if s.get('closed') or s.get('caution')]),
            ', '.join('%s %d/%d' % (s['name'], s.get('closed', 0), s.get('caution', 0)) for s in shires if s.get('closed') or s.get('caution'))))
    return C


# ---------------------------------------------------------------- rain near each gauge
def rain_near(G, pos, now):
    """The nearest rain gauge (DWER telemetry or Bureau weather station) within 25 km of each river gauge."""
    R = []
    try:
        t = get(DWER + '/telem/rain.cfm')
        for row in re.findall(r'<tr class=\w+>(.*?)</tr>', t, re.S):
            td = [clean(re.sub(r'<span.*?</span>', ' ', c, flags=re.S)) for c in re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)]
            if len(td) < 8 or not td[0].isdigit(): continue
            try: at = dt.datetime.strptime(td[3], '%H:%M %d%b%Y').replace(tzinfo=AWST)
            except Exception: continue  # noqa: BLE001
            if now - at > dt.timedelta(hours=26): continue
            nine = now.replace(hour=9, minute=0, second=0, microsecond=0)
            if now < nine: nine -= dt.timedelta(days=1)
            cur = at >= nine
            R.append({'id': td[0], 'n': td[2], 'src': 'DWER', 's9': num(td[4]) if cur else None, 'to9': num(td[5]) if cur else None, 'd3': num(td[7])})
    except Exception as e:  # noqa: BLE001
        log('DWER rain not read: %s' % e)
    need = [r['id'] for r in R if r['id'] not in pos]
    for k in range(0, len(need), 100):
        q = KIWIS + urllib.parse.urlencode({'request': 'getStationList', 'station_no': ','.join(need[k:k + 100]), 'returnfields': 'station_no,station_latitude,station_longitude'})
        try:
            for no, la, lo in json.loads(get(q))[1:]: pos[no] = [round(float(la), 5), round(float(lo), 5)]
        except Exception as e:  # noqa: BLE001
            log('Rain gauge positions not read: %s' % e)
    for i in [r['id'] for r in R if r['id'] not in pos][:60]:          # not in Water Data Online: DWER's own site summary
        try:
            m = re.search(r'Latitude:\s*(-?\d+\.\d+).*?Longitude:\s*(-?\d+\.\d+)', get(DWER + '/wir/reports/publish/%s/sitesum.htm' % i, timeout=30, tries=1), re.S)
            pos[i] = [round(float(m.group(1)), 5), round(float(m.group(2)), 5)] if m else []
        except Exception: pos[i] = []  # noqa: BLE001
    for r in R: r['ll'] = pos.get(r['id']) or None
    try:
        x = ftp_get('IDW60920.xml')
        for st in re.findall(r'<station (.*?)</station>', x, re.S):
            hd = dict(re.findall(r'([\w-]+)="([^"]*)"', st.split('>', 1)[0]))
            s9 = re.search(r'type="rainfall">([\d.]+)<', st); to9 = re.search(r'type="rainfall_24hr">([\d.]+)<', st)
            if s9 is None and to9 is None: continue
            R.append({'id': 'BOM' + hd.get('bom-id', ''), 'n': hd.get('description', hd.get('stn-name', '')), 'src': 'BoM', 'll': [float(hd['lat']), float(hd['lon'])],
                      's9': float(s9.group(1)) if s9 else None, 'to9': float(to9.group(1)) if to9 else None, 'd3': None})
    except Exception as e:  # noqa: BLE001
        log('BoM rain not read: %s' % e)
    R = [r for r in R if r['ll']]
    def km2(a, b):
        return math.hypot((a[0] - b[0]) * 111.2, (a[1] - b[1]) * 111.2 * math.cos(math.radians(a[0])))
    n = 0
    for g in G:
        g['rain'] = None
        if g.get('lat') is None: continue
        best = min(((km2((g['lat'], g['lng']), r['ll']), r) for r in R), key=lambda z: z[0], default=(None, None))
        if best[1] and best[0] <= 25:
            r = best[1]; g['rain'] = {'n': r['n'], 'src': r['src'], 'km': round(best[0], 1), 's9': r['s9'], 'to9': r['to9'], 'd3': r['d3']}; n += 1
    wet = sorted([g for g in G if g['rain'] and (g['rain']['s9'] or 0) + (g['rain']['to9'] or 0) > 0], key=lambda g: -((g['rain']['s9'] or 0) + (g['rain']['to9'] or 0)))
    log('Rain gauges: %d; river gauges with rain nearby: %d; wettest: %s' % (len(R), n, ', '.join('%s %s %s/%s mm' % (g['river'], g['name'], g['rain']['s9'], g['rain']['to9']) for g in wet[:4])))
    return R


# ---------------------------------------------------------------- DWER's own hourly tables (flow in m3/s, stage)
PUB = 'https://kumina.water.wa.gov.au/waterinformation/wir/reports/publish/%s/%s'


def hourly_table(html):
    """DWER's HYHOURF report (te2/te4.htm): {'YYYY-MM-DDTHH:00': value} for the hour starting at HH."""
    m = re.search(r'(?s)<pre>(.*?)</pre>', html)
    if not m: return {}
    t = re.sub(r'<[^>]+>', '', m.group(1))
    st = re.search(r'Start Time\s+(\d\d)/(\d\d)/(\d{4})', t)
    hd = re.search(r'Hour((?:\s+\d\d/\d\d)+)\s+Hour', t)
    if not st or not hd: return {}
    y, days, prev = int(st.group(3)), [], None
    for dd, mo in re.findall(r'(\d\d)/(\d\d)', hd.group(1)):
        if prev and int(mo) < prev: y += 1                                     # across the new year
        prev = int(mo); days.append('%04d-%s-%s' % (y, mo, dd))
    out = {}
    for line in t.splitlines():
        r = re.match(r'\s*(\d+)-\s*(\d+)\s+(.*?)\s+\d+-\s*\d+\s*$', line)
        if not r: continue
        cells = re.findall(r'\[\s*\]|-?\d+\.\d+', r.group(3))
        if len(cells) != len(days): continue
        for d, c in zip(days, cells):
            if c.startswith('['): continue
            out['%sT%02d:00' % (d, int(r.group(1)))] = float(c)
    return out


def dwer_tables(G):
    """Flow (m3/s) and stage for the last 6 days from each DWER gauge's station page: {id: {'q': {...}, 's': {...}}}."""
    def one(g):
        o = {}
        for k, page in (('q', 'te4.htm'), ('s', 'te2.htm')):
            try: o[k] = hourly_table(get(PUB % (g['id'], page), timeout=40, tries=2))
            except Exception: o[k] = {}  # noqa: BLE001
        return g['id'], o
    out = {}
    with cf.ThreadPoolExecutor(8) as X:
        for sid, o in X.map(one, [g for g in G if not g['id'].startswith('B')]):
            out[sid] = o
    log('DWER hourly tables: flow for %d gauges, stage for %d' % (sum(1 for o in out.values() if o['q']), sum(1 for o in out.values() if o['s'])))
    return out


# ---------------------------------------------------------------- rain upstream (DWER's hydrographic subcatchments)
SUBCATCH = 'https://public-services.slip.wa.gov.au/public/rest/services/SLIP_Public_Services/Water/MapServer/33/query'


def subcatchments():
    """DWER-030: [{ufi, down, ref, rings, bbox}] (geometry simplified to about 300 m)."""
    out, last = [], 0
    while True:                                                              # page through by object id (offsets skipped some)
        q = SUBCATCH + '?' + urllib.parse.urlencode({'where': 'objectid > %d' % last, 'outFields': 'objectid,ufi,downstream,win_ref', 'returnGeometry': 'true', 'outSR': 4326,
                                                     'maxAllowableOffset': 0.003, 'geometryPrecision': 4, 'orderByFields': 'objectid', 'resultRecordCount': 500, 'f': 'json'})
        for k in range(4):                                                   # the service is sometimes briefly unavailable
            j = json.loads(get(q, timeout=240))
            if not j.get('error'): break
            time.sleep(10 * (k + 1))
        F = j.get('features', [])
        if not F:
            if j.get('error'): log('Subcatchments: %s' % j['error'])
            break
        last = max(f['attributes'].get('objectid', f['attributes'].get('OBJECTID', 0)) for f in F)
        for f in F:
            a, rings = f['attributes'], (f.get('geometry') or {}).get('rings') or []
            if not rings: continue
            xs = [p[0] for r in rings for p in r]; ys = [p[1] for r in rings for p in r]
            out.append({'ufi': int(a['ufi'] or 0), 'down': int(a['downstream'] or 0), 'ref': (a.get('win_ref') or '').strip(), 'rings': rings,
                        'bbox': (min(xs), min(ys), max(xs), max(ys))})
    log('Subcatchments read: %d' % len(out))
    return out


def inside(lng, lat, rings):
    c = False
    for r in rings:                                                          # even-odd: holes count themselves out
        for (x1, y1), (x2, y2) in zip(r, r[1:] + r[:1]):
            if (y1 > lat) != (y2 > lat) and lng < (x2 - x1) * (lat - y1) / (y2 - y1) + x1: c = not c
    return c


def where(S, lng, lat):
    for s in S:
        b = s['bbox']
        if b[0] <= lng <= b[2] and b[1] <= lat <= b[3] and inside(lng, lat, s['rings']): return s['ufi']
    return None


def upstream_map(G, R, out_dir, now):
    """For each river gauge, the rain gauges in its catchment: {gauge id: [rain id, ...]}. The subcatchments are read
    weekly (or daily while new gauges turn up) and cached in rivers-upstream.json as each gauge's upstream
    subcatchments and each rain gauge's subcatchment."""
    path = os.path.join(out_dir, 'rivers-upstream.json')
    try: U = json.load(open(path))
    except Exception: U = {}  # noqa: BLE001
    if U.get('v') != 4: U = {}
    U.setdefault('up', {}); U.setdefault('rain', {})
    new = [r for r in R if r['id'] not in U['rain']] + [g for g in G if g['id'] not in U['up'] and g.get('lat') is not None]
    stale = U.get('built', '') < (now - dt.timedelta(days=7)).strftime('%Y-%m-%d') or U.get('v') != 4
    if stale or (new and U.get('built', '') < now.strftime('%Y-%m-%d')):
        S = subcatchments()
        if len(S) >= 1000:
            kids, by_ref = {}, {}
            for s in S:
                kids.setdefault(s['down'], []).append(s['ufi'])
                if s['ref']: by_ref.setdefault(s['ref'], s['ufi'])
            for r in R: U['rain'][r['id']] = where(S, r['ll'][1], r['ll'][0])
            for g in G:
                top = by_ref.get(g['id'])
                if top is None and g.get('lat') is not None: top = where(S, g['lng'], g['lat'])
                seen, todo = set(), [top] if top is not None else []
                while todo:
                    u = todo.pop()
                    if u in seen: continue
                    seen.add(u); todo += kids.get(u, [])
                U['up'][g['id']] = sorted(seen)
            U['built'] = now.strftime('%Y-%m-%d'); U['v'] = 4
            json.dump(U, open(path, 'w'), separators=(',', ':'), sort_keys=True)
        else: log('Too few subcatchments read; keeping the old upstream list')
    rain_in = {}
    for rid, u in U['rain'].items():
        if u is not None: rain_in.setdefault(u, []).append(rid)
    out = {}
    for gid, ups in U['up'].items():
        ids = sorted(set(rid for u in ups for rid in rain_in.get(u, [])))
        if ids: out[gid] = ids
    log('Upstream rain: %d river gauges with rain gauges in their catchment (median %d)' % (len(out), sorted(len(v) for v in out.values())[len(out) // 2] if out else 0))
    return out


RAIN_PAGE = 'https://script.google.com/macros/s/AKfycbyoxJApPxqA86gVVXen0USujHH7OAz3_nEwonfV-8j1G4pWAyKU7aIBRCRxsYZ5DcdJ/exec'


def rain_page():
    """Every gauge on our Rainfall page (DPIRD, Bureau and DWER, about 500): since 9 am, the 24 hours to 9 am, 3 days."""
    t = get(RAIN_PAGE, timeout=150, tries=2)
    for _ in range(3):   # the page arrives as an escaped JavaScript string inside Google's wrapper
        t = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), t)
        t = t.replace('\\\\', '\\').replace('\\/', '/').replace('\\"', '"')
    R = []
    for m in re.finditer(r'\{[^{}]*?"m60_daily"[^{}]*\}', t):
        try: o = json.loads(m.group(0))
        except Exception: continue  # noqa: BLE001
        if o.get('lat') is None or o.get('lng') is None or not o.get('name'): continue
        d, d2 = o.get('daily'), o.get('d2')
        R.append({'id': 'P:' + o['name'], 'n': re.sub(r'\s+\(.*?\)\s*$', '', o['name']), 'src': o.get('source') or o.get('src') or '', 'll': [o['lat'], o['lng']],
                  's9': d, 'to9': round(d2 - d, 1) if (d is not None and d2 is not None and d2 >= d) else None, 'd3': o.get('d3')})
    log('Rainfall page gauges: %d' % len(R))
    return R


def rain_upstream(G, R, U):
    by = {r['id']: r for r in R}
    for g in G:
        L = [by[i] for i in U.get(g['id'], []) if i in by]
        if not L: g['up'] = None; continue
        def agg(k):
            v = [r[k] for r in L if r.get(k) is not None]
            return (round(sum(v) / len(v), 1), max(v), len(v)) if v else None
        w = max(L, key=lambda r: ((r.get('s9') or 0) + (r.get('to9') or 0), r.get('d3') or 0))
        g['up'] = {'n': len(L), 's9': agg('s9'), 'to9': agg('to9'), 'd3': agg('d3'),
                   'top': {'n': w['n'], 'src': w['src'], 's9': w.get('s9'), 'to9': w.get('to9'), 'd3': w.get('d3')}}


# ---------------------------------------------------------------- peaks over the last days and this month
def peaks(G, H, now, out_dir):
    """Each gauge's highest level over the last 1-7 days and this month, with when, the peak flow, and the rise to it
    (the peak less the lowest level before it in the period): g['pk'][n] = [level, when, peak flow, rise]."""
    path = os.path.join(out_dir, 'rivers-daily.json')
    try: D = json.load(open(path))
    except Exception: D = {'d': {}}  # noqa: BLE001
    D.setdefault('d', {})
    D['d'] = {k: v for k, v in D['d'].items() if not re.match(r'O\d+$', k)}
    def put(sid, d, i, v, f):
        e = D['d'].setdefault(sid, {}).setdefault(d, [None, None, None])
        while len(e) < 3: e.append(None)
        e[i] = v if e[i] is None else f(e[i], v)
    for sid, hh in H['h'].items():                                           # daily highest [0] and lowest [2] level, highest flow [1]
        for k, v in hh.items(): put(sid, k[:10], 0, v, max); put(sid, k[:10], 2, v, min)
    for sid, qq in H.get('q', {}).items():
        for k, v in qq.items(): put(sid, k[:10], 1, v, max)
    if not D.get('seeded'):                                                  # the start of the month, from Water Data Online
        ids = [g['id'] for g in G if not g['id'].startswith('B')]
        for sid, hh in kiwis_history(ids, days=12).items():
            for k, v in hh.items(): put(sid, k[:10], 0, v, max); put(sid, k[:10], 2, v, min)
        D['seeded'] = now.strftime('%Y-%m-%d')
    keep = (now - dt.timedelta(days=40)).strftime('%Y-%m-%d')
    for sid in list(D['d']):
        D['d'][sid] = {d: e for d, e in D['d'][sid].items() if d >= keep}
    json.dump(D, open(path, 'w'), separators=(',', ':'), sort_keys=True)
    month0 = now.strftime('%Y-%m-01')
    for g in G:
        hh, qq, dd = H['h'].get(g['id'], {}), H.get('q', {}).get(g['id'], {}), D['d'].get(g['id'], {})
        live = g.get('at') and not g.get('off_air')
        pk = {}
        for n in range(1, 8):
            cut = (now - dt.timedelta(hours=24 * n)).strftime('%Y-%m-%dT%H:00')
            S = sorted((k, v) for k, v in hh.items() if k >= cut)
            if live: S.append((g['at'][:16], g['lvl']))
            if not S: continue
            ip = max(range(len(S)), key=lambda i: (S[i][1], i))
            low = min(v for _, v in S[:ip + 1])
            Q = [v for k, v in qq.items() if k >= cut]
            pk[str(n)] = [round(S[ip][1], 3), S[ip][0], round(max(Q), 3) if Q else None, round(S[ip][1] - low, 3)]
        M = sorted((d, e) for d, e in dd.items() if d >= month0 and e[0] is not None)
        if M or live:
            cand = [(e[0], d) for d, e in M] + ([(g['lvl'], g['at'][:16])] if live and g['at'][:7] == month0[:7] else [])
            v, k = max(cand)
            lows = [e[2] for d, e in M if d <= k[:10] and len(e) > 2 and e[2] is not None] + [v]
            if len(k) == 10:                                                  # a day's highest: its hour, if we still have it
                hrs = [kk for kk, vv in hh.items() if kk[:10] == k and vv == v]; k = hrs[0] if hrs else k
            Q = [e[1] for d, e in M if e[1] is not None]
            pk['m'] = [round(v, 3), k, round(max(Q), 3) if Q else None, round(v - min(lows), 3)]
        g['pk'] = pk


HYDRO = 'https://public-services.slip.wa.gov.au/public/rest/services/SLIP_Public_Services/Water/MapServer/7/query'


def river_lines(G, out_dir, now):
    """The courses of the rivers that have gauges (DWER hydrography, mainstream and major river lines), plus every
    named major river, for the map: rivers-lines.json, rebuilt weekly."""
    path = os.path.join(out_dir, 'rivers-lines.json')
    try:
        old = json.load(open(path))
        if old.get('built', '') >= (now - dt.timedelta(days=7)).strftime('%Y-%m-%d') and old.get('features'): return
    except Exception: pass  # noqa: BLE001
    names = sorted(set(re.sub(r'\s+', ' ', g['river']).strip() for g in G if g.get('river') and not STILL.search(g['river'])))
    wheres = ["level = 2 AND named > 0"] + ["level IN (1, 2) AND hyd_name IN (%s)" % ','.join("'%s'" % n.replace("'", "''") for n in names[i:i + 25]) for i in range(0, len(names), 25)]
    lines, seen = {}, set()
    for w in wheres:
        last = 0
        while True:
            q = HYDRO + '?' + urllib.parse.urlencode({'where': '(%s) AND objectid > %d' % (w, last), 'outFields': 'objectid,hyd_name', 'returnGeometry': 'true', 'outSR': 4326,
                                                     'maxAllowableOffset': 0.004, 'geometryPrecision': 3, 'orderByFields': 'objectid', 'resultRecordCount': 1000, 'f': 'json'})
            j = {}
            for k in range(4):
                try: j = json.loads(get(q, timeout=240))
                except Exception as e: j = {'error': str(e)}  # noqa: BLE001
                if not j.get('error'): break
                time.sleep(10 * (k + 1))
            F = j.get('features', [])
            if not F:
                if j.get('error'): log('River lines: %s' % j['error'])
                break
            last = max(f['attributes']['objectid'] for f in F)
            for f in F:
                oid = f['attributes']['objectid']
                if oid in seen: continue
                seen.add(oid)
                nm = (f['attributes'].get('hyd_name') or '').strip()
                for path_ in (f.get('geometry') or {}).get('paths') or []:
                    if len(path_) > 1: lines.setdefault(nm, []).append(path_)
    feats = [{'type': 'Feature', 'properties': {'name': nm}, 'geometry': {'type': 'MultiLineString', 'coordinates': ps}} for nm, ps in lines.items()]
    if len(feats) < 20: log('River lines: too few read (%d); keeping the old file' % len(feats)); return
    json.dump({'type': 'FeatureCollection', 'built': now.strftime('%Y-%m-%d'), 'features': feats}, open(path, 'w'), separators=(',', ':'))
    log('River lines: %d rivers, %d segments, %d KB' % (len(feats), len(seen), os.path.getsize(path) // 1024))


BASINS = 'https://public-services.slip.wa.gov.au/public/rest/services/SLIP_Public_Services/Water/MapServer/31/query'


def label_spot(rings):
    """A point well inside the largest ring (for the basin's name): the grid point furthest from its edge."""
    r = max(rings, key=len)
    xs = [p[0] for p in r]; ys = [p[1] for p in r]
    best, bd = None, -1
    for i in range(1, 24):
        for j in range(1, 24):
            x = min(xs) + (max(xs) - min(xs)) * i / 24; y = min(ys) + (max(ys) - min(ys)) * j / 24
            if not inside(x, y, [r]): continue
            d = min(math.hypot(x - a[0], y - a[1]) for a in r[::max(1, len(r) // 400)])
            if d > bd: best, bd = (x, y), d
    return best or ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)


def basins(out_dir, now):
    """DWER's river basins (DWER-027): faint outlines and names for the map, rivers-basins.json, rebuilt monthly."""
    path = os.path.join(out_dir, 'rivers-basins.json')
    try:
        old = json.load(open(path))
        if old.get('built', '') >= (now - dt.timedelta(days=30)).strftime('%Y-%m-%d') and old.get('features'): return
    except Exception: pass  # noqa: BLE001
    q = BASINS + '?' + urllib.parse.urlencode({'where': '1=1', 'outFields': 'basin_name', 'returnGeometry': 'true', 'outSR': 4326,
                                               'maxAllowableOffset': 0.01, 'geometryPrecision': 3, 'f': 'json'})
    j = {}
    for k in range(4):
        try: j = json.loads(get(q, timeout=240))
        except Exception as e: j = {'error': str(e)}  # noqa: BLE001
        if not j.get('error'): break
        time.sleep(10 * (k + 1))
    feats = []
    for f in j.get('features', []):
        rings = (f.get('geometry') or {}).get('rings') or []
        if not rings: continue
        nm = (f['attributes'].get('basin_name') or '').strip()
        feats.append({'type': 'Feature', 'properties': {'name': nm}, 'geometry': {'type': 'MultiLineString', 'coordinates': rings}})
        x, y = label_spot(rings)
        feats.append({'type': 'Feature', 'properties': {'name': nm, 'label': 1}, 'geometry': {'type': 'Point', 'coordinates': [round(x, 3), round(y, 3)]}})
    if len(feats) < 40: log('Basins: too few read (%d)' % len(feats)); return
    json.dump({'type': 'FeatureCollection', 'built': now.strftime('%Y-%m-%d'), 'features': feats}, open(path, 'w'), separators=(',', ':'))
    log('Basins: %d, %d KB' % (len(feats) // 2, os.path.getsize(path) // 1024))


def districts(G):
    """The Bureau's forecast district for each gauge (the same districts as the rest of the site); the nearest one
    for a gauge just outside the simplified coastline."""
    dd = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'districts.json')))['districts']
    for d in dd:
        xs = [p[0] for r in d['rings'] for p in r]; ys = [p[1] for r in d['rings'] for p in r]; d['bb'] = (min(xs), min(ys), max(xs), max(ys))
    for g in G:
        g['dist'] = None
        if g.get('lat') is None: continue
        for d in dd:
            b = d['bb']
            if b[0] <= g['lng'] <= b[2] and b[1] <= g['lat'] <= b[3] and inside(g['lng'], g['lat'], d['rings']): g['dist'] = d['name']; break
        if not g['dist']:
            g['dist'] = min(dd, key=lambda d: min(math.hypot(p[0] - g['lng'], p[1] - g['lat']) for r in d['rings'] for p in r[::3]))['name']
    log('Districts: %s' % ', '.join('%s %d' % (n, c) for n, c in sorted(__import__('collections').Counter(g['dist'] for g in G).items(), key=lambda x: str(x[0]))))


STILL = re.compile(r'(?i)^lake\b|\binlet\b|\bestuary\b|\bweir\b')   # lakes, inlets and weir pools: a level, not a river flow


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    now = dt.datetime.now(AWST)
    G = read_dwer()
    if len(G) < 50: sys.exit('Too few gauges read from DWER (%d); not publishing.' % len(G))
    pos = sites([g['id'] for g in G], os.path.join(out_dir, 'rivers-sites.json'))
    for k in [k for k in pos if re.match(r'O\d+$', k)]: del pos[k]          # no shared (partner) gauges
    for g in G:                                                           # reporting or not (also used to match the Bureau's gauges)
        try: g['age'] = round((now - dt.datetime.fromisoformat(g['at'])).total_seconds() / 3600, 1)
        except Exception: g['age'] = None  # noqa: BLE001
        g['off_air'] = g['cls'] == 'rowGREY' or g['age'] is None or g['age'] > 48
    try:
        rows, F, matched = flood_levels(G, out_dir, now)
        G += bom_gauges(rows, F, matched, pos, now)
        try: G += hcs_gauges(G, pos, now)
        except Exception as e:  # noqa: BLE001
            log('Bureau water-level sites skipped: %s' % e)
        json.dump(F, open(os.path.join(out_dir, 'rivers-flood.json'), 'w'), separators=(',', ':'), sort_keys=True)
    except Exception as e:  # noqa: BLE001
        log('Flood levels skipped: %s' % e); [g.setdefault('fl', None) for g in G]
    # the hourly record: levels (h) and DWER's flows (q)
    hp = os.path.join(out_dir, 'rivers-history.json')
    try: H = json.load(open(hp))
    except Exception: H = {'h': {}}  # noqa: BLE001
    H.setdefault('q', {})
    for part in ('h', 'q'): H[part] = {k: v for k, v in H.get(part, {}).items() if not re.match(r'O\d+$', k)}   # no shared (partner) gauges
    cut = (now - dt.timedelta(hours=KEEP_H)).strftime('%Y-%m-%dT%H:00')
    thin = [g['id'] for g in G if not g['id'].startswith('B') and len([k for k in H['h'].get(g['id'], {}) if k >= cut]) < 24]   # gauges without a day of record yet
    if thin and (not H.get('seeded') or H.get('seeded') < now.strftime('%Y-%m-%d')):
        for sid, hh in kiwis_history(thin).items():
            cur = H['h'].setdefault(sid, {})
            for k, v in hh.items(): cur.setdefault(k, v)
        H['seeded'] = now.strftime('%Y-%m-%d')
    for g in G:
        if g.get('hist'): H['h'].setdefault(g['id'], {}).update(g.pop('hist')); continue   # a Bureau gauge: its own last 7 days
        if not g['at']: continue
        H['h'].setdefault(g['id'], {})[g['at'][:13] + ':00'] = g['lvl']
    # DWER's hourly tables, once an hour: their flow in m3/s, and their stage record to fill any gap in ours
    if H.get('tables', '') <= (now - dt.timedelta(minutes=50)).isoformat(timespec='minutes'):
        T = dwer_tables(G)
        filled = 0
        for g in G:
            t = T.get(g['id'])
            if not t: continue
            if t['q']: H['q'].setdefault(g['id'], {}).update(t['q'])
            if t['s'] and g.get('off') is not None:
                cur = H['h'].setdefault(g['id'], {})
                for k, st in t['s'].items():
                    if k not in cur and k >= cut: cur[k] = round(st - g['off'], 3); filled += 1
        H['tables'] = now.isoformat(timespec='minutes')
        log('Gaps filled from DWER\'s stage tables: %d hourly readings' % filled)
    for part in ('h', 'q'):
        for sid in list(H[part]):
            H[part][sid] = {k: v for k, v in H[part][sid].items() if k >= cut}
            if not H[part][sid]: del H[part][sid]
    H['made'] = now.isoformat(timespec='minutes')
    json.dump(H, open(hp, 'w'), separators=(',', ':'), sort_keys=True)
    # now: each gauge with its changes, flow, and where it sits against its record
    for g in G:
        p = pos.get(g['id']); g['lat'], g['lng'] = (p if p else (None, None))
        hh = H['h'].get(g['id'], {})
        ago = (now - dt.timedelta(hours=24)).strftime('%Y-%m-%dT%H:00')
        old = [v for k, v in sorted(hh.items()) if k <= ago]
        g['d24'] = round(g['lvl'] - old[-1], 3) if old else None
        g['hi8'] = round(max(hh.values()), 3) if hh else g['lvl']
        g['still'] = bool(STILL.search(g['river'])) or g['name'].lower().startswith('weir ')
        g['pct'] = max(0, round(100 * g['lvl'] / g['rec'])) if g['rec'] and g['rec'] > 0.2 and not g['still'] else None   # below the gauge's zero counts as 0%
        if g['id'].startswith('B'):
            try: g['age'] = round((now - dt.datetime.fromisoformat(g['at'])).total_seconds() / 3600, 1)
            except Exception: g['age'] = None  # noqa: BLE001
            g['off_air'] = g['age'] is None or g['age'] > 48
        g['tidal'] = g['id'] in TIDAL or tidal([v for k, v in sorted(hh.items()) if k >= (now - dt.timedelta(hours=72)).strftime('%Y-%m-%dT%H:00')])
        # the rise over the last 3 hours, per hour (steadier than one hour's change)
        g['r3'] = None
        if g.get('at'):
            k3 = (dt.datetime.fromisoformat(g['at']) - dt.timedelta(hours=3)).strftime('%Y-%m-%dT%H:00')
            back = [v for k, v in sorted(hh.items()) if k <= k3 and k >= (dt.datetime.fromisoformat(g['at']) - dt.timedelta(hours=5)).strftime('%Y-%m-%dT%H:00')]
            if back: g['r3'] = round((g['lvl'] - back[-1]) / 3, 3)
        # flow as DWER publishes it (their latest hour), and its change over the hour before
        qq = H['q'].get(g['id'], {})
        ks = sorted(qq)
        g['q'] = qq[ks[-1]] if ks else None
        g['qat'] = ks[-1] if ks else None
        g['dq'] = round(qq[ks[-1]] - qq[ks[-2]], 3) if len(ks) > 1 else None
        g['dry'] = (g['q'] is not None and g['q'] < 0.001) or g['lvl'] <= 0.02
    try: flood_roads(out_dir)
    except Exception as e:  # noqa: BLE001
        log('Flooded roads not read: %s' % e)
        if not os.path.exists(os.path.join(out_dir, 'rivers-roads.json')): json.dump({'type': 'FeatureCollection', 'features': []}, open(os.path.join(out_dir, 'rivers-roads.json'), 'w'))
    R = []
    try: R = rain_near(G, pos, now) or []
    except Exception as e:  # noqa: BLE001
        log('Rain skipped: %s' % e); [g.setdefault('rain', None) for g in G]
    try:
        RP = rain_page()
        if len(RP) < 200: RP = R                                              # the Rainfall page didn't load: DWER and Bureau gauges only
        rain_upstream(G, RP, upstream_map(G, RP, out_dir, now) if RP else {})
    except Exception as e:  # noqa: BLE001
        log('Upstream rain skipped: %s' % e); [g.setdefault('up', None) for g in G]
    json.dump(pos, open(os.path.join(out_dir, 'rivers-sites.json'), 'w'), separators=(',', ':'), sort_keys=True)
    try: basins(out_dir, now)
    except Exception as e:  # noqa: BLE001
        log('Basins skipped: %s' % e)
    try: river_lines(G, out_dir, now)
    except Exception as e:  # noqa: BLE001
        log('River lines skipped: %s' % e)
    try: peaks(G, H, now, out_dir)
    except Exception as e:  # noqa: BLE001
        log('Peaks skipped: %s' % e)
    for f in ('rivers-upstream.json', 'rivers-daily.json', 'rivers-lines.json', 'rivers-basins.json'):                 # always something to publish
        if not os.path.exists(os.path.join(out_dir, f)): json.dump({}, open(os.path.join(out_dir, f), 'w'))
    wp = os.path.join(out_dir, 'rivers-waves.json')
    try: WAVES.update(json.load(open(wp)))
    except Exception: pass  # noqa: BLE001
    try:
        travel(G, H, now)
        json.dump(WAVES, open(wp, 'w'), separators=(',', ':'), sort_keys=True)
    except Exception as e:  # noqa: BLE001
        log('Travel times skipped: %s' % e)
    try: districts(G)
    except Exception as e:  # noqa: BLE001
        log('Districts skipped: %s' % e)
    D = {'made': now.isoformat(timespec='minutes'), 'gauges': G}
    json.dump(D, open(os.path.join(out_dir, 'rivers.json'), 'w'), separators=(',', ':'))
    rising = sorted([g for g in G if rising_now(g)], key=lambda g: -(g['r3'] or g['rate'] or 0))
    log('Flow from DWER: %d gauges. Biggest: %s' % (len([g for g in G if g['q'] is not None]), ', '.join(
        '%s %s %.1f m3/s' % (g['river'], g['name'], g['q']) for g in sorted([g for g in G if g['q'] is not None and not g['off_air']], key=lambda g: -g['q'])[:5])))
    log('Tidal: %s' % ', '.join(g['river'] + ' ' + g['name'] for g in G if g['tidal']))
    log('Still water (lakes, weir pools): %s' % ', '.join(g['river'] + ' ' + g['name'] for g in G if g['still']))
    log('Not reporting: %d' % len([g for g in G if g['off_air']]))
    log('Rising: %d. Fastest: %s' % (len(rising), ', '.join('%s %s %+.3f m/h' % (g['river'], g['name'], g['r3'] or g['rate']) for g in rising[:5])))
    top = sorted([g for g in G if g['pct'] is not None and not g['still']], key=lambda g: -g['pct'])[:5]
    log('Highest vs record: %s' % ', '.join('%s %s %d%%' % (g['river'], g['name'], g['pct']) for g in top))
    log('History: %d gauges, %d hourly readings, %d flow readings' % (len(H['h']), sum(len(v) for v in H['h'].values()), sum(len(v) for v in H['q'].values())))


RISE, FAST = 0.02, 0.10   # metres an hour, averaged over 3 hours: rising, and rising fast (the page uses the same)


TRAVEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'rivers-travel.json')
WAVES = {'open': {}, 'log': []}   # loaded from / saved to rivers-waves.json by main()


def calibrated(r, live):
    """A pair's travel times from its past floods (r['ev'], from the quality-coded records) plus the floods this
    job has watched itself (live, from rivers-waves.json), each of those counted twice: recent floods count for
    more, and they reach the quality-coded records only months later (an event already there isn't counted again)."""
    ev = [(x[0], x[1]) for x in r.get('ev', [])]
    hist_h = [x[2] for x in r.get('ev', [])]
    add = []
    for e in live:
        ha = int(dt.datetime.fromisoformat(e['pk']).timestamp() // 3600)
        if any(abs(ha - h) <= 48 for h in hist_h): continue
        add += [(e['lag'], e['rise'])] * 2
    if not add or not ev: return r
    m = ev + add; lags = sorted(x[0] for x in m)
    q = lambda p: lags[min(len(lags) - 1, int(p * (len(lags) - 1) + 0.5))]
    big = sorted(x[0] for x in sorted(m, key=lambda x: -x[1])[:max(1, len(m) // 3)])
    last = max(live, key=lambda e: e['pk'])
    return dict(r, n=len(ev) + len(add) // 2, med=q(0.5), lo=q(0.25), hi=q(0.75), big=big[len(big) // 2], cal=len(add) // 2,
                lastlive={'pk': last['pk'], 'lag': last['lag'], 'pred': last['pred']})


def learn(W, by, H, now):
    """Close the flood waves being watched: once the downstream gauge has peaked (risen 0.2 m+ above its level when
    the upstream gauge peaked, then dropped 5 cm+ for 3 hours) or the watch window has run out, log the real delay
    beside the predicted one. Each logged flood then counts in that pair's travel times (calibrated)."""
    for key, w in list(W['open'].items()):
        ta = dt.datetime.fromisoformat(w['pk']); end = ta + dt.timedelta(hours=w['win'])
        hb = H['h'].get(w['b'], {})
        ks = sorted(k for k in hb if ta.strftime('%Y-%m-%dT%H:00') <= k <= end.strftime('%Y-%m-%dT%H:00'))
        base = w.get('base') if w.get('base') is not None else (hb[ks[0]] if ks else None)
        done = now > end
        if ks and base is not None:
            kb = max(ks, key=lambda k: hb[k]); vb = hb[kb]
            after = [hb[k] for k in ks if k > kb]
            tb = dt.datetime.fromisoformat(kb).replace(tzinfo=AWST)
            if vb - base >= 0.2 and kb != ks[-1] and len(after) >= 3 and max(after[-3:]) <= vb - 0.05:
                lag = int(round((tb - ta).total_seconds() / 3600))
                W['log'].append({'a': w['a'], 'b': w['b'], 'pk': w['pk'], 'pkb': tb.isoformat(timespec='minutes'), 'lag': lag, 'pred': w['pred'], 'first': w.get('first'),
                                 'err': lag - w['pred'], 'rise': w['rise'], 'riseb': round(vb - base, 2)})
                log('Flood wave learnt: %s %s -> %s %s took %d h (predicted %d h)' % (by.get(w['a'], {}).get('river', ''), by.get(w['a'], {}).get('name', w['a']),
                    by.get(w['b'], {}).get('river', ''), by.get(w['b'], {}).get('name', w['b']), lag, w['pred']))
                del W['open'][key]; continue
        if done:
            log('Flood wave not seen downstream: %s -> %s (peak %s)' % (w['a'], w['b'], w['pk'])); del W['open'][key]
    W['log'] = W['log'][-500:]


def travel(G, H, now):
    """Flood travel times (data/rivers-travel.json, learnt from past floods by travel.py). Every gauge with one gets
    g['dn'] = {to, tn (name), tr (river), n, med, lo, hi, big} (hours). When a flood rise is under way (the gauge
    has risen by the pair's flood size within 3 days), also: st = 'rising' (not yet peaked) or 'peaked', pk = when
    it peaked and eta = when that peak usually reaches the next gauge (the big-flood time when this rise is in the
    top third of past ones). The downstream gauge gets g['inc'] = [{fr, fn, eta, st}] for each wave on its way."""
    try: T = json.load(open(TRAVEL))['pairs']
    except Exception as e:  # noqa: BLE001
        log('No travel times (%s)' % e); return
    W = WAVES                                                               # live flood waves and what they did (rivers-waves.json)
    by = {g['id']: g for g in G}; n = 0
    learn(W, by, H, now)
    for g in G:
        r = T.get(g['id'])
        if not r or 'med' not in r or r['to'] not in by: continue
        b = by[r['to']]
        r = calibrated(r, [e for e in W['log'] if e['a'] == g['id'] and e['b'] == b['id']])
        d = {'to': b['id'], 'tn': b['name'], 'tr': b['river'], 'n': r['n'], 'med': r['med'], 'lo': r['lo'], 'hi': r['hi'], 'big': r['big']}
        if r.get('cal'): d['cal'] = r['cal']; d['last'] = r['lastlive']
        g['dn'] = d; n += 1
        hh = H['h'].get(g['id'], {})
        if g.get('off_air') or not hh: continue
        last = sorted(k for k in hh if k >= (now - dt.timedelta(hours=72)).strftime('%Y-%m-%dT%H:00'))
        if len(last) < 6: continue
        kp = max(last, key=lambda k: hh[k]); vp = hh[kp]
        before = [hh[k] for k in hh if (dt.datetime.fromisoformat(kp) - dt.timedelta(hours=72)).strftime('%Y-%m-%dT%H:00') <= k < kp]
        rise = vp - min(before) if before else 0
        if rise < r.get('rise', 0.3): continue
        tp = dt.datetime.fromisoformat(kp).replace(tzinfo=AWST)
        peaked = kp < last[-1] and g['lvl'] < vp - 0.05 and now - tp >= dt.timedelta(hours=2)
        lag = d['big'] if rise >= 2 * r.get('rise', 0.3) else d['med']
        # first flow of the season: no flood here for FIRST_GAP_D days (the record's last flood, or one this job saw)
        hp = int(tp.timestamp() // 3600)
        prev = [x for x in (r.get('lastpk'), W.setdefault('lastpk', {}).get(g['id'])) if x and x < hp - 72]
        gap = (hp - max(prev)) / 24 if prev else None
        if gap is not None and gap >= 60:
            d['first'] = round(gap)
            if r.get('first'): lag = max(lag, r['first']['med']); d['fmed'] = r['first']['med']; d['fn'] = r['first']['n']
            if r.get('wet'): d['wmed'] = r['wet']['med']
        if not W['lastpk'].get(g['id']) or W['lastpk'][g['id']] < hp: W['lastpk'][g['id']] = hp
        d['st'] = 'peaked' if peaked else 'rising'
        d['rise'] = round(rise, 2)
        if peaked:
            d['pk'] = tp.isoformat(timespec='minutes'); eta = tp + dt.timedelta(hours=lag)
            key = g['id'] + '>' + b['id']
            if key not in W['open'] or W['open'][key]['pk'] != d['pk']:      # a new wave: watch for it downstream, to learn from it
                if not any(e['a'] == g['id'] and e['pk'] == d['pk'] for e in W['log']):
                    W['open'][key] = {'a': g['id'], 'b': b['id'], 'pk': d['pk'], 'pred': lag, 'rise': d['rise'], 'first': d.get('first'),
                                      'base': H['h'].get(b['id'], {}).get(kp), 'win': min(KEEP_H - 12, int(2.5 * max(lag, r['hi']) + 24))}
            if eta > now - dt.timedelta(hours=6): d['eta'] = eta.isoformat(timespec='minutes')
            else: d.pop('st'); continue                                   # long since passed downstream
        b.setdefault('inc', []).append({'fr': g['id'], 'fn': g['name'], 'fr_r': g['river'], 'st': d['st'], 'eta': d.get('eta'), 'lag': lag})
    act = [g for g in G if g.get('dn', {}).get('st')]
    log('Travel times: %d gauges; flood waves under way: %s' % (n, ', '.join('%s %s -> %s (%s%s)' % (g['river'], g['name'], g['dn']['tn'], g['dn']['st'],
        ', due ' + g['dn']['eta'] if g['dn'].get('eta') else '') for g in act) or 'none'))


def rising_now(g):
    if g['off_air'] or g['tidal']: return False
    r = g['r3'] if g['r3'] is not None else g['rate']
    if r is None: return False
    return r >= (FAST if g['dry'] else RISE) and (g['rate'] or 0) > 0


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'out')

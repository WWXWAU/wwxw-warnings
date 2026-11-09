"""WA river levels for the West WX Watchers River Levels page.

Every 15 minutes (GitHub Actions):
  * DWER's telemetered river gauges (kumina.water.wa.gov.au/waterinformation/telem/stage.cfm): level, hourly change,
    trend and record high for ~250 gauges (provisional, unaudited data).
  * Gauge positions from the Bureau's Water Data Online (KiWIS), cached in rivers-sites.json.
  * An hourly 8-day level record per gauge, kept in rivers-history.json: our own readings, with the gaps filled from
    Water Data Online's provisional level series (about a day behind, so it seeds the first week).
Writes rivers.json (now) and rivers-history.json (the record) into the output folder.
"""
import bisect, datetime as dt, ftplib, io, json, math, os, re, sys, time, urllib.parse, urllib.request

UA = {'User-Agent': 'Mozilla/5.0 (West WX Watchers river levels; westweatherwatchers.com)'}
DWER = 'https://kumina.water.wa.gov.au/waterinformation'
KIWIS = 'http://www.bom.gov.au/waterdata/services?service=kisters&type=queryServices&datasource=0&format=json&'
AWST = dt.timezone(dt.timedelta(hours=8))
KEEP_H = 8 * 24
TIDAL = {'616004', '616094'}   # known tide-affected gauges (Swan estuary at Guildford; below Kent Street Weir), on top of the test below


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
    return set(w for w in re.findall(r'[a-z]+', t.lower()) if w not in STOP and len(w) > 1)


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


# ---------------------------------------------------------------- flow, from the level
def rating_build(ids, out_dir, now):
    """Each gauge's level-to-flow relationship, from the Bureau's daily highest and lowest level and flow over
    five years (Water Data Online). Rebuilt weekly into rivers-ratings.json: {id: [[level, flow], ...]}."""
    path = os.path.join(out_dir, 'rivers-ratings.json')
    try: R = json.load(open(path))
    except Exception: R = {'r': {}}  # noqa: BLE001
    if R.get('built', '') >= (now - dt.timedelta(days=7)).strftime('%Y-%m-%d') and len(R['r']) > 100:
        return R
    want = {}
    for par in ('Water Course Level', 'Water Course Discharge'):
        q = KIWIS + urllib.parse.urlencode({'request': 'getTimeseriesList', 'station_no': ','.join(ids), 'parametertype_name': par,
                                            'ts_name': 'DMQaQc.Merged.DailyMax.24HR,DMQaQc.Merged.DailyMin.24HR', 'returnfields': 'station_no,ts_id,ts_name'})
        try:
            for no, ts, nm in json.loads(get(q, timeout=180))[1:]: want[(no, par[13:16], 'Max' if 'DailyMax' in nm else 'Min')] = ts   # (id, 'Lev'/'Dis', 'Max'/'Min')
        except Exception as e:  # noqa: BLE001
            log('Rating series list not read (%s): %s' % (par, e)); return R
    vals = {}
    keys = list(want)
    for k in range(0, len(keys), 20):
        chunk = keys[k:k + 20]
        q = KIWIS + urllib.parse.urlencode({'request': 'getTimeseriesValues', 'ts_id': ','.join(want[c] for c in chunk), 'period': 'P1826D', 'returnfields': 'Timestamp,Value'})
        try: res = json.loads(get(q, timeout=300))
        except Exception as e:  # noqa: BLE001
            log('  rating values not read: %s' % e); continue
        back = {v: kk for kk, v in want.items()}
        for r in res:
            kk = back.get(str(r.get('ts_id')))
            if kk: vals[kk] = {ts[:10]: v for ts, v in r.get('data', []) if v is not None}
        time.sleep(0.5)
    built = 0
    for sid in ids:
        pts = []
        for mm in ('Max', 'Min'):
            L, Q = vals.get((sid, 'Lev', mm), {}), vals.get((sid, 'Dis', mm), {})
            pts += [(L[d], Q[d]) for d in L if d in Q and Q[d] >= 0]
        if len(pts) < 60: continue
        pts.sort()
        # bins of about equal count; the median flow in each; then made never to fall as the level rises
        n = len(pts); nb = min(40, max(8, n // 25)); knots = []
        for b in range(nb):
            seg = pts[b * n // nb:(b + 1) * n // nb]
            if not seg: continue
            qs = sorted(q for _, q in seg)
            knots.append([round(sum(l for l, _ in seg) / len(seg), 3), qs[len(qs) // 2]])
        top = pts[-max(3, n // 200):]                                     # the highest few days pin the top of the curve
        knots.append([round(sum(l for l, _ in top) / len(top), 3), sorted(q for _, q in top)[len(top) // 2]])
        out = []
        for l, q in sorted(knots):
            if out and l <= out[-1][0] + 0.002: out[-1][1] = max(out[-1][1], q); continue
            out.append([l, max(q, out[-1][1] if out else 0)])
        if len(out) >= 4 and out[-1][1] > 0:
            R['r'][sid] = [[l, round(q, 4)] for l, q in out]; built += 1
    R['built'] = now.strftime('%Y-%m-%d')
    json.dump(R, open(path, 'w'), separators=(',', ':'), sort_keys=True)
    log('Flow ratings built: %d gauges' % built)
    return R


def flow(knots, lvl):
    """Flow (m3/s) at a level from a gauge's rating; (flow, beyond) where beyond = above the highest level rated."""
    if not knots or lvl is None: return None, False
    ls = [k[0] for k in knots]
    if lvl <= ls[0]: return knots[0][1] if lvl >= ls[0] - 0.05 else 0.0, False
    i = bisect.bisect_left(ls, lvl)
    if i >= len(knots):                                                   # above the curve: carry on along its last slope, flagged
        (l1, q1), (l2, q2) = knots[-2], knots[-1]
        s = (q2 - q1) / (l2 - l1) if l2 > l1 else 0
        return max(q2, q2 + s * (lvl - l2)), True
    (l1, q1), (l2, q2) = knots[i - 1], knots[i]
    return q1 + (q2 - q1) * (lvl - l1) / (l2 - l1), False


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    now = dt.datetime.now(AWST)
    G = read_dwer()
    if len(G) < 50: sys.exit('Too few gauges read from DWER (%d); not publishing.' % len(G))
    pos = sites([g['id'] for g in G], os.path.join(out_dir, 'rivers-sites.json'))
    json.dump(pos, open(os.path.join(out_dir, 'rivers-sites.json'), 'w'), separators=(',', ':'), sort_keys=True)
    # the hourly record
    hp = os.path.join(out_dir, 'rivers-history.json')
    try: H = json.load(open(hp))
    except Exception: H = {'h': {}}  # noqa: BLE001
    cut = (now - dt.timedelta(hours=KEEP_H)).strftime('%Y-%m-%dT%H:00')
    thin = [g['id'] for g in G if len([k for k in H['h'].get(g['id'], {}) if k >= cut]) < 24]   # gauges without a day of record yet
    if thin and (not H.get('seeded') or H.get('seeded') < now.strftime('%Y-%m-%d')):
        for sid, hh in kiwis_history(thin).items():
            cur = H['h'].setdefault(sid, {})
            for k, v in hh.items(): cur.setdefault(k, v)
        H['seeded'] = now.strftime('%Y-%m-%d')
    for g in G:
        if not g['at']: continue
        hk = g['at'][:13] + ':00'
        H['h'].setdefault(g['id'], {})[hk] = g['lvl']
    for sid in list(H['h']):
        H['h'][sid] = {k: v for k, v in H['h'][sid].items() if k >= cut}
        if not H['h'][sid]: del H['h'][sid]
    H['made'] = now.isoformat(timespec='minutes')
    json.dump(H, open(hp, 'w'), separators=(',', ':'), sort_keys=True)
    # now: each gauge with its change over 24 h and its 8-day high, and where it sits against its record
    for g in G:
        p = pos.get(g['id']); g['lat'], g['lng'] = (p if p else (None, None))
        hh = H['h'].get(g['id'], {})
        ago = (now - dt.timedelta(hours=24)).strftime('%Y-%m-%dT%H:00')
        old = [v for k, v in sorted(hh.items()) if k <= ago]
        g['d24'] = round(g['lvl'] - old[-1], 3) if old else None
        g['hi8'] = round(max(hh.values()), 3) if hh else g['lvl']
        g['pct'] = max(0, round(100 * g['lvl'] / g['rec'])) if g['rec'] and g['rec'] > 0.2 else None   # below the gauge's zero counts as 0%
        try: g['age'] = round((now - dt.datetime.fromisoformat(g['at'])).total_seconds() / 3600, 1)
        except Exception: g['age'] = None  # noqa: BLE001
        g['off_air'] = g['cls'] == 'rowGREY' or g['age'] is None or g['age'] > 48       # not reporting
        g['tidal'] = g['id'] in TIDAL or tidal([v for k, v in sorted(hh.items()) if k >= (now - dt.timedelta(hours=72)).strftime('%Y-%m-%dT%H:00')])
    try: flood_levels(G, out_dir, now)
    except Exception as e:  # noqa: BLE001
        log('Flood levels skipped: %s' % e); [g.setdefault('fl', None) for g in G]
    R = rating_build([g['id'] for g in G], out_dir, now)
    for g in G:
        q, beyond = flow(R['r'].get(g['id']), g['lvl'])
        g['q'] = None if q is None else round(q, 3 if q < 1 else 2 if q < 10 else 1)
        g['qx'] = beyond
        if g['q'] is not None and g['rate'] is not None:                    # the flow an hour ago, for the change
            q0, _ = flow(R['r'].get(g['id']), g['lvl'] - g['rate']); g['dq'] = round(g['q'] - q0, 3)
    log('Flow estimated: %d gauges. Biggest: %s' % (len([g for g in G if g['q'] is not None]), ', '.join(
        '%s %s %.1f m3/s' % (g['river'], g['name'], g['q']) for g in sorted([g for g in G if g['q'] is not None and not g['off_air']], key=lambda g: -g['q'])[:5])))
    D = {'made': now.isoformat(timespec='minutes'), 'gauges': G}
    json.dump(D, open(os.path.join(out_dir, 'rivers.json'), 'w'), separators=(',', ':'))
    rising = sorted([g for g in G if (g['rate'] or 0) > 0.005 and not g['tidal'] and not g['off_air']], key=lambda g: -(g['rate'] or 0))
    log('Tidal: %s' % ', '.join(g['river'] + ' ' + g['name'] for g in G if g['tidal']))
    log('Not reporting: %d' % len([g for g in G if g['off_air']]))
    log('Rising: %d. Fastest: %s' % (len(rising), ', '.join('%s %s %+.3f m/h' % (g['river'], g['name'], g['rate']) for g in rising[:5])))
    top = sorted([g for g in G if g['pct'] is not None], key=lambda g: -g['pct'])[:5]
    log('Highest vs record: %s' % ', '.join('%s %s %d%%' % (g['river'], g['name'], g['pct']) for g in top))
    log('History: %d gauges, %d hourly readings' % (len(H['h']), sum(len(v) for v in H['h'].values())))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'out')

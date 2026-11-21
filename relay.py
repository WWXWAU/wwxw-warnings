#!/usr/bin/env python3
"""
West WX Watchers — BoM warnings relay (runs on GitHub Actions every 5 minutes).

Fetches WA Severe Thunderstorm, Severe Weather and Tropical Cyclone warnings from the
Bureau of Meteorology's anonymous FTP server (ftp.bom.gov.au/anon/gen/fwo — BoM's free
public channel for warning products) and writes data/warnings.json for the website.

Warning areas:
  * Tropical cyclone watches/warnings: BoM's own polygon from the CAP file.
  * Severe thunderstorm / severe weather: the yellow warning area in BoM's warning image,
    placed on the map by matching the image to the WA coastline (data/frames.json remembers each frame).
    Otherwise an outline around the "Locations which may be
    affected" listed in the warning (40 km buffer), trimmed to the named forecast districts
    and the WA coast. Falls back to the named districts if fewer than 2 towns can be placed.
The official BoM warning image is saved alongside (unaltered) and linked to BoM.

Usage: python relay.py            (live, from BoM FTP)
       python relay.py --local DIR (test: read the CAP/PNG files from DIR instead)
"""
import ftplib, io, json, os, re, sys, time, zipfile, urllib.request, datetime as dt
import xml.etree.ElementTree as ET
from shapely.geometry import Point, Polygon, MultiPolygon, mapping, shape
from shapely.ops import unary_union
try:
    import PIL  # noqa: F401  (Pillow reads BoM's warning images)
except ImportError:
    import subprocess
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', 'pillow', 'numpy', 'h5py'], check=False)
try:
    from warnimg import render as warn_images          # post and story images for each current warning
except Exception as e:
    warn_images = None
    print('Warning images unavailable:', e, flush=True)
try:
    from imgarea import yellow_area
except Exception as e:   # if the image reader isn't available, fall back to the town/district outlines
    yellow_area = None
    print('Image areas unavailable:', e, flush=True)

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
IMG = os.path.join(DATA, 'img')
CAP = '{urn:oasis:names:tc:emergency:cap:1.2}'

# product code -> (type, official image product)
PRODUCTS = {
    'IDW21033': ('Severe Thunderstorm Warning', 'IDW21041'),
    'IDW21034': ('Severe Thunderstorm Warning', 'IDW21044'),
    'IDW21035': ('Severe Thunderstorm Warning (Perth Area)', 'IDW20147'),
    'IDW21037': ('Severe Weather Warning', 'IDW21063'),
    'IDW21038': ('Severe Weather Warning', 'IDW21066'),
    'IDW24500': ('Tropical Cyclone Advice', 'IDW60280'),
    'IDW24510': ('Tropical Cyclone Advice', 'IDW60284'),
    'IDW24520': ('Tropical Cyclone Advice', 'IDW60287'),
}
HAZARDS = ['destructive winds', 'damaging winds', 'intense rainfall', 'heavy rainfall', 'giant hail', 'large hail',
           'tornado', 'abnormally high tides', 'damaging surf', 'gales', 'very destructive winds']
BUFFER_DEG = 0.5           # about 55 km around each listed town (BoM draws generously)
KEEP_ENDED_H = 6           # keep cancelled/expired warnings in the file this long (so subscribers hear about it)


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- fetching
EXTRA_RE = re.compile(r'^IDW\d{5}\.cap\.xml$|^IDW[23]\d{4}\.txt$')   # other WA warnings (flood, frost): sorted out by their text


def fetch_ftp(names):
    out = {}
    try:
        ftp = ftplib.FTP('ftp.bom.gov.au', timeout=60)
        ftp.login()
        ftp.cwd('/anon/gen/fwo')
        present = set(ftp.nlst())
        known = set(names)
        names = list(names) + sorted(n for n in present if EXTRA_RE.match(n) and n not in known)
        for n in names:
            if n not in present:
                continue
            buf = io.BytesIO()
            ftp.retrbinary('RETR ' + n, buf.write)
            out[n] = buf.getvalue()
        ftp.quit()
    except Exception as e:
        log('FTP problem:', e)
        return None   # leave the previous file as it is
    return out


def fetch_local(folder, names):
    names = list(names) + [n for n in os.listdir(folder) if EXTRA_RE.match(n) and n not in names]
    return {n: open(os.path.join(folder, n), 'rb').read() for n in names if os.path.exists(os.path.join(folder, n))}


# ---------------------------------------------------------------- flood and frost warnings
def extra_kind(txt):
    t = txt.lower()
    if 'flood' in t and 'watch' in t[:200]: return 'Flood Watch'
    if 'flood warning' in t or 'flood' in t[:200]: return 'Flood Warning'
    if 'frost' in t[:300]: return 'Frost Warning'
    return None


MONTHS = {m: i + 1 for i, m in enumerate(['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
                                          'september', 'october', 'november', 'december'])}


def parse_txt(raw, code):
    """A plain-text BoM warning (used when there's no CAP copy): headline, issue time, text."""
    t = raw.decode('latin-1').replace('\r', '')
    lines = [l.strip() for l in t.split('\n')]
    head = next((l for l in lines[:15] if re.search(r'flood|frost', l, re.I)), '')
    if not head: return []
    m = re.search(r'Issued at (\d{1,2}):(\d{2}) ?([ap]m) (?:WST|AWST) on \w+ (\d{1,2}) (\w+) (\d{4})', t, re.I)
    if not m: return []
    hh = int(m.group(1)) % 12 + (12 if m.group(3).lower() == 'pm' else 0)
    sent = dt.datetime(int(m.group(6)), MONTHS.get(m.group(5).lower(), 1), int(m.group(4)), hh, int(m.group(2)),
                       tzinfo=dt.timezone(dt.timedelta(hours=8)))
    body = '\n'.join(l for l in lines[lines.index(head) + 1:] if not re.match(r'(Issued at|by the Bureau|Australian Government)', l, re.I)).strip()
    body = re.split(r'\n(?:The next|Next) [^\n]*will be issued', body)[0] if body else body
    exp = sent + dt.timedelta(hours=24)
    return [{'code': code, 'msgType': 'Alert', 'sent': sent.isoformat(), 'event': head, 'headline': head,
             'description': re.sub(r'\n{3,}', '\n\n', body)[:3000], 'expires': exp.isoformat(), 'severity': '', 'urgency': '',
             'areas': [], 'polys': [], 'cancelled': bool(re.match(r'(final|cancellation)', head, re.I))}]


def places_named(desc, places):
    """Places mentioned anywhere in a warning's text (flood warnings name river towns and gauges, not a list)."""
    out = []
    desc = re.sub(r'Bureau of Meteorology,? \w+', '', desc)
    for m in re.finditer(r"\b([A-Z][a-z']+(?: [A-Z][a-z']+){0,2})\b(?! (?:River|Creek|Brook|Dam|Catchment|Basin|Range))", desc):
        for k in range(3, 0, -1):
            words = m.group(1).split()[:k]
            nm = ' '.join(words)
            if len(words) == k and len(nm) >= 5 and norm(nm) in places:
                if nm not in out: out.append(nm)
                break
    return [n for n in out if not any(n != o and o.startswith(n + ' ') for o in out)][:20]


# ---------------------------------------------------------------- places (GeoNames, CC BY 4.0)
def load_places():
    path = os.path.join(DATA, 'wa_places.json')
    if os.path.exists(path):
        return json.load(open(path))
    log('Downloading GeoNames AU (once)...')
    raw = urllib.request.urlopen('https://download.geonames.org/export/dump/AU.zip', timeout=120).read()
    places = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for line in z.read('AU.txt').decode('utf-8').splitlines():
            f = line.split('\t')
            # populated places (P) and a few useful localities (L / T) in WA (admin1 code 08)
            if len(f) < 15 or f[10] != '08' or f[6] not in ('P', 'L', 'T', 'S'):
                continue
            lat, lng, pop = float(f[4]), float(f[5]), int(f[14] or 0)
            for nm in [f[1], f[2]]:
                k = norm(nm)
                if k and (k not in places or pop > places[k][2] or (f[6] == 'P' and places[k][3] != 'P')):
                    places[k] = [round(lat, 4), round(lng, 4), pop, f[6]]
    json.dump(places, open(path, 'w'))
    log('Saved', len(places), 'WA place names.')
    return places


def norm(s):
    return re.sub(r'[^a-z0-9 ]', '', s.lower().replace('mt ', 'mount ').replace('&', 'and')).strip()


# ---------------------------------------------------------------- reading CAP
def text(el, tag):
    x = el.find(CAP + tag)
    return (x.text or '').strip() if x is not None and x.text else ''


def parse_cap(raw, code):
    root = ET.fromstring(raw)
    alert = root if root.tag == CAP + 'alert' else root.find('.//' + CAP + 'alert')
    if alert is None:
        return []
    msg_type, sent = text(alert, 'msgType'), text(alert, 'sent')
    out = []
    for info in alert.findall(CAP + 'info'):
        headline, desc = text(info, 'headline'), text(info, 'description')
        areas, polys = [], []
        for a in info.findall(CAP + 'area'):
            d = text(a, 'areaDesc')
            if d:
                areas.append(d)
            for p in a.findall(CAP + 'polygon'):
                pts = [tuple(map(float, xy.split(','))) for xy in (p.text or '').split() if ',' in xy]
                if len(pts) >= 3:
                    polys.append(Polygon([(lng, lat) for lat, lng in pts]))
        out.append({'code': code, 'msgType': msg_type, 'sent': sent, 'event': text(info, 'event'),
                    'headline': headline, 'description': desc, 'expires': text(info, 'expires'),
                    'severity': text(info, 'severity'), 'urgency': text(info, 'urgency'),
                    'areas': areas, 'polys': polys,
                    'cancelled': msg_type == 'Cancel' or headline.lower().startswith('cancellation')})
    return out


def towns_in(desc):
    """Every 'Locations which may be affected include ...' list (a warning can have one per area), in order."""
    out = []
    for m in re.finditer(r'Locations which may be affected include ([^.]+)\.', desc, re.I):
        for t in re.sub(r'\s+and\s+', ', ', m.group(1)).split(','):
            t = t.strip()
            if t and t not in out: out.append(t)
    return out


def hazards_in(txt):
    t = txt.lower()
    found = [h for h in HAZARDS if h in t]
    # keep the strongest of each pair
    for weak, strong in [('damaging winds', 'destructive winds'), ('heavy rainfall', 'intense rainfall'), ('large hail', 'giant hail')]:
        if weak in found and strong in found:
            found.remove(weak)
    return found


# ---------------------------------------------------------------- polygons
def load_districts():
    d = json.load(open(os.path.join(DATA, 'districts.json')))
    shapes = {x['name'].lower(): unary_union([Polygon(r).buffer(0) for r in x['rings']]) for x in d['districts']}
    wa = unary_union([Polygon(r).buffer(0) for r in d['wa']])
    return shapes, wa


def named_districts(areas, desc, shapes):
    txt = (' '.join(areas) + ' ' + desc).lower()
    return [n for n in shapes if re.search(r'\b' + re.escape(n) + r'\b', txt)]


def tidy_area(g, dists, shapes, wa):
    """Clean an area traced from BoM's warning image: close small notches (about 12 km), drop thin slivers
    (about 5 km), then trim to the districts the warning names (and the coast), so edges that follow a
    district boundary run exactly along it."""
    g = g.buffer(0.11, 16).buffer(-0.11, 16)          # close notches and gaps
    g = g.buffer(-0.045, 16).buffer(0.045, 16)        # remove slivers and specks
    if dists:
        g = g.intersection(unary_union([shapes[n] for n in dists]).buffer(0))
    g = g.intersection(wa) if g.intersects(wa) else g
    if g.geom_type == 'MultiPolygon':                 # leave out crumbs the trim may cut off
        g = unary_union([p for p in g.geoms if p.area >= 0.02])
    return g


def warning_area(w, places, shapes, wa, img=None):
    if w['polys']:                                            # BoM's own polygon (cyclones)
        return unary_union(w['polys']), 'bom', []
    if img and yellow_area:                                   # the yellow area in BoM's warning image
        try:
            g, cal = yellow_area(img, json.load(open(os.path.join(DATA, 'districts.json')))['wa'])
            log('  image calibration fit', round(cal.get('fit', 0), 3))
            if g is not None and not g.is_empty:
                return tidy_area(g, named_districts(w['areas'], w['description'], shapes), shapes, wa), 'image', []
        except Exception as e:
            log('  image area failed:', e)
    towns = towns_in(w['description']) or (places_named(w['headline'] + '. ' + w['description'], places) if w.get('scan') else [])
    pts = [(t, places[norm(t)]) for t in towns if norm(t) in places]
    dists = named_districts(w['areas'], w['description'], shapes)
    clip = unary_union([shapes[n] for n in dists]) if dists else wa
    if len(pts) >= 2:
        hull = unary_union([Point(p[1], p[0]).buffer(BUFFER_DEG, 24) for _, p in pts]).convex_hull
        area = hull.buffer(0.15, 16).buffer(-0.15, 16).intersection(clip.buffer(0.05)).intersection(wa)   # smooth, trim
        if not area.is_empty:
            return area, 'towns', [t for t, _ in pts]
    if dists:
        return clip.intersection(wa), 'districts', [t for t, _ in pts]
    return None, 'none', [t for t, _ in pts]


def geojson(g):
    if g is None or g.is_empty:
        return None
    g = g.simplify(0.01, preserve_topology=True)
    m = mapping(g)
    def rnd(c):
        return [rnd(x) for x in c] if isinstance(c[0], (list, tuple)) else [round(c[0], 3), round(c[1], 3)]
    m['coordinates'] = rnd(m['coordinates'])
    return m


# ---------------------------------------------------------------- main
# ---------------------------------------------------------------- tropical cyclone forecast tracks (for the cyclone page)
# BoM's Tropical Cyclone Forecast Track Map product (IDW60281, one per system: IDW60281-IDW60289) as data: the
# system's number (01U) and name, the forecast positions to +72 h, the headline and discussion (with the chance of
# it becoming a cyclone). Written to data/cyclone-bom.json; the cyclone page (Cyclones.gs) reads it.
TC_TRACKS = ['IDW6028%d.xml' % i for i in range(1, 10)]


def tc_tracks(files):
    out = []
    for n in TC_TRACKS:
        if n not in files: continue
        root = ET.fromstring(files[n])
        el = {e.get('type'): (e.text or '').strip() for e in root.iter('element')}
        issued = (root.findtext('.//amoc/issue-time-utc') or '').strip()
        pts = []
        for h in range(0, 241, 6):
            k = 'plus%d' % h
            if 'latitude_' + k not in el: continue
            la, lo = el['latitude_' + k], el['longitude_' + k]
            try:   # a point the Bureau hasn't given a position for (e.g. 'XX' once the system is expected to weaken)
                lat = -float(la[:-1]) if la.endswith('S') else float(la[:-1])
                lng = float(lo[:-1]) if lo.endswith('E') else 360 - float(lo[:-1])
            except ValueError:
                continue
            pts.append({'h': h, 't': el.get('date_' + k), 'lat': lat, 'lng': lng, 'cat': el.get('category_name_' + k, ''), 'acc': el.get('position_acc_km_' + k)})
        if not pts: continue
        dist = el.get('disturbance_id', '')
        m = re.search(r'(\d+)\s*%\)?\s*chance', el.get('discussion', ''))
        cone = []   # the Bureau's likely-track area(s): WKT polygons, lon lat
        for t in root.iter('text'):
            if t.get('type') == 'warning_area_polygons' and t.text and 'EMPTY' not in t.text:
                for ring in re.findall(r'\(\(([^()]+)\)', t.text):
                    try: cone.append([[round(float(a), 3), round(float(b), 3)] for a, b in (xy.split() for xy in ring.split(','))][::3])
                    except ValueError: pass
        extra = {k: el.get(k, '') for k in ('warning_zones', 'watch_zones', 'cancelled_zones', 'location', 'movement')}
        extra.update({'analysis': el.get('analysis_time', ''), 'nearby': el.get('nearby_town_1', ''), 'cone': cone})
        out.append({'product': n.split('.')[0], 'id': dist.split('_')[-1] if dist else '', 'name': el.get('disturbance_full_name', ''),
                    'cyclone': el.get('cyclone_name', ''), 'type': el.get('dist_type', ''), 'issued': issued,
                    'headline': el.get('headline', ''), 'discussion': el.get('discussion', ''), 'intensity': el.get('intensity', ''),
                    'chance': int(m.group(1)) if m else None, 'next': root.findtext('.//text[@type="warning_next_issue"]') or '', 'pts': pts, **extra})
    # post and story images of each new issue (for the owner's email), in data/tcimg; older ones are removed
    folder = os.path.join(DATA, 'tcimg'); os.makedirs(folder, exist_ok=True); keep = set()
    for sy in out:
        tag = 'tc-' + (sy['id'] or 'x') + '-' + re.sub(r'\D', '', sy['issued'])[:12]
        post, story = tag + '-post.png', tag + '-story.png'
        try:
            if not (os.path.exists(os.path.join(folder, post)) and os.path.exists(os.path.join(folder, story))):
                from tcimg import render as tc_render
                tc_render(sy, os.path.join(folder, post), os.path.join(folder, story))
                log('Cyclone images:', post, story)
            sy['post'], sy['story'] = 'tcimg/' + post, 'tcimg/' + story
            keep.update([post, story])
        except Exception as e:  # noqa: BLE001
            log('Cyclone images failed:', e)
    for f in os.listdir(folder):
        if f not in keep: os.remove(os.path.join(folder, f))
    path = os.path.join(DATA, 'cyclone-bom.json')
    res = {'updated': dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'source': 'Bureau of Meteorology, ftp.bom.gov.au', 'systems': out}
    prev = json.load(open(path)) if os.path.exists(path) else {}
    if json.dumps(prev.get('systems'), sort_keys=True) != json.dumps(out, sort_keys=True):
        json.dump(res, open(path, 'w'), indent=1)
        log('Cyclone tracks:', ', '.join(s['name'] + ' (' + str(len(s['pts'])) + ' points)' for s in out) or 'none')

# ---------------------------------------------------------------- JTWC (US Joint Typhoon Warning Center)
JTWC = 'https://www.metoc.navy.mil/jtwc/'


def _jget(u):
    req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0 (westweatherwatchers.com relay)'})
    return urllib.request.urlopen(req, timeout=40).read().decode('utf-8', 'replace')


def _jlat(a):
    return -float(a[:-1]) if a.endswith('S') else float(a[:-1])


def _jlon(a):
    return float(a[:-1]) if a.endswith('E') else 360 - float(a[:-1])


def _jtime(ddhhmm):
    """'201800Z' -> ISO time; the month and year are the nearest that fit (warnings are a few days old at most)."""
    now = dt.datetime.utcnow(); d, h, m = int(ddhhmm[:2]), int(ddhhmm[2:4]), int(ddhhmm[4:6])
    for mo in (0, -1, 1):
        y, mm = now.year, now.month + mo
        if mm < 1: y, mm = y - 1, 12
        if mm > 12: y, mm = y + 1, 1
        try: t = dt.datetime(y, mm, d, h, m)
        except ValueError: continue
        if abs((t - now).total_seconds()) < 12 * 86400: return t.strftime('%Y-%m-%dT%H:%M:00Z')
    return ''


def jtwc():
    """Current JTWC warnings (forecast tracks) and the areas they're watching (invests), from JTWC's public RSS
    list, to data/cyclone-jtwc.json (written only when something changed)."""
    try:
        rss = _jget(JTWC + 'rss/jtwc.rss')
    except Exception as e:  # noqa: BLE001
        log('JTWC list not read:', e); return
    links = sorted(set(re.findall(r'https?://[^"<\s]+?web\.txt', rss)))
    storms, invests = [], []
    for u in links:
        try: txt = _jget(u)
        except Exception as e:  # noqa: BLE001
            log('JTWC', u, 'not read:', e); continue
        name = os.path.basename(u)
        if name.startswith('ab'):   # the daily advisories: the invests
            for m in re.finditer(r'\(INVEST (\d\d[A-Z])\)(.*?)(?=\n\s*\(\d\)|\n\s*[A-C]\. |\Z)', txt, re.S):
                body = re.sub(r'\s+', ' ', m.group(2))
                pos = re.search(r'NOW LOCATED NEAR (\d+\.\d[NS]) (\d+\.\d[EW])', body) or re.search(r'LOCATED NEAR (\d+\.\d[NS]) (\d+\.\d[EW])', body)
                if not pos: continue
                ch = re.search(r'TROPICAL CYCLONE WITHIN THE NEXT 24 HOURS (?:IS|REMAINS|IS UPGRADED TO|IS DOWNGRADED TO|HAS BEEN UPGRADED TO)?\s*(LOW|MEDIUM|HIGH)', body)
                wind = re.search(r'MAXIMUM SUSTAINED SURFACE WINDS ARE ESTIMATED AT (\d+) TO (\d+) KNOTS', body)
                mslp = re.search(r'NEAR (\d{3,4}) MB', body)
                invests.append({'id': m.group(1), 'lat': _jlat(pos.group(1)), 'lng': _jlon(pos.group(2)), 'chance': ch.group(1).lower() if ch else '',
                                'kt': [int(wind.group(1)), int(wind.group(2))] if wind else None, 'hpa': int(mslp.group(1)) if mslp else None,
                                'text': body.strip()[:2500], 'src': u})
            continue
        sub = re.search(r'SUBJ/(.*?)//', txt, re.S)
        subj = re.sub(r'\s+', ' ', sub.group(1)) if sub else ''
        mm = re.search(r'(TROPICAL (?:CYCLONE|STORM|DEPRESSION)|TYPHOON|SUPER TYPHOON|SUBTROPICAL STORM) (\d\d[A-Z])(?: \(([A-Z\- ]+)\))? WARNING NR (\d+)', subj)
        if not mm:
            if 'FORMATION ALERT' in txt.upper(): log('JTWC formation alert seen:', name)
            continue
        pts = []
        for b in re.split(r'\n\s*---', txt):
            p = re.search(r'(\d{6})Z --- (?:NEAR )?(\d+\.\d[NS]) (\d+\.\d[EW])', b)
            if not p: continue
            w = re.search(r'MAX SUSTAINED WINDS - (\d+) KT, GUSTS (\d+) KT', b)
            hrs = re.search(r'(\d+) HRS, VALID AT', b)
            pts.append({'h': int(hrs.group(1)) if hrs else 0, 't': _jtime(p.group(1)), 'lat': _jlat(p.group(2)), 'lng': _jlon(p.group(3)),
                        'kt': int(w.group(1)) if w else None, 'gust': int(w.group(2)) if w else None})
        if not pts: continue
        mv = re.search(r'MOVEMENT PAST SIX HOURS - (\d+) DEGREES AT (\d+) KTS', txt)
        storms.append({'id': mm.group(2), 'name': (mm.group(3) or '').title(), 'kind': mm.group(1).title(), 'warning': int(mm.group(4)),
                       'issued': pts[0]['t'], 'move': [int(mv.group(1)), int(mv.group(2))] if mv else None, 'pts': pts, 'src': u})
    path = os.path.join(DATA, 'cyclone-jtwc.json')
    res = {'updated': dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'source': 'Joint Typhoon Warning Center (metoc.navy.mil/jtwc)',
           'storms': storms, 'invests': invests}
    prev = json.load(open(path)) if os.path.exists(path) else {}
    if json.dumps([prev.get('storms'), prev.get('invests')], sort_keys=True) != json.dumps([storms, invests], sort_keys=True):
        json.dump(res, open(path, 'w'), indent=1)
        log('JTWC:', ', '.join(s['id'] + (' ' + s['name'] if s['name'] else '') for s in storms) or 'no warnings', '·',
            ', '.join('Invest ' + i['id'] for i in invests) or 'no invests')


def main():
    local = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == '--local' else None
    names = [c + '.cap.xml' for c in PRODUCTS] + [img + '.png' for _, img in PRODUCTS.values()]
    names += TC_TRACKS
    files = fetch_local(local, names) if local else fetch_ftp(names)
    if files is not None:
        try: tc_tracks(files)
        except Exception as e: log('Cyclone tracks:', e)
    if '--local' not in sys.argv:
        try: jtwc()
        except Exception as e: log('JTWC:', e)
    if files is None:
        sys.exit(0)
    places, (shapes, wa) = load_places(), load_districts()
    out_path = os.path.join(DATA, 'warnings.json')
    prev = json.load(open(out_path)) if os.path.exists(out_path) else {'warnings': []}
    now = dt.datetime.now(dt.timezone.utc)
    os.makedirs(IMG, exist_ok=True)
    warnings, keep_imgs = [], set()

    jobs = [(c, t, i) for c, (t, i) in PRODUCTS.items()]
    extra = sorted(set(n.split('.')[0] for n in files if EXTRA_RE.match(n)) - set(PRODUCTS))
    jobs += [(c, None, None) for c in extra]
    for code, wtype, img in jobs:
        raw = files.get(code + '.cap.xml')
        try:
            if raw:
                infos = parse_cap(raw, code)
            elif wtype is None and files.get(code + '.txt'):
                infos = parse_txt(files[code + '.txt'], code)
            else:
                continue
        except Exception as e:
            log(code, 'could not be read:', e)
            continue
        if wtype is None:                     # flood / frost: keep only those, skip every other product
            infos = [w for w in infos if extra_kind(w['event'] + ' ' + w['headline'])]
            for w in infos: w['scan'] = True
            if not infos: continue
        for i, w in enumerate(infos):
            exp = dt.datetime.fromisoformat(w['expires']) if w['expires'] else None
            ended = w['cancelled'] or (exp is not None and exp < now)
            if ended and exp is not None and (now - exp).total_seconds() > KEEP_ENDED_H * 3600 and not w['cancelled']:
                continue
            pic = files.get(img + '.png') if img and not ended and not code.startswith('IDW245') else None
            area, how, placed = warning_area(w, places, shapes, wa, pic)
            if how == 'image':
                placed = [t for t in towns_in(w['description']) if norm(t) in places]
            kind = wtype or extra_kind(w['event'] + ' ' + w['headline'])
            if code.startswith('IDW245'):
                kind = 'Tropical Cyclone ' + ('Watch' if 'watch' in w['headline'].lower() else 'Warning')
            item = {
                'id': code + (('-' + str(i)) if len(infos) > 1 else ''), 'product': code, 'type': kind,
                'status': 'cancelled' if w['cancelled'] else ('expired' if ended else 'current'),
                'headline': w['headline'], 'sent': w['sent'], 'expires': w['expires'],
                'hazards': hazards_in(w['headline'] + ' ' + w['description']),
                'districts': [n.title() for n in named_districts(w['areas'], w['description'], shapes)],
                'towns': towns_in(w['description']) or (placed if wtype is None else []), 'townsPlaced': placed,
                'description': w['description'][:3000], 'areaSource': how, 'area': geojson(area),
                'bomUrl': 'https://www.bom.gov.au/products/' + code + '.shtml',
            }
            if wtype is None:
                item['hazards'] = (['flooding'] if 'Flood' in kind else ['frost']) + [h for h in item['hazards'] if h == 'heavy rainfall']
            if img and files.get(img + '.png') and item['status'] == 'current':
                open(os.path.join(IMG, img + '.png'), 'wb').write(files[img + '.png'])
                item['image'] = 'img/' + img + '.png'
                keep_imgs.add(img + '.png')
            if item.get('area') and item['status'] == 'current':
                try:                                       # people living in towns in the area
                    from warnimg import people_in
                    n, towns = people_in(item['area'])
                    item['people'], item['peopleTowns'] = n, [t for t, _ in towns[:8]]
                except Exception as e:
                    log('  people count failed:', e)
            if warn_images and wtype is not None and item['status'] == 'current':
                # a square post and a story image, named after this issue of the warning (made once per issue)
                tag = item['id'] + '-' + re.sub(r'\D', '', item['sent'])[:12]
                post, story = tag + '-post.png', tag + '-story.png'
                try:
                    if not (os.path.exists(os.path.join(IMG, post)) and os.path.exists(os.path.join(IMG, story))):
                        warn_images(item, os.path.join(IMG, post), os.path.join(IMG, story))
                    item['post'], item['story'] = 'img/' + post, 'img/' + story
                    keep_imgs.update([post, story])
                except Exception as e:
                    log('  warning images failed:', e)
            warnings.append(item)

    for f in os.listdir(IMG):                   # remove images of warnings that have ended
        if f not in keep_imgs:
            os.remove(os.path.join(IMG, f))
    result = {'source': 'Bureau of Meteorology (ftp.bom.gov.au/anon/gen/fwo)',
              'note': 'Unofficial copy for West WX Watchers. Official warnings: www.bom.gov.au. '
                      'Severe thunderstorm, severe weather, flood and frost areas are approximate, drawn around the locations named in each warning.',
              'warnings': warnings}
    # write (and so commit) only when the warnings themselves change, not just the check time
    if not os.path.exists(out_path) or json.dumps(prev.get('warnings'), sort_keys=True) != json.dumps(warnings, sort_keys=True):
        result['updated'] = now.isoformat(timespec='seconds')
        json.dump(result, open(out_path, 'w'), indent=1)
        log('Updated:', len(warnings), 'warning(s):', ', '.join(w['type'] + ' [' + w['status'] + ', ' + w['areaSource'] + ']' for w in warnings) or 'none')
    else:
        log('No change (' + str(len(warnings)) + ' warning(s)).')


if __name__ == '__main__':
    main()

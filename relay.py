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
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', 'pillow'], check=False)
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
def fetch_ftp(names):
    out = {}
    try:
        ftp = ftplib.FTP('ftp.bom.gov.au', timeout=60)
        ftp.login()
        ftp.cwd('/anon/gen/fwo')
        present = set(ftp.nlst())
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
    return {n: open(os.path.join(folder, n), 'rb').read() for n in names if os.path.exists(os.path.join(folder, n))}


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
    m = re.search(r'Locations which may be affected include ([^.]+)\.', desc, re.I)
    if not m:
        return []
    s = re.sub(r'\s+and\s+', ', ', m.group(1))
    return [t.strip() for t in s.split(',') if t.strip()]


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


def warning_area(w, places, shapes, wa, img=None):
    if w['polys']:                                            # BoM's own polygon (cyclones)
        return unary_union(w['polys']), 'bom', []
    if img and yellow_area:                                   # the yellow area in BoM's warning image
        try:
            g, cal = yellow_area(img, json.load(open(os.path.join(DATA, 'districts.json')))['wa'])
            log('  image calibration fit', round(cal.get('fit', 0), 3))
            if g is not None and not g.is_empty:
                return g.intersection(wa.buffer(0.05)) if g.intersects(wa) else g, 'image', []
        except Exception as e:
            log('  image area failed:', e)
    towns = towns_in(w['description'])
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
def main():
    local = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == '--local' else None
    names = [c + '.cap.xml' for c in PRODUCTS] + [img + '.png' for _, img in PRODUCTS.values()]
    files = fetch_local(local, names) if local else fetch_ftp(names)
    if files is None:
        sys.exit(0)
    places, (shapes, wa) = load_places(), load_districts()
    out_path = os.path.join(DATA, 'warnings.json')
    prev = json.load(open(out_path)) if os.path.exists(out_path) else {'warnings': []}
    now = dt.datetime.now(dt.timezone.utc)
    os.makedirs(IMG, exist_ok=True)
    warnings, keep_imgs = [], set()

    for code, (wtype, img) in PRODUCTS.items():
        raw = files.get(code + '.cap.xml')
        if not raw:
            continue
        try:
            infos = parse_cap(raw, code)
        except Exception as e:
            log(code, 'could not be read:', e)
            continue
        for i, w in enumerate(infos):
            exp = dt.datetime.fromisoformat(w['expires']) if w['expires'] else None
            ended = w['cancelled'] or (exp is not None and exp < now)
            if ended and exp is not None and (now - exp).total_seconds() > KEEP_ENDED_H * 3600 and not w['cancelled']:
                continue
            pic = files.get(img + '.png') if not ended and not code.startswith('IDW245') else None
            area, how, placed = warning_area(w, places, shapes, wa, pic)
            if how == 'image':
                placed = [t for t in towns_in(w['description']) if norm(t) in places]
            kind = wtype
            if code.startswith('IDW245'):
                kind = 'Tropical Cyclone ' + ('Watch' if 'watch' in w['headline'].lower() else 'Warning')
            item = {
                'id': code + (('-' + str(i)) if len(infos) > 1 else ''), 'product': code, 'type': kind,
                'status': 'cancelled' if w['cancelled'] else ('expired' if ended else 'current'),
                'headline': w['headline'], 'sent': w['sent'], 'expires': w['expires'],
                'hazards': hazards_in(w['headline'] + ' ' + w['description']),
                'districts': [n.title() for n in named_districts(w['areas'], w['description'], shapes)],
                'towns': towns_in(w['description']), 'townsPlaced': placed,
                'description': w['description'][:3000], 'areaSource': how, 'area': geojson(area),
                'bomUrl': 'https://www.bom.gov.au/products/' + code + '.shtml',
            }
            if files.get(img + '.png') and item['status'] == 'current':
                open(os.path.join(IMG, img + '.png'), 'wb').write(files[img + '.png'])
                item['image'] = 'img/' + img + '.png'
                keep_imgs.add(img + '.png')
            warnings.append(item)

    for f in os.listdir(IMG):                   # remove images of warnings that have ended
        if f not in keep_imgs:
            os.remove(os.path.join(IMG, f))
    result = {'source': 'Bureau of Meteorology (ftp.bom.gov.au/anon/gen/fwo)',
              'note': 'Unofficial copy for West WX Watchers. Official warnings: www.bom.gov.au. '
                      'Severe thunderstorm and severe weather areas are approximate, drawn around the locations listed in each warning.',
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

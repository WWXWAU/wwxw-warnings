#!/usr/bin/env python3
"""
West WX Watchers — images for posting a BoM warning: a square post (1080x1080) and a story (1080x1920).

Drawn from the relay's warning record: the warning area on a map of WA (with the listed towns),
the threats (damaging winds, large hail, heavy rain...) and the weather situation from the warning text.
Unofficial: the images say so, and point to bom.gov.au.

    from warnimg import render
    render(item, 'post.png', 'story.png')        # item = one warning from data/warnings.json

    python warnimg.py data/warnings.json OUTDIR  # test: images for every warning in a file
    python warnimg.py data/warnings.json OUTDIR --styles   # the same in every style

Styles (STYLE, or render(..., style=)): 'classic' (light), 'night' (dark map with a glowing area),
'satellite' (NASA Blue Marble relief), 'clouds' (the latest Himawari infrared clouds over a dark relief map),
'poster' (dark map, hazard-striped area and a warning-coloured banner). Imagery comes from NASA GIBS
(free to use with credit); if it can't be fetched the map falls back to 'night'.
"""
import io, json, math, os, re, sys, urllib.request, datetime as dt
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, 'wxvideo')
S = 2                                                   # drawn at twice the size, then scaled down (smooth edges)

BG = (238, 244, 245); TEXT = (14, 42, 51); MUTED = (74, 100, 112); ACCENT = (14, 124, 134)
HEAD = (14, 42, 51); OCEAN = (201, 222, 228); LAND = (246, 249, 248); OTHER = (232, 238, 238); COAST = (110, 138, 148)
DIST = (170, 186, 192)
TYPE_COL = {'Severe Thunderstorm Warning': (242, 194, 0), 'Severe Thunderstorm Warning (Perth Area)': (242, 194, 0),
            'Severe Weather Warning': (255, 145, 0), 'Tropical Cyclone Warning': (229, 57, 53), 'Tropical Cyclone Watch': (171, 71, 188)}
HAZ = {   # label, chip colour
    'very destructive winds': ('Very destructive winds', (183, 28, 28)), 'destructive winds': ('Destructive winds', (198, 40, 40)),
    'damaging winds': ('Damaging winds', (230, 81, 0)), 'gales': ('Gales', (230, 81, 0)),
    'giant hail': ('Giant hail', (69, 39, 160)), 'large hail': ('Large hail', (94, 53, 177)),
    'intense rainfall': ('Intense rainfall', (13, 71, 161)), 'heavy rainfall': ('Heavy rainfall', (21, 101, 192)),
    'tornado': ('Tornadoes', (106, 27, 154)), 'abnormally high tides': ('Abnormally high tides', (0, 105, 92)),
    'damaging surf': ('Damaging surf', (0, 121, 107)),
}

STYLE = os.environ.get('WARN_STYLE', 'classic')
STYLES = ['classic', 'light', 'dark', 'satellite', 'clouds']   # (night and poster: earlier trials, still drawable)
BRAND = ('light', 'dark', 'satellite', 'clouds')                # the website's look: outlook-image layout
LIGHT = dict(bg=BG, text=TEXT, muted=MUTED, accent=ACCENT, rule=(201, 216, 220), stamp=(157, 205, 211))
DARK = dict(bg=(16, 35, 42), text=(226, 238, 240), muted=(157, 182, 189), accent=(63, 193, 201), rule=(40, 67, 77), stamp=(157, 205, 211))   # the site's dark mode
LIGHT['surface'] = (255, 255, 255); DARK['surface'] = (22, 48, 58)
MAPS = {   # ocean, WA, other states, district lines, coast, label text, label outline, other towns
    'light': dict(ocean=OCEAN, land=LAND, other=OTHER, dist=DIST + (255,), coast=COAST + (255,), lab=TEXT, halo=(255, 255, 255), town=MUTED, img=None),
    'dark': dict(ocean=(13, 29, 35), land=(22, 48, 58), other=(16, 37, 45), dist=(52, 82, 94, 255), coast=(92, 128, 140, 255),
                 lab=(226, 238, 240), halo=(13, 29, 35), town=(157, 182, 189), img=None),
    'classic': dict(ocean=OCEAN, land=LAND, other=OTHER, dist=DIST + (255,), coast=COAST + (255,), lab=TEXT, halo=(255, 255, 255), town=MUTED, img=None),
    'night': dict(ocean=(8, 19, 29), land=(30, 44, 54), other=(20, 30, 38), dist=(70, 92, 106, 255), coast=(104, 136, 152, 255),
                  lab=(255, 255, 255), halo=(6, 12, 16), town=(176, 192, 200), img=None),
    'satellite': dict(ocean=(8, 19, 29), land=(30, 44, 54), other=(20, 30, 38), dist=(255, 255, 255, 60), coast=(255, 255, 255, 150),
                      lab=(255, 255, 255), halo=(6, 12, 16), town=(222, 230, 234), img='relief'),
    'clouds': dict(ocean=(8, 19, 29), land=(30, 44, 54), other=(20, 30, 38), dist=(255, 255, 255, 45), coast=(160, 214, 224, 170),
                   lab=(255, 255, 255), halo=(6, 12, 16), town=(222, 230, 234), img='clouds'),
    'poster': dict(ocean=(6, 10, 14), land=(26, 30, 34), other=(16, 19, 22), dist=(62, 70, 78, 255), coast=(120, 130, 138, 255),
                   lab=(255, 255, 255), halo=(0, 0, 0), town=(170, 178, 184), img=None),
}
REP_COL = {'wind': (230, 81, 0), 'hail': (94, 53, 177), 'rain': (21, 101, 192)}

_FC = {}
def font(wt, size):
    k = (wt, size)
    if k not in _FC:
        f = ImageFont.truetype(os.path.join(ASSETS, 'Lexend.ttf'), int(size * S))
        try: f.set_variation_by_axes([wt])
        except Exception: pass
        _FC[k] = f
    return _FC[k]

merc = lambda la: math.log(math.tan(math.pi / 4 + math.radians(la) / 2))


# ---------------------------------------------------------------- the words
def clean(s):
    return re.sub(r'\s+', ' ', s or '').strip()

def situation(desc):
    """The 'Weather Situation' paragraph; for warnings without one (thunderstorms), the opening sentence(s)."""
    d = desc or ''
    m = re.search(r'Weather Situation:?\s*(.+?)(?:\n\s*\n|$)', d, re.I | re.S)
    if m:
        return clean(m.group(1))
    d = re.split(r'Locations which may be affected include', d, flags=re.I)[0]
    return clean(d)

def details(desc, situ):
    """Other sentences about the threats (e.g. 'DAMAGING WINDS, averaging 60 km/h with gusts to 100 km/h...')."""
    d = desc or ''
    m = re.search(r'Weather Situation:?\s*(.+?)(?:\n\s*\n|$)', d, re.I | re.S)
    if m: d = d[:m.start()] + d[m.end():]                 # not the situation again
    d = re.split(r'Locations which may be affected include', d, flags=re.I)[0]
    sents = [clean(s) for s in re.split(r'(?<=[.!])\s+(?=[A-Z])', clean(d))]
    out = []
    for s in sents:
        if not s or s in situ or situ.startswith(s[:60]): continue
        if re.search(r'wind|gust|hail|rain|flood|tornado|tide|surf|gale', s, re.I):
            out.append(s)
    return out[:3]

# ---------------------------------------------------------------- values the warning says were recorded
_OBS = re.compile(r'\b(recorded|observed|reported|measured|registered)\b', re.I)
_TIME = re.compile(r'\b(\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?)', re.I)
_PLACE = re.compile(r"\b(?:at|near|in) ((?:[A-Z][\w'’\-]*|Mt|of|the|and)(?: (?:[A-Z][\w'’\-]*|\(\w+\)|of|the))*)")
_PLACE_SUBJ = re.compile(r"^((?:[A-Z][\w'’\-]*)(?: [A-Z][\w'’\-]*)*) (?:recorded|observed|reported|measured|registered)")

def reports(desc):
    """Values the warning says were recorded or reported (wind gusts, rain totals, hail sizes), strongest first:
    [{'kind': 'wind'|'rain'|'hail', 'value': '91 km/h', 'label': 'Wind gust', 'where': 'Newman Airport', 'when': '2:25 pm'}]"""
    out = []
    parts = []
    for sent in re.split(r'(?<=[.!])\s+(?=[A-Z])', clean(desc)):
        if _OBS.search(sent):   # 'X recorded 98 km/h and Y recorded 30 mm': one report each
            parts += [p for p in re.split(r';\s*|,?\s+and\s+(?=[A-Z])', sent) if re.search(r'\d|sized? hail', p, re.I)]
    for s in parts:
        kind = val = None; label = ''
        m = re.search(r'(\d{2,3})\s*km/?h', s)
        if m and re.search(r'wind|gust', s, re.I):
            kind, val, num, label = 'wind', m.group(1) + ' km/h', int(m.group(1)), 'Wind gust'
        else:
            m = re.search(r'(\d+(?:\.\d+)?)\s*(cm|mm|centimetre|millimetre)s?\b[^.]*?\bhail|\bhail[^.]*?(\d+(?:\.\d+)?)\s*(cm|mm)\b', s, re.I)
            mw = re.search(r'\b(golf ?ball|tennis ?ball|cricket ?ball|marble|pea|coin|cent coin|dollar coin|ping ?pong ball)[- ]sized? hail', s, re.I)
            if m:
                n, u = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
                u = 'cm' if u.lower().startswith('c') else 'mm'
                kind, val, num, label = 'hail', n + ' ' + u, float(n) * (10 if u == 'cm' else 1), 'Hail'
            elif mw:
                kind, val, num, label = 'hail', re.sub(r'\s+', ' ', mw.group(1)).capitalize() + ' size', 0, 'Hail'
            else:
                m = re.search(r'(\d+(?:\.\d+)?)\s*mm\b', s)
                if m and re.search(r'rain|fell|recorded|total', s, re.I):
                    per = re.search(r'\bin (?:the |just |about |under |less than )?((?:\d+|one|two|three|six|twelve|24) (?:minutes?|hours?)|(?:half an |an )?hour)', s, re.I)
                    label = 'Rain' + (' in ' + re.sub(r'^(?:an |)hour$', '1 hour', re.sub(r'^half an hour$', '30 minutes', per.group(1))) if per else '')
                    kind, val, num = 'rain', m.group(1) + ' mm', float(m.group(1))
        if not kind: continue
        where = ''
        ps = _PLACE_SUBJ.search(s)
        if ps and ps.group(1) not in ('A', 'An', 'The', 'Wind', 'Large', 'Heavy', 'Hail', 'Rainfall'):
            where = ps.group(1)
        else:
            for pm in _PLACE.finditer(s):
                w = pm.group(1)
                if re.match(r'(the )?(hour|minutes?|warning|area|last|past)', w, re.I): continue
                where = re.sub(r' (?:the|of|and)$', '', w); break
        tm = _TIME.search(s)
        when = re.sub(r'\s*([ap])\.?m\.?', r' \1m', tm.group(1).lower()) if tm else ''
        out.append({'kind': kind, 'value': val, 'num': num, 'label': label, 'where': where, 'when': when, 'text': s})
    rank = {'wind': 0, 'hail': 1, 'rain': 2}
    out.sort(key=lambda r: (rank[r['kind']], -r['num']))
    return out[:4]


def when(iso):
    try:
        t = dt.datetime.fromisoformat(iso).astimezone(dt.timezone(dt.timedelta(hours=8)))
        return t.strftime('%a %-d %b, %-I:%M %p').replace('AM', 'am').replace('PM', 'pm')
    except Exception:
        return ''

def wrap(d, text, f, width):
    words, lines, cur = text.split(), [], ''
    for w in words:
        t = (cur + ' ' + w).strip()
        if d.textlength(t, font=f) > width and cur:
            lines.append(cur); cur = w
        else:
            cur = t
    if cur: lines.append(cur)
    return lines


# ---------------------------------------------------------------- the map
_GEO = {}
def geo():
    if not _GEO:
        _GEO['states'] = json.load(open(os.path.join(ASSETS, 'aus_states.json')))
        d = json.load(open(os.path.join(HERE, 'data', 'districts.json')))
        _GEO['districts'] = [r for x in d['districts'] for r in x['rings']]
        _GEO['places'] = json.load(open(os.path.join(HERE, 'data', 'wa_places.json')))
        _GEO['towns'] = json.load(open(os.path.join(ASSETS, 'towns.json')))
    return _GEO

# ---------------------------------------------------------------- people in the warning area
def _inside(x, y, ring):
    c, j = False, len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]; xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi: c = not c
        j = i
    return c

def people_in(area):
    """People living in towns inside the area (GeoNames populations in wa_places.json): (total, [(town, people), ...]).
    A city is listed whole and suburb by suburb, so a smaller place near a bigger one already counted is skipped."""
    if not area: return 0, []
    polys = area['coordinates'] if area['type'] == 'MultiPolygon' else [area['coordinates']]
    def inn(lng, lat): return any(_inside(lng, lat, p[0]) and not any(_inside(lng, lat, h) for h in p[1:]) for p in polys)
    places = geo()['places']
    cand = sorted(((v[2], k, v[0], v[1]) for k, v in places.items() if len(v) > 3 and v[3] == 'P' and v[2] > 0 and inn(v[1], v[0])), reverse=True)
    kept = []
    for pop, k, la, lo in cand:
        if any(math.hypot((la - b[2]) * 111, (lo - b[3]) * 111 * math.cos(math.radians(la))) < max(5, min(45, math.sqrt(b[0]) / 30)) for b in kept):
            continue
        kept.append((pop, k, la, lo))
    return sum(k[0] for k in kept), [(k[1].title(), k[0]) for k in kept]

def people_text(n):
    if n <= 0: return ''
    r = round(n, -1) if n < 1000 else round(n, -2) if n < 10000 else round(n, -3)
    return 'About {:,} people in towns in the warning area'.format(int(r))

def norm(s):
    return re.sub(r'[^a-z0-9 ]', '', s.lower().replace('mt ', 'mount ').replace('&', 'and')).strip()

GIBS = 'https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi'
HIMAWARI = ['Himawari_AHI_Band13_Clean_Infrared', 'Himawari_AHI_Band14_Longwave_Window']
_CAPS = {}

def _gibs_get(url, tries=2):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'westwxwatchers-warning-images'})
            return urllib.request.urlopen(req, timeout=40).read()
        except Exception as e:  # noqa: BLE001
            err = e
    raise err

def himawari_layer():
    """(layer, time) for the newest Himawari infrared picture on NASA GIBS, or (None, None)."""
    if 'him' not in _CAPS:
        _CAPS['him'] = (None, None)
        try:
            xml = _gibs_get(GIBS + '?SERVICE=WMS&REQUEST=GetCapabilities&VERSION=1.3.0').decode('utf-8', 'replace')
            for lay in HIMAWARI:
                i = xml.find('<Name>%s</Name>' % lay)
                if i < 0: continue
                m = re.search(r'<Dimension[^>]*name="time"[^>]*default="([^"]+)"', xml[i:i + 6000])
                _CAPS['him'] = (lay, m.group(1) if m else None); break
        except Exception as e:  # noqa: BLE001
            print('Himawari list not read:', e)
    return _CAPS['him']

def gibs_map(layer, lng0, lng1, lat_top, lat_bot, W, H, k, cm, time=None, fmt='image/jpeg'):
    """A GIBS picture (plate carrée) of the box, stretched row by row onto our Mercator map: W x H pixels."""
    hq = max(64, int(W * (lat_top - lat_bot) / (lng1 - lng0)))
    url = (GIBS + '?SERVICE=WMS&REQUEST=GetMap&VERSION=1.1.1&SRS=EPSG:4326&STYLES=&LAYERS=%s&BBOX=%.4f,%.4f,%.4f,%.4f'
           '&WIDTH=%d&HEIGHT=%d&FORMAT=%s' % (layer, lng0, lat_bot, lng1, lat_top, W, hq, fmt.replace('/', '%2F')))
    if time: url += '&TIME=' + time
    src = Image.open(io.BytesIO(_gibs_get(url))).convert('RGB')
    out = Image.new('RGB', (W, H))
    for y in range(H):
        lat = math.degrees(2 * math.atan(math.exp(cm + math.radians((H / 2 - y - 0.5) / k))) - math.pi / 2)
        sy = min(hq - 1, max(0, int((lat_top - lat) / (lat_top - lat_bot) * hq)))
        out.paste(src.crop((0, sy, W, sy + 1)), (0, y))
    return out

def _area_mask(polys, X, Y, ox, oy, W, H):
    m = Image.new('L', (W, H), 0); md = ImageDraw.Draw(m)
    for poly in polys:
        md.polygon([(X(x) - ox, Y(y) - oy) for x, y in poly[0]], fill=255)
        for hole in poly[1:]: md.polygon([(X(x) - ox, Y(y) - oy) for x, y in hole], fill=0)
    return m

def draw_map(img, box, item, col, style='classic', rounded=True):
    """The warning area on WA, fitted to the area, inside box = (x0, y0, x1, y1) in drawing pixels.
    Returns a credit line for the imagery used ('' for none)."""
    G = geo(); x0, y0, x1, y1 = box; W, H = x1 - x0, y1 - y0
    st = MAPS.get(style, MAPS['classic']); credit = ''
    ga = item.get('area') or None
    polys = (ga['coordinates'] if ga['type'] == 'MultiPolygon' else [ga['coordinates']]) if ga else []
    pts = [pt for poly in polys for ring in poly[:1] for pt in ring]
    if pts:
        a, c = min(p[0] for p in pts), max(p[0] for p in pts); b, e = min(p[1] for p in pts), max(p[1] for p in pts)
    else:
        a, b, c, e = 112.5, -35.5, 129.5, -13.5
    # frame: the area plus a margin; at least 6 degrees across; as wide or tall as the box allows
    cx, cm = (a + c) / 2, (merc(b) + merc(e)) / 2
    span = max((c - a) * 1.5, 6.0); mspan = max((merc(e) - merc(b)) * 1.45, math.radians(6.0) * 0.9)
    k = min(W / span, H / math.degrees(mspan))           # pixels per degree
    X = lambda lng: x0 + W / 2 + (lng - cx) * k
    Y = lambda lat: y0 + H / 2 - math.degrees(merc(lat) - cm) * k
    ox, oy = x0, y0
    def rings(g):
        cs = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
        for poly in cs:
            for ring in poly[:1]:
                yield [(X(p[0]) - ox, Y(p[1]) - oy) for p in ring]
    # the base: drawn land and sea, or satellite imagery
    base = None
    if st['img']:
        lng0, lng1 = cx - W / 2 / k, cx + W / 2 / k
        inv = lambda mm: math.degrees(2 * math.atan(math.exp(mm)) - math.pi / 2)
        lat_top, lat_bot = inv(cm + math.radians(H / 2 / k)), inv(cm - math.radians(H / 2 / k))
        try:
            rel = gibs_map('BlueMarble_ShadedRelief_Bathymetry', lng0, lng1, lat_top, lat_bot, W, H, k, cm)
            if st['img'] == 'relief':
                base = ImageEnhance.Brightness(ImageEnhance.Color(rel).enhance(1.15)).enhance(0.78)
                credit = 'Map: NASA Blue Marble'
            else:
                base = ImageEnhance.Brightness(ImageEnhance.Color(rel).enhance(0.35)).enhance(0.42)
                credit = 'Map: NASA Blue Marble'
                lay, t = himawari_layer()
                if lay:
                    ir = gibs_map(lay, lng0, lng1, lat_top, lat_bot, W, H, k, cm, time=t, fmt='image/png').convert('L').filter(ImageFilter.GaussianBlur(2.2 * S))   # soften the 2 km pixels
                    # cold cloud tops are bright: white cloud, the coldest tops tinted
                    a_ = ir.point(lambda v: 0 if v < 70 else min(235, int((v - 70) * 1.9)))
                    base.paste(Image.new('RGB', (W, H), (236, 244, 248)), (0, 0), a_)
                    cold = ir.point(lambda v: 0 if v < 200 else min(170, (v - 200) * 5))
                    base.paste(Image.new('RGB', (W, H), (120, 200, 255)), (0, 0), cold)
                    item['_sat_time'] = t
                    credit = 'Satellite: Himawari-9 (JMA) via NASA GIBS' + (' · ' + when_sat(t) if t else '')
                else:
                    credit += ' · satellite clouds unavailable'
        except Exception as ex:  # noqa: BLE001
            print('Imagery not fetched (%s): drawn map instead' % ex)
            base = None; st = MAPS['dark' if style in BRAND else 'night']
    layer = (base.convert('RGBA') if base else Image.new('RGBA', (W, H), st['ocean'] + (255,)))
    d = ImageDraw.Draw(layer)
    if base is None:
        for name, gj in G['states'].items():
            for r in rings(gj):
                if len(r) > 2: d.polygon(r, fill=st['land'] if name == 'Western Australia' else st['other'])
    m = _area_mask(polys, X, Y, ox, oy, W, H) if polys else None
    dark = style not in ('classic', 'light')
    if m is not None:
        if style in BRAND:
            # like the outlook's areas: a strong fill and a darker edge (a bright edge over dark maps)
            layer.paste(Image.new('RGBA', (W, H), col + (255,)), (0, 0), m.point(lambda v: int(v * (0.62 if style == 'light' else 0.42 if st['img'] else 0.55))))
            e1 = m.filter(ImageFilter.FIND_EDGES)
            if style != 'light':
                layer.paste(Image.new('RGBA', (W, H), (13, 29, 35, 255)), (0, 0), e1.filter(ImageFilter.MaxFilter(9)).point(lambda v: int(v * 0.6)))
            ec = tuple(int(v * 0.68) for v in col) if style == 'light' else col
            layer.paste(Image.new('RGBA', (W, H), ec + (255,)), (0, 0), e1.filter(ImageFilter.MaxFilter(5)))
        elif style == 'classic':
            layer.paste(Image.new('RGBA', (W, H), col + (255,)), (0, 0), m.point(lambda v: int(v * 0.55)))
            edge = m.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.MaxFilter(5))
            layer.paste(Image.new('RGBA', (W, H), tuple(int(v * 0.72) for v in col) + (255,)), (0, 0), edge)
        else:
            # outer glow, a fill (striped on the poster), then a crisp bright outline
            edge = m.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.MaxFilter(3))
            glow = edge.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(14 * S))
            glow = glow.point(lambda v: min(255, int(v * 3.2)))
            layer.paste(Image.new('RGBA', (W, H), col + (255,)), (0, 0), ImageChops.multiply(glow, ImageOps.invert(m).point(lambda v: int(v * 0.9))))
            if style == 'poster':
                stripes = Image.new('L', (W, H), 0); sd = ImageDraw.Draw(stripes); step = 26 * S
                for i in range(-H, W + H, step):
                    sd.polygon([(i, 0), (i + step // 2, 0), (i + step // 2 - H, H), (i - H, H)], fill=255)
                layer.paste(Image.new('RGBA', (W, H), col + (255,)), (0, 0), ImageChops.multiply(m, stripes.point(lambda v: int(v * 0.62))))
                layer.paste(Image.new('RGBA', (W, H), col + (255,)), (0, 0), m.point(lambda v: int(v * 0.16)))
            else:
                layer.paste(Image.new('RGBA', (W, H), col + (255,)), (0, 0), m.point(lambda v: int(v * (0.30 if st['img'] else 0.40))))
            layer.paste(Image.new('RGBA', (W, H), (0, 0, 0, 255)), (0, 0), m.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.MaxFilter(11)).point(lambda v: int(v * 0.55)))
            layer.paste(Image.new('RGBA', (W, H), col + (255,)), (0, 0), m.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.MaxFilter(7)))
    # district lines, then coast and borders on top (semi-transparent on imagery)
    ov = Image.new('RGBA', (W, H), (0, 0, 0, 0)); od = ImageDraw.Draw(ov)
    for r in G['districts']:
        od.line([(X(p[0]) - ox, Y(p[1]) - oy) for p in r], fill=st['dist'], width=int(1.1 * S), joint='curve')
    for name, gj in G['states'].items():
        for r in rings(gj):
            if len(r) > 2: od.line(r + [r[0]], fill=st['coast'], width=int((1.3 if base else 1.6) * S), joint='curve')
    layer = Image.alpha_composite(layer, ov); d = ImageDraw.Draw(layer)
    # towns: the ones named in the warning first, then a few big ones for bearings
    named = [t for t in item.get('towns', []) if norm(t) in G['places']]
    others = [t['n'] for t in G['towns'][:40]]
    placed, ft_b, ft_r = [], font(700 if dark else 600, 23 if dark else 21), font(500, 18)
    for i, n in enumerate(named + [o for o in others if o not in named]):
        if n in named:
            lat, lng = G['places'][norm(n)][:2]; f, dot = ft_b, st['lab']
        else:
            t = next(t for t in G['towns'] if t['n'] == n); lat, lng = t['lat'], t['lng']; f, dot = ft_r, st['town']
        px, py = X(lng) - ox, Y(lat) - oy
        if not (24 * S < px < W - 24 * S and 20 * S < py < H - 20 * S): continue
        tw = d.textlength(n, font=f); left = px + 10 * S + tw > W - 10 * S
        tx = px - 10 * S - tw if left else px + 10 * S
        bb = (min(px, tx) - 4 * S, py - 14 * S, max(px, tx + tw) + 4 * S, py + 14 * S)
        if any(bb[0] < q[2] and bb[2] > q[0] and bb[1] < q[3] and bb[3] > q[1] for q in placed):
            continue
        if n not in named and len([q for q in placed]) > len(named) + 6: break
        placed.append(bb)
        r = 5 * S if n in named else 4 * S
        d.ellipse([px - r, py - r, px + r, py + r], fill=dot, outline=st['halo'] if dark else (255, 255, 255), width=int(1.5 * S))
        d.text((tx, py - (14 if dark and n in named else 13) * S), n, font=f, fill=dot, stroke_width=int(3 * S), stroke_fill=st['halo'])
    # rounded corners
    mask = Image.new('L', (W, H), 0); ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, H - 1], radius=18 * S if rounded else 0, fill=255)
    img.paste(layer.convert('RGB'), (x0, y0), mask)
    return credit

def when_sat(t):
    try:
        x = dt.datetime.fromisoformat(t.replace('Z', '+00:00')).astimezone(dt.timezone(dt.timedelta(hours=8)))
        return 'image ' + x.strftime('%-I:%M %p').lower() + ' AWST'
    except Exception:
        return ''


# ---------------------------------------------------------------- the pieces
def header(img, d, item, col, Wd, h, th=None):
    d.rectangle([0, 0, Wd, h], fill=HEAD)
    logo = Image.open(os.path.join(ASSETS, 'logo-dark.png')).convert('RGBA')
    lh = int(h * 0.62); logo = logo.resize((int(logo.width * lh / logo.height), lh), Image.LANCZOS)
    img.paste(logo, (int(28 * S), int((h - lh) / 2)), logo)
    d.rectangle([0, h - 8 * S, Wd, h], fill=col)

def chips(d, hazards, x, y, maxw, size=22):
    f = font(700, size); cx, cy, rows = x, y, 1
    hh = int(size * 1.9 * S)
    for hz in hazards:
        lab, c = HAZ.get(hz, (hz.capitalize(), (90, 90, 90)))
        lab = lab.upper(); tw = d.textlength(lab, font=f) + 34 * S
        if cx + tw > x + maxw and cx > x: cx = x; cy += hh + 12 * S; rows += 1
        d.rounded_rectangle([cx, cy, cx + tw, cy + hh], radius=hh // 2, fill=c)
        d.text((cx + 17 * S, cy + hh / 2), lab, font=f, fill=(255, 255, 255), anchor='lm')
        cx += tw + 12 * S
    return cy + hh

def textbox(d, x, y, w, title, body, size, max_lines, col, th=LIGHT, plain=False):
    ft, fb = font(700, size * 0.8), font(400, size)
    if plain:   # the site's headings: sentence case, bold
        d.text((x, y), title, font=font(700, size * 0.92), fill=col); y += int(size * 1.45 * S)
    else:
        d.text((x, y), title.upper(), font=ft, fill=col)
        y += int(size * 1.35 * S)
    lines = wrap(d, body, fb, w)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while lines[-1] and d.textlength(lines[-1] + '…', font=fb) > w: lines[-1] = lines[-1].rsplit(' ', 1)[0]
        lines[-1] += '…'
    for ln in lines:
        d.text((x, y), ln, font=fb, fill=th['text']); y += int(size * 1.42 * S)
    return y

def report_cards(d, reps, x, y, w, th, size=1.0, cols=2, head=None):
    """Reported values: the value in white on a solid block (wind orange, hail purple, rain blue),
    what it was beside it and where / when under that. Returns the bottom y."""
    if not reps: return y
    d.text((x, y), 'Reported', font=font(700, 22 * size), fill=head or th['accent']); y += int(34 * size * S)
    bh, gap = int(64 * size * S), int(16 * S)
    n = len(reps); cols = max(1, min(cols, n)); cw = (w - gap * (cols - 1)) / cols
    fv, f1, f2 = font(700, 30 * size), font(600, 19 * size), font(400, 16 * size)
    for i, r in enumerate(reps):
        cx = x + (i % cols) * (cw + gap); cy = y + (i // cols) * (bh + gap)
        bw = d.textlength(r['value'], font=fv) + 36 * S
        d.rounded_rectangle([cx, cy, cx + bw, cy + bh], radius=int(10 * S), fill=REP_COL[r['kind']])
        d.text((cx + bw / 2, cy + bh / 2), r['value'], font=fv, fill=(255, 255, 255), anchor='mm')
        tx = cx + bw + 16 * S; room = cw - bw - 16 * S
        sub = ' · '.join(t for t in (r['where'], r['when']) if t)
        while sub and d.textlength(sub, font=f2) > room and ' ' in sub: sub = sub.rsplit(' ', 1)[0]
        d.text((tx, cy + bh * 0.30), r['label'], font=f1, fill=th['text'], anchor='lm')
        if sub: d.text((tx, cy + bh * 0.72), sub, font=f2, fill=th['muted'], anchor='lm')
    return y + ((n - 1) // cols + 1) * (bh + gap) - gap

def stamp(item):
    s = 'Issued ' + when(item.get('sent'))
    if item.get('expires') and item.get('status') == 'current':
        s += ' · until ' + when(item['expires']).split(', ')[-1]
    return s + ' AWST'


# ---------------------------------------------------------------- the two images
def render(item, post_path=None, story_path=None, style=None):
    style = style or STYLE
    if style in BRAND:
        return render_brand(item, post_path, story_path, style)
    th = LIGHT if style == 'classic' else DARK
    col = TYPE_COL.get(item.get('type'), (242, 194, 0))
    situ = situation(item.get('description', ''))
    more = [x for x in details(item.get('description', ''), situ) if not _OBS.search(x)]
    reps = item.get('reports')
    if reps is None: reps = reports(item.get('description', ''))
    hz = item.get('hazards') or []
    kind = item.get('type', 'Warning'); title = kind.replace(' (Perth Area)', '')
    ppl = people_text(item.get('people') or people_in(item.get('area'))[0])
    plain = style != 'classic'; hc = th['accent'] if style == 'classic' else col   # headings: warning colour on the dark styles
    foot = lambda cr: ('Unofficial copy · official warnings: bom.gov.au · Warning © Bureau of Meteorology') + ('' if not cr else '')
    if post_path:
        Wd = Hd = 1080 * S
        img = Image.new('RGB', (Wd, Hd), th['bg']); d = ImageDraw.Draw(img)
        if style == 'poster':
            header(img, d, item, col, Wd, 118 * S, th)
            d.text((Wd - 32 * S, 72 * S), stamp(item), font=font(500, 21), fill=th['stamp'], anchor='rs')
            d.rectangle([0, 118 * S, Wd, 214 * S], fill=col)
            ft = font(800, 52 if len(title) < 30 else 42)
            d.text((36 * S, 166 * S), title.upper(), font=ft, fill=(12, 12, 12), anchor='lm')
            y = 236 * S
        else:
            header(img, d, item, col, Wd, 150 * S, th)
            d.text((Wd - 32 * S, 62 * S), title, font=font(700, 38 if len(kind) < 30 else 32), fill=(255, 255, 255), anchor='rs')
            d.text((Wd - 32 * S, 104 * S), stamp(item), font=font(400, 21), fill=th['stamp'], anchor='rs')
            y = 172 * S
        y = chips(d, hz, 36 * S, y, Wd - 72 * S, 22) if hz else y
        if ppl:
            d.text((36 * S, y + 12 * S), ppl, font=font(600, 21), fill=th['text']); y += 40 * S
        if reps:
            y = report_cards(d, reps[:2], 36 * S, y + 20 * S, Wd - 72 * S, th, 1.0, 2, hc)
        map_top = y + 18 * S
        text_h = (160 if reps else 196) * S
        credit = draw_map(img, (36 * S, map_top, Wd - 36 * S, Hd - text_h - 64 * S), item, col, style)
        if credit:
            d.text((Wd - 48 * S, Hd - text_h - 64 * S - 12 * S), credit, font=font(500, 14), fill=(220, 228, 232), anchor='rs',
                   stroke_width=int(2 * S), stroke_fill=(0, 0, 0))
        textbox(d, 36 * S, Hd - text_h - 44 * S, Wd - 72 * S, 'Weather situation', situ, 23, 3 if reps else 4, hc, th, plain)
        d.line([36 * S, Hd - 50 * S, Wd - 36 * S, Hd - 50 * S], fill=th['rule'], width=int(1.5 * S))
        d.text((Wd / 2, Hd - 24 * S), foot(credit), font=font(400, 17), fill=th['muted'], anchor='mm')
        img.resize((Wd // S, Hd // S), Image.LANCZOS).save(post_path, optimize=True)
    if story_path:
        Wd, Hd = 1080 * S, 1920 * S
        img = Image.new('RGB', (Wd, Hd), th['bg']); d = ImageDraw.Draw(img)
        header(img, d, item, col, Wd, 190 * S, th)
        y = 226 * S
        if style == 'poster':
            f = font(800, 60 if len(title) < 30 else 50)
            lines = wrap(d, title.upper(), f, Wd - 96 * S)
            d.rectangle([0, 190 * S, Wd, 190 * S + (len(lines) * 70 + 50) * S], fill=col)
            y = 190 * S + 24 * S
            for ln in lines:
                d.text((48 * S, y), ln, font=f, fill=(12, 12, 12)); y += 70 * S
            y += 44 * S
        else:
            f = font(700, 56 if len(kind) < 30 else 46)
            for ln in wrap(d, title, f, Wd - 96 * S):
                d.text((48 * S, y), ln, font=f, fill=th['text']); y += 66 * S
        d.text((48 * S, y + 6 * S), stamp(item), font=font(400, 26), fill=th['muted']); y += 58 * S
        if hz: y = chips(d, hz, 48 * S, y + 6 * S, Wd - 96 * S, 26) + 28 * S
        if ppl:
            d.text((48 * S, y - 6 * S), ppl, font=font(600, 26), fill=th['text']); y += 46 * S
        if reps:
            y = report_cards(d, reps[:4], 48 * S, y, Wd - 96 * S, th, 1.2, 1 if len(reps) == 1 else 2, hc) + 30 * S
        # the map takes whatever the text below it doesn't need
        sc = ImageDraw.Draw(Image.new('RGB', (Wd, 10)))
        need = textbox(sc, 0, 0, Wd - 96 * S, 'Weather situation', situ, 28, 6 if reps else 7, hc, th, plain) + 18 * S
        if more: need = textbox(sc, 0, need, Wd - 96 * S, 'What to expect', ' '.join(more), 26, 5, hc, th, plain) + 18 * S
        if item.get('towns'): need = textbox(sc, 0, need, Wd - 96 * S, 'Locations which may be affected', ', '.join(item['towns']), 26, 3, hc, th, plain)
        mh = max(620 * S, min(1000 * S, Hd - 120 * S - need - 34 * S - y)) if plain else (700 if reps else 780) * S - (60 * S if style == 'poster' else 0)
        credit = draw_map(img, (48 * S, y, Wd - 48 * S, y + mh), item, col, style)
        if credit:
            d.text((Wd - 62 * S, y + mh - 14 * S), credit, font=font(500, 17), fill=(220, 228, 232), anchor='rs',
                   stroke_width=int(2 * S), stroke_fill=(0, 0, 0))
        y += mh + 34 * S
        y = textbox(d, 48 * S, y, Wd - 96 * S, 'Weather situation', situ, 28, 6 if reps else 7, hc, th, plain) + 18 * S
        if more and (plain or y < Hd - 380 * S):
            y = textbox(d, 48 * S, y, Wd - 96 * S, 'What to expect', ' '.join(more), 26, 5, hc, th, plain) + 18 * S
        towns = item.get('towns') or []
        if towns and (plain or y < Hd - 260 * S):
            y = textbox(d, 48 * S, y, Wd - 96 * S, 'Locations which may be affected', ', '.join(towns), 26, 3, hc, th, plain)
        d.line([48 * S, Hd - 92 * S, Wd - 48 * S, Hd - 92 * S], fill=th['rule'], width=int(1.5 * S))
        d.text((Wd / 2, Hd - 62 * S), 'Unofficial copy · always check the official warning at bom.gov.au', font=font(500, 22), fill=th['muted'], anchor='mm')
        d.text((Wd / 2, Hd - 32 * S), 'Warning © Commonwealth of Australia, Bureau of Meteorology', font=font(400, 18), fill=th['muted'], anchor='mm')
        img.resize((Wd // S, Hd // S), Image.LANCZOS).save(story_path, optimize=True)


# ---------------------------------------------------------------- the website's look (same layout as the outlook image)
def rep_pills(d, reps, x, y, maxw, th, size):
    """Reported values as legend rows: a coloured pill with the value, then what / where / when."""
    fp, fl = font(700, size), font(500, size * 0.86)
    hh = int(size * 1.75 * S)
    for r in reps:
        c = REP_COL[r['kind']]; v = r['value']
        tw = d.textlength(v, font=fp) + 30 * S
        d.rounded_rectangle([x, y, x + tw, y + hh], radius=hh // 2, fill=c)
        d.text((x + 15 * S, y + hh / 2), v, font=fp, fill=(255, 255, 255), anchor='lm')
        sub = r['label'] + (' at ' + r['where'] if r['where'] else '') + (', ' + r['when'] if r['when'] else '')
        while d.textlength(sub, font=fl) > maxw - tw - 20 * S and ' ' in sub: sub = sub.rsplit(' ', 1)[0]
        d.text((x + tw + 14 * S, y + hh / 2), sub, font=fl, fill=th['text'], anchor='lm')
        y += hh + 12 * S
    return y - 12 * S

def legend(d, x, y, col, title, sub, th, size):
    """The outlook's legend item: a swatch, a bold name and a muted line."""
    sw = int(size * 2.0 * S)
    d.rounded_rectangle([x, y, x + sw, y + sw], radius=int(5 * S), fill=col, outline=tuple(int(v * 0.68) for v in col), width=int(2 * S))
    d.text((x + sw + 16 * S, y - 2 * S), title, font=font(600, size), fill=th['text'])
    if sub: d.text((x + sw + 16 * S, y + size * 1.25 * S), sub, font=font(400, size * 0.74), fill=th['muted'])
    return y + max(sw, int(size * 2.2 * S))

def brand_header(img, d, Wd, h, title, sub, size):
    d.rectangle([0, 0, Wd, h], fill=HEAD)
    logo = Image.open(os.path.join(ASSETS, 'logo-dark.png')).convert('RGBA')
    lh = int(h * 0.66); logo = logo.resize((int(logo.width * lh / logo.height), lh), Image.LANCZOS)
    img.paste(logo, (int(28 * S), int((h - lh) / 2)), logo)
    f = font(700, size)
    while d.textlength(title, font=f) > Wd - logo.width - 90 * S: size -= 2; f = font(700, size)
    d.text((Wd - 32 * S, h * 0.50), title, font=f, fill=(255, 255, 255), anchor='rs')
    d.text((Wd - 32 * S, h * 0.80), sub, font=font(400, size * 0.55), fill=(157, 205, 211), anchor='rs')
    d.rectangle([0, h - 6 * S, Wd, h], fill=ACCENT)

def render_brand(item, post_path, story_path, style):
    th = LIGHT if style in ('light', 'satellite') else DARK
    col = TYPE_COL.get(item.get('type'), (242, 194, 0))
    situ = situation(item.get('description', ''))
    more = [x for x in details(item.get('description', ''), situ) if not _OBS.search(x)]
    reps = item.get('reports')
    if reps is None: reps = reports(item.get('description', ''))
    hz = item.get('hazards') or []
    title = item.get('type', 'Warning').replace(' (Perth Area)', '')
    ppl = people_text(item.get('people') or people_in(item.get('area'))[0])
    ppl = ppl.replace('About ', 'About ').replace(' in towns in the warning area', ' people in towns in the area').replace(' people people', ' people') if ppl else ''
    towns = item.get('towns') or []

    def panel(d, Wd, y, pad, size, situ_lines, extra):
        """Draws the legend panel from y down; returns the bottom. Run once on a scratch image to measure."""
        y = legend(d, pad, y, col, 'Warning area', ppl or ('Includes ' + ', '.join(towns[:3]) if towns else ''), th, size) + int(18 * S)
        if hz: y = chips(d, hz, pad, y, Wd - 2 * pad, size * 0.82) + int(18 * S)
        if reps: y = rep_pills(d, reps[:extra and 4 or 2], pad, y, Wd - 2 * pad, th, size * 0.9) + int(20 * S)
        y = textbox(d, pad, y, Wd - 2 * pad, 'Weather situation', situ, size * 0.92, situ_lines, th['accent'] if th is DARK else ACCENT, th) + int(10 * S)
        if extra:
            if more: y = textbox(d, pad, y + 8 * S, Wd - 2 * pad, 'What to expect', ' '.join(more), size * 0.86, 4, th['accent'] if th is DARK else ACCENT, th) + int(10 * S)
            if towns: y = textbox(d, pad, y + 8 * S, Wd - 2 * pad, 'Locations which may be affected', ', '.join(towns), size * 0.86, 3, th['accent'] if th is DARK else ACCENT, th) + int(10 * S)
        return y

    def footer(d, Wd, Hd, pad, fh, size):
        d.line([pad, Hd - fh, Wd - pad, Hd - fh], fill=th['rule'], width=int(1.5 * S))
        d.text((pad, Hd - fh / 2), 'Warning © Bureau of Meteorology', font=font(500, size), fill=th['muted'], anchor='lm')
        d.text((Wd - pad, Hd - fh / 2), 'Unofficial copy · official warnings: bom.gov.au', font=font(400, size), fill=th['muted'], anchor='rm')

    for path, Wd, Hd, hh, tsize, size, lines, extra in ((post_path, 1080, 1080, 130, 42, 24, 3, False),
                                                         (story_path, 1080, 1920, 170, 44, 30, 5, True)):
        if not path: continue
        Wd, Hd, hh = Wd * S, Hd * S, hh * S
        pad, fh = 36 * S, 66 * S
        scratch = ImageDraw.Draw(Image.new('RGB', (Wd, Hd)))
        ph = panel(scratch, Wd, 0, pad, size, lines, extra) + 28 * S      # panel height
        map_bot = Hd - fh - ph - 20 * S
        img = Image.new('RGB', (Wd, Hd), th['bg']); d = ImageDraw.Draw(img)
        credit = draw_map(img, (0, hh, Wd, map_bot), item, col, style, rounded=False)
        brand_header(img, d, Wd, hh, title, stamp(item), tsize)
        if credit:
            d.text((Wd - 16 * S, map_bot - 12 * S), credit, font=font(500, 15 if not extra else 18), fill=(235, 241, 243), anchor='rs',
                   stroke_width=int(2 * S), stroke_fill=(13, 29, 35))
        panel(d, Wd, map_bot + 30 * S, pad, size, lines, extra)
        footer(d, Wd, Hd, pad, fh, 17 if not extra else 20)
        img.resize((Wd // S, Hd // S), Image.LANCZOS).save(path, optimize=True)


if __name__ == '__main__':
    src, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    styles = (list(BRAND) if '--brand' in sys.argv else ['night', 'satellite', 'clouds', 'poster'] if '--yellow' in sys.argv else STYLES) if any(a in sys.argv for a in ('--styles', '--brand', '--yellow')) else [STYLE]
    for w in json.load(open(src)).get('warnings', []):
        for stl in styles:
            base = os.path.join(out, w['id'] + ('-' + stl if len(styles) > 1 else ''))
            render(w, base + '-post.png', base + '-story.png', style=stl)
            print('made', base + '-post.png', base + '-story.png')

#!/usr/bin/env python3
"""
West WX Watchers — images for posting a BoM warning: a square post (1080x1080) and a story (1080x1920).

Drawn from the relay's warning record: the warning area on a map of WA (with the listed towns),
the threats (damaging winds, large hail, heavy rain...) and the weather situation from the warning text.
Unofficial: the images say so, and point to bom.gov.au.

    from warnimg import render
    render(item, 'post.png', 'story.png')        # item = one warning from data/warnings.json

    python warnimg.py data/warnings.json OUTDIR  # test: images for every warning in a file
"""
import json, math, os, re, sys, datetime as dt
from PIL import Image, ImageDraw, ImageFilter, ImageFont

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

def draw_map(img, box, item, col):
    """The warning area on WA, fitted to the area, inside box = (x0, y0, x1, y1) in drawing pixels."""
    G = geo(); x0, y0, x1, y1 = box; W, H = x1 - x0, y1 - y0
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
    layer = Image.new('RGB', (W, H), OCEAN); d = ImageDraw.Draw(layer)
    ox, oy = x0, y0
    def rings(g):
        cs = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
        for poly in cs:
            for ring in poly[:1]:
                yield [(X(p[0]) - ox, Y(p[1]) - oy) for p in ring]
    for name, gj in G['states'].items():
        for r in rings(gj):
            if len(r) > 2: d.polygon(r, fill=LAND if name == 'Western Australia' else OTHER)
    # the warning area: a soft-edged fill and a strong outline
    if polys:
        m = Image.new('L', (W, H), 0); md = ImageDraw.Draw(m)
        for poly in polys:
            md.polygon([(X(x) - ox, Y(y) - oy) for x, y in poly[0]], fill=255)
            for hole in poly[1:]: md.polygon([(X(x) - ox, Y(y) - oy) for x, y in hole], fill=0)
        fill = Image.new('RGB', (W, H), col)
        layer.paste(fill, (0, 0), m.point(lambda v: int(v * 0.55)))
        edge = m.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.MaxFilter(5))
        layer.paste(Image.new('RGB', (W, H), tuple(int(v * 0.72) for v in col)), (0, 0), edge)
    # district lines, then coast and borders on top
    for r in G['districts']:
        d.line([(X(p[0]) - ox, Y(p[1]) - oy) for p in r], fill=DIST, width=int(1.1 * S), joint='curve')
    for name, gj in G['states'].items():
        for r in rings(gj):
            if len(r) > 2: d.line(r + [r[0]], fill=COAST, width=int(1.6 * S), joint='curve')
    # towns: the ones named in the warning first, then a few big ones for bearings
    named = [t for t in item.get('towns', []) if norm(t) in G['places']]
    others = [t['n'] for t in G['towns'][:40]]
    placed, ft_b, ft_r = [], font(600, 21), font(500, 18)
    for i, n in enumerate(named + [o for o in others if o not in named]):
        if n in named:
            lat, lng = G['places'][norm(n)][:2]; f, dot = ft_b, TEXT
        else:
            t = next(t for t in G['towns'] if t['n'] == n); lat, lng = t['lat'], t['lng']; f, dot = ft_r, MUTED
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
        d.ellipse([px - r, py - r, px + r, py + r], fill=dot, outline=(255, 255, 255), width=int(1.5 * S))
        d.text((tx, py - 13 * S), n, font=f, fill=dot, stroke_width=int(3 * S), stroke_fill=(255, 255, 255))
    # rounded corners
    mask = Image.new('L', (W, H), 0); ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, H - 1], radius=18 * S, fill=255)
    img.paste(layer, (x0, y0), mask)


# ---------------------------------------------------------------- the pieces
def header(img, d, item, col, Wd, h):
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

def textbox(d, x, y, w, title, body, size, max_lines, col):
    ft, fb = font(700, size * 0.8), font(400, size)
    d.text((x, y), title.upper(), font=ft, fill=col)
    y += int(size * 1.35 * S)
    lines = wrap(d, body, fb, w)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while lines[-1] and d.textlength(lines[-1] + '…', font=fb) > w: lines[-1] = lines[-1].rsplit(' ', 1)[0]
        lines[-1] += '…'
    for ln in lines:
        d.text((x, y), ln, font=fb, fill=TEXT); y += int(size * 1.42 * S)
    return y

def stamp(item):
    s = 'Issued ' + when(item.get('sent'))
    if item.get('expires') and item.get('status') == 'current':
        s += ' · until ' + when(item['expires']).split(', ')[-1]
    return s + ' AWST'


# ---------------------------------------------------------------- the two images
def render(item, post_path=None, story_path=None):
    col = TYPE_COL.get(item.get('type'), (242, 194, 0))
    situ = situation(item.get('description', ''))
    more = details(item.get('description', ''), situ)
    hz = item.get('hazards') or []
    kind = item.get('type', 'Warning')
    if post_path:
        Wd = Hd = 1080 * S
        img = Image.new('RGB', (Wd, Hd), BG); d = ImageDraw.Draw(img)
        header(img, d, item, col, Wd, 150 * S)
        d.text((Wd - 32 * S, 62 * S), kind.replace(' (Perth Area)', ''), font=font(700, 38 if len(kind) < 30 else 32), fill=(255, 255, 255), anchor='rs')
        d.text((Wd - 32 * S, 104 * S), stamp(item), font=font(400, 21), fill=(157, 205, 211), anchor='rs')
        y = chips(d, hz, 36 * S, 172 * S, Wd - 72 * S, 22) if hz else 172 * S
        ppl = people_text(item.get('people') or people_in(item.get('area'))[0])
        if ppl:
            d.text((36 * S, y + 12 * S), ppl, font=font(600, 21), fill=TEXT); y += 40 * S
        map_top = y + 18 * S
        text_h = 196 * S
        draw_map(img, (36 * S, map_top, Wd - 36 * S, Hd - text_h - 64 * S), item, col)
        textbox(d, 36 * S, Hd - text_h - 44 * S, Wd - 72 * S, 'Weather situation', situ, 23, 4, ACCENT)
        d.line([36 * S, Hd - 50 * S, Wd - 36 * S, Hd - 50 * S], fill=(201, 216, 220), width=int(1.5 * S))
        d.text((Wd / 2, Hd - 24 * S), 'Unofficial copy · official warnings: bom.gov.au · Warning © Bureau of Meteorology', font=font(400, 17), fill=MUTED, anchor='mm')
        img.resize((Wd // S, Hd // S), Image.LANCZOS).save(post_path, optimize=True)
    if story_path:
        Wd, Hd = 1080 * S, 1920 * S
        img = Image.new('RGB', (Wd, Hd), BG); d = ImageDraw.Draw(img)
        header(img, d, item, col, Wd, 190 * S)
        y = 226 * S
        f = font(700, 56 if len(kind) < 30 else 46)
        for ln in wrap(d, kind.replace(' (Perth Area)', ''), f, Wd - 96 * S):
            d.text((48 * S, y), ln, font=f, fill=TEXT); y += 66 * S
        d.text((48 * S, y + 6 * S), stamp(item), font=font(400, 26), fill=MUTED); y += 58 * S
        if hz: y = chips(d, hz, 48 * S, y + 6 * S, Wd - 96 * S, 26) + 28 * S
        ppl = people_text(item.get('people') or people_in(item.get('area'))[0])
        if ppl:
            d.text((48 * S, y - 6 * S), ppl, font=font(600, 26), fill=TEXT); y += 46 * S
        mh = 780 * S
        draw_map(img, (48 * S, y, Wd - 48 * S, y + mh), item, col); y += mh + 34 * S
        y = textbox(d, 48 * S, y, Wd - 96 * S, 'Weather situation', situ, 28, 7, ACCENT) + 18 * S
        if more and y < Hd - 380 * S:
            y = textbox(d, 48 * S, y, Wd - 96 * S, 'What to expect', ' '.join(more), 26, 5, ACCENT) + 18 * S
        towns = item.get('towns') or []
        if towns and y < Hd - 260 * S:
            y = textbox(d, 48 * S, y, Wd - 96 * S, 'Locations which may be affected', ', '.join(towns), 26, 3, ACCENT)
        d.line([48 * S, Hd - 92 * S, Wd - 48 * S, Hd - 92 * S], fill=(201, 216, 220), width=int(1.5 * S))
        d.text((Wd / 2, Hd - 62 * S), 'Unofficial copy · always check the official warning at bom.gov.au', font=font(500, 22), fill=MUTED, anchor='mm')
        d.text((Wd / 2, Hd - 32 * S), 'Warning © Commonwealth of Australia, Bureau of Meteorology', font=font(400, 18), fill=MUTED, anchor='mm')
        img.resize((Wd // S, Hd // S), Image.LANCZOS).save(story_path, optimize=True)


if __name__ == '__main__':
    src, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    for w in json.load(open(src)).get('warnings', []):
        base = os.path.join(out, w['id'])
        render(w, base + '-post.png', base + '-story.png')
        print('made', base + '-post.png', base + '-story.png')

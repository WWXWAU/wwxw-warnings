#!/usr/bin/env python3
"""
West WX Watchers — weather story video (1080x1920, 30 fps): rain, max/min/current temperature or gusts.

  python3 wxvideo.py data.json out.mp4 [--caption "..."] [--logo logo-dark.png]

data.json (VideoMaker.gs in the rainfall project):
  {"kind": "rain"|"tmax"|"tmin"|"temp"|"gust", "title": "...", "sub": "...", "src": "BoM, DPIRD",
   "days": 1, "points": [[name, lat, lng, value], ...]}
"""
import argparse, csv, json, math, os, re, subprocess, sys, tempfile
from datetime import date, datetime
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))
W, H, FPS = 1080, 1920, 30
PPD = 260                                   # base map pixels per degree of longitude
LNG0, LNG1, LAT0, LAT1 = 108.0, 134.0, -9.0, -40.0   # base map extent (N edge LAT0, S edge LAT1)
# Website theme (dark): the outlook page's colours
BG, SURFACE, TEXT, MUTED, LINE, ACCENT, ON_ACCENT = (16, 35, 42), (22, 48, 58), (226, 238, 240), (157, 182, 189), (40, 67, 77), (63, 193, 201), (8, 24, 29)
LOGO = None   # set from --logo

def merc(lat): return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
SCALE = PPD * 180 / math.pi                  # pixels per radian of Mercator y
BW = int((LNG1 - LNG0) * PPD)
BH = int((merc(LAT0) - merc(LAT1)) * SCALE)
def to_px(lat, lng): return ((lng - LNG0) * PPD, (merc(LAT0) - merc(lat)) * SCALE)
def lat_of(py): return math.degrees(2 * math.atan(math.exp(merc(LAT0) - py / SCALE)) - math.pi / 2)

FONT_DIR = '/usr/share/fonts'
_FC = {}
def font(name, size):
    """Lexend (the website font) at a weight: name = weight number or 'bold'/'semi'/'med'/'black'."""
    wt = {'black': 800, 'blacki': 800, 'bold': 700, 'cond': 600, 'semi': 600, 'med': 500, 'reg': 400}.get(name, name)
    k = (wt, size)
    if k not in _FC:
        f = ImageFont.truetype(os.path.join(HERE, 'Lexend.ttf'), size)
        f.set_variation_by_axes([wt]); _FC[k] = f
    return _FC[k]

# ---------------------------------------------------------------- data
RAIN_STOPS = [(0.5, (40, 70, 160, 0)), (1, (45, 85, 200, 150)), (5, (40, 150, 225, 190)), (10, (40, 190, 120, 205)),
              (15, (150, 215, 60, 215)), (25, (255, 225, 70, 225)), (40, (255, 150, 40, 230)), (60, (235, 60, 40, 235)),
              (100, (160, 20, 70, 240)), (150, (110, 30, 150, 240))]
TEMP_STOPS = [(-5, (120, 80, 200, 215)), (0, (70, 110, 230, 215)), (5, (60, 160, 235, 215)), (10, (60, 200, 200, 215)),
              (15, (70, 200, 120, 215)), (20, (160, 215, 70, 215)), (25, (240, 225, 70, 220)), (30, (250, 170, 50, 225)),
              (35, (240, 100, 40, 230)), (40, (210, 40, 40, 235)), (45, (150, 20, 60, 240)), (50, (90, 10, 60, 240))]
GUST_STOPS = [(15, (50, 110, 200, 0)), (20, (50, 110, 200, 120)), (40, (50, 170, 200, 175)), (60, (90, 200, 110, 200)),
              (70, (220, 220, 60, 215)), (80, (250, 160, 40, 225)), (90, (235, 60, 40, 235)), (110, (170, 20, 90, 240)),
              (130, (110, 30, 150, 240))]

def fmt_mm(v): return f"{v:.0f} mm" if v >= 10 else f"{v:.1f} mm"
def fmt_t(v): return f"{v:.1f}°"
def fmt_g(v): return f"{v:.0f} km/h"

TEMP = dict(stops=TEMP_STOPS, legend=[0, 5, 10, 15, 20, 25, 30, 35, 40, 45], unit='°C', fmt=fmt_t, sig=0.5, cover=(2.5, 4.0), floor=None, near=3)
KINDS = {
    'rain': dict(stops=RAIN_STOPS, legend=[1, 5, 10, 15, 25, 40, 60, 100, 150], unit='mm', fmt=fmt_mm, sig=0.22, cover=(0.22, 0.62),
                 floor=0.5, order=-1, word='gauge'),
    'tmax': dict(TEMP, order=-1, word='station'),
    'temp': dict(TEMP, order=-1, word='station'),
    'tmin': dict(TEMP, order=1, word='station'),
    'gust': dict(stops=GUST_STOPS, legend=[20, 40, 60, 70, 80, 90, 110, 130], unit='km/h', fmt=fmt_g, sig=0.5, cover=(2.0, 3.5),
                 floor=15, order=-1, word='station', smooth=True, near=15),
}
K = KINDS['rain']   # set in main

def read_data(path):
    doc = json.load(open(path, encoding='utf-8'))
    pts = []
    for name, lat, lng, v in doc['points']:
        if v is None or not (-36 < lat < -13 and 112 < lng < 129.5): continue
        pts.append({'name': str(name).strip(), 'lat': float(lat), 'lng': float(lng), 'v': float(v)})
    return doc, pts

def caption_for(kind, pts, days):
    vs = [p['v'] for p in pts]; hi, lo = max(vs), min(vs)
    if kind == 'rain':
        big, soak = (50, 25) if days <= 1 else (80, 40)
        return 'Big falls!' if hi >= big else 'Solid soaking!' if hi >= soak else 'Showers about' if hi >= 5 else 'Mostly dry'
    if kind in ('tmax', 'temp'):
        return 'Scorcher!' if hi >= 45 else 'Hot one!' if hi >= 40 else 'Warm to hot' if hi >= 35 else 'Warm day' if hi >= 28 else 'Mild'
    if kind == 'tmin':
        return 'Frosty start!' if lo <= 0 else 'Chilly night' if lo <= 5 else 'Cool night' if lo <= 10 else 'Warm night'
    return 'Wild winds!' if hi >= 100 else 'Gusty!' if hi >= 80 else 'Breezy' if hi >= 60 else 'Light winds'

def badge_for(kind, pts):
    n = lambda f: sum(1 for p in pts if f(p['v']))
    pl = lambda c, w: f'{c} {w}{"s" if c != 1 else ""}'
    w = K['word']
    if kind == 'rain':
        for thr in (25, 10, 1):
            c = n(lambda v: v >= thr)
            if c: return pl(c, w) + f' over {thr} mm'
        return 'No gauge over 1 mm'
    if kind in ('tmax', 'temp'):
        for thr in (45, 40, 35, 30):
            c = n(lambda v: v >= thr)
            if c: return pl(c, w) + f' at {thr}° or more'
        return pl(len(pts), w)
    if kind == 'tmin':
        for thr in (0, 2, 5, 10):
            c = n(lambda v: v <= thr)
            if c: return pl(c, w) + f' at {thr}° or below'
        return pl(len(pts), w)
    for thr in (90, 70, 50):
        c = n(lambda v: v >= thr)
        if c: return pl(c, w) + f' gusting {thr}+ km/h'
    return pl(len(pts), w)

TOWNS = []
def label_name(g):
    """Station name for a label; DFES portable stations get the nearest town instead of their code."""
    if re.search(r'PORTABLE|DFES|\bBTS[A-Z]\b', g['name'], re.I) and TOWNS:
        t = min(TOWNS, key=lambda t: (t['lat'] - g['lat']) ** 2 + (t['lng'] - g['lng']) ** 2)
        return 'Near ' + t['n'] + ' (DFES portable)'
    return nice_name(g['name']).title()

def nice_name(n):
    n = n.replace('_', ' ').strip()
    for junk in (' AWS', ' Aero', ' Airport', ' (DPIRD)', ' Comparison'):
        if n.lower().endswith(junk.lower()):
            n = n[: -len(junk)]
    return n.upper()

# ---------------------------------------------------------------- base map
def rings(geom):
    polys = geom['coordinates'] if geom['type'] == 'MultiPolygon' else [geom['coordinates']]
    for poly in polys:
        for ring in poly:
            yield ring

def draw_poly(dr, geom, fill=None, outline=None, width=1, s=1.0):
    for k, ring in enumerate(rings(geom)):
        pts = [tuple(c * s for c in to_px(lat, lng)) for lng, lat in ring]
        if len(pts) > 2:
            dr.polygon(pts, fill=fill if k == 0 or fill is None else fill)

def build_base(gauges, states):
    """Land, sea, borders and the rain field, at full base resolution."""
    sea, land, wa_land = (11, 26, 32), SURFACE, (27, 58, 69)
    base = Image.new('RGB', (BW, BH), sea)
    dr = ImageDraw.Draw(base)
    for name, g in states.items():
        if name in ('Western Australia', 'Northern Territory', 'South Australia'):
            for ring in rings(g):
                pts = [to_px(lat, lng) for lng, lat in ring]
                if len(pts) > 2: dr.polygon(pts, fill=wa_land if name == 'Western Australia' else land)
    # WA land mask (for the rain field)
    mask = Image.new('L', (BW, BH), 0)
    md = ImageDraw.Draw(mask)
    for ring in rings(states['Western Australia']):
        pts = [to_px(lat, lng) for lng, lat in ring]
        if len(pts) > 2: md.polygon(pts, fill=255)

    # rain field on a quarter-resolution grid
    q = 4
    gw, gh = BW // q, BH // q
    xs = LNG0 + (np.arange(gw) + 0.5) * q / PPD
    ys = np.array([lat_of((j + 0.5) * q) for j in range(gh)])
    LNG, LAT = np.meshgrid(xs, ys)
    keep = (LNG > 112) & (LNG < 129.6) & (LAT < -13) & (LAT > -35.6)
    glat = np.array([g['lat'] for g in gauges]); glng = np.array([g['lng'] for g in gauges]); gmm = np.array([g['v'] for g in gauges])
    c0 = math.cos(math.radians(-25))
    tree = cKDTree(np.c_[glng * c0, glat])
    qpts = np.c_[LNG[keep] * c0, LAT[keep]]
    d, idx = tree.query(qpts, k=16, distance_upper_bound=max(1.2, K['cover'][1] + 0.3))
    valid = np.isfinite(d)
    idx = np.where(valid, idx, 0)
    sig = K['sig']
    if K['floor'] is None or K.get('smooth'):   # temperature and wind: smooth surface, no bullseyes round each station
        w = np.where(valid, 1.0 / (d ** 2 + sig ** 2) ** 1.5, 0.0)
    else:                                       # rain: local, so showers stay where they fell
        w = np.where(valid, np.exp(-(d ** 2) / (2 * sig ** 2)) / (d + 0.03), 0.0)
    val = (w * gmm[idx]).sum(1) / np.maximum(w.sum(1), 1e-9)
    dmin = np.where(valid[:, 0], d[:, 0], 9)
    c_in, c_out = K['cover']
    cover = np.clip((c_out - dmin) / (c_out - c_in), 0, 1)
    cover = cover * cover * (3 - 2 * cover)
    field = np.zeros(LNG.shape); field[keep] = val
    cov = np.zeros(LNG.shape); cov[keep] = cover

    rgba = colourise(field, cov)
    fimg = Image.fromarray(rgba, 'RGBA').filter(ImageFilter.GaussianBlur(1.2)).resize((BW, BH), Image.BICUBIC)
    a = np.array(fimg.split()[3], dtype=np.float32) * (np.array(mask, dtype=np.float32) / 255)
    fimg.putalpha(Image.fromarray(a.astype(np.uint8)))
    base = base.convert('RGBA'); base.alpha_composite(fimg)

    # borders on top: coast + state lines
    dr = ImageDraw.Draw(base)
    for name, g in states.items():
        if name not in ('Western Australia', 'Northern Territory', 'South Australia'): continue
        for ring in rings(g):
            pts = [to_px(lat, lng) for lng, lat in ring]
            if len(pts) > 2: dr.line(pts + [pts[0]], fill=(84, 122, 134, 255), width=3)
    return base.convert('RGB')

def colourise(v, cov):
    st = K['stops']
    out = np.zeros(v.shape + (4,), np.float32)
    xs = [x[0] for x in st]
    for ch in range(4):
        out[..., ch] = np.interp(v, xs, [x[1][ch] for x in st])
    out[..., 3] *= cov
    if K['floor'] is not None: out[v < K['floor'], 3] = 0
    return out.clip(0, 255).astype(np.uint8)

# ---------------------------------------------------------------- picking the story
def score(g): return -K['order'] * g['v']   # higher = more extreme (wettest, hottest, coldest, windiest)

def pick_regions(gauges, towns, n=3):
    ranked = sorted(gauges, key=lambda g: -score(g))
    if K['floor'] is not None:   # rain: only places that actually got rain
        top = ranked[0]['v']
        ranked = [g for g in ranked if g['v'] >= max(2, 0.2 * top)]
    else:
        lim = K.get('near', 3)   # only places close to the extreme: within 3° (temps) or 15 km/h (gusts)
        ranked = [g for g in ranked if score(g) >= score(ranked[0]) - lim][:40]
    regions, used = [], []
    for g in ranked:
        if any(dist(g, u) < (2.6 if K['floor'] is not None and not K.get('smooth') else 4.0) for u in used): continue
        used.append(g)
        members = sorted([x for x in gauges if dist(x, g) < 2.2], key=lambda x: -score(x))
        labels = []
        for x in members:
            if K['floor'] is not None and x['v'] < max(1, 0.25 * g['v']): break
            if all(dist(x, l) > 0.55 for l in labels): labels.append(x)
            if len(labels) == 3: break
        clat = sum(l['lat'] for l in labels) / len(labels); clng = sum(l['lng'] for l in labels) / len(labels)
        town = min(towns, key=lambda t: (t['lat'] - g['lat']) ** 2 + ((t['lng'] - g['lng']) * 0.9) ** 2)
        span = max(4.2, 1.9 * max([abs(l['lng'] - clng) for l in labels] + [abs(l['lat'] - clat) * 0.56 for l in labels]) + 3.2)
        regions.append({'lat': clat - 0.06 * span, 'lng': clng, 'span': span, 'labels': labels, 'tag': 'Around ' + town['n']})
        if len(regions) == n: break
    return regions

def dist(a, b): return math.hypot(a['lat'] - b['lat'], (a['lng'] - b['lng']) * math.cos(math.radians(a['lat'])))

# ---------------------------------------------------------------- frame drawing
class Cam:
    def __init__(self, lat, lng, span): self.lat, self.lng, self.span = lat, lng, span
def lerp(a, b, t): return a + (b - a) * t
def ease(t): t = max(0.0, min(1.0, t)); return t * t * (3 - 2 * t)
def cam_mix(a, b, t):
    t = ease(t)
    return Cam(lerp(a.lat, b.lat, t), lerp(a.lng, b.lng, t), math.exp(lerp(math.log(a.span), math.log(b.span), t)))

def view(bases, cam):
    """Crop the base map around the camera and scale it to the frame."""
    bw = cam.span * PPD
    level = 0
    while level + 1 < len(bases) and bw / (2 ** (level + 1)) >= W: level += 1
    img, f = bases[level], 2 ** level
    cx, cy = to_px(cam.lat, cam.lng)
    bwl, bhl = bw / f, bw * H / W / f
    box = (cx / f - bwl / 2, cy / f - bhl / 2, cx / f + bwl / 2, cy / f + bhl / 2)
    frame = img.transform((W, H), Image.EXTENT, box, Image.BILINEAR)
    def proj(lat, lng):
        x, y = to_px(lat, lng)
        return ((x / f - box[0]) / bwl * W, (y / f - box[1]) / bhl * H)
    return frame, proj

def text_box(dr, xy, text, fnt, fg, bg, pad=(14, 8), anchor='lt', radius=None, outline=None):
    l, t, r, b = dr.textbbox((0, 0), text, font=fnt)
    w, h = r - l + 2 * pad[0], b - t + 2 * pad[1]
    x, y = xy
    if anchor[0] == 'm': x -= w / 2
    if anchor[0] == 'r': x -= w
    if anchor[1] == 'b': y -= h
    dr.rounded_rectangle([x, y, x + w, y + h], radius=h / 2 if radius is None else radius, fill=bg, outline=outline, width=2 if outline else 0)
    dr.text((x + pad[0] - l, y + pad[1] - t), text, font=fnt, fill=fg)
    return (x, y, x + w, y + h)

def draw_gauges(dr, proj, gauges, r=5):
    for g in gauges:
        x, y = proj(g['lat'], g['lng'])
        if -10 < x < W + 10 and -10 < y < H + 10:
            col = TEXT if K['floor'] is None or g['v'] >= 1 else (110, 140, 150)
            dr.ellipse([x - r, y - r, x + r, y + r], outline=col, width=2)


def draw_label(img, proj, g, pop):
    """A card like the website's point panel: the total big, the gauge name underneath."""
    if pop <= 0: return
    dr = ImageDraw.Draw(img)
    x, y = proj(g['lat'], g['lng'])
    s = 0.6 + 0.4 * ease(pop)
    fv, fn = font(700, int(52 * s)), font(500, int(24 * s))
    name, val = label_name(g), K['fmt'](g['v'])
    wv = dr.textlength(val, font=fv); wn = dr.textlength(name, font=fn)
    w, h = max(wv, wn) + 36 * s, 96 * s
    bx, by = x - w / 2, y - 26 * s - h
    dr.rounded_rectangle([bx, by, bx + w, by + h], radius=14 * s, fill=SURFACE, outline=ACCENT, width=2)
    dr.polygon([(x - 10 * s, by + h - 1), (x + 10 * s, by + h - 1), (x, by + h + 14 * s)], fill=ACCENT)
    dr.text((x, by + 10 * s), val, font=fv, fill=TEXT, anchor='mt')
    dr.text((x, by + h - 12 * s), name, font=fn, fill=MUTED, anchor='mb')
    dr.ellipse([x - 9, y - 9, x + 9, y + 9], fill=ACCENT, outline=(255, 255, 255), width=3)

TITLE, SRC = "Yesterday's rain", 'BoM, DPIRD, DWER'
def header(img, period_text, tag=None):
    grad = Image.new('L', (1, 380)); grad.putdata([int(235 * (1 - i / 380) ** 1.3) for i in range(380)])
    shade = Image.new('RGBA', (W, 380), BG + (255,)); shade.putalpha(grad.resize((W, 380)))
    img.alpha_composite(shade, (0, 0))
    dr = ImageDraw.Draw(img)
    dr.text((48, 118), TITLE, font=font(700, 92), fill=TEXT)
    dr.text((52, 232), period_text, font=font(500, 30), fill=MUTED)
    if tag:
        text_box(dr, (48, 286), tag, font(600, 32), ON_ACCENT, ACCENT, pad=(20, 8))

def caption(img, text, alpha=1.0, y=None):
    if alpha <= 0: return
    dr = ImageDraw.Draw(img)
    f = font(700, 76)
    l, t, r, b = dr.textbbox((0, 0), text, font=f)
    w, h = r - l + 80, b - t + 44
    x, y = (W - w) / 2, (H - 520 if y is None else y)
    dr.rounded_rectangle([x, y, x + w, y + h], radius=h / 2, fill=SURFACE + (240,), outline=LINE, width=2)
    dr.text((x + 40 - l, y + 22 - t), text, font=f, fill=TEXT)

def legend(img):
    dr = ImageDraw.Draw(img)
    x0, y0, bw, bh = 48, H - 262, W - 96, 20
    vals = K['legend']
    seg = bw / (len(vals) - 1)
    for i in range(len(vals) - 1):
        a = colourise(np.array([[vals[i] + 0.01]]), np.ones((1, 1)))[0, 0]
        dr.rectangle([x0 + i * seg, y0, x0 + (i + 1) * seg, y0 + bh], fill=tuple(int(c) for c in a[:3]))
    for i, v in enumerate(vals):
        dr.text((x0 + i * seg, y0 + bh + 8), str(v), font=font(500, 22), fill=MUTED, anchor='mt')
    dr.text((x0 + bw, y0 - 10), K['unit'], font=font(500, 22), fill=MUTED, anchor='rb')

def logo_img(height):
    if LOGO is None: return None
    k = ('logo', height)
    if k not in _FC:
        _FC[k] = LOGO.resize((max(1, round(LOGO.width * height / LOGO.height)), height), Image.LANCZOS)
    return _FC[k]

def footer(img):
    dr = ImageDraw.Draw(img)
    dr.rectangle([0, H - 190, W, H], fill=BG + (235,))
    dr.line([0, H - 190, W, H - 190], fill=LINE, width=2)
    lg = logo_img(96)
    if lg is not None:
        img.alpha_composite(lg, (48, H - 143))
        tx = 48 + lg.width + 28
    else:
        dr.text((48, H - 140), 'West WX Watchers', font=font(700, 40), fill=TEXT); tx = None
    if tx:
        dr.text((tx, H - 128), 'westweatherwatchers.com', font=font(600, 30), fill=ACCENT)
        dr.text((tx, H - 84), 'Data: ' + SRC, font=font(500, 24), fill=MUTED)
    else:
        dr.text((48, H - 88), 'westweatherwatchers.com · Data: ' + SRC, font=font(500, 24), fill=MUTED)

# ---------------------------------------------------------------- main
def main():
    global LOGO, TITLE, SRC, K
    ap = argparse.ArgumentParser()
    ap.add_argument('data'); ap.add_argument('out')
    ap.add_argument('--caption', help='big caption text; default picked from the values')
    ap.add_argument('--logo', help='logo PNG (light, transparent background)')
    a = ap.parse_args()
    if a.logo: LOGO = Image.open(a.logo).convert('RGBA')
    doc, gauges = read_data(a.data)
    if not gauges: sys.exit('No stations with values in the data.')
    kind = doc.get('kind', 'rain'); K = KINDS[kind]
    TITLE, period, SRC = doc['title'], doc['sub'], doc.get('src', 'BoM, DPIRD, DWER')
    states = json.load(open(os.path.join(HERE, 'aus_states.json')))
    towns = json.load(open(os.path.join(HERE, 'towns.json')))
    TOWNS[:] = towns
    top = sorted(gauges, key=lambda g: -score(g))
    cap = (a.caption or '').strip() or caption_for(kind, gauges, int(doc.get('days', 1)))
    badge = badge_for(kind, gauges)
    print(f'{kind}: {len(gauges)} stations, top {top[0]["name"]} {top[0]["v"]}. Building the map...', flush=True)

    base = build_base(gauges, states)
    bases = [base]
    while bases[-1].width > 1500: bases.append(bases[-1].resize((bases[-1].width // 2, bases[-1].height // 2), Image.LANCZOS))
    regions = pick_regions(gauges, towns)

    full = Cam(-25.3, 121.0, 16.8)
    shots = [('intro', full, None, 3.0)]
    for r in regions: shots.append(('region', Cam(r['lat'], r['lng'], r['span']), r, 4.0))
    shots.append(('summary', full, None, 4.5)); shots.append(('end', full, None, 2.0))
    MOVE = 1.0

    ff = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                           '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '20', '-preset', 'medium', '-movflags', '+faststart', a.out],
                          stdin=subprocess.PIPE)
    prev = full
    for kind, cam, r, dur in shots:
        nfr = int(dur * FPS)
        for i in range(nfr):
            t = i / FPS
            c = cam_mix(prev, cam, t / MOVE) if kind in ('region', 'summary') else cam
            frame, proj = view(bases, c)
            frame = frame.convert('RGBA')
            dr = ImageDraw.Draw(frame)
            draw_gauges(dr, proj, gauges, r=4 if c.span > 9 else 6)
            if kind == 'region':
                for k, g in enumerate(r['labels']):
                    draw_label(frame, proj, g, (t - MOVE - 0.15 - 0.35 * k) / 0.3)
            header(frame, period, r['tag'] if kind == 'region' and t > 0.4 else None)
            if kind == 'summary' and t > 0.8:
                dr = ImageDraw.Draw(frame); y = 350
                for k, g in enumerate(top[:3]):
                    p = ease((t - 0.8 - 0.25 * k) / 0.3)
                    if p <= 0: continue
                    fv = font(700, 78); txt = K['fmt'](g['v'])
                    dx = -40 * (1 - p)
                    dr.text((48 + dx, y), txt, font=fv, fill=(255, 225, 70))
                    tw = dr.textlength(txt, font=fv)
                    dr.text((72 + tw + dx, y + 36), label_name(g), font=font(500, 32), fill=TEXT)
                    y += 98
                if t > 1.8:
                    text_box(dr, (48, y + 14), badge, font(600, 32), ON_ACCENT, ACCENT, pad=(20, 8))
            if kind != 'end':
                caption(frame, cap, 1.0, None if kind == 'region' else 820)
                legend(frame)
            else:
                dk = Image.new('RGBA', (W, H), BG + (int(235 * ease(t / 0.5)),)); frame.alpha_composite(dk)
                dr = ImageDraw.Draw(frame)
                lg = logo_img(300)
                if lg is not None:
                    frame.alpha_composite(lg, (int((W - lg.width) / 2), int(H / 2 - 260)))
                    dr.text((W / 2, H / 2 + 110), 'westweatherwatchers.com', font=font(600, 46), fill=ACCENT, anchor='mm')
                else:
                    dr.text((W / 2, H / 2 - 40), 'West WX Watchers', font=font(700, 84), fill=TEXT, anchor='mm')
                    dr.text((W / 2, H / 2 + 50), 'westweatherwatchers.com', font=font(600, 46), fill=ACCENT, anchor='mm')
            if kind != 'end' or LOGO is None or t < 0.3: footer(frame)
            ff.stdin.write(frame.convert('RGB').tobytes())
        prev = cam
    ff.stdin.close(); ff.wait()
    print('Wrote', a.out, flush=True)

if __name__ == '__main__':
    main()

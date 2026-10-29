#!/usr/bin/env python3
"""
West WX Watchers — weather story video (1080x1920, 30 fps): rain, max/min/current temperature or gusts.
Light "contour map" look in the website's colours: banded colour areas with thin edges, white cards for the
title, labels, top list and key, and the logo in its own colours.

  python3 wxvideo.py data.json out.mp4 [--caption "..."] [--regions 0-5] [--top 3-10] [--logo logo.png]

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
# Website theme (light): the outlook page's colours
BG, SURFACE, TEXT, MUTED, LINE, ACCENT, ON_ACCENT = (238, 244, 245), (255, 255, 255), (14, 42, 51), (74, 100, 112), (201, 216, 220), (14, 124, 134), (255, 255, 255)
SEA, LAND, WA_LAND, COAST = (206, 225, 230), (229, 233, 229), (247, 247, 242), (128, 152, 160)
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
# Colour bands (lower edge of each band, colour). Rain: the rainfall page's own scale.
RAIN_BANDS = [(0.2, (205, 208, 210)), (1, (178, 206, 240)), (2, (122, 172, 236)), (5, (58, 118, 214)), (10, (30, 140, 170)),
              (15, (38, 168, 108)), (25, (108, 196, 86)), (35, (188, 212, 58)), (50, (245, 200, 50)), (75, (245, 140, 40)),
              (100, (225, 70, 40)), (150, (170, 30, 50)), (200, (120, 30, 120))]
def bands_from(stops, edges):
    xs = [s[0] for s in stops]
    return [(e, tuple(int(round(np.interp(e + 0.001, xs, [s[1][ch] for s in stops]))) for ch in range(3))) for e in edges]
KINDS['rain']['bands'] = RAIN_BANDS
KINDS['rain']['legend'] = [0.2, 1, 2, 5, 10, 15, 25, 35, 50, 75, 100, 150, 200]
for _k in ('tmax', 'temp', 'tmin'):
    KINDS[_k]['bands'] = bands_from(TEMP_STOPS, list(range(-4, 50, 2)))
    KINDS[_k]['legend'] = list(range(0, 48, 4))
KINDS['gust']['bands'] = bands_from(GUST_STOPS, [20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 130])
KINDS['gust']['legend'] = [20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 130]
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

def field_values(gauges, LNG, LAT):
    glat = np.array([g['lat'] for g in gauges]); glng = np.array([g['lng'] for g in gauges]); gv = np.array([g['v'] for g in gauges])
    c0 = math.cos(math.radians(-25))
    tree = cKDTree(np.c_[glng * c0, glat])
    d, idx = tree.query(np.c_[LNG.ravel() * c0, LAT.ravel()], k=16, distance_upper_bound=max(1.2, K['cover'][1] + 0.3))
    valid = np.isfinite(d); idx = np.where(valid, idx, 0); sig = K['sig']
    if K['floor'] is None or K.get('smooth'):   # temperature and wind: smooth surface
        w = np.where(valid, 1.0 / (d ** 2 + sig ** 2) ** 1.5, 0.0)
    else:                                       # rain: local, so showers stay where they fell
        w = np.where(valid, np.exp(-(d ** 2) / (2 * sig ** 2)) / (d + 0.03), 0.0)
    val = (w * gv[idx]).sum(1) / np.maximum(w.sum(1), 1e-9)
    dmin = np.where(valid[:, 0], d[:, 0], 9)
    return val.reshape(LNG.shape).astype(np.float32), dmin.reshape(LNG.shape).astype(np.float32)

def build_base(gauges, states):
    """Light map with the banded colour field and thin band edges, at full base resolution."""
    base = Image.new('RGB', (BW, BH), SEA)
    dr = ImageDraw.Draw(base)
    for name, g in states.items():
        if name in ('Western Australia', 'Northern Territory', 'South Australia'):
            for ring in rings(g):
                pts = [to_px(lat, lng) for lng, lat in ring]
                if len(pts) > 2: dr.polygon(pts, fill=WA_LAND if name == 'Western Australia' else LAND)
    mask = Image.new('L', (BW, BH), 0); md = ImageDraw.Draw(mask)
    for ring in rings(states['Western Australia']):
        pts = [to_px(lat, lng) for lng, lat in ring]
        if len(pts) > 2: md.polygon(pts, fill=255)
    # the field over WA's box only: coarse grid, then smoothly up to full resolution
    X0, Y0 = [int(v) for v in to_px(-13.0, 112.0)]; X1, Y1 = [int(v) for v in to_px(-35.7, 129.7)]
    q = 4; gw, gh = (X1 - X0) // q + 2, (Y1 - Y0) // q + 2
    xs = LNG0 + (X0 + np.arange(gw) * q) / PPD
    ys = np.array([lat_of(Y0 + j * q) for j in range(gh)])
    LNG, LAT = np.meshgrid(xs, ys)
    val, dmin = field_values(gauges, LNG, LAT)
    from scipy.ndimage import map_coordinates
    jj, ii = np.mgrid[0:Y1 - Y0, 0:X1 - X0].astype(np.float32) / q
    V = map_coordinates(val, [jj, ii], order=1)
    D = map_coordinates(dmin, [jj, ii], order=1)
    del jj, ii
    thr = np.array([b[0] for b in K['bands']], np.float32)
    cols = np.array([b[1] for b in K['bands']], np.uint8)
    idx = np.digitize(V, thr) - 1
    m = np.array(mask.crop((X0, Y0, X1, Y1)), dtype=np.uint8) > 127
    c_in, c_out = K['cover']
    ok = (idx >= 0) & m & ((D < (c_in + c_out) / 2) if (K['floor'] is not None and not K.get('smooth')) else (D < 6))
    idx = np.where(ok, idx, -1).astype(np.int16)
    rgba = np.zeros(idx.shape + (4,), np.uint8)
    rgba[ok, :3] = cols[idx[ok]]; rgba[ok, 3] = 230
    edge = np.zeros(idx.shape, bool)
    edge[:, 1:] |= idx[:, 1:] != idx[:, :-1]; edge[1:, :] |= idx[1:, :] != idx[:-1, :]
    edge[:, :-1] |= edge[:, 1:]; edge[:-1, :] |= edge[1:, :]          # 2 px lines
    edge &= m
    rgba[edge] = (60, 80, 86, 140)
    base = base.convert('RGBA')
    base.alpha_composite(Image.fromarray(rgba, 'RGBA'), (X0, Y0))
    dr = ImageDraw.Draw(base)
    for name, g in states.items():
        if name not in ('Western Australia', 'Northern Territory', 'South Australia'): continue
        for ring in rings(g):
            pts = [to_px(lat, lng) for lng, lat in ring]
            if len(pts) > 2: dr.line(pts + [pts[0]], fill=COAST + (255,), width=3)
    return base.convert('RGB')

def band_colour(v):
    c = None
    for t, col in K['bands']:
        if v >= t: c = col
    return c or K['bands'][0][1]

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

def card(img, box, r=26, fill=SURFACE, a=245):
    layer = Image.new('RGBA', img.size, (0, 0, 0, 0)); d = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = box
    d.rounded_rectangle([x0 + 3, y0 + 6, x1 + 3, y1 + 6], radius=r, fill=(14, 42, 51, 40))   # soft shadow
    d.rounded_rectangle(box, radius=r, fill=fill + (a,), outline=LINE + (255,), width=2)
    img.alpha_composite(layer)

def draw_gauges(dr, proj, gauges, r=4):
    for g in gauges:
        x, y = proj(g['lat'], g['lng'])
        if -10 < x < W + 10 and -10 < y < H + 10:
            dr.ellipse([x - r, y - r, x + r, y + r], fill=(70, 92, 100), outline=(255, 255, 255), width=1)

def draw_label(img, proj, g, pop, taken=None):
    if pop <= 0: return
    dr = ImageDraw.Draw(img)
    x, y = proj(g['lat'], g['lng'])
    s = 0.6 + 0.4 * ease(pop)
    fv, fn = font(700, int(50 * s)), font(500, int(23 * s))
    name, val = label_name(g), K['fmt'](g['v'])
    w = max(dr.textlength(val, font=fv), dr.textlength(name, font=fn)) + 40 * s
    h = 96 * s; bx, by = x - w / 2, y - 30 * s - h
    below = False
    if taken is not None:
        hit = lambda a, b: a[0] < b[2] + 8 and b[0] < a[2] + 8 and a[1] < b[3] + 8 and b[1] < a[3] + 8
        if any(hit((bx, by, bx + w, by + h), t) for t in taken):
            by = y + 30 * s; below = True
            if any(hit((bx, by, bx + w, by + h), t) for t in taken):   # still clashes: push sideways
                bx = max(t[2] for t in taken) + 12; by = y - h / 2; below = None
        taken.append((bx, by, bx + w, by + h))
    x_mid = bx + w / 2
    sw = 12 * s
    dr.rounded_rectangle([bx, by, bx + w, by + h], radius=16 * s, fill=SURFACE, outline=LINE, width=2)
    dr.rounded_rectangle([bx, by, bx + sw, by + h], radius=16 * s, fill=band_colour(g['v']))   # colour tab = its band
    dr.rectangle([bx + sw / 2, by, bx + sw, by + h], fill=band_colour(g['v']))
    dr.text((x_mid + sw / 2, by + 10 * s), val, font=fv, fill=TEXT, anchor='mt')
    dr.text((x_mid + sw / 2, by + h - 12 * s), name, font=fn, fill=MUTED, anchor='mb')
    if below is False: dr.line([x, by + h, x, y - 8], fill=ACCENT, width=3)
    elif below: dr.line([x, by, x, y + 8], fill=ACCENT, width=3)
    else: dr.line([bx, by + h / 2, x + 8, y], fill=ACCENT, width=3)
    dr.ellipse([x - 8, y - 8, x + 8, y + 8], fill=ACCENT, outline=(255, 255, 255), width=3)

def logo_img(height):
    if LOGO is None: return None
    k = ('logo', height)
    if k not in _FC: _FC[k] = LOGO.resize((max(1, round(LOGO.width * height / LOGO.height)), height), Image.LANCZOS)
    return _FC[k]

TITLE, SRC = "Yesterday's rain", 'BoM, DPIRD, DWER'
def top_card(img, sub, cap, tag=None, slide=1.0):
    y0 = int(36 - 280 * (1 - ease(slide)))
    card(img, (30, y0, W - 30, y0 + 238))
    dr = ImageDraw.Draw(img)
    lg = logo_img(66)
    if lg is not None: img.alpha_composite(lg, (W - 58 - lg.width, y0 + 24))
    dr.text((60, y0 + 30), TITLE, font=font(700, 62), fill=TEXT)
    dr.text((62, y0 + 112), sub, font=font(500, 25), fill=MUTED)
    b = text_box(dr, (60, y0 + 166), cap, font(700, 28), ON_ACCENT, ACCENT, pad=(22, 9))
    if tag: text_box(dr, (b[2] + 14, y0 + 166), tag, font(600, 26), ACCENT, SURFACE, pad=(20, 10), outline=ACCENT)

def bottom_card(img, show_logo_text=True):
    y0 = H - 236
    card(img, (30, y0, W - 30, H - 36))
    dr = ImageDraw.Draw(img)
    vals = K['legend']; x0, bw, by, bh = 60, W - 120, y0 + 46, 26
    seg = bw / len(vals)
    for i, v in enumerate(vals):
        dr.rectangle([x0 + i * seg, by, x0 + (i + 1) * seg - 3, by + bh], fill=band_colour(v))
        lab = (f"{v:g}") if K['unit'] != '°C' else f"{v:g}°"
        dr.text((x0 + i * seg, by + bh + 8), lab, font=font(500, 20), fill=MUTED)
    dr.text((x0, y0 + 16), K['unit'], font=font(600, 20), fill=MUTED)
    dr.line([60, y0 + 124, W - 60, y0 + 124], fill=LINE, width=2)
    dr.text((60, y0 + 140), 'westweatherwatchers.com', font=font(700, 30), fill=ACCENT)
    dr.text((W - 60, y0 + 146), 'Data: ' + SRC, font=font(500, 22), fill=MUTED, anchor='ra')

def summary_card(img, rows, badge, t):
    n = len(rows); rh = 92 if n <= 5 else 70
    y0 = 310; h = 70 + n * rh + 80
    card(img, (30, y0, W - 30, y0 + h))
    dr = ImageDraw.Draw(img)
    dr.text((60, y0 + 26), 'Top ' + str(n), font=font(700, 34), fill=TEXT)
    fv, fn = font(700, 46 if rh > 80 else 38), font(600, 32 if rh > 80 else 28)
    for k, g in enumerate(rows):
        p = ease((t - 0.2 - 0.12 * k) / 0.3)
        if p <= 0: continue
        y = y0 + 76 + k * rh; dx = -30 * (1 - p)
        dr.rounded_rectangle([60 + dx, y, W - 60 + dx, y + rh - 10], radius=14, fill=(238, 244, 245) if k % 2 == 0 else SURFACE)
        cx, cy = 100 + dx, y + (rh - 10) / 2
        dr.ellipse([cx - 22, cy - 22, cx + 22, cy + 22], fill=band_colour(g['v']))
        bc = band_colour(g['v'])
        dr.text((cx, cy), str(k + 1), font=font(700, 24), fill=TEXT if sum(bc) > 420 else (255, 255, 255), anchor='mm')
        nm = label_name(g)
        while dr.textlength(nm, font=fn) > 560 and len(nm) > 6: nm = nm[:-1]
        dr.text((140 + dx, cy), nm, font=fn, fill=TEXT, anchor='lm')
        dr.text((W - 84 + dx, cy), K['fmt'](g['v']), font=fv, fill=ACCENT, anchor='rm')
    if t > 0.4 + 0.12 * n:
        text_box(dr, (60, y0 + 76 + n * rh + 6), badge, font(600, 28), ON_ACCENT, ACCENT, pad=(20, 9))

# ---------------------------------------------------------------- main
def main():
    global LOGO, TITLE, SRC, K
    ap = argparse.ArgumentParser()
    ap.add_argument('data'); ap.add_argument('out')
    ap.add_argument('--caption', help='short caption; default picked from the values')
    ap.add_argument('--regions', type=int, default=3, help='zoom-in stops, 0-5')
    ap.add_argument('--top', type=int, default=3, help='how many in the top list, 3-10')
    ap.add_argument('--logo', help='logo PNG (its own colours, transparent background)')
    a = ap.parse_args()
    lp = a.logo or os.path.join(HERE, 'logo.png')
    if os.path.exists(lp): LOGO = Image.open(lp).convert('RGBA')
    doc, gauges = read_data(a.data)
    if not gauges: sys.exit('No stations with values in the data.')
    kind = doc.get('kind', 'rain'); K = KINDS[kind]
    TITLE, period, SRC = doc['title'], doc['sub'], doc.get('src', 'BoM, DPIRD, DWER')
    states = json.load(open(os.path.join(HERE, 'aus_states.json')))
    towns = json.load(open(os.path.join(HERE, 'towns.json'))); TOWNS[:] = towns
    ranked = sorted(gauges, key=lambda g: -score(g))
    if K['floor'] is not None: ranked = [g for g in ranked if g['v'] >= 0.2] or ranked
    ntop = max(3, min(10, a.top)); nreg = max(0, min(5, a.regions))
    cap = (a.caption or '').strip() or caption_for(kind, gauges, int(doc.get('days', 1)))
    badge = badge_for(kind, gauges)
    print(f'{kind}: {len(gauges)} stations, top {ranked[0]["name"]} {ranked[0]["v"]}; {nreg} zoom stops, top {ntop}. Building the map...', flush=True)
    base = build_base(gauges, states)
    bases = [base]
    while bases[-1].width > 1500: bases.append(bases[-1].resize((bases[-1].width // 2, bases[-1].height // 2), Image.LANCZOS))
    regions = pick_regions(gauges, towns, nreg) if nreg else []

    full = Cam(-25.0, 121.0, 18.5)
    shots = [('intro', full, None, 3.0)]
    for r in regions: shots.append(('region', Cam(r['lat'] - 0.02 * r['span'], r['lng'], r['span']), r, 4.0))
    shots.append(('summary', full, None, 3.0 + 0.25 * ntop)); shots.append(('end', full, None, 2.2))
    MOVE = 1.1
    ff = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                           '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '20', '-preset', 'medium', '-movflags', '+faststart', a.out],
                          stdin=subprocess.PIPE)
    prev = full; T = 0.0
    for kind_s, cam, r, dur in shots:
        for i in range(int(dur * FPS)):
            t = i / FPS
            c = cam_mix(prev, cam, t / MOVE) if kind_s in ('region', 'summary') else cam
            frame, proj = view(bases, c)
            frame = frame.convert('RGBA')
            dr = ImageDraw.Draw(frame)
            draw_gauges(dr, proj, gauges, r=3 if c.span > 9 else 5)
            if kind_s == 'region':
                taken = []
                for k, g in enumerate(r['labels']):
                    draw_label(frame, proj, g, (t - MOVE - 0.1 - 0.3 * k) / 0.3, taken)
            if kind_s != 'end':
                top_card(frame, period, cap, r['tag'] if kind_s == 'region' and t > 0.4 else None, slide=min(1.0, (T + t) / 0.6))
                if kind_s == 'summary' and t > MOVE * 0.6: summary_card(frame, ranked[:ntop], badge, t - MOVE * 0.6)
                bottom_card(frame)
            else:
                fade = ease(t / 0.5)
                frame.alpha_composite(Image.new('RGBA', (W, H), BG + (int(250 * fade),)))
                dr = ImageDraw.Draw(frame)
                lg = logo_img(300)
                if lg is not None: frame.alpha_composite(lg, (int((W - lg.width) / 2), int(H / 2 - 240)))
                else: dr.text((W / 2, H / 2 - 40), 'West WX Watchers', font=font(700, 84), fill=TEXT, anchor='mm')
                dr.text((W / 2, H / 2 + 130), 'westweatherwatchers.com', font=font(700, 48), fill=ACCENT, anchor='mm')
                dr.text((W / 2, H / 2 + 196), 'Data: ' + SRC, font=font(500, 28), fill=MUTED, anchor='mm')
            ff.stdin.write(frame.convert('RGB').tobytes())
        T += dur; prev = cam
    ff.stdin.close(); ff.wait()
    print('Wrote', a.out, flush=True)

if __name__ == '__main__':
    main()

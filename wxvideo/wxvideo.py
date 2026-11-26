#!/usr/bin/env python3
"""
West WX Watchers — weather story video (1080x1920, 30 fps): rain, max/min/current temperature or gusts.
Light "contour map" look in the website's colours: banded colour areas with thin edges, white cards for the
title, labels, top list and key, and the logo in its own colours.

  python3 wxvideo.py data.json out.mp4 [--caption "..."] [--regions 0-5] [--top 3-10] [--logo logo.png] [--style map|3d]

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
CLIP = None   # district rings to colour (set from the data, when a region is picked)

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
# More from Live Obs (Nov 2026): feels like, wind, dew point, humidity, Delta T, pressure, soil, evapotranspiration
def _scale(stops, edges, legend, unit, fmt, order=-1, word='station', sig=0.5, cover=(2.5, 4.0), near=3):
    return dict(stops=stops, bands=bands_from(stops, edges), legend=legend, unit=unit, fmt=fmt, sig=sig, cover=cover, floor=None, order=order, word=word, near=near)
WIND_STOPS = [(0, (170, 190, 210, 215)), (10, (90, 170, 210, 215)), (20, (80, 200, 140, 215)), (30, (200, 220, 70, 220)), (40, (250, 170, 50, 225)), (50, (235, 80, 40, 235)), (65, (160, 20, 90, 240))]
DEW_STOPS = [(-5, (150, 110, 70, 215)), (0, (190, 150, 90, 215)), (5, (225, 205, 140, 215)), (10, (170, 215, 150, 215)), (15, (80, 190, 120, 215)), (20, (40, 160, 150, 220)), (25, (30, 110, 175, 230))]
RH_STOPS = [(0, (160, 100, 50, 215)), (20, (215, 160, 90, 215)), (40, (235, 215, 140, 215)), (60, (150, 210, 160, 215)), (80, (70, 170, 200, 220)), (100, (40, 90, 180, 230))]
DT_STOPS = [(0, (44, 127, 184, 215)), (2, (65, 182, 196, 215)), (4, (127, 205, 187, 215)), (6, (199, 233, 180, 215)), (8, (246, 226, 127, 220)), (10, (246, 165, 74, 225)), (12, (232, 88, 44, 230)), (15, (178, 24, 43, 235))]
PRES_STOPS = [(985, (110, 40, 150, 230)), (995, (60, 110, 210, 220)), (1005, (70, 180, 200, 215)), (1012, (150, 210, 120, 215)), (1018, (240, 220, 90, 220)), (1025, (245, 150, 50, 225)), (1035, (210, 50, 40, 235))]
ET_STOPS = [(0, (247, 244, 232, 215)), (2, (239, 227, 184, 215)), (4, (221, 182, 90, 220)), (6, (201, 124, 42, 225)), (8, (156, 67, 30, 230)), (10, (124, 45, 26, 235)), (14, (90, 28, 20, 240))]
ETW_STOPS = [(-60, (90, 28, 20, 235)), (-30, (201, 124, 42, 225)), (-10, (230, 207, 134, 215)), (0, (214, 236, 210, 215)), (10, (159, 211, 199, 215)), (30, (78, 167, 201, 225)), (60, (44, 95, 163, 235))]
fmt_pc = lambda v: f"{v:.0f}%"; fmt_hpa = lambda v: f"{v:.0f} hPa"; fmt_dt = lambda v: f"{v:.1f}°"; fmt_et = lambda v: f"{v:.1f} mm" if abs(v) < 20 else f"{v:.0f} mm"
KINDS.update({
    'app': dict(KINDS['temp']), 'soil': dict(KINDS['temp']),
    'wind': _scale(WIND_STOPS, [0, 5, 10, 15, 20, 25, 30, 40, 50, 65], [0, 10, 20, 30, 40, 50, 65], 'km/h', fmt_g, near=10),
    'dew': _scale(DEW_STOPS, list(range(-6, 28, 2)), list(range(-4, 28, 4)), '°C', fmt_t),
    'rh': _scale(RH_STOPS, list(range(0, 101, 10)), list(range(0, 101, 20)), '%', fmt_pc, near=10),
    'dt': _scale(DT_STOPS, [0, 2, 4, 6, 8, 10, 12, 15], [0, 2, 4, 6, 8, 10, 12, 15], '°C', fmt_dt),
    'pres': _scale(PRES_STOPS, list(range(985, 1036, 3)), list(range(988, 1036, 6)), 'hPa', fmt_hpa, near=3),
    'et': _scale(ET_STOPS, [0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14], [0, 2, 4, 6, 8, 10, 12, 14], 'mm', fmt_et, near=2),
    'etw': _scale(ETW_STOPS, [-60, -45, -30, -20, -10, 0, 10, 25, 50], [-60, -30, -10, 0, 10, 25, 50], 'mm', fmt_et, near=10),
})
K = KINDS['rain']   # set in main

def read_data(path):
    doc = json.load(open(path, encoding='utf-8'))
    pts = []
    for row in doc.get('points') or []:
        name, lat, lng, v = row[:4]
        if v is None or not (-36 < lat < -13 and 112 < lng < 129.5): continue
        pts.append({'name': str(name).strip(), 'lat': float(lat), 'lng': float(lng), 'v': float(v), 'd': row[4] if len(row) > 4 else None})
    return doc, pts

def caption_for(kind, pts, days):
    vs = [p['v'] for p in pts]; hi, lo = max(vs), min(vs)
    if K['order'] != KINDS.get(kind, K)['order'] or kind not in ('rain', 'tmax', 'temp', 'tmin', 'gust'):   # the other end, or a newer kind
        v = lo if K['order'] == 1 else hi
        return ('Lowest ' if K['order'] == 1 else 'Highest ') + K['fmt'](v)
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
    if K['order'] != KINDS.get(kind, K)['order'] or kind not in ('rain', 'tmax', 'temp', 'tmin', 'gust'):
        return pl(len(pts), w)
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
    if CLIP:   # a region picked on the page: colour only its districts (rings as flat [lng, lat, lng, lat, ...])
        for r in CLIP:
            pts = [to_px(r[i + 1], r[i]) for i in range(0, len(r) - 1, 2)]
            if len(pts) > 2: md.polygon(pts, fill=255)
    else:
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
    mk = np.array(mask, dtype=np.uint8)
    mj = np.clip(Y0 + np.arange(gh) * q, 0, BH - 1); mi = np.clip(X0 + np.arange(gw) * q, 0, BW - 1)
    HF.update(val=val, m=(mk[np.ix_(mj, mi)] > 127).astype(np.float32), X0=X0, Y0=Y0, q=q)
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

def count_from():
    """Where the numbers start counting from: rain from 0, others from the middle of the pack (up to highs, down to lows)."""
    if 'c0' not in K:
        vs = sorted(x['v'] for x in STATIONS) or [0]
        K['c0'] = 0.0 if K['floor'] is not None and not K.get('smooth') else vs[len(vs) // 2]
    return K['c0']
def counted(v, t):
    return v if t is None else lerp(count_from(), v, 1 - (1 - max(0.0, min(1.0, t))) ** 3)

def draw_label(img, proj, g, pop, taken=None, count=None):
    if pop <= 0: return
    dr = ImageDraw.Draw(img)
    x, y = proj(g['lat'], g['lng'])
    s = 0.6 + 0.4 * ease(pop)
    fv, fn = font(700, int(50 * s)), font(500, int(23 * s))
    name, val = label_name(g), K['fmt'](counted(g['v'], count))
    vfull = K['fmt'](g['v'])
    w = max(dr.textlength(vfull, font=fv) + 10 * s, dr.textlength(name, font=fn)) + 40 * s
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
    room = W - 120 - (lg.width + 30 if lg is not None else 0); fs = 62
    while fs > 38 and dr.textlength(TITLE, font=font(700, fs)) > room: fs -= 2   # long titles shrink to clear the logo
    dr.text((60, y0 + 30 + (62 - fs) * 0.6), TITLE, font=font(700, fs), fill=TEXT)
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
    dr.text((60, y0 + 146), 'Data: ' + SRC, font=font(500, 22), fill=MUTED)

def summary_card(img, rows, badge, t):
    n = len(rows); rh = 92 if n <= 5 else 70
    y0 = 310; h = 70 + n * rh + 80
    card(img, (30, y0, W - 30, y0 + h))
    dr = ImageDraw.Draw(img)
    dr.text((60, y0 + 26), ('Lowest ' if K['order'] == 1 else 'Top ') + str(n), font=font(700, 34), fill=TEXT)
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
        dr.text((W - 84 + dx, cy), K['fmt'](counted(g['v'], (t - 0.2 - 0.12 * k) / 0.9)), font=fv, fill=ACCENT, anchor='rm')
    if t > 0.4 + 0.12 * n:
        text_box(dr, (60, y0 + 76 + n * rh + 6), badge, font(600, 28), ON_ACCENT, ACCENT, pad=(20, 9))

# ---------------------------------------------------------------- 3D flyover (terrain)
# The colour map raised into a landscape: hills where the story is (wetter, hotter, or colder when the story is the
# lowest), lit from the north-west, with haze in the distance. Drawn column by column ("voxel space"): for every
# screen column we step away from the camera over the height grid and paint whatever rises above what's drawn so far.
SKY_TOP, SKY_LOW, HAZE = (186, 214, 228), (228, 239, 242), (224, 236, 239)
HF = {}          # height-field grid from build_base: val (coarse values), m (inside the coloured area), X0, Y0, q
HFOV = math.radians(34)
FOC = (W / 2) / math.tan(HFOV / 2)

class Cam3:
    def __init__(self, lat, lng, span, tilt=40.0, head=0.0): self.lat, self.lng, self.span, self.tilt, self.head = lat, lng, span, tilt, head
def cam3_mix(a, b, t):
    t = ease(t)
    return Cam3(lerp(a.lat, b.lat, t), lerp(a.lng, b.lng, t), math.exp(lerp(math.log(a.span), math.log(b.span), t)),
                lerp(a.tilt, b.tilt, t), lerp(a.head, b.head, t))

def story_norm(v):
    """0..1 for how far along the story each value is (1 = the wettest / hottest / coldest end)."""
    vs = np.array([g['v'] for g in STATIONS])
    if K['floor'] is not None and not K.get('smooth'):
        hi = max(vs.max(), 1.0)
        return np.sqrt(np.clip(v, 0, None) / hi)
    if K['order'] == 1: lo, hi = vs.min(), np.percentile(vs, 92); p = (hi - v) / max(hi - lo, 1e-6)
    else: lo, hi = np.percentile(vs, 8), vs.max(); p = (v - lo) / max(hi - lo, 1e-6)
    return np.clip(p, 0, 1)

STATIONS = []
def build_terrain(full):
    from scipy.ndimage import gaussian_filter
    val, m = HF['val'], HF['m']
    p = story_norm(np.nan_to_num(val, nan=0.0))
    if K['floor'] is not None and not K.get('smooth'): p = np.where(val >= 0.2, p, 0)
    hmax = full.span * PPD * 0.075
    hgt = gaussian_filter((0.04 + 0.96 * p) * gaussian_filter(m, 1.5) * hmax, 4.5).astype(np.float32)
    gy, gx = np.gradient(hgt, HF['q'])
    nx, ny, nz = -gx * 1.6, -gy * 1.6, np.ones_like(hgt)      # a little extra relief for the shading
    L = np.array([-0.55, -0.6, 0.58]); L /= np.linalg.norm(L)  # light from the north-west (image y runs south)
    sh = (nx * L[0] + ny * L[1] + nz * L[2]) / np.sqrt(nx ** 2 + ny ** 2 + nz ** 2)
    shade = np.clip(1 + 1.1 * (sh - L[2]), 0.6, 1.2).astype(np.float32)   # flat ground = 1 (unchanged)
    return hgt, shade

def terrain_frame(levels, hgt, shade, c, full, grow):
    """One frame: for every screen column, walk the ground from near (below the frame) to far (the top row) along the
    line that column sees, lift each point by the terrain, and paint the pixels it rises above."""
    from scipy.ndimage import map_coordinates
    X0, Y0, q = HF['X0'], HF['Y0'], HF['q']
    tx, ty = to_px(c.lat, c.lng); ty = -ty                       # world: x east, y north (base-map pixels), z up
    D = c.span * PPD / 2 / math.tan(HFOV / 2)
    tl, hd = math.radians(c.tilt), math.radians(c.head)
    fh = (math.sin(hd), math.cos(hd))
    C = np.array([tx - D * math.sin(tl) * fh[0], ty - D * math.sin(tl) * fh[1], D * math.cos(tl)])
    f = (np.array([tx, ty, 0.0]) - C) / D
    r = np.array([math.cos(hd), -math.sin(hd), 0.0]); u = np.cross(r, f)
    sc = grow * min(1.0, (c.span / (1.1 * full.span)) ** 0.7)
    S = 720
    rows = np.linspace(H * 1.45, 0, S, dtype=np.float32)[:, None]   # near (below the frame) to far (top row)
    kc = ((np.arange(W, dtype=np.float32) - W / 2 + 0.5) / FOC)[None, :]
    kr = (rows - H / 2) / FOC
    dz = f[2] - kr * u[2]                                          # (S,1): ray's vertical component (r has none)
    ok = dz < -1e-4
    tt = np.where(ok, -C[2] / np.minimum(dz, -1e-4), 0)
    dx = f[0] + kc * r[0] - kr * u[0]; dy = f[1] + kc * r[1] - kr * u[1]
    GX = C[0] + tt * dx; GY = C[1] + tt * dy                       # ground point seen by each (row, column)
    px, py = GX, -GY                                               # base-map pixels
    gi, gj = (px - X0) / q, (py - Y0) / q
    z = map_coordinates(hgt, [gj, gi], order=1, mode='constant', cval=0.0) * sc
    vx, vy, vz = GX - C[0], GY - C[1], z - C[2]
    zc = vx * f[0] + vy * f[1] + vz * f[2]
    yc = vx * u[0] + vy * u[1] + vz * u[2]
    Y = np.where(ok, H / 2 - FOC * yc / np.maximum(zc, 1.0), np.inf).astype(np.float32)
    M = np.minimum.accumulate(Y, axis=0)
    dist = (tt * np.sqrt(dx ** 2 + dy ** 2 + dz ** 2)).astype(np.float32)
    col = np.empty((S, W, 3), np.float32); col[:] = HAZE
    lev = np.clip(np.floor(np.log2(np.maximum(dist / FOC, 1e-6))), 0, len(levels) - 1).astype(int)
    lev = np.where(ok, lev, -1)
    for L in np.unique(lev):
        if L < 0: continue
        sel = lev == L; arr = levels[L]; fL = 2 ** L
        x = px[sel] / fL - 0.5; y = py[sel] / fL - 0.5
        x0 = np.clip(np.floor(x).astype(np.int64), 0, arr.shape[1] - 2); y0 = np.clip(np.floor(y).astype(np.int64), 0, arr.shape[0] - 2)
        ax = np.clip(x - x0, 0, 1)[:, None]; ay = np.clip(y - y0, 0, 1)[:, None]
        out = (arr[y0, x0] * (1 - ax) * (1 - ay) + arr[y0, x0 + 1] * ax * (1 - ay) + arr[y0 + 1, x0] * (1 - ax) * ay + arr[y0 + 1, x0 + 1] * ax * ay)
        out[(x < 0) | (y < 0) | (x > arr.shape[1] - 1) | (y > arr.shape[0] - 1)] = SEA
        col[sel] = out
    s = map_coordinates(shade, [gj, gi], order=1, mode='constant', cval=1.0)
    col *= (1 + (s - 1) * min(1.0, grow * 1.2))[..., None]
    hz = np.clip((dist - 1.2 * D) / (2.6 * D), 0, 0.82)[..., None]
    col = np.clip(col * (1 - hz) + np.array(HAZE, np.float32) * hz, 0, 255).astype(np.uint8)
    rq = -np.arange(H, dtype=np.float32); negM = -M
    idx = np.empty((H, W), np.int32)
    for c_ in range(W): idx[:, c_] = np.searchsorted(negM[:, c_], rq, side='left')
    pad = np.concatenate([col, np.zeros((1, W, 3), np.uint8)], 0)
    img = pad[idx, np.arange(W)[None, :]]
    skym = idx >= S
    if skym.any():
        tsk = np.clip(np.arange(H, dtype=np.float32) / (H * 0.35), 0, 1)[:, None, None]
        sky = (np.array(SKY_TOP, np.float32) * (1 - tsk) + np.array(SKY_LOW, np.float32) * tsk).astype(np.uint8)
        img[skym] = np.broadcast_to(sky, (H, W, 3))[skym]
    frame = Image.fromarray(img, 'RGB')
    def proj(lat, lng):
        x, y = to_px(lat, lng)
        zz = map_coordinates(hgt, [[(y - Y0) / q], [(x - X0) / q]], order=1, mode='constant', cval=0.0)[0] * sc
        v = np.array([x, -y, zz]) - C; zc_ = v @ f
        if zc_ < 1: return (-999, -999)
        return (W / 2 + FOC * (v @ r) / zc_, H / 2 - FOC * (v @ u) / zc_)
    return frame, proj, math.radians(90 - c.tilt)

def pulse(img, xy, t, squash):
    """Rings spreading out from the top spot."""
    if t <= 0: return
    layer = Image.new('RGBA', img.size, (0, 0, 0, 0)); d = ImageDraw.Draw(layer)
    for k in range(2):
        u = (t - 0.45 * k) % 1.6 / 1.6
        if t - 0.45 * k < 0: continue
        r = 18 + 110 * ease(u); al = int(200 * (1 - u))
        d.ellipse([xy[0] - r, xy[1] - r * squash, xy[0] + r, xy[1] + r * squash], outline=ACCENT + (al,), width=5)
    img.alpha_composite(layer)

def render_3d(ff, bases, gauges, ranked, regions, full, period, cap, badge, ntop, region=False):
    """Rise out of the flat map, fly to each hot spot and circle it, pull back for the top list."""
    STATIONS[:] = gauges
    hgt, shade = build_terrain(full)
    levels = [np.asarray(b, dtype=np.uint8) for b in bases]
    off = 0.0 if region else -0.12 * full.span
    start = Cam3(full.lat, full.lng, full.span * 1.0, 0, 0)
    over = Cam3(full.lat + off, full.lng, full.span * (1.05 if region else 1.1), 48, -12)
    shots = [('intro', start, over, None, 4.2)]
    head = -12
    for i, rg in enumerate(regions):
        head = 16 if i % 2 == 0 else -16
        shots.append(('region', None, Cam3(rg['lat'] + 0.1 * rg['span'], rg['lng'], rg['span'] * 1.2, 52, head), rg, 4.8))
    back = Cam3(full.lat + off, full.lng, full.span * 1.1, 40, 0)
    shots.append(('summary', None, back, None, 3.0 + 0.25 * ntop)); shots.append(('end', None, back, None, 2.2))
    MOVE = 1.5
    prev = start; T = 0.0
    for kind_s, a_, b, rg, dur in shots:
        if kind_s == 'intro': cue('whoosh', 0.4, 0.8)
        if kind_s in ('region', 'summary'): cue('whoosh', T + 0.05, 1.0 if kind_s == 'region' else 0.6)
        if kind_s == 'region':
            for k in range(len(rg['labels'])): cue('pop', T + MOVE + 0.1 + 0.3 * k)
            cue('ding', T + MOVE + 0.1 + 1.1)
        if kind_s == 'summary':
            for k in range(ntop): cue('tick', T + MOVE * 0.6 + 0.2 + 0.12 * k)
        if kind_s == 'end': cue('swell', T)
        for i in range(int(dur * FPS)):
            t = i / FPS
            if kind_s == 'intro':
                c = cam3_mix(a_, b, t / (dur - 0.3)); grow = ease((t - 0.3) / 2.6)
            elif kind_s in ('region', 'summary'):
                c = cam3_mix(prev, b, t / MOVE); grow = 1.0
                if kind_s == 'region' and t > MOVE: c.head += 9 * (t - MOVE) / (dur - MOVE) * (1 if b.head >= 0 else -1)
            else:
                c, grow = b, 1.0
            frame, proj, pitch = terrain_frame(levels, hgt, shade, c, full, grow)
            frame = frame.convert('RGBA')
            if kind_s == 'region':
                top = rg['labels'][0]
                pulse(frame, proj(top['lat'], top['lng']), t - MOVE - 0.1, math.sin(pitch))
                taken = []
                for k, g in enumerate(rg['labels']):
                    tp = t - MOVE - 0.1 - 0.3 * k
                    draw_label(frame, proj, g, tp / 0.3, taken, count=tp / 1.1)
            if kind_s != 'end':
                top_card(frame, period, cap, rg['tag'] if kind_s == 'region' and t > 0.4 else None, slide=min(1.0, (T + t) / 0.6))
                if kind_s == 'summary' and t > MOVE * 0.6: summary_card(frame, ranked[:ntop], badge, t - MOVE * 0.6)
                bottom_card(frame)
            else:
                end_card(frame, t)
            ff.stdin.write(frame.convert('RGB').tobytes())
        T += dur; prev = b if b is not None else prev
    return T

# ---------------------------------------------------------------- shared bits for every style
CUES = []                                     # (sound, seconds) for the soundtrack
def cue(kind, t, gain=1.0): CUES.append((kind, t, gain))

def set_ppd(p):
    """Map detail (pixels per degree). The still-camera styles draw at about the frame's own resolution (faster)."""
    global PPD, SCALE, BW, BH
    PPD = p; SCALE = PPD * 180 / math.pi
    BW = int((LNG1 - LNG0) * PPD); BH = int((merc(LAT0) - merc(LAT1)) * SCALE)

def end_card(frame, t):
    fade = ease(t / 0.5)
    frame.alpha_composite(Image.new('RGBA', (W, H), BG + (int(250 * fade),)))
    dr = ImageDraw.Draw(frame)
    lg = logo_img(300)
    if lg is not None: frame.alpha_composite(lg, (int((W - lg.width) / 2), int(H / 2 - 240)))
    else: dr.text((W / 2, H / 2 - 40), 'West WX Watchers', font=font(700, 84), fill=TEXT, anchor='mm')
    dr.text((W / 2, H / 2 + 130), 'Data: ' + SRC, font=font(500, 28), fill=MUTED, anchor='mm')

def fit_cam(v):
    if not v: return Cam(-25.0, 121.0, 18.5)
    sp, la = float(v['span']), float(v['lat'])
    hh = 0.93 * H / W * sp / 2 * math.cos(math.radians(la))   # keep the view inside the base map (north edge 9 deg S)
    return Cam(min(la, LAT0 - 0.5 - hh), float(v['lng']), sp)

def still_frame(gauges, states, cam):
    """The coloured map for one still camera, drawn at about frame resolution: (frame RGBA, projector)."""
    set_ppd(max(40, math.ceil(W * 1.15 / cam.span)))
    b = build_base(gauges, states)
    fr, proj = view([b], cam)
    return fr.convert('RGBA'), proj

def plain_frame(states, cam):
    """The map with no colours (land, sea, coast) for the same camera."""
    set_ppd(max(40, math.ceil(W * 1.15 / cam.span)))
    base = Image.new('RGB', (BW, BH), SEA); dr = ImageDraw.Draw(base)
    for name, g in states.items():
        if name in ('Western Australia', 'Northern Territory', 'South Australia'):
            for ring in rings(g):
                pts = [to_px(lat, lng) for lng, lat in ring]
                if len(pts) > 2: dr.polygon(pts, fill=WA_LAND if name == 'Western Australia' else LAND)
                if len(pts) > 2: dr.line(pts + [pts[0]], fill=COAST, width=3)
    fr, proj = view([base], cam)
    return fr.convert('RGBA'), proj

def stat_card(img, rows, y0=300):
    """Small running-total card under the title: [(label, value), ...]."""
    card(img, (30, y0, W - 30, y0 + 112), r=22)
    dr = ImageDraw.Draw(img); n = len(rows); cw = (W - 120) / n
    for k, (lab, val) in enumerate(rows):
        x = 60 + k * cw
        dr.text((x, y0 + 18), lab, font=font(500, 22), fill=MUTED)
        dr.text((x, y0 + 50), val, font=font(700, 38), fill=TEXT)

# ---------------------------------------------------------------- style: rain build (districts fill one by one)
def render_build(ff, gauges, states, full, period, cap, badge, ntop, dists):
    """Start from the plain map; each district's rain fills in (driest first, wettest last) with its top gauge."""
    colour, proj = still_frame(gauges, states, full)
    plain, _ = plain_frame(states, full)
    # a mask per district, in frame pixels
    masks = {}
    for name, rs in dists.items():
        m = Image.new('L', (W, H), 0); md = ImageDraw.Draw(m)
        for r in rs:
            pts = [proj(r[i + 1], r[i]) for i in range(0, len(r) - 1, 2)]
            if len(pts) > 2: md.polygon(pts, fill=255)
        masks[name] = m.filter(ImageFilter.GaussianBlur(1.2))
    by = {}
    for g in gauges:
        if g.get('d') in masks: by.setdefault(g['d'], []).append(g)
    steps = sorted([(max(x['v'] for x in gs), d, max(gs, key=lambda x: x['v'])) for d, gs in by.items()])
    dry = [s for s in steps if s[0] < 1]; wet = [s for s in steps if s[0] >= 1]
    seq = ([('Dry areas', [s[1] for s in dry], None)] if dry else []) + [(s[1], [s[1]], s[2]) for s in wet]
    ranked = sorted(gauges, key=lambda g: -g['v'])
    STEP = 1.25 if len(seq) <= 12 else 1.0
    total = 1.2 + STEP * len(seq) + 1.0 + (3.0 + 0.25 * ntop) + 2.2
    shown = Image.new('L', (W, H), 0)
    best, nwet = None, 0
    T = 0.0
    cue('whoosh', 0.2)
    def base_frame(reveal, extra=None, a=0.0):
        fr = plain.copy()
        m = reveal if extra is None else Image.composite(Image.new('L', (W, H), 255), reveal, extra.point(lambda v: int(v * a)))
        fr.paste(colour, (0, 0), m)
        return fr
    # intro: the plain map
    for i in range(int(1.2 * FPS)):
        t = i / FPS; fr = plain.copy()
        top_card(fr, period, cap, None, slide=min(1.0, t / 0.6)); bottom_card(fr)
        ff.stdin.write(fr.convert('RGB').tobytes())
    T = 1.2
    for name, ds, g in seq:
        m = Image.new('L', (W, H), 0)
        for d in ds: m = Image.composite(Image.new('L', (W, H), 255), m, masks[d])
        cue('pop', T + 0.25)
        if g is not None: cue('tick', T + 0.25 + 0.9)
        for i in range(int(STEP * FPS)):
            t = i / FPS; a = ease(t / 0.45)
            fr = base_frame(shown, m, a)
            dr = ImageDraw.Draw(fr); draw_gauges(dr, proj, [x for x in gauges if x.get('d') in ds or shown.getpixel((int(min(W - 1, max(0, proj(x['lat'], x['lng'])[0]))), int(min(H - 1, max(0, proj(x['lat'], x['lng'])[1]))))) > 128], r=3)
            if g is not None: draw_label(fr, proj, g, (t - 0.25) / 0.3, [], count=(t - 0.25) / 0.9)
            cur = best if g is None or (best is not None and best['v'] >= g['v']) or t < 1.15 * 0.9 else g
            nw = nwet + (sum(1 for x in by[ds[0]] if x['v'] >= 1) if g is not None and t > 0.3 else 0)
            top_card(fr, period, cap, name)
            stat_card(fr, [('Wettest so far', K['fmt'](cur['v']) if cur else '—'), ('Gauges 1 mm+', str(nw))])
            bottom_card(fr)
            ff.stdin.write(fr.convert('RGB').tobytes())
        shown = Image.composite(Image.new('L', (W, H), 255), shown, m)
        if g is not None:
            nwet += sum(1 for x in by[name] if x['v'] >= 1)
            if best is None or g['v'] > best['v']: best = g
        T += STEP
    # hold on the full picture, then the top list
    cue('whoosh', T + 0.6, 0.6)
    ts = 3.0 + 0.25 * ntop + 1.0
    for k in range(ntop): cue('tick', T + 1.0 + 0.2 + 0.12 * k)
    cue('ding', T + 1.0 + 0.2 + 0.12 * ntop + 0.9)
    for i in range(int(ts * FPS)):
        t = i / FPS; fr = base_frame(shown)
        draw_gauges(ImageDraw.Draw(fr), proj, gauges, r=3)
        top_card(fr, period, cap, None)
        if t > 1.0: summary_card(fr, ranked[:ntop], badge, t - 1.0)
        bottom_card(fr)
        ff.stdin.write(fr.convert('RGB').tobytes())
    T += ts
    cue('swell', T)
    for i in range(int(2.2 * FPS)):
        fr = base_frame(shown); end_card(fr, i / FPS); ff.stdin.write(fr.convert('RGB').tobytes())
    return T + 2.2

# ---------------------------------------------------------------- style: head to head (two stations race)
H2H_COL = [(14, 124, 134), (232, 120, 40)]
def render_h2h(ff, doc, states, period):
    S = doc['series'][:2]
    order = K['order']
    for s in S:
        s['v'] = [None if x is None else float(x) for x in s['v']]
        s['ok'] = [x for x in s['v'] if x is not None]
    allv = [x for s in S for x in s['ok']]
    lo, hi = min(allv), max(allv)
    step = next(x for x in (1, 2, 5, 10, 20, 50, 100) if (hi - lo) / x <= 5)   # round numbers on the axis
    lo = math.floor(lo / step) * step; hi = math.ceil(hi / step) * step
    if hi - lo < 2 * step: hi += step; lo -= step
    nt = int(round((hi - lo) / step))
    n = max(len(s['v']) for s in S); hrs = S[0]['t']
    best = [(max if order != 1 else min)(s['ok']) for s in S]
    win = 0 if (best[0] >= best[1]) == (order != 1) else 1
    diff = abs(best[0] - best[1])
    word = {'tmax': 'hotter', 'temp': 'hotter', 'app': 'hotter', 'tmin': 'colder', 'gust': 'gustier', 'wind': 'windier', 'dew': 'more humid',
            'rh': 'more humid', 'pres': 'higher', 'rain': 'wetter'}.get(doc.get('kind'), 'higher')
    if order == 1 and word == 'hotter': word = 'colder'
    # mini map
    mm = Image.new('RGBA', (420, 520), (0, 0, 0, 0)); md = ImageDraw.Draw(mm)
    mp = lambda lat, lng: ((lng - 112.5) / 17 * 400 + 10, (-13.3 - lat) / 22.6 * 500 + 10)
    for ring in rings(states['Western Australia']):
        pts = [mp(lat, lng) for lng, lat in ring]
        if len(pts) > 2: md.polygon(pts, fill=WA_LAND + (255,), outline=COAST + (255,))
    for k, s in enumerate(S):
        x, y = mp(s['lat'], s['lng']); md.ellipse([x - 11, y - 11, x + 11, y + 11], fill=H2H_COL[k] + (255,), outline=(255, 255, 255, 255), width=3)
    RACE, HOLD = 8.0, 3.2
    T = 0.0; cue('whoosh', 0.1)
    for j in range(n): cue('tick', 0.8 + RACE * (j + 1) / n, 0.6)
    cue('ding', 0.8 + RACE + 0.3)
    total = 0.8 + RACE + HOLD
    CX0, CX1, CY0, CY1 = 120, W - 70, 760, 1250
    def chart_xy(j, v): return (CX0 + (CX1 - CX0) * j / max(1, n - 1), CY1 - (CY1 - CY0) * (v - lo) / (hi - lo))
    for i in range(int(total * FPS)):
        t = i / FPS; p = max(0.0, min(1.0, (t - 0.8) / RACE)); jf = p * (n - 1)
        fr = Image.new('RGBA', (W, H), BG + (255,)); dr = ImageDraw.Draw(fr)
        top_card(fr, period, doc.get('cap') or (S[0]['name'] + ' v ' + S[1]['name']), None, slide=min(1.0, t / 0.6))
        # score cards
        for k, s in enumerate(S):
            x0 = 30 + k * (W - 60) / 2 + (0 if k == 0 else 10); x1 = x0 + (W - 60) / 2 - 10
            card(fr, (x0, 300, x1, 700), r=24); dr = ImageDraw.Draw(fr)
            dr.rounded_rectangle([x0, 300, x0 + 14, 700], radius=7, fill=H2H_COL[k])
            nm = label_name({'name': s['name'], 'lat': s['lat'], 'lng': s['lng']})
            fn = font(600, 34)
            while dr.textlength(nm, font=fn) > x1 - x0 - 60 and len(nm) > 4: nm = nm[:-1]
            dr.text((x0 + 36, 326), nm, font=fn, fill=TEXT)
            seen = [x for x in s['v'][:int(jf) + 1] if x is not None]
            cur = None
            if seen:
                j0 = int(jf); a = s['v'][j0]; b = s['v'][min(n - 1, j0 + 1)]
                cur = a if a is not None and (b is None or j0 + 1 >= n) else (lerp(a, b, jf - j0) if a is not None else b)
            dr.text((x0 + 36, 390), K['fmt'](cur) if cur is not None else '—', font=font(700, 92), fill=H2H_COL[k])
            sofar = (max if order != 1 else min)(seen + ([cur] if cur is not None else [])) if seen else None
            dr.text((x0 + 36, 520), ('Highest' if order != 1 else 'Lowest') + ' so far', font=font(500, 24), fill=MUTED)
            dr.text((x0 + 36, 556), K['fmt'](sofar) if sofar is not None else '—', font=font(700, 46), fill=TEXT)
            if t > 0.8 + RACE + 0.3 and k == win:
                text_box(dr, (x0 + 36, 632), 'Winner', font(700, 26), ON_ACCENT, H2H_COL[k], pad=(18, 7))
        # chart
        card(fr, (30, 730, W - 30, 1380), r=24); dr = ImageDraw.Draw(fr)
        for q in range(nt + 1):
            v = lo + step * q; y = chart_xy(0, v)[1]
            dr.line([CX0, y, CX1, y], fill=LINE, width=2)
            dr.text((CX0 - 14, y), f'{v:g}', font=font(500, 22), fill=MUTED, anchor='rm')
        for j in range(0, n, max(1, n // 6)):
            x = chart_xy(j, lo)[0]
            lab = datetime.utcfromtimestamp(hrs[j] * 3600 + 8 * 3600).strftime('%-I%p').lower() if j < len(hrs) else ''
            dr.text((x, CY1 + 22), lab, font=font(500, 20), fill=MUTED, anchor='mt')
        for k, s in enumerate(S):
            pts = []
            for j in range(int(jf) + 1):
                if s['v'][j] is not None: pts.append(chart_xy(j, s['v'][j]))
            j0 = int(jf)
            if j0 + 1 < n and s['v'][j0] is not None and s['v'][j0 + 1] is not None:
                pts.append(chart_xy(jf, lerp(s['v'][j0], s['v'][j0 + 1], jf - j0)))
            if len(pts) > 1: dr.line(pts, fill=H2H_COL[k], width=7, joint='curve')
            if pts: x, y = pts[-1]; dr.ellipse([x - 11, y - 11, x + 11, y + 11], fill=H2H_COL[k], outline=(255, 255, 255), width=3)
        if 0 < p < 1 or t <= 0.8 + RACE:
            hidx = min(len(hrs) - 1, int(round(jf)))
            clock = datetime.utcfromtimestamp(hrs[hidx] * 3600 + 8 * 3600).strftime('%-I %p %a').replace('AM', 'am').replace('PM', 'pm')
            text_box(dr, (W - 60, 760), clock, font(700, 30), ON_ACCENT, ACCENT, pad=(18, 8), anchor='rt')
        # map and result
        card(fr, (30, 1410, W - 30, H - 36), r=24); dr = ImageDraw.Draw(fr)
        fr.alpha_composite(mm.resize((336, 416), Image.LANCZOS), (60, 1440))
        if t > 0.8 + RACE + 0.3:
            u = ease((t - 0.8 - RACE - 0.3) / 0.5)
            dr.text((430, 1520), S[win]['name'].title()[:22], font=font(700, 44), fill=H2H_COL[win])
            dr.text((430, 1580), f"{word} by", font=font(500, 34), fill=MUTED)
            dr.text((430, 1630), K['fmt'](diff * u), font=font(700, 84), fill=TEXT)
            dr.text((430, 1740), ('peak ' if order != 1 else 'low ') + K['fmt'](best[win]) + ' v ' + K['fmt'](best[1 - win]), font=font(500, 26), fill=MUTED)
        else:
            for k, s in enumerate(S):
                dr.ellipse([430, 1530 + k * 90, 456, 1556 + k * 90], fill=H2H_COL[k])
                dr.text((476, 1543 + k * 90), s['name'].title()[:24], font=font(600, 34), fill=TEXT, anchor='lm')
        ff.stdin.write(fr.convert('RGB').tobytes())
    T = total; cue('swell', T)
    for i in range(int(2.2 * FPS)):
        fr = Image.new('RGBA', (W, H), BG + (255,)); end_card(fr, 1.0); ff.stdin.write(fr.convert('RGB').tobytes())
    return T + 2.2

# ---------------------------------------------------------------- style: time-lapse (hour by hour)
def render_timelapse(ff, doc, states, full, period, cap, ntop):
    names = doc['stations']; hrs = doc['hours']; vals = doc['vals']
    frames, tops, peak = [], [], {}
    print(f'time-lapse: {len(hrs)} hours, {len(names)} stations', flush=True)
    for h, row in zip(hrs, vals):
        gs = [{'name': n[0], 'lat': n[1], 'lng': n[2], 'v': float(v)} for n, v in zip(names, row) if v is not None and -36 < n[1] < -13 and 112 < n[2] < 129.5]
        if len(gs) < 5: continue
        STATIONS[:] = gs
        fr, proj = still_frame(gs, states, full)
        draw_gauges(ImageDraw.Draw(fr), proj, gs, r=3 if full.span > 9 else 5)
        top = max(gs, key=score)
        frames.append((h, fr, proj, top))
        for g in gs:
            k = g['name']
            if k not in peak or score(g) > score(peak[k]): peak[k] = g
    if not frames: sys.exit('No hourly values for the time-lapse.')
    HOUR, FADE = 0.6, 0.3
    T = 0.0; cue('whoosh', 0.1)
    best = None
    for j in range(len(frames)): cue('tick', 0.6 + j * HOUR, 0.5)
    for j, (h, fr, proj, top) in enumerate(frames):
        nxt = frames[j + 1] if j + 1 < len(frames) else None
        if best is None or score(top) > score(best): best = top; cue('pop', 0.6 + j * HOUR + 0.05)
        dur = HOUR + (0.6 if j == 0 else 0) + (1.2 if nxt is None else 0)
        for i in range(int(dur * FPS)):
            t = i / FPS; tt = t - (0.6 if j == 0 else 0)
            f = fr.copy()
            if nxt is not None and tt > HOUR - FADE:
                f = Image.blend(fr, nxt[1], ease((tt - (HOUR - FADE)) / FADE))
            clock = datetime.utcfromtimestamp(h * 3600 + 8 * 3600)   # Perth time
            draw_label(f, proj, top, 1.0, [(0, 0, W, 430), (0, H - 250, W, H)])   # keep clear of the cards
            top_card(f, period, clock.strftime('%-I %p').replace('AM', 'am').replace('PM', 'pm') + ' ' + clock.strftime('%a %-d %b'), None, slide=min(1.0, (T + t) / 0.6))
            stat_card(f, [(('Highest' if K['order'] != 1 else 'Lowest') + ' this hour', K['fmt'](top['v'])), ('Peak so far', K['fmt'](best['v']) + ' ' + label_name(best)[:14])])
            bottom_card(f)
            ff.stdin.write(f.convert('RGB').tobytes())
        T += dur
    ranked = sorted(peak.values(), key=lambda g: -score(g))
    last = frames[-1][1]
    badge = f"Peak over {len(frames)} hours"
    ts = 3.0 + 0.25 * ntop
    cue('whoosh', T, 0.6)
    for k in range(ntop): cue('tick', T + 0.2 + 0.12 * k)
    cue('ding', T + 0.2 + 0.12 * ntop + 0.9)
    for i in range(int(ts * FPS)):
        f = last.copy(); top_card(f, period, cap, None); summary_card(f, ranked[:ntop], badge, i / FPS); bottom_card(f)
        ff.stdin.write(f.convert('RGB').tobytes())
    T += ts; cue('swell', T)
    for i in range(int(2.2 * FPS)):
        f = last.copy(); end_card(f, i / FPS); ff.stdin.write(f.convert('RGB').tobytes())
    return T + 2.2

# ---------------------------------------------------------------- main
def main():
    global LOGO, TITLE, SRC, K, CLIP
    ap = argparse.ArgumentParser()
    ap.add_argument('data'); ap.add_argument('out')
    ap.add_argument('--caption', help='short caption; default picked from the values')
    ap.add_argument('--regions', type=int, default=3, help='zoom-in stops, 0-5')
    ap.add_argument('--top', type=int, default=3, help='how many in the top list, 3-10')
    ap.add_argument('--logo', help='logo PNG (its own colours, transparent background)')
    ap.add_argument('--style', choices=['map', '3d', 'build', 'h2h', 'timelapse'], help='default: from the data (map if not set)')
    ap.add_argument('--sound', choices=['on', 'off'], help='music and effects (default: from the data, on)')
    a = ap.parse_args()
    lp = a.logo or os.path.join(HERE, 'logo.png')
    if os.path.exists(lp): LOGO = Image.open(lp).convert('RGBA')
    doc, gauges = read_data(a.data)
    style = a.style or doc.get('style') or 'map'
    if not gauges and style not in ('h2h', 'timelapse'): sys.exit('No stations with values in the data.')
    STATIONS[:] = gauges
    kind = doc.get('kind', 'rain'); K = dict(KINDS.get(kind, KINDS['temp']))
    if doc.get('order') in (-1, 1) and kind != 'rain': K['order'] = doc['order']   # tell the story of the highest or the lowest
    CLIP = doc.get('clip') or None
    TITLE, period, SRC = doc['title'], doc['sub'], doc.get('src', 'BoM, DPIRD, DWER')
    states = json.load(open(os.path.join(HERE, 'aus_states.json')))
    towns = json.load(open(os.path.join(HERE, 'towns.json'))); TOWNS[:] = towns
    ranked = sorted(gauges, key=lambda g: -score(g))
    if K['floor'] is not None: ranked = [g for g in ranked if g['v'] >= 0.2] or ranked
    ntop = max(3, min(10, a.top)); nreg = max(0, min(5, a.regions))
    cap = (a.caption or '').strip() or (caption_for(kind, gauges, int(doc.get('days', 1))) if gauges else '')
    badge = badge_for(kind, gauges) if gauges else ''
    v = doc.get('view'); full = fit_cam(v)
    vid = a.out + '.video.mp4'
    ff = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                           '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '20', '-preset', 'medium', '-movflags', '+faststart', vid],
                          stdin=subprocess.PIPE)
    print(f'{kind} ({style}): {len(gauges)} stations; {nreg} zoom stops, top {ntop}.', flush=True)
    if style == 'build':
        total = render_build(ff, gauges, states, full, period, cap, badge, ntop, doc.get('dists') or {})
    elif style == 'h2h':
        doc['cap'] = (a.caption or '').strip()
        total = render_h2h(ff, doc, states, period)
    elif style == 'timelapse':
        total = render_timelapse(ff, doc, states, full, period, cap, ntop)
    else:
        base = build_base(gauges, states)
        bases = [base]
        while bases[-1].width > 1500: bases.append(bases[-1].resize((bases[-1].width // 2, bases[-1].height // 2), Image.LANCZOS))
        regions = pick_regions(gauges, towns, nreg) if nreg else []
        if style == '3d':
            c3 = Cam(float(v['lat']), float(v['lng']), float(v['span'])) if v else full   # 3D: no edge to keep inside
            total = render_3d(ff, bases, gauges, ranked, regions, c3, period, cap, badge, ntop, region=bool(v))
        else:
            total = render_flat(ff, bases, gauges, ranked, regions, full, period, cap, badge, ntop)
    ff.stdin.close(); ff.wait()
    if ff.returncode: sys.exit('ffmpeg failed')
    if (a.sound or doc.get('sound') or 'on') == 'on':
        import sound
        mix = sound.Mix(total); mix.music()
        for kind_, t_, g_ in CUES: mix.cue(kind_, t_, g_)
        wav = a.out + '.wav'; mix.write(wav)
        r = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', vid, '-i', wav, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '160k',
                            '-shortest', '-movflags', '+faststart', a.out])
        os.remove(wav)
        if r.returncode: sys.exit('Adding the sound failed')
        os.remove(vid)
    else:
        os.replace(vid, a.out)
    print('Wrote', a.out, flush=True)

def render_flat(ff, bases, gauges, ranked, regions, full, period, cap, badge, ntop):
    shots = [('intro', full, None, 3.0)]
    for r in regions: shots.append(('region', Cam(r['lat'] - 0.02 * r['span'], r['lng'], r['span']), r, 4.0))
    shots.append(('summary', full, None, 3.0 + 0.25 * ntop)); shots.append(('end', full, None, 2.2))
    MOVE = 1.1
    prev = full; T = 0.0
    for kind_s, cam, r, dur in shots:
        if kind_s in ('region', 'summary'): cue('whoosh', T + 0.05, 1.0 if kind_s == 'region' else 0.6)
        if kind_s == 'region':
            for k in range(len(r['labels'])): cue('pop', T + MOVE + 0.1 + 0.3 * k)
            cue('ding', T + MOVE + 0.1 + 1.1)
        if kind_s == 'summary':
            for k in range(ntop): cue('tick', T + MOVE * 0.6 + 0.2 + 0.12 * k)
        if kind_s == 'end': cue('swell', T)
        for i in range(int(dur * FPS)):
            t = i / FPS
            c = cam_mix(prev, cam, t / MOVE) if kind_s in ('region', 'summary') else cam
            frame, proj = view(bases, c)
            frame = frame.convert('RGBA')
            dr = ImageDraw.Draw(frame)
            draw_gauges(dr, proj, gauges, r=3 if c.span > 9 else 5)
            if kind_s == 'region':
                pulse(frame, proj(r['labels'][0]['lat'], r['labels'][0]['lng']), t - MOVE - 0.1, 1.0)
                taken = []
                for k, g in enumerate(r['labels']):
                    tp = t - MOVE - 0.1 - 0.3 * k
                    draw_label(frame, proj, g, tp / 0.3, taken, count=tp / 1.1)
            if kind_s != 'end':
                top_card(frame, period, cap, r['tag'] if kind_s == 'region' and t > 0.4 else None, slide=min(1.0, (T + t) / 0.6))
                if kind_s == 'summary' and t > MOVE * 0.6: summary_card(frame, ranked[:ntop], badge, t - MOVE * 0.6)
                bottom_card(frame)
            else:
                end_card(frame, t)
            ff.stdin.write(frame.convert('RGB').tobytes())
        T += dur; prev = cam
    return T

if __name__ == '__main__':
    main()

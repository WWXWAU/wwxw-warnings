"""Find BoM's yellow warning area in a warning image and convert it to lng/lat (auto-calibrated against the WA coast)."""
import io, math, json
import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import box, Polygon
from shapely.ops import unary_union

def mercy(lat):
    return np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))

def wa_raster(wa_rings, step=0.05):
    # land mask of WA on a lng/lat grid (112..130, -36..-13)
    W, H = int((130 - 112) / step), int((36 - 13) / step)
    im = Image.new('L', (W, H), 0); d = ImageDraw.Draw(im)
    for r in wa_rings:
        d.polygon([((x - 112) / step, (-13 - y) / step) for x, y in r], fill=1)
    return np.array(im, dtype=bool), step

def calibrate(rgb, wa_rings):
    """Find px-per-degree (s), lng at x=0 (L0) and Mercator y at row 0 (M0) that best match the image's sea/land to WA."""
    a = rgb.astype(int); R, G, B = a[..., 0], a[..., 1], a[..., 2]
    sea = (B > R + 12) & (B > 200)                         # BoM's light-blue sea
    land = (R > 235) & (G > 225) & (B < 235) & (B > 150)   # BoM's cream land
    known = sea | land
    land_r, st = wa_raster(wa_rings)
    ys, xs = np.nonzero(known[::3, ::3]); ys = ys * 3; xs = xs * 3; obs = land[ys, xs]
    def score(s, L0, M0):
        lng = L0 + xs / s
        lat = np.degrees(2 * np.arctan(np.exp(M0 - ys / (s * 180 / np.pi))) - np.pi / 2)
        ok = (lng > 112.05) & (lng < 128.9) & (lat > -35.95) & (lat < -13.05)   # compare inside WA's longitudes only
        if ok.sum() < 2000: return -1
        gi = ((lng[ok] - 112) / st).astype(int); gj = ((-13 - lat[ok]) / st).astype(int)
        return (land_r[gj, gi] == obs[ok]).mean()
    best = (-1, None)
    for s in np.arange(20, 70, 2.0):                     # coarse search
        for L0 in np.arange(100, 122, 0.5):
            for lat0 in np.arange(-8, -30, -0.5):
                v = score(s, L0, mercy(lat0))
                if v > best[0]: best = (v, (s, L0, lat0))
    s, L0, lat0 = best[1]
    for step in (0.5, 0.15, 0.05):                       # refine
        cand = [(s + i * step * 2, L0 + j * step, lat0 + k * step) for i in (-1, 0, 1) for j in (-2, -1, 0, 1, 2) for k in (-2, -1, 0, 1, 2)]
        for c in cand:
            v = score(c[0], c[1], mercy(c[2]))
            if v > best[0]: best = (v, c)
        s, L0, lat0 = best[1]
    return {'s': s, 'L0': L0, 'M0': float(mercy(lat0)), 'fit': round(best[0], 4)}

FRAMES = None
def cached_calibration(rgb, wa_rings, path=None):
    """Work out an image frame's calibration once, then reuse it (keyed by the frame's sea/land pattern)."""
    import hashlib, os
    global FRAMES
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'frames.json')
    if FRAMES is None:
        FRAMES = json.load(open(path)) if os.path.exists(path) else {}
    a = rgb.astype(int)
    sea = ((a[..., 2] > a[..., 0] + 12) & (a[..., 2] > 200))[::10, ::10]
    key = str(rgb.shape[1]) + 'x' + str(rgb.shape[0]) + ':' + hashlib.md5(np.packbits(sea).tobytes()).hexdigest()[:16]
    if key in FRAMES:
        return FRAMES[key]
    for k, c in FRAMES.items():                      # nearly the same frame (labels/yellow differ): reuse
        if k.split(':')[0] == key.split(':')[0] and 'sea' in c:
            other = np.unpackbits(np.array(c['sea'], dtype=np.uint8))[:sea.size].reshape(sea.shape).astype(bool)
            if (other == sea).mean() > 0.985:
                return c
    cal = calibrate(rgb, wa_rings)
    cal = {k: float(v) for k, v in cal.items()}
    cal['sea'] = np.packbits(sea).tolist()
    FRAMES[key] = cal
    json.dump(FRAMES, open(path, 'w'))
    return cal

def yellow_area(png_bytes, wa_rings):
    rgb = np.array(Image.open(io.BytesIO(png_bytes)).convert('RGB'))
    H, W, _ = rgb.shape
    a = rgb.astype(int)
    yel = (a[..., 0] > 225) & (a[..., 1] > 185) & (a[..., 1] < 235) & (a[..., 2] < 90)
    cal = cached_calibration(rgb, wa_rings)
    if cal['fit'] < 0.93: return None, cal
    # connected yellow regions; drop the legend swatch (a filled rectangle in the bottom-left corner)
    lab = np.zeros(yel.shape, int); n = 0; regions = []
    for y0, x0 in zip(*np.nonzero(yel)):
        if lab[y0, x0]: continue
        n += 1; st = [(y0, x0)]; lab[y0, x0] = n; pix = []
        while st:
            y, x = st.pop(); pix.append((y, x))
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                yy, xx = y + dy, x + dx
                if 0 <= yy < H and 0 <= xx < W and yel[yy, xx] and not lab[yy, xx]:
                    lab[yy, xx] = n; st.append((yy, xx))
        ys = [p[0] for p in pix]; xs = [p[1] for p in pix]
        fill = len(pix) / ((max(ys) - min(ys) + 1) * (max(xs) - min(xs) + 1))
        if min(ys) > H * 0.88 and max(xs) < W * 0.3 and fill > 0.9: continue     # legend swatch
        if len(pix) < 30: continue
        regions.append(pix)
    if not regions: return None, cal
    s, L0, M0 = cal['s'], cal['L0'], cal['M0']
    def ll(x, y):
        return (L0 + x / s, math.degrees(2 * math.atan(math.exp(M0 - y / (s * 180 / math.pi))) - math.pi / 2))
    polys = []
    for pix in regions:
        rows = {}
        for y, x in pix: rows.setdefault(y, []).append(x)
        boxes = []
        for y, xl in rows.items():                       # one box per run of pixels in each row
            xl.sort(); a0 = xl[0]; prev = a0
            for x in xl[1:] + [None]:
                if x is None or x != prev + 1:
                    boxes.append(box(a0, y, prev + 1, y + 1)); a0 = x
                if x is not None: prev = x
        g = unary_union(boxes).buffer(1.5).buffer(-1.5)  # close the gaps left by labels on top of the yellow
        for p in (g.geoms if g.geom_type == 'MultiPolygon' else [g]):
            polys.append(Polygon([ll(x, y) for x, y in p.exterior.coords]))
    return unary_union(polys), cal

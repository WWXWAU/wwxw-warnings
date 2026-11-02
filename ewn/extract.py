"""Read EWN's significant weather map into reference areas for the outlook check.

python3 ewn/extract.py IMAGE.png OUT.json [PREVIEW.png]

The map is always the same 1000x753 Mercator picture of Australia, so its position is fixed (fitted to
town markers, 1 Nov 2026). Hazard areas are see-through colour over a satellite background with a solid
outline; the arrows pointing at them are the same colour as the outlines, so thin shapes are removed.
Output: storms (red + pink), severe (pink thunderstorms), plus severe wind / heavy rain kept for later.
Only the areas over WA are kept, cut at 130°E (grid points on a polygon edge count as outside).
"""
import json, math, sys
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from skimage import measure

# --- map position (Web Mercator): x = X0 + SX*lng, y = Y0 + SY*mercY(lat)
SX, X0 = 16.9, -1771.6509
SY, Y0 = -968.2987, -118.9718
SIZE = (1000, 753)
WA = dict(lng_min=112.0, lng_max=130.0, lat_min=-36.0, lat_max=-13.0)
MIN_PX = 250          # smaller blobs are arrowheads / labels, not areas (1° is about 17 px)


def merc(lat):
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def to_px(lat, lng):
    return X0 + SX * lng, Y0 + SY * merc(lat)


def to_ll(x, y):
    lng = (x - X0) / SX
    lat = math.degrees(2 * math.atan(math.exp((y - Y0) / SY)) - math.pi / 2)
    return round(lat, 2), round(lng, 2)


def classify(rgb):
    R, G, B = (rgb[:, :, i].astype(int) for i in range(3))
    redness = R - np.maximum(G, B * 0.75)
    pink = (R > 150) & (R - G > 70) & (B - G > 45)                 # severe thunderstorms (magenta)
    red = (R > 140) & (R - G > 85) & (B - G < 40) & ~pink           # non-severe thunderstorms
    windy = (R > 150) & (G > 150) & (B < 120) & (abs(R - G) < 45) & (R + G - 2 * B > 120)   # severe winds (yellow-green)
    rain = (B > 150) & (G > 140) & (R < 120)                        # heavy rainfall (cyan)
    # Solid (not see-through) colour = the outlines and the arrows pointing at the areas. Leaving it out keeps
    # the arrows from joining the areas; the 2-pixel outline gap is closed again in clean().
    solid = ((R > 230) & (G < 85) & (B < 85)) | ((R > 235) & (B > 185) & (G < 140))
    return {'red': red & ~solid, 'pink': pink & ~solid, 'wind': windy, 'rain': rain}


def clean(mask):
    m = ndimage.binary_opening(mask, structure=np.ones((5, 5)))     # drops arrow shafts and outline-only lines
    m = ndimage.binary_closing(m, structure=np.ones((7, 7)))        # fills label text, outline gaps
    m = ndimage.binary_fill_holes(m)
    lab, n = ndimage.label(m)
    if n:
        sizes = ndimage.sum(m, lab, range(1, n + 1))
        m = np.isin(lab, [i + 1 for i, s in enumerate(sizes) if s >= MIN_PX])
    return m


def wa_window(mask):
    x0, y0 = to_px(WA['lat_max'], WA['lng_min'])
    x1, y1 = to_px(WA['lat_min'], WA['lng_max'])
    keep = np.zeros_like(mask)
    keep[int(math.floor(y0)):int(math.ceil(y1)), int(math.floor(x0)):int(round(x1)) + 1] = True
    return mask & keep


def polygons(mask):
    out = []
    padded = np.pad(mask.astype(float), 1)
    for c in measure.find_contours(padded, 0.5):
        c = measure.approximate_polygon(c, tolerance=1.5)
        if len(c) < 4:
            continue
        ring = [to_ll(x - 1, y - 1) for y, x in c[:-1]]
        # areas ending at the cut: push that edge past 130°E so border points count inside
        ring = [[la, 130.5 if lo >= WA['lng_max'] - 0.1 else lo] for la, lo in ring]
        out.append(ring)
    return out


def area_deg2(mask):
    return round(float(mask.sum()) / (SX * SX), 1)   # rough, at mid latitudes


def extract(path):
    im = Image.open(path).convert('RGB')
    if im.size != SIZE:
        raise SystemExit(f'unexpected image size {im.size}: the map layout has changed, check the position fit')
    rgb = np.array(im)
    cls = classify(rgb)
    pink = wa_window(clean(cls['pink']))
    storms = wa_window(clean(cls['red'] | cls['pink']))
    wind = wa_window(clean(cls['wind']))
    rain = wa_window(clean(cls['rain']))
    res = {
        'storms': polygons(storms), 'severe': polygons(pink), 'severe_wind': polygons(wind), 'heavy_rain': polygons(rain),
        'px': {k: int(v.sum()) for k, v in (('storms', storms), ('severe', pink), ('severe_wind', wind), ('heavy_rain', rain))},
    }
    return im, res, {'storms': storms, 'severe': pink, 'severe_wind': wind, 'heavy_rain': rain}


def preview(im, masks, path):
    """Our own drawing: the traced areas over a plain outline grid (EWN's picture is not reused)."""
    x0, y0 = to_px(WA['lat_max'], WA['lng_min'])
    x1, y1 = to_px(WA['lat_min'], WA['lng_max'] + 1)
    box = (int(x0), int(y0), int(x1), int(y1))
    base = Image.new('RGB', im.size, (245, 245, 240))
    d = ImageDraw.Draw(base)
    for lo in range(112, 132, 2):
        x, _ = to_px(-20, lo); d.line([(x, 0), (x, im.size[1])], fill=(215, 215, 210))
    for la in range(-14, -38, -2):
        _, y = to_px(la, 120); d.line([(0, y), (im.size[0], y)], fill=(215, 215, 210))
    land = np.array(im).astype(int)
    sea = (land[:, :, 2] > land[:, :, 0] + 25) & (land[:, :, 2] > 90)
    edge = sea ^ ndimage.binary_erosion(sea, iterations=1)
    arr = np.array(base)
    arr[edge] = (120, 120, 120)
    for key, col in (('storms', (95, 179, 95)), ('severe', (224, 112, 32)), ('severe_wind', (180, 180, 0)), ('heavy_rain', (40, 150, 220))):
        m = masks[key]
        arr[m] = (arr[m] * 0.45 + np.array(col) * 0.55).astype(np.uint8)
    out = Image.fromarray(arr).crop(box)
    out = out.resize((out.width * 2, out.height * 2))
    out.save(path)


if __name__ == '__main__':
    im, res, masks = extract(sys.argv[1])
    json.dump(res, open(sys.argv[2], 'w'))
    print(json.dumps(res['px']), '| storm areas', len(res['storms']), '| severe areas', len(res['severe']))
    if len(sys.argv) > 3:
        preview(im, masks, sys.argv[3])

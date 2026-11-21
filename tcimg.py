"""
tcimg.py: post and story images of the Bureau's tropical cyclone Forecast Track Map (IDW6028x), in the same look as
the warning images (warnimg.py): the dark header, a map with the forecast track, and the details underneath.

  render(system, post_path, story_path)

`system` is one entry of data/cyclone-bom.json (relay.py, tc_tracks). The map: NASA GIBS Blue Marble with the newest
Himawari-9 infrared clouds over it, the Bureau's likely-track area, the forecast positions coloured by category, and
the places near the track.
"""
import datetime as dt
import math
import os
import re
import sys

from PIL import Image, ImageDraw

import warnimg as W
from warnimg import S, font, brand_header, wrap, DARK, ACCENT

CAT_COL = {'tropical low': (100, 181, 246), 'category 1': (255, 235, 59), 'category 2': (255, 179, 0),
           'category 3': (251, 140, 0), 'category 4': (229, 57, 53), 'category 5': (142, 36, 170)}
PLACES = [('Cocos (Keeling) Islands', -12.19, 96.83), ('Christmas Island', -10.49, 105.63), ('Broome', -17.96, 122.24),
          ('Port Hedland', -20.31, 118.6), ('Karratha', -20.74, 116.85), ('Exmouth', -21.93, 114.13), ('Onslow', -21.64, 115.11),
          ('Carnarvon', -24.88, 113.66), ('Geraldton', -28.77, 114.61), ('Perth', -31.95, 115.86), ('Derby', -17.3, 123.63),
          ('Kununurra', -15.77, 128.74), ('Kalumburu', -14.3, 126.64), ('Darwin', -12.46, 130.84), ('Denham', -25.93, 113.53),
          ('Newman', -23.36, 119.73), ('Fitzroy Crossing', -18.19, 125.57), ('Halls Creek', -18.23, 127.67)]
AWST = dt.timezone(dt.timedelta(hours=8))


def short(s):
    """The Bureau's words, a little shorter: km/h, km."""
    s = re.sub(r'\s+', ' ', s or '').strip()
    s = re.sub(r'kilometres per hour', 'km/h', s, flags=re.I)
    s = re.sub(r'kilometres', 'km', s, flags=re.I)
    s = re.sub(r'\s+([.,])', r'\1', s)
    return s.rstrip(' .')


def cat_of(p):
    c = (p.get('cat') or '').lower().replace('severe tropical cyclone ', '').replace('tropical cyclone ', '')
    return c if c in CAT_COL else ('tropical low' if 'low' in c else c)


def when(t, fmt='%a %-I%p'):
    try:
        x = dt.datetime.fromisoformat(t).astimezone(AWST)
        return x.strftime(fmt).replace('AM', 'am').replace('PM', 'pm')
    except Exception:
        return ''


def title_of(s):
    if s.get('cyclone'):
        return ('Tropical Cyclone ' if 'cyclone' not in s['cyclone'].lower() else '') + s['cyclone'].title()
    return s.get('name') or 'Tropical Low'


def stamp(s):
    p0 = (s.get('pts') or [{}])[0]
    return 'Bureau forecast track · ' + (s.get('analysis') or when(p0.get('t'), '%-I:%M %p AWST').replace('AM', 'am').replace('PM', 'pm')) \
        + ' ' + when(p0.get('t'), '%a %-d %b')


def extent(s, box_w, box_h):
    """lng0, lng1, k (px per radian), cm (Mercator centre) so the track, the likely-track area and the nearest place fit."""
    lons = [p['lng'] for p in s['pts']]; lats = [p['lat'] for p in s['pts']]
    for poly in s.get('cone') or []:
        lons += [c[0] % 360 for c in poly]; lats += [c[1] for c in poly]
    lo0, lo1, la0, la1 = min(lons), max(lons), min(lats), max(lats)
    # the nearest place, if it's not too far away, so people can see where it is
    cx, cy = (lo0 + lo1) / 2, (la0 + la1) / 2
    near = sorted(PLACES, key=lambda p: (p[2] - cx) ** 2 + (p[1] - cy) ** 2)[0]
    if abs(near[2] - cx) < 18 and abs(near[1] - cy) < 14:
        lo0, lo1, la0, la1 = min(lo0, near[2]), max(lo1, near[2]), min(la0, near[1]), max(la1, near[1])
    pad_x = max(2.5, (lo1 - lo0) * 0.18); pad_y = max(2.0, (la1 - la0) * 0.18)
    lo0 -= pad_x; lo1 += pad_x; la0 -= pad_y; la1 += pad_y
    m = W.merc
    span_x = math.radians(lo1 - lo0); span_y = m(la1) - m(la0)
    span_x = max(span_x, math.radians(12))
    # match the box's shape
    if span_x / span_y < box_w / box_h: span_x = span_y * box_w / box_h
    else: span_y = span_x * box_h / box_w
    cm = (m(la0) + m(la1)) / 2; clon = (lo0 + lo1) / 2
    return clon - math.degrees(span_x) / 2, clon + math.degrees(span_x) / 2, box_w / span_x, cm


def draw_map(img, box, s, sc=1.0):
    x0, y0, x1, y1 = box; Wb, Hb = x1 - x0, y1 - y0
    lng0, lng1, k, cm = extent(s, Wb, Hb)
    X = lambda lo: x0 + (lo % 360 - lng0) * math.pi / 180 * k
    Y = lambda la: y0 + Hb / 2 - (W.merc(la) - cm) * k
    lat_at = lambda y: math.degrees(2 * math.atan(math.exp(cm + (Hb / 2 - y) / k)) - math.pi / 2)
    lat_top, lat_bot = lat_at(0), lat_at(Hb)
    credit = 'Blue Marble: NASA'
    try:
        base = W.gibs_map('BlueMarble_ShadedRelief_Bathymetry', lng0, lng1, lat_top, lat_bot, Wb, Hb, k * math.pi / 180, cm)
    except Exception as e:  # noqa: BLE001
        print('base map:', e); base = Image.new('RGB', (Wb, Hb), (24, 52, 72))
    base = Image.blend(base, Image.new('RGB', base.size, (10, 25, 35)), 0.28)   # a little darker, so the track stands out
    try:   # the newest Himawari-9 infrared: cold cloud tops white
        import numpy as np
        bt, t = W.himawari_map(lng0, lng1, lat_top, lat_bot, Wb, Hb, k * math.pi / 180, cm)
        if bt is not None:
            a = np.clip((288.0 - np.nan_to_num(bt, nan=300.0)) / 78.0, 0, 1) ** 0.8 * 235
            cloud = Image.new('RGB', base.size, (240, 246, 250))
            base = Image.composite(cloud, base, Image.fromarray(a.astype('uint8'), 'L'))
            credit = 'Himawari-9 ' + t.astimezone(AWST).strftime('%-I:%M %p').lower() + ' AWST · Blue Marble: NASA'
    except Exception as e:  # noqa: BLE001
        print('clouds:', e)
    img.paste(base, (x0, y0))
    lay = Image.new('RGBA', img.size, (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    for poly in s.get('cone') or []:   # the Bureau's likely-track area
        pts = [(X(c[0]), Y(c[1])) for c in poly]
        if len(pts) > 2:
            d.polygon(pts, fill=(255, 255, 255, 46))
            d.line(pts + [pts[0]], fill=(255, 255, 255, 170), width=int(2 * S))
    img.paste(lay, (0, 0), lay); d = ImageDraw.Draw(img)
    # places
    fp = font(600, 17 * sc)
    for n, la, lo in PLACES:
        px, py = X(lo), Y(la)
        if not (x0 + 30 * S < px < x1 - 30 * S and y0 + 20 * S < py < y1 - 20 * S): continue
        r = 5 * S
        d.ellipse([px - r, py - r, px + r, py + r], fill=(255, 255, 255), outline=(13, 29, 35), width=int(2 * S))
        anchor, tx = ('rm', px - 10 * S) if px > x1 - 260 * S else ('lm', px + 10 * S)
        d.text((tx, py), n, font=fp, fill=(255, 255, 255), anchor=anchor, stroke_width=int(3 * S), stroke_fill=(13, 29, 35))
    # the track
    P = [(X(p['lng']), Y(p['lat'])) for p in s['pts']]
    d.line(P, fill=(13, 29, 35), width=int(7 * S), joint='curve')
    d.line(P, fill=(255, 255, 255), width=int(3 * S), joint='curve')
    ft = font(700, 16 * sc)
    for i, (p, (px, py)) in enumerate(zip(s['pts'], P)):
        c = CAT_COL.get(cat_of(p), (200, 200, 200)); r = (13 if i == 0 else 9) * S * sc
        d.ellipse([px - r, py - r, px + r, py + r], fill=c, outline=(13, 29, 35), width=int(3 * S))
        if i == 0 or p.get('h', 0) % 24 == 0:
            lab = 'Now' if i == 0 else when(p.get('t'))
            d.text((px + r + 8 * S, py), lab, font=ft, fill=(255, 255, 255), anchor='lm', stroke_width=int(3 * S), stroke_fill=(13, 29, 35))
    return credit


def legend_cats(d, s, x, y, size, th):
    seen = []
    for p in s['pts']:
        c = cat_of(p)
        if c in CAT_COL and c not in seen: seen.append(c)
    f = font(500, size); cx = x
    for c in seen:
        r = size * 0.42 * S
        d.ellipse([cx, y - r, cx + 2 * r, y + r], fill=CAT_COL[c], outline=(13, 29, 35), width=int(2 * S))
        lab = c.capitalize() if c == 'tropical low' else c.title()
        d.text((cx + 2 * r + 8 * S, y), lab, font=f, fill=th['text'], anchor='lm'); cx += 2 * r + 8 * S + d.textlength(lab, font=f) + 22 * S
    if s.get('cone'):
        d.rectangle([cx, y - size * 0.4 * S, cx + 26 * S, y + size * 0.4 * S], fill=(120, 140, 150), outline=(255, 255, 255), width=int(2 * S))
        d.text((cx + 34 * S, y), 'Likely track area', font=f, fill=th['text'], anchor='lm')


def facts(s):
    out = []
    inten = short(s.get('intensity'))
    m = re.search(r'(\d+) km/h with wind gusts to (\d+) km/h', inten)
    out.append(('Winds', (m.group(1) + ' km/h near the centre, gusts to ' + m.group(2) + ' km/h') if m else inten))
    if s.get('nearby') or s.get('location'):
        out.append(('Where', short(s.get('nearby') or s.get('location'))))
    if s.get('movement'): out.append(('Moving', short(s['movement'])))
    for lab, k in (('Warning zone', 'warning_zones'), ('Watch zone', 'watch_zones')):
        v = short(s.get(k))
        if v and v.lower() not in ('none', ''): out.append((lab, v))
    return out


def chance_text(s):
    m = re.search(r'(Very Low|Low|Moderate|High)\s*\((\d+)%\)\s*chance of developing into a tropical cyclone\s*([^.]*)', s.get('discussion') or '', re.I)
    if m: return m.group(1).capitalize() + ' (' + m.group(2) + '%) chance of becoming a tropical cyclone ' + m.group(3).strip()
    return ('%d%% chance of becoming a tropical cyclone' % s['chance']) if s.get('chance') is not None else ''


def render(s, post_path=None, story_path=None):
    th = DARK
    title = title_of(s)
    for path, Wd, Hd, hh, tsize, size, story in ((post_path, 1080, 1080, 130, 42, 20, False), (story_path, 1080, 1920, 170, 44, 30, True)):
        if not path: continue
        Wd, Hd, hh = Wd * S, Hd * S, hh * S
        pad, fh = 36 * S, 62 * S

        def panel(d, y):
            fb, fl = font(700, size * 1.3), font(400, size * 0.92)
            for ln in wrap(d, short(s.get('headline')) + '.', fb, Wd - 2 * pad)[:3]:
                d.text((pad, y), ln, font=fb, fill=th['text']); y += int(size * 1.65 * S)
            y += int(10 * S)
            ch = chance_text(s)
            if ch:
                ft = font(700, size * 0.82); tw = d.textlength(ch.upper(), font=ft) + 34 * S; hgt = int(size * 1.8 * S)
                while tw > Wd - 2 * pad and ft.size > 10 * S: ft = font(700, ft.size / S - 1); tw = d.textlength(ch.upper(), font=ft) + 34 * S
                c = (229, 57, 53) if re.match(r'high', ch, re.I) else (251, 140, 0) if re.match(r'moderate', ch, re.I) else (63, 120, 140)
                d.rounded_rectangle([pad, y, pad + tw, y + hgt], radius=hgt // 2, fill=c)
                d.text((pad + 17 * S, y + hgt / 2), ch.upper(), font=ft, fill=(255, 255, 255), anchor='lm'); y += hgt + int(16 * S)
            lw = max(d.textlength(a, font=font(700, size * 0.9)) for a, _ in facts(s)) + 18 * S
            for lab, val in facts(s):
                d.text((pad, y), lab, font=font(700, size * 0.9), fill=th['accent'])
                lines = wrap(d, val[:1].upper() + val[1:], fl, Wd - 2 * pad - lw)[:2]
                for ln in lines:
                    d.text((pad + lw, y), ln, font=fl, fill=th['text']); y += int(size * 1.32 * S)
                y += int(4 * S)
            if story and s.get('discussion'):
                y += int(12 * S)
                d.text((pad, y), 'Outlook', font=font(700, size * 0.92), fill=th['accent']); y += int(size * 1.45 * S)
                for para in [short(x) + '.' for x in re.split(r'\n\s*\n', s['discussion']) if x.strip()]:
                    for ln in wrap(d, para, fl, Wd - 2 * pad)[:6]:
                        d.text((pad, y), ln, font=fl, fill=th['text']); y += int(size * 1.32 * S)
                    y += int(10 * S)
            return y

        scratch = ImageDraw.Draw(Image.new('RGB', (Wd, Hd)))
        ph = panel(scratch, 0) + 34 * S
        map_bot = Hd - fh - ph - 46 * S
        img = Image.new('RGB', (Wd, Hd), th['bg']); d = ImageDraw.Draw(img)
        credit = draw_map(img, (0, hh, Wd, map_bot), s, 1.45 if story else 1.0)
        d = ImageDraw.Draw(img)
        brand_header(img, d, Wd, hh, title, stamp(s), tsize)
        d.text((Wd - 16 * S, map_bot - 12 * S), credit, font=font(500, 14 if not story else 17), fill=(235, 241, 243), anchor='rs',
               stroke_width=int(2 * S), stroke_fill=(13, 29, 35))
        legend_cats(d, s, pad, map_bot + 24 * S, size * 0.72, th)
        panel(d, map_bot + 52 * S)
        d.line([pad, Hd - fh, Wd - pad, Hd - fh], fill=th['rule'], width=int(1.5 * S))
        fs = 16 if not story else 20
        d.text((pad, Hd - fh / 2), 'Forecast track © Bureau of Meteorology', font=font(500, fs), fill=th['muted'], anchor='lm')
        d.text((Wd - pad, Hd - fh / 2), 'Unofficial copy · official: bom.gov.au', font=font(400, fs), fill=th['muted'], anchor='rm')
        img.resize((Wd // S, Hd // S), Image.LANCZOS).save(path, optimize=True)


if __name__ == '__main__':
    import json
    src, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    for s in json.load(open(src)).get('systems', []):
        base = os.path.join(out, 'tc-' + (s.get('id') or 'x'))
        render(s, base + '-post.png', base + '-story.png')
        print('made', base + '-post.png', base + '-story.png')

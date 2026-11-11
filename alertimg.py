"""Facebook story (1080 x 1920) and square post (1080 x 1080) images for the Rainfall project's extreme alerts:
heavy rainfall at gauges, and damaging wind gusts at stations. Drawn like the warning images (warnimg.py): the
site's header, the latest Himawari-9 satellite picture under the map, each station marked with its value, then the
readings, what to do, and the source line.

Input: the alert queue the Rainfall web app serves (?page=alertimg): a list of
  {id, kind: 'rain' | 'gust', title, time (ISO), items: [{name, district, src, lat, lng, vals: [{v, unit, label}]}]}
Usage: python alertimg.py <queue.json> <out dir> [--all]   (draws alerts not yet drawn into <out dir>, or all)
"""
import datetime as dt, json, os, re, sys
from PIL import Image, ImageDraw
import warnimg as W

S = W.S
KIND = {   # chip colour, title, what to do
    'rain': ((21, 101, 192), 'Heavy Rainfall Alert', 'Be alert for flash flooding. Avoid low-lying areas and never drive, walk or ride through floodwater.'),
    'gust': ((211, 47, 47), 'Damaging Wind Gust Alert', 'Secure loose items, keep clear of trees and powerlines, and take care on the roads.'),
}
SRC = {'BOM': 'BoM', 'DPIRD': 'DPIRD', 'DWER': 'DWER'}


def when(iso):
    t = dt.datetime.fromisoformat(iso.replace('Z', '+00:00')).astimezone(dt.timezone(dt.timedelta(hours=8)))
    return t.strftime('%a %-d %b, %-I:%M %p').replace('AM', 'am').replace('PM', 'pm') + ' AWST'


def val(v):
    return ('%g' % v['v']) + (' ' + v['unit'] if v['unit'] else '')


def summary(a):
    """The alert in words, as the email's copy-and-paste story text says it."""
    items = a['items']; i = items[0]
    where = i['name'] + (' (' + i['district'] + ')' if i.get('district') else '')
    if a['kind'] == 'gust':
        s = where + ' has recorded a wind gust of ' + val(i['vals'][0]) + '.'
    else:
        parts = [val(v) + ' in ' + v['label'] for v in i['vals']]
        s = where + ' has recorded heavy rainfall of ' + (', '.join(parts[:-1]) + ' and ' + parts[-1] if len(parts) > 1 else parts[0]) + '.'
    if len(items) > 1:
        s += ' ' + str(len(items) - 1) + ' more ' + ('station' if a['kind'] == 'gust' else 'gauge') + ('s' if len(items) > 2 else '') + ' below.'
    return s


def nearby(lo, la, centre, n=30):
    """Places to name around the stations: towns of 100+ people first, then the other towns and communities nearest
    the stations (collisions are sorted out when they're drawn)."""
    G = W.geo(); big, rest = [], []
    for k, v in G['places'].items():
        if v[3] != 'P' or not (la[0] <= v[0] <= la[1] and lo[0] <= v[1] <= lo[1]): continue
        if re.search(r'\b(range|ranges|river|hills?|plateau|gorge|island)\b', k): continue
        dist = min((v[0] - c[1]) ** 2 + (v[1] - c[0]) ** 2 for c in centre)
        (big if v[2] >= 100 else rest).append((-v[2] if v[2] >= 100 else dist, k))
    return [k.title() for _, k in sorted(big)[:10] + sorted(rest)[:n]]


def rivers(lo, la):
    """River lines in the frame (from the River page's map layer, when the job has it)."""
    path = os.environ.get('RIVER_LINES', 'out/rivers-lines.json')
    try: F = json.load(open(path))['features']
    except Exception:  # noqa: BLE001
        try:
            import urllib.request
            F = json.loads(urllib.request.urlopen('https://raw.githubusercontent.com/WWXWAU/wwxw-warnings/river-data/rivers-lines.json', timeout=60).read())['features']
        except Exception: return []  # noqa: BLE001
    out = []
    for f in F:
        g = f['geometry']; parts = g['coordinates'] if g['type'] == 'MultiLineString' else [g['coordinates']]
        for ln in parts:
            if any(lo[0] <= x <= lo[1] and la[0] <= y <= la[1] for x, y in ln): out.append(ln)
    return out


def render(a, story_path, post_path, style='light'):
    col, title, todo = KIND.get(a['kind'], KIND['rain'])
    th = W.DARK
    items = a['items'][:5]
    # the map: a plain map fitted to the stations (at least ~3 degrees across), with the places around them named
    pts = [[i['lng'], i['lat']] for i in items if i.get('lat') is not None]
    lo = [min(p[0] for p in pts) - 0.8, max(p[0] for p in pts) + 0.8]; la = [min(p[1] for p in pts) - 0.7, max(p[1] for p in pts) + 0.7]
    t_local = dt.datetime.fromisoformat(a['time'].replace('Z', '+00:00')).astimezone(dt.timezone(dt.timedelta(hours=8)))
    at = t_local.strftime('%-I:%M %p').replace('AM', 'am').replace('PM', 'pm')
    item = {'type': '', 'towns': [], '_frame': [[lo[0], la[0]], [lo[1], la[1]]], '_span': 3.0,
            '_near': nearby([lo[0] - 1.5, lo[1] + 1.5], [la[0] - 1.5, la[1] + 1.5], pts),
            '_lines': rivers([lo[0] - 2, lo[1] + 2], [la[0] - 2, la[1] + 2]),
            '_marks': [{'lat': i['lat'], 'lng': i['lng'], 'col': col, 'name': i['name'],
                        'label': val(i['vals'][0]) + (' in ' + i['vals'][0]['label'] if a['kind'] == 'rain' else ' gust'), 'when': at}
                       for i in items if i.get('lat') is not None]}
    sub = when(a['time'])

    def panel(d, Wd, y, pad, size, story):
        fp, fl, fs = W.font(700, size * 1.05), W.font(600, size * 0.86), W.font(400, size * 0.72)
        y = W.textbox(d, pad, y, Wd - 2 * pad, 'Heavy rainfall' if a['kind'] == 'rain' else 'Damaging winds', summary(a), size * (0.95 if story else 0.85), 4, th['accent'], th) + int(16 * S)
        for i in items:
            hh = int(size * 2.0 * S); x = pad
            for v in i['vals'][:3]:                        # value pills: 31.4 mm in 1 hr
                t = val(v) + (' in ' + v['label'] if a['kind'] == 'rain' else '')
                tw = d.textlength(t, font=fp) + 34 * S
                d.rounded_rectangle([x, y, x + tw, y + hh], radius=hh // 2, fill=col)
                d.text((x + 17 * S, y + hh / 2), t, font=fp, fill=(255, 255, 255), anchor='lm')
                x += tw + 12 * S
            y += hh + 8 * S
            d.text((pad, y), i['name'], font=fl, fill=th['text'])
            meta = ' · '.join(t for t in (i.get('district'), SRC.get(i.get('src'), i.get('src') or '') + ' station') if t)
            d.text((pad + d.textlength(i['name'], font=fl) + 14 * S, y + size * 0.16 * S), meta, font=fs, fill=th['muted'])
            y += int(size * 1.55 * S) + (14 if story else 8) * S
        y += 8 * S
        if story: y = W.textbox(d, pad, y, Wd - 2 * pad, 'What to do', todo, size * 0.9, 4, th['accent'], th) + int(10 * S)
        return y

    def footer(d, Wd, Hd, pad, fh, size):
        d.line([pad, Hd - fh, Wd - pad, Hd - fh], fill=th['rule'], width=int(1.5 * S))
        d.text((pad, Hd - fh / 2), 'Gauges: BoM, DPIRD, DWER' if a['kind'] == 'rain' else 'Stations: BoM, DPIRD', font=W.font(500, size), fill=th['muted'], anchor='lm')
        d.text((Wd - pad, Hd - fh / 2), 'Unofficial · warnings: bom.gov.au', font=W.font(400, size), fill=th['muted'], anchor='rm')

    for path, Wd, Hd, hh, tsize, size, story in ((post_path, 1080, 1080, 130, 42, 24, False), (story_path, 1080, 1920, 170, 46, 32, True)):
        if not path: continue
        Wd, Hd, hh = Wd * S, Hd * S, hh * S
        pad, fh = 40 * S, 66 * S
        ph = panel(ImageDraw.Draw(Image.new('RGB', (Wd, Hd))), Wd, 0, pad, size, story) + 30 * S
        map_bot = Hd - fh - ph - 20 * S
        img = Image.new('RGB', (Wd, Hd), th['bg']); d = ImageDraw.Draw(img)
        credit = W.draw_map(img, (0, hh, Wd, map_bot), item, col, style, rounded=False, brand=True)
        W.brand_header(img, d, Wd, hh, title, sub, tsize)
        if credit:
            d.text((Wd - 16 * S, map_bot - 12 * S), credit, font=W.font(500, 18 if story else 15), fill=(235, 241, 243), anchor='rs',
                   stroke_width=int(2 * S), stroke_fill=(13, 29, 35))
        panel(d, Wd, map_bot + 32 * S, pad, size, story)
        footer(d, Wd, Hd, pad, fh, 20 if story else 17)
        img.resize((Wd // S, Hd // S), Image.LANCZOS).save(path, optimize=True)


if __name__ == '__main__':
    src, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    for a in json.load(open(src)):
        base = os.path.join(out, a['id'])
        if os.path.exists(base + '-story.png') and '--all' not in sys.argv: continue
        try:
            render(a, base + '-story.png', base + '-post.png')
            print('made', base + '-story.png')
        except Exception as e:  # noqa: BLE001
            print('alert image failed', a.get('id'), e)

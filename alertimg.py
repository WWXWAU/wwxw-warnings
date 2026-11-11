"""Facebook story (1080 x 1920) and square post (1080 x 1080) images for the Rainfall project's extreme alerts:
heavy rainfall at gauges, and damaging wind gusts at stations. Drawn like the warning images (warnimg.py): the
site's header, the latest Himawari-9 satellite picture under the map, each station marked with its value, then the
readings, what to do, and the source line.

Input: the alert queue the Rainfall web app serves (?page=alertimg): a list of
  {id, kind: 'rain' | 'gust', title, time (ISO), items: [{name, district, src, lat, lng, vals: [{v, unit, label}]}]}
Usage: python alertimg.py <queue.json> <out dir> [--all]   (draws alerts not yet drawn into <out dir>, or all)
"""
import datetime as dt, json, os, sys
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


def render(a, story_path, post_path, style='clouds'):
    col, title, todo = KIND.get(a['kind'], KIND['rain'])
    th = W.DARK
    items = a['items'][:5]
    # the map: fit the stations with room around them (at least ~6 degrees across, as the warnings)
    pts = [[i['lng'], i['lat']] for i in items if i.get('lat') is not None]
    lo = [min(p[0] for p in pts) - 1.2, max(p[0] for p in pts) + 1.2]; la = [min(p[1] for p in pts) - 1.0, max(p[1] for p in pts) + 1.0]
    item = {'type': '', 'towns': [], '_frame': [[lo[0], la[0]], [lo[1], la[1]]],
            '_marks': [{'lat': i['lat'], 'lng': i['lng'], 'col': col, 'label': val(i['vals'][0])} for i in items if i.get('lat') is not None]}
    sub = when(a['time'])

    def panel(d, Wd, y, pad, size, story):
        fp, fl, fs = W.font(700, size * 1.05), W.font(600, size * 0.86), W.font(400, size * 0.72)
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

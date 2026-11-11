"""Promo video for the four public pages (vertical 1080 x 1920, 30 fps), from phone footage of the live site
(tools/promo_capture.py -> promo-shots branch). Each page is a scene: a caption at the top and the phone screen below,
slowly zooming or scrolling, shots cross-fading. Scenes are encoded one file each and joined (concat, no re-encode),
so the full promo and the per-page snippets share the same scene files.

Usage: python tools/promo_video.py <shots dir> <out dir> [--frames]   (--frames: just a few still frames to check)
"""
import os, subprocess, sys
from PIL import Image, ImageDraw, ImageFilter
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import warnimg as Wm

Wm.S = 1
F = lambda wt, sz: Wm.font(wt, sz)
W, H, FPS = 1080, 1920, 30
BG, BG2, ACC, TXT, MUT = (13, 29, 35), (22, 48, 58), (63, 193, 201), (240, 246, 247), (157, 182, 189)
PX, PY, PW = 120, 400, 840          # the phone screen: left, top, width (height from the 1080 x 1920 shots)
PH = int(PW * 1920 / 1080)
XF = 0.35                           # cross-fade between shots (s)

SCENES = {   # page: (label, colour, [(shot, seconds, headline, motion)])  motion: zoom focus (x, y fractions) or ('scroll', from, to)
    'rain': ('WA Rainfall', (63, 140, 220), [
        ('rain-3-7Days', 3.4, '700+ rain gauges, updated every 15 minutes', (0.45, 0.35)),
        ('rain-5-lightning', 3.2, 'Lightning strikes across WA', (0.6, 0.3)),
        ('rain-6-top10', 3.4, 'The heaviest falls, ranked', (0.5, 0.75))]),
    'obs': ('Live Observations', (240, 150, 60), [
        ('obs-2-Temperature', 3.3, 'Temperature, wind and rain from 700+ stations', (0.5, 0.4)),
        ('obs-3-Maxgust24hrs', 3.2, 'BoM warnings right on the map', (0.62, 0.42)),
        ('obs-6-flyto', 3.3, 'Live lightning strikes', (0.5, 0.75))]),
    'river': ('River Levels', (63, 193, 201), [
        ('river-1-start', 3.0, 'Every WA river gauge, live', (0.5, 0.3)),
        ('river-3-waves', 3.6, 'Flood waves tracked river to river', (0.5, 0.45)),
        ('river-4-gauge', 3.6, 'Arrival times learnt from 20 years of floods', (0.5, 0.75)),
        ('river-6-shire', 3.2, 'Road closures from Main Roads and the shires', (0.5, 0.4))]),
    'ripper': ('Ripper Weather', (250, 196, 60), [
        ('ripper-1-start', 3.4, "Where's the best weather in WA today?", (0.5, 0.45)),
        ('ripper-2-tomorrow', 3.2, 'And tomorrow, for planning the weekend', (0.5, 0.45))]),
}


def wrap(d, text, f, w):
    out, line = [], ''
    for word in text.split():
        t = (line + ' ' + word).strip()
        if d.textlength(t, font=f) > w and line: out.append(line); line = word
        else: line = t
    return out + [line]


def backdrop():
    im = Image.new('RGB', (W, H), BG); d = ImageDraw.Draw(im)
    for y in range(H):                                   # a soft vertical gradient
        t = y / H; d.line([(0, y), (W, y)], fill=tuple(int(BG[i] + (BG2[i] - BG[i]) * t * 0.9) for i in range(3)))
    return im


BACK = backdrop()
LOGO = Image.open(os.path.join(Wm.ASSETS, 'logo-dark.png')).convert('RGBA')
_shots = {}


def shot(name):
    if name not in _shots: _shots[name] = Image.open(os.path.join(SHOTS, 'phone-dark-' + name + '.jpg')).convert('RGB')
    return _shots[name]


def screen(name, t, dur, focus):
    """The phone screen at time t of a shot: a slow zoom (1.00 -> 1.07) towards the focus point."""
    im = shot(name); z = 1.0 + 0.07 * (t / dur)
    cw, ch = im.width / z, im.height / z
    cx, cy = focus[0] * im.width, focus[1] * im.height
    x0 = min(max(cx - cw / 2, 0), im.width - cw); y0 = min(max(cy - ch / 2, 0), im.height - ch)
    return im.resize((PW, PH), Image.BILINEAR, box=(x0, y0, x0 + cw, y0 + ch))


MASK = Image.new('L', (PW, PH), 0); ImageDraw.Draw(MASK).rounded_rectangle([0, 0, PW - 1, PH - 1], radius=44, fill=255)
SHADOW = Image.new('RGBA', (W, H), (0, 0, 0, 0))
ImageDraw.Draw(SHADOW).rounded_rectangle([PX - 6, PY + 14, PX + PW + 6, PY + PH + 22], radius=50, fill=(0, 0, 0, 150))
SHADOW = SHADOW.filter(ImageFilter.GaussianBlur(22))


def caption(im, label, col, head, alpha=1.0):
    """The scene's label chip and the shot's headline, above the phone."""
    lay = Image.new('RGBA', (W, PY), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    lh = 70; lg = LOGO.resize((int(LOGO.width * lh / LOGO.height), lh), Image.LANCZOS); lay.alpha_composite(lg, ((W - lg.width) // 2, 34))
    fl = F(700, 30); tw = d.textlength(label.upper(), font=fl)
    d.rounded_rectangle([(W - tw) / 2 - 22, 130, (W + tw) / 2 + 22, 178], radius=24, fill=col)
    d.text((W / 2, 154), label.upper(), font=fl, fill=BG, anchor='mm')
    fh = F(800, 60); lines = wrap(d, head, fh, W - 120)
    if len(lines) > 2: fh = F(800, 50); lines = wrap(d, head, fh, W - 100)
    y = 200 + (2 - len(lines)) * 34
    a = int(255 * alpha)
    for ln in lines:
        d.text((W / 2, y), ln, font=fh, fill=TXT[:3] + (a,), anchor='ma'); y += fh.size + 10
    im.paste(lay, (0, 0), lay)


def scene_frames(key):
    label, col, shots = SCENES[key]
    total = sum(s[1] for s in shots); n = int(total * FPS)
    starts = []; t0 = 0
    for s in shots: starts.append(t0); t0 += s[1]
    for f in range(n):
        t = f / FPS
        i = max(k for k in range(len(shots)) if starts[k] <= t)
        name, dur, head, focus = shots[i]; lt = t - starts[i]
        scr = screen(name, lt, dur, focus); hd, ha = head, 1.0
        if i + 1 < len(shots) and lt > dur - XF:          # cross-fade into the next shot
            a = (lt - (dur - XF)) / XF; nx = shots[i + 1]
            scr = Image.blend(scr, screen(nx[0], 0, nx[1], nx[3]), a)
            hd, ha = (head, 1 - a * 2) if a < 0.5 else (nx[2], (a - 0.5) * 2)
        im = BACK.copy(); im.paste(SHADOW, (0, 0), SHADOW)
        im.paste(scr, (PX, PY), MASK)
        caption(im, label, col, hd, max(0.0, min(1.0, ha)))
        fade = min(1.0, t / 0.3, (total - t) / 0.3)       # in from and out to the backdrop
        if fade < 1: im = Image.blend(BACK, im, max(0.0, fade))
        yield im


def card_frames(kind, secs, sub=''):
    """Title and end cards."""
    n = int(secs * FPS)
    for f in range(n):
        t = f / FPS; im = BACK.copy(); d = ImageDraw.Draw(im)
        a = min(1.0, t / 0.4, (secs - t) / 0.35)
        lh = 210 if kind == 'intro' else 150
        lg = LOGO.resize((int(LOGO.width * lh / LOGO.height), lh), Image.LANCZOS)
        s = 1 + 0.03 * t / secs
        lg = lg.resize((int(lg.width * s), int(lg.height * s)), Image.LANCZOS)
        im.paste(lg, ((W - lg.width) // 2, 560 - lg.height // 2), lg)
        if kind == 'intro':
            d.text((W / 2, 780), 'WA weather.', font=F(800, 92), fill=TXT, anchor='ma')
            d.text((W / 2, 890), 'Live. Free.', font=F(800, 92), fill=ACC, anchor='ma')
            if sub: d.text((W / 2, 1060), sub, font=F(600, 44), fill=MUT, anchor='ma')
        else:
            d.text((W / 2, 720), 'westweatherwatchers.com', font=F(800, 64), fill=TXT, anchor='ma')
            d.text((W / 2, 820), 'Free · updated live', font=F(600, 46), fill=ACC, anchor='ma')
            y = 960
            for p in sub.split('|') if sub else []:
                d.text((W / 2, y), p, font=F(600, 40), fill=MUT, anchor='ma'); y += 58
            d.text((W / 2, H - 150), 'Not for the protection of life or property.', font=F(400, 30), fill=MUT, anchor='ma')
            d.text((W / 2, H - 105), 'Official warnings: bom.gov.au', font=F(400, 30), fill=MUT, anchor='ma')
        if a < 1: im = Image.blend(BACK, im, max(0.0, a))
        yield im


def encode(frames, path):
    tmp = path[:-4] + '.part.mp4'
    p = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', str(FPS), '-i', '-',
                          '-c:v', 'libx264', '-crf', '19', '-preset', 'veryfast', '-pix_fmt', 'yuv420p', '-r', str(FPS), tmp], stdin=subprocess.PIPE)
    for im in frames: p.stdin.write(im.tobytes())
    p.stdin.close()
    if p.wait() == 0: os.replace(tmp, path)
    else: raise SystemExit('ffmpeg failed for ' + path)


def concat(parts, path):
    lst = path + '.txt'
    open(lst, 'w').write(''.join("file '%s'\n" % os.path.abspath(p) for p in parts))
    tmp = path[:-4] + '.part.mp4'
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', '-movflags', '+faststart', tmp], check=True)
    os.replace(tmp, path); os.remove(lst)


if __name__ == '__main__':
    SHOTS, OUT = sys.argv[1], sys.argv[2]
    os.makedirs(OUT, exist_ok=True)
    if '--frames' in sys.argv:   # a few stills at the busiest moments
        for key in SCENES:
            fr = list(scene_frames(key)); n = len(fr)
            for k in (int(n * 0.2), int(n * 0.55)): fr[k].save(os.path.join(OUT, 'check-%s-%d.jpg' % (key, k)), quality=88)
        next(x for i, x in enumerate(card_frames('intro', 3.0, 'Rainfall · Live Obs · Rivers · Ripper Weather')) if i == 45).save(os.path.join(OUT, 'check-intro.jpg'))
        next(x for i, x in enumerate(card_frames('outro', 4.0, 'Rainfall · Live Obs|River Levels · Ripper Weather')) if i == 60).save(os.path.join(OUT, 'check-outro.jpg'))
        sys.exit()
    sc = os.path.join(OUT, 'scenes'); os.makedirs(sc, exist_ok=True)
    for key in SCENES:
        encode(scene_frames(key), os.path.join(sc, key + '.mp4')); print('scene', key)
    encode(card_frames('intro', 3.0, 'Rainfall · Live Obs · Rivers · Ripper Weather'), os.path.join(sc, 'intro.mp4'))
    encode(card_frames('outro', 4.0, 'Rainfall · Live Obs|River Levels · Ripper Weather'), os.path.join(sc, 'outro.mp4'))
    names = {'rain': 'WA Rainfall', 'obs': 'Live Observations', 'river': 'River Levels', 'ripper': 'Ripper Weather'}
    for key, nm in names.items():
        encode(card_frames('intro', 2.0, 'Sneak peek: ' + nm), os.path.join(sc, 'intro-' + key + '.mp4'))
        encode(card_frames('outro', 2.6, nm), os.path.join(sc, 'outro-' + key + '.mp4'))
    concat([os.path.join(sc, x + '.mp4') for x in ('intro', 'rain', 'obs', 'river', 'ripper', 'outro')], os.path.join(OUT, 'wwxw-promo.mp4'))
    for key in names:
        concat([os.path.join(sc, x + '.mp4') for x in ('intro-' + key, key, 'outro-' + key)], os.path.join(OUT, 'wwxw-sneak-peek-%s.mp4' % key))
    print('done')

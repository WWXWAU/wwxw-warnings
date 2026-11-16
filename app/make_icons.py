"""App icons from the WWXW logo's emblem: launcher icons (plain, round, adaptive foreground) and the white
notification icon (a lightning bolt). Run from app/: python3 make_icons.py  -> res/"""
import os
from PIL import Image, ImageDraw
logo = Image.open('../wxvideo/logo.png').convert('RGBA')
emb = logo.crop((0, 0, 470, 457))
ImageDraw.Draw(emb).rectangle((438, 270, 470, 457), fill=(0, 0, 0, 0))   # the W of WATCHERS starts here
emb = emb.crop(emb.getbbox())
BG, DISC = (14, 42, 51, 255), (238, 244, 245, 255)


def fit(e, s):
    r = min(s / e.width, s / e.height); return e.resize((max(1, int(e.width * r)), max(1, int(e.height * r))), Image.LANCZOS)


def square(size):
    im = Image.new('RGBA', (size, size), BG); d = ImageDraw.Draw(im); m = int(size * 0.12)
    d.ellipse((m, m, size - m, size - m), fill=DISC)
    e = fit(emb, int(size * 0.56)); im.alpha_composite(e, ((size - e.width) // 2, (size - e.height) // 2)); return im


os.makedirs('res', exist_ok=True)
square(1024).save('res/icon-1024.png')
for k, f in {'mdpi': 1, 'hdpi': 1.5, 'xhdpi': 2, 'xxhdpi': 3, 'xxxhdpi': 4}.items():
    os.makedirs('res/mipmap-' + k, exist_ok=True); os.makedirs('res/drawable-' + k, exist_ok=True)
    L = int(48 * f); sq = square(L); sq.save('res/mipmap-%s/ic_launcher.png' % k)
    m = Image.new('L', (L, L), 0); ImageDraw.Draw(m).ellipse((0, 0, L - 1, L - 1), fill=255)
    o = Image.new('RGBA', (L, L)); o.paste(sq, (0, 0), m); o.save('res/mipmap-%s/ic_launcher_round.png' % k)
    F = int(108 * f); fg = Image.new('RGBA', (F, F)); d = ImageDraw.Draw(fg); c, R = F / 2, F * 0.31   # adaptive: safe zone is the middle 66/108
    d.ellipse((c - R, c - R, c + R, c + R), fill=DISC); e = fit(emb, int(F * 0.42)); fg.alpha_composite(e, (int(c - e.width / 2), int(c - e.height / 2)))
    fg.save('res/mipmap-%s/ic_launcher_foreground.png' % k)
    N = int(24 * f); n = Image.new('RGBA', (N, N)); u = N / 24
    ImageDraw.Draw(n).polygon([(13 * u, 2 * u), (4 * u, 14 * u), (11 * u, 14 * u), (10 * u, 22 * u), (19 * u, 10 * u), (12 * u, 10 * u)], fill=(255, 255, 255, 255))
    n.save('res/drawable-%s/ic_stat_wwxw.png' % k)

"""Probe: do the MUR SST tile colours match NASA's colour table exactly (so temperatures can be read back)?"""
import urllib.request, json, io, os, subprocess, sys
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', 'pillow'], check=True)
from PIL import Image
cm = json.load(open(os.path.join(os.path.dirname(__file__), 'sstcm.json'))); T = {(r, g, b): v for r, g, b, v in cm}
for z, x, y in ((3, 6, 4), (4, 13, 8), (5, 26, 17)):
    u = 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/GHRSST_L4_MUR_Sea_Surface_Temperature/default/default/GoogleMapsCompatible_Level7/%d/%d/%d.png' % (z, y, x)
    im = Image.open(io.BytesIO(urllib.request.urlopen(u, timeout=60).read())); print(z, x, y, im.mode, im.size)
    px = list(im.convert('RGBA').getdata()); sea = [p for p in px if p[3] >= 128]
    hit = sum(1 for p in sea if p[:3] in T); vals = sorted(T[p[:3]] for p in sea if p[:3] in T)
    print('  sea px', len(sea), 'exact colour matches', hit, 'temps', vals[0] if vals else None, '-', vals[-1] if vals else None, 'warm >=26.5:', sum(v >= 26.5 for v in vals))

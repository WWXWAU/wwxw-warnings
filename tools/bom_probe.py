"""Probe: the full GIBS colour map for MUR SST (for reading temperatures back off the tiles)."""
import urllib.request, re, json
x = urllib.request.urlopen('https://gibs.earthdata.nasa.gov/colormaps/v1.3/GHRSST_Sea_Surface_Temperature.xml', timeout=60).read().decode()
out = []
for e in re.findall(r'<ColorMapEntry[^>]*>', x):
    rgb = re.search(r'rgb="(\d+),(\d+),(\d+)"', e); v = re.search(r'value="([\[\(])([-\d.]+|-INF),([-\d.]+|INF)[\)\]]"', e)
    if not rgb or not v or 'transparent="true"' in e: continue
    lo = v.group(2); hi = v.group(3)
    out.append([int(rgb.group(1)), int(rgb.group(2)), int(rgb.group(3)), lo, hi])
print('CM', json.dumps(out, separators=(',', ':')))

"""Probe: NASA GIBS sea surface temperature tiles for the cyclones page (layer names, tile sets, latest dates)."""
import urllib.request, re, datetime as dt
cap = urllib.request.urlopen('https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/1.0.0/WMTSCapabilities.xml', timeout=120).read().decode()
for blk in re.findall(r'<Layer>(.*?)</Layer>', cap, re.S):
    ident = re.search(r'<ows:Identifier>([^<]+)', blk).group(1)
    if not re.search(r'Sea_Surface_Temp|SST', ident, re.I): continue
    tms = re.findall(r'<TileMatrixSet>([^<]+)', blk); dv = re.search(r'<Default>([^<]+)', blk); ext = re.findall(r'<Value>([^<]+)</Value>', blk)
    fmt = re.findall(r'<Format>([^<]+)', blk)
    print(ident, tms, 'default', dv.group(1) if dv else None, 'range', ext[-1][:60] if ext else None, fmt)
for lay, tm in (('GHRSST_L4_MUR_Sea_Surface_Temperature', 'GoogleMapsCompatible_Level7'),):
    for t in ('default', (dt.date.today() - dt.timedelta(days=1)).isoformat(), (dt.date.today() - dt.timedelta(days=2)).isoformat()):
        u = 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/%s/default/%s/%s/3/4/6.png' % (lay, t, tm)
        try: r = urllib.request.urlopen(u, timeout=60); b = r.read(); print(t, r.status, len(b), r.headers.get('Access-Control-Allow-Origin'))
        except Exception as e: print(t, 'fail', e)

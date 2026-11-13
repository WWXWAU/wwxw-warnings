"""Probe: the GIBS colour maps for the MUR SST layers (for the cyclones page key)."""
import urllib.request, re
cap = urllib.request.urlopen('https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/1.0.0/WMTSCapabilities.xml', timeout=120).read().decode()
for blk in re.findall(r'<Layer>(.*?)</Layer>', cap, re.S):
    ident = re.search(r'<ows:Identifier>([^<]+)', blk).group(1)
    if ident not in ('GHRSST_L4_MUR_Sea_Surface_Temperature', 'GHRSST_L4_MUR_Sea_Surface_Temperature_Anomalies'): continue
    hrefs = re.findall(r'href="([^"]+)"', blk); print('==', ident, hrefs)
    for u in hrefs:
        if 'colormap' in u.lower() and u.endswith('.xml'):
            x = urllib.request.urlopen(u, timeout=60).read().decode()
            ents = re.findall(r'<ColorMapEntry[^>]*>', x)
            print(len(ents), 'entries'); [print('  ', e) for e in ents[::max(1, len(ents) // 30)]]
            leg = re.findall(r'<LegendEntry[^>]*>', x); print(len(leg), 'legend'); [print('  L', e) for e in leg[::max(1, len(leg) // 25)]]

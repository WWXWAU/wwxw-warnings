"""Probe: the GIBS colour maps for the MUR SST layers (for the cyclones page key)."""
import urllib.request, re
cap = urllib.request.urlopen('https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/1.0.0/WMTSCapabilities.xml', timeout=120).read().decode()
for blk in re.findall(r'<Layer>(.*?)</Layer>', cap, re.S):
    ident = re.search(r'<ows:Identifier>([^<]+)', blk).group(1)
    if ident in ('GHRSST_L4_MUR_Sea_Surface_Temperature', 'GHRSST_L4_MUR_Sea_Surface_Temperature_Anomalies'):
        for u in re.findall(r'xlink:href="([^"]+colormaps[^"]+\.xml)"', blk):
            print('==', ident, u)
            x = urllib.request.urlopen(u, timeout=60).read().decode()
            ents = re.findall(r'<ColorMapEntry rgb="([^"]+)"[^>]*?(?:transparent="(\w+)")?[^>]*?(?:sourceValue="([^"]+)")?[^>]*?label="([^"]*)"', x)
            print(len(ents), 'entries')
            for e in ents[::max(1, len(ents) // 40)]: print('  ', e)
            print('legend:', re.findall(r'<LegendEntry rgb="([^"]+)"[^>]*tooltip="([^"]+)"', x)[:60])

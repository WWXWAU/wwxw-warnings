"""Probe: the GIBS colour maps for the MUR SST layers (for the cyclones page key)."""
import urllib.request, re
for name in ('GHRSST_L4_MUR_Sea_Surface_Temperature', 'GHRSST_L4_MUR_Sea_Surface_Temperature_Anomalies'):
    for v in ('v1.3', 'v1.2', 'v1.0'):
        u = 'https://gibs.earthdata.nasa.gov/colormaps/%s/%s.xml' % (v, name)
        try: x = urllib.request.urlopen(u, timeout=60).read().decode()
        except Exception as e: print(u, e); continue
        print('==', u, len(x))
        ents = re.findall(r'<ColorMapEntry[^>]*>', x)
        print(len(ents), 'entries'); [print('  ', e) for e in ents[::max(1, len(ents) // 30)]]
        leg = re.findall(r'<LegendEntry[^>]*>', x); print(len(leg), 'legend'); [print('  L', e) for e in leg[::max(1, len(leg) // 30)]]
        break

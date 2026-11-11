"""Probe 36: geometry formats in the shire road report API."""
import json, urllib.request
BUA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36', 'Accept': 'application/json, */*', 'X-Requested-With': 'XMLHttpRequest'}
seen = set()
for h in ['www.carnarvon.wa.gov.au', 'www.esperance.wa.gov.au', 'www.ckb.wa.gov.au', 'eastpilbara.wa.gov.au', 'www.uppergascoyne.wa.gov.au', 'www.porthedland.wa.gov.au', 'www.perenjori.wa.gov.au']:
    d = json.loads(urllib.request.urlopen(urllib.request.Request('https://%s/api/roadreports/getReportItems?displayType=map' % h, headers=BUA), timeout=60).read())
    for m in d['mapData']:
        md = m.get('MappingData')
        keys = [k for k in m if k not in ('MappingData',)]
        try: g = json.loads(md) if md else None
        except Exception: g = 'BAD'
        kinds = tuple(sorted(set(x.get('type') for x in g))) if isinstance(g, list) else (str(type(g)),)
        sig = (m.get('MapType'), kinds)
        if sig in seen: continue
        seen.add(sig)
        print('\n##', h, m['Title'], sig)
        if isinstance(g, list):
            for x in g[:2]: print('  ', json.dumps(x)[:600])
        else:
            print('  no MappingData; other fields:', {k: m[k] for k in m if k not in ('MappingData', 'Type', 'Categories', 'MarkerDescription') and m[k] not in (None, '', [])})

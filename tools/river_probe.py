"""Probe 35: shire road reports via the shared CMS API - statuses, geometry types, freshness."""
import json, collections, urllib.request, re
BUA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36', 'Accept': 'application/json, */*', 'X-Requested-With': 'XMLHttpRequest'}
HOSTS = ['www.swek.wa.gov.au', 'eastpilbara.wa.gov.au', 'www.sdwk.wa.gov.au', 'www.porthedland.wa.gov.au', 'www.carnarvon.wa.gov.au', 'www.uppergascoyne.wa.gov.au',
         'www.meekashire.wa.gov.au', 'www.cue.wa.gov.au', 'www.yalgoo.wa.gov.au', 'www.murchison.wa.gov.au', 'www.leonora.wa.gov.au', 'www.dundas.wa.gov.au',
         'www.esperance.wa.gov.au', 'www.perenjori.wa.gov.au', 'www.ckb.wa.gov.au', 'www.menzies.wa.gov.au', 'www.hallscreek.wa.gov.au', 'www.broome.wa.gov.au']
for h in HOSTS:
    try:
        d = json.loads(urllib.request.urlopen(urllib.request.Request('https://%s/api/roadreports/getReportItems?displayType=map' % h, headers=BUA), timeout=60).read())
    except Exception as e: print('\n##', h, 'ERR', str(e)[:80]); continue
    M = d.get('mapData') or []
    print('\n##', h, len(M), 'items; types', collections.Counter(m['Type']['Name'] for m in M), 'map types', collections.Counter(m.get('MapType') for m in M))
    geo = collections.Counter()
    for m in M:
        try: g = json.loads(m.get('MappingData') or '[]'); geo.update(x.get('type') for x in g)
        except Exception: geo['bad'] += 1
    print('  geometry', geo, '| latest update', max((m.get('LastUpdated') or '' for m in M), key=lambda s: s[-20:]) if M else '')
    for m in [m for m in M if m['Type']['Name'] != 'Open'][:8]:
        print('  -', m['Type']['Name'], '|', m['Title'], '|', m.get('SubTitle'), '|', m.get('LastUpdated'), '|', m.get('PublishFrom'), '-', m.get('PublishTo'), '|', re.sub(r'<[^>]+>', ' ', m.get('MarkerDescription') or '')[:160])

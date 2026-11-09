"""Probe 9: Main Roads travel map layers (water level / floodway gauges?)."""
import json, re, sys
sys.path.insert(0, 'rivers'); import rivers as RV
def J(u):
    try: return json.loads(RV.get(u, 90, 2))
    except Exception as e: print('FAILED', u, e); return {}
for s in ['TravelInformation', 'Apps/TravelMap', 'Overlay']:
    j = J('https://gisservices.mainroads.wa.gov.au/arcgis/rest/services/%s/MapServer?f=json' % s)
    print(s, [(l['id'], l['name']) for l in j.get('layers', [])])
B = 'https://travelmap.mainroads.wa.gov.au'
for u in [B + '/Home/Map', B + '/']:
    t = RV.get(u, 60, 1); print('\n==', u, len(t))
    js = sorted(set(re.findall(r'src="([^"]+\.js[^"]*)"', t))); print('scripts', js)
    for s in js:
        if s.startswith('http') and 'travelmap' not in s: continue
        try: c = RV.get(s if s.startswith('http') else B + s, 60, 1)
        except Exception as e: print('fail', s, e); continue
        hits = sorted(set(re.findall(r'["\'](/[A-Za-z]+/[A-Za-z]+[^"\']{0,60})["\']', c)))
        print('  ', s, len(c), [h for h in hits if re.search(r'(?i)api|get|flood|water|gauge|level|camera|incident|closure', h)][:80])
        for m in re.finditer(r'(?i)(water ?level|gauge|floodway)', c):
            print('     ...', c[max(0, m.start() - 150):m.end() + 150].replace('\n', ' ')[:300]); break
services2 = J('https://services2.arcgis.com/cHGEnmsJ165IBJRM/ArcGIS/rest/services?f=json')
print('services2 water/flood/gauge:', [s['name'] for s in services2.get('services', []) if re.search(r'(?i)flood|water|gauge|level|river|creek|weather|camera', s['name'])])

"""Probe 8: Main Roads WA services: road closures (flooding) and any water level gauges."""
import json, re, sys
sys.path.insert(0, 'rivers'); import rivers as RV
def J(u):
    try: return json.loads(RV.get(u, 90, 2))
    except Exception as e: print('FAILED', u, e); return {}
for base in ['https://services2.arcgis.com/cHGEnmsJ165IBJRM/ArcGIS/rest/services', 'https://gisservices.mainroads.wa.gov.au/arcgis/rest/services']:
    j = J(base + '?f=json'); sv = [s['name'] + ':' + s['type'] for s in j.get('services', [])]; print(base, len(sv))
    print('  all:', sv[:400])
    for f in j.get('folders', []):
        jj = J(base + '/' + f + '?f=json'); print('  folder', f, [s['name'] + ':' + s['type'] for s in jj.get('services', [])])
c = J('https://services2.arcgis.com/cHGEnmsJ165IBJRM/arcgis/rest/services/WebEoc_RoadClosures/FeatureServer?f=json'); print('CLOSURES layers:', [(l['id'], l['name']) for l in c.get('layers', [])])
for l in c.get('layers', []):
    q = J('https://services2.arcgis.com/cHGEnmsJ165IBJRM/arcgis/rest/services/WebEoc_RoadClosures/FeatureServer/%d/query?where=1%%3D1&outFields=*&f=json&resultRecordCount=3' % l['id'])
    print(' layer', l['id'], l['name'], 'geom', q.get('geometryType'), 'n?', len(q.get('features', [])))
    for ft in q.get('features', [])[:2]: print('   ', json.dumps(ft['attributes'])[:900])
t = RV.get('https://www.mainroads.wa.gov.au/travelmap/', 60, 1)
print('TRAVELMAP urls:', sorted(set(re.findall(r'https?://[^"\'\s)]+', t)))[:80])

"""Probe 15: DWER hydrographic catchment layers — fields and samples."""
import json, sys
sys.path.insert(0, 'rivers'); import rivers as RV
B = 'https://public-services.slip.wa.gov.au/public/rest/services/SLIP_Public_Services/Water/MapServer/'
def J(u):
    try: return json.loads(RV.get(u, 120, 1))
    except Exception as e: print('FAILED', u, e); return {}
for l in (31, 32, 33, 34, 61, 7):
    j = J(B + '%d?f=json' % l)
    print('\n== layer', l, j.get('name'), j.get('geometryType'), 'maxRecords', j.get('maxRecordCount'))
    print('  fields:', [(f['name'], f.get('alias')) for f in j.get('fields', [])])
    c = J(B + '%d/query?where=1%%3D1&returnCountOnly=true&f=json' % l); print('  count', c.get('count'))
    s = J(B + '%d/query?where=1%%3D1&outFields=*&returnGeometry=false&resultRecordCount=4&f=json' % l)
    for f in s.get('features', [])[:4]: print('   ', f['attributes'])
# the catchment polygon that contains Walyunga (616011)
s = J(B + '32/query?geometry=116.0685,-31.7505&geometryType=esriGeometryPoint&inSR=4326&spatialRel=esriSpatialRelIntersects&outFields=*&returnGeometry=false&f=json')
print('\ncatchment at Walyunga:', [f['attributes'] for f in s.get('features', [])])
s = J(B + '33/query?geometry=116.0685,-31.7505&geometryType=esriGeometryPoint&inSR=4326&spatialRel=esriSpatialRelIntersects&outFields=*&returnGeometry=false&f=json')
print('subcatchment at Walyunga:', [f['attributes'] for f in s.get('features', [])])

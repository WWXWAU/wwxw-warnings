"""Probe 18: DWER hydrography lines (layer 7) — how many per level, for drawing the rivers."""
import json, sys, urllib.parse
sys.path.insert(0, 'rivers'); import rivers as RV
B = 'https://public-services.slip.wa.gov.au/public/rest/services/SLIP_Public_Services/Water/MapServer/7/query'
def J(p):
    try: return json.loads(RV.get(B + '?' + urllib.parse.urlencode(p), 180, 2))
    except Exception as e: print('FAILED', e); return {}
j = J({'where': '1=1', 'outStatistics': json.dumps([{'statisticType': 'count', 'onStatisticField': 'objectid', 'outStatisticFieldName': 'n'}]), 'groupByFieldsForStatistics': 'level,level_name,named', 'f': 'json'})
for f in sorted(j.get('features', []), key=lambda f: (f['attributes']['level'] or 0)): print(f['attributes'])
j = J({'where': "level <= 2 AND named = 1", 'outFields': 'hyd_name,level', 'returnGeometry': 'true', 'outSR': 4326, 'maxAllowableOffset': 0.01, 'geometryPrecision': 3, 'resultRecordCount': 2000, 'f': 'json'})
F = j.get('features', []); print('level<=2 named sample', len(F), 'bytes', len(json.dumps(F)), 'more', j.get('exceededTransferLimit'))
print(sorted(set(f['attributes']['hyd_name'] for f in F))[:80])

"""Probe 30: what road closure data Main Roads' ArcGIS account offers (layers, incident types, local roads)."""
import sys, json, collections, urllib.parse
sys.path.insert(0, 'rivers'); import rivers as RV
B = 'https://services2.arcgis.com/cHGEnmsJ165IBJRM/arcgis/rest/services'
d = json.loads(RV.get(B + '?f=json', 60, 2))
names = [s['name'] for s in d.get('services', [])]
print('services', len(names)); print([n for n in names if re.search('(?i)clos|incident|road|webeoc|flood|travel|event|condition', n)] if (re := __import__('re')) else '')
for svc in ('WebEoc_RoadClosures', 'WebEoc_RoadIncidents'):
    try: s = json.loads(RV.get(B + '/%s/FeatureServer?f=json' % svc, 60, 2))
    except Exception as e: print(svc, e); continue
    for L in s.get('layers', []):
        q = B + '/%s/FeatureServer/%d/query?' % (svc, L['id']) + urllib.parse.urlencode({'where': '1=1', 'outFields': '*', 'returnGeometry': 'false', 'f': 'json'})
        try: r = json.loads(RV.get(q, 60, 2))
        except Exception as e: print(svc, L, e); continue
        F = [f['attributes'] for f in r.get('features', [])]
        print('\n==', svc, L['id'], L['name'], len(F), 'fields', list(F[0].keys()) if F else '')
        for k in ('IncidentTy', 'ClosureTyp', 'publishExt', 'Region', 'RoadOwner', 'Owner', 'Authority', 'RoadType'):
            if F and k in F[0]: print(' ', k, collections.Counter(f[k] for f in F).most_common(15))
        for f in [f for f in F if 'lood' in json.dumps(f) or 'ater' in json.dumps(f)][:6]: print('  ', {k: v for k, v in f.items() if v not in (None, '')})

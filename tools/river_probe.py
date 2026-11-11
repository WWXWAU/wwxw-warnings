"""Probe 37: test run of the shire road reports."""
import sys, json, os
sys.path.insert(0, 'rivers'); import rivers as RV
os.makedirs('tmpout', exist_ok=True)
C = RV.shire_roads('tmpout')
for s in C['shires']: print(s)
for f in C['features'][:400]:
    p = f['properties']; g = f['geometry']
    print('%-20s %-28s %d %-30s | %s | %s | %s' % (p['shire'], p['type'][:28], p['closed'], p['road'][:30], p['where'][:70], p['updated'], (g or {}).get('type')))
print(len(json.dumps(C)) // 1024, 'KB')

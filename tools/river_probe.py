"""Probe 27: test run of the Bureau rain job and the Bureau-only level sites."""
import sys, json, datetime as dt, os
sys.path.insert(0, 'rivers'); import bomrain, rivers as RV
os.makedirs('tmpout', exist_ok=True)
bomrain.main('tmpout')
D = json.load(open('tmpout/bom-rain.json')); print('nine', D['nine'], 'gauges', len(D['gauges']))
for g in D['gauges'][:6] + [g for g in D['gauges'] if g[4]][:6]: print(g)
print('since9 null (automatic):', [g[1] for g in D['gauges'] if not g[4] and g[5] is None][:30])
pos = {}
for g in RV.hcs_gauges([], pos, dt.datetime.now(RV.AWST))[:3]: print(g)
G = RV.read_dwer(); pos = {}
print([ (g['id'], g['river'], g['name'], g['lvl'], g['at'], g['fl']) for g in RV.hcs_gauges(G, pos, dt.datetime.now(RV.AWST))])

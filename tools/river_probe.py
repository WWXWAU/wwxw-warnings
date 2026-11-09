"""Probe 7: every WA river-level gauge in Water Data Online with recent data, and who runs it."""
import json, sys, urllib.parse, re
sys.path.insert(0, 'rivers'); import rivers as RV
K = RV.KIWIS
q = K + urllib.parse.urlencode({'request': 'getTimeseriesList', 'parametertype_name': 'Water Course Level', 'ts_name': 'Received.Provisional.AsStored.1',
                                'returnfields': 'station_no,station_name,station_latitude,station_longitude,coverage,ts_id'})
rows = json.loads(RV.get(q, 300))[1:]
wa = [r for r in rows if r[2] and -36 < float(r[2]) < -13 and 112 < float(r[3]) < 129]
recent = [r for r in wa if r[5] and r[5] >= '2026-11-01']
dwer = set(re.findall(r'/publish/(\d{6})/', RV.get(RV.DWER + '/telem/stage.cfm')))
other = [r for r in recent if r[0] not in dwer]
print('WA level series: %d, with data since 1 Nov: %d, not in DWER table: %d' % (len(wa), len(recent), len(other)))
for r in other[:80]: print('  ', r[0], r[1], r[2][:7], r[3][:7], r[5][:16])
q = K + urllib.parse.urlencode({'request': 'getStationList', 'station_no': ','.join(r[0] for r in other[:300]), 'returnfields': 'station_no,station_name,site_name,catchment_name'})
try: print(RV.get(q, 120)[:3000])
except Exception as e: print('station info failed', e)
for par in ['Water Course Discharge', 'Storage Level']:
    q = K + urllib.parse.urlencode({'request': 'getTimeseriesList', 'parametertype_name': par, 'ts_name': 'Received.Provisional.AsStored.1', 'returnfields': 'station_no,station_name,station_latitude,station_longitude,coverage'})
    rr = [r for r in json.loads(RV.get(q, 300))[1:] if r[2] and -36 < float(r[2]) < -13 and 112 < float(r[3]) < 129 and r[5] and r[5] >= '2026-11-01']
    print(par, len(rr), [r[1] for r in rr if r[0] not in dwer][:40])

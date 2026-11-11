"""Probe 39: which long hourly level series Water Data Online has for WA gauges (for flood travel times)."""
import sys, json, urllib.parse
sys.path.insert(0, 'rivers'); import rivers as RV
q = RV.KIWIS + urllib.parse.urlencode({'request': 'getTimeseriesList', 'station_no': '802055,802006,802137', 'parametertype_name': 'Water Course Level',
                                       'returnfields': 'station_no,ts_id,ts_name,coverage'})
rows = json.loads(RV.get(q, 120))
for r in rows: print(r)
# try 10 years of one series
for name in ('DMQaQc.Merged.HourlyMean.HR', 'DMQaQc.Merged.AsStored.1', 'Received.Provisional.AsStored.1'):
    ts = [r for r in rows[1:] if r[0] == '802055' and r[2] == name]
    if not ts: continue
    q = RV.KIWIS + urllib.parse.urlencode({'request': 'getTimeseriesValues', 'ts_id': ts[0][1], 'from': '2016-01-01', 'to': '2026-11-01', 'returnfields': 'Timestamp,Value'})
    try:
        res = json.loads(RV.get(q, 300)); d = res[0]['data']
        print(name, len(d), d[:2], d[-2:], len(json.dumps(res)) // 1024, 'KB')
    except Exception as e: print(name, 'ERR', e)

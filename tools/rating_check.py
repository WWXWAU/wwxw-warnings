"""Check the level-to-flow estimates against the Bureau's own provisional flows (same times, last few days)."""
import json, sys, urllib.request, urllib.parse, subprocess, statistics
sys.path.insert(0, 'rivers'); import rivers as RV
subprocess.run('git fetch -q --depth 1 origin river-data && git show origin/river-data:rivers-ratings.json > /tmp/rr.json', shell=True, check=True)
R = json.load(open('/tmp/rr.json'))['r']; ids = sorted(R)
K = RV.KIWIS
def series(par):
    q = K + urllib.parse.urlencode({'request': 'getTimeseriesList', 'station_no': ','.join(ids), 'parametertype_name': par, 'ts_name': 'Received.Provisional.AsStored.1', 'returnfields': 'station_no,ts_id'})
    return {no: ts for no, ts in json.loads(RV.get(q, 180))[1:]}
L, Q = series('Water Course Level'), series('Water Course Discharge')
errs, rows = [], []
both = [i for i in ids if i in L and i in Q]
for k in range(0, len(both), 20):
    ch = both[k:k + 20]; tl = [L[i] for i in ch]; tq = [Q[i] for i in ch]
    q = K + urllib.parse.urlencode({'request': 'getTimeseriesValues', 'ts_id': ','.join(tl + tq), 'period': 'P10D', 'returnfields': 'Timestamp,Value'})
    res = {str(r['ts_id']): {t: v for t, v in r['data'] if v is not None} for r in json.loads(RV.get(q, 300))}
    for i in ch:
        lv, qv = res.get(L[i], {}), res.get(Q[i], {})
        common = sorted(set(lv) & set(qv))[::12]
        for t in common:
            est, _ = RV.flow(R[i], lv[t]); obs = qv[t]
            if obs >= 0.05: errs.append(abs(est - obs) / obs); rows.append((i, t, lv[t], obs, est))
errs.sort(); n = len(errs)
print('pairs %d, gauges %d' % (n, len(set(r[0] for r in rows))))
print('median error %.0f%%, 75th %.0f%%, 90th %.0f%%' % (100 * errs[n // 2], 100 * errs[3 * n // 4], 100 * errs[9 * n // 10]))
by = {}
for i, t, l, o, e in rows: by.setdefault(i, []).append(abs(e - o) / o)
bad = sorted(((statistics.median(v), i) for i, v in by.items()), reverse=True)[:12]
for m, i in bad:
    r = [x for x in rows if x[0] == i][-1]; print('  %s median %.0f%%  e.g. level %.3f obs %.3f est %.3f' % (i, 100 * m, r[2], r[3], r[4]))
good = sum(1 for v in by.values() if statistics.median(v) <= 0.25); print('gauges within 25%%: %d of %d' % (good, len(by)))

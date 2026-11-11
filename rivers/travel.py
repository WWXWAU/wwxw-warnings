"""Flood travel times between river gauges, learnt from past floods (data/rivers-travel.json).

For each river gauge, the next gauge downstream comes from DWER's subcatchments (rivers-upstream.json: a gauge
is downstream of another when its catchment contains the other's). Then, from Water Data Online's quality-coded
hourly levels (DMQaQc.Merged.HourlyMean.HR) since 2006, each flood peak at the upstream gauge is matched to the
peak it produced at the downstream gauge, and the delay is recorded. Per pair: how many floods, the median delay,
the range most fell in (the middle 80%), and the median in the bigger floods (the top third by rise).

Run by travel.yml (weekly, or by hand). Only gauges north of LAT_MAX for now (the northern rivers).
Usage: python rivers/travel.py <river-data dir with rivers.json and rivers-upstream.json> [out file]
"""
import datetime as dt, json, os, sys, time, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rivers import KIWIS, get, log

LAT_MAX = -28.0          # gauges north of this latitude
FROM = '2006-01-01'
MAX_LAG_H = 240          # a downstream peak more than 10 days later isn't counted
MIN_EVENTS = 3           # fewer matched floods than this: no travel time


def series(sid, tsid):
    """{hour index (h since 1970, AWST): level} from the hourly means."""
    q = KIWIS + urllib.parse.urlencode({'request': 'getTimeseriesValues', 'ts_id': tsid, 'from': FROM, 'to': dt.date.today().isoformat(),
                                        'returnfields': 'Timestamp,Value', 'timezone': 'GMT+8'})
    res = json.loads(get(q, timeout=400, tries=3))
    out = {}
    for ts, v in res[0].get('data', []):
        if v is None: continue
        t = dt.datetime.fromisoformat(ts[:19])
        out[int((t - dt.datetime(1970, 1, 1)).total_seconds() // 3600)] = float(v)
    return out


def peaks(s):
    """Flood peaks: the highest level within 48 h either side, risen at least R m from the lowest in the 72 h
    before, where R = max(0.3 m, a quarter of the gap between the gauge's median and 99.9th percentile)."""
    if len(s) < 24 * 60: return [], 0
    vals = sorted(s.values()); med = vals[len(vals) // 2]; top = vals[min(len(vals) - 1, int(len(vals) * 0.999))]
    R = max(0.3, 0.25 * (top - med))
    hs = sorted(s); out = []
    i = 0
    for h in hs:
        v = s[h]
        win = [s[k] for k in range(h - 48, h + 49) if k in s]
        if v < max(win) or (out and h - out[-1][0] < 48): continue
        before = [s[k] for k in range(h - 72, h) if k in s]
        if len(before) < 36: continue
        rise = v - min(before)
        if rise >= R: out.append((h, v, rise))
    return out, R


def match(PA, sb):
    """For each upstream peak, the downstream peak it produced: the highest downstream level within MAX_LAG_H
    after it, which must have risen 0.2 m+ above the level when the upstream gauge peaked and must not be at the
    window's end (still rising). Skipped when another big upstream peak follows within the window (two waves)."""
    out = []
    for n, (h, v, rise) in enumerate(PA):
        nxt = [p for p in PA[n + 1:] if p[0] - h <= MAX_LAG_H]
        if nxt and max(p[2] for p in nxt) >= 0.5 * rise: continue
        base = sb.get(h)
        if base is None: continue
        win = [(k, sb[k]) for k in range(h, h + MAX_LAG_H + 1) if k in sb]
        if len(win) < MAX_LAG_H * 0.7: continue
        kb, vb = max(win, key=lambda x: x[1])
        if vb - base < 0.2 or kb >= h + MAX_LAG_H - 12 or kb == h: continue
        out.append((kb - h, rise, h))
    return out


def stats(m):
    lags = sorted(x[0] for x in m)
    q = lambda p: lags[min(len(lags) - 1, int(p * (len(lags) - 1) + 0.5))]
    big = sorted(m, key=lambda x: -x[1])[:max(1, len(m) // 3)]
    bl = sorted(x[0] for x in big)
    return {'n': len(lags), 'med': q(0.5), 'lo': q(0.1), 'hi': q(0.9), 'big': bl[len(bl) // 2],
            'last': dt.datetime.utcfromtimestamp(max(x[2] for x in m) * 3600).strftime('%Y-%m-%d')}


def main(data_dir, out_path):
    G = {g['id']: g for g in json.load(open(os.path.join(data_dir, 'rivers.json')))['gauges']}
    U = json.load(open(os.path.join(data_dir, 'rivers-upstream.json')))['up']
    use = {i: set(U[i]) for i in G if i in U and U[i] and not i.startswith('B') and G[i].get('lat') is not None and G[i]['lat'] > LAT_MAX
           and not G[i].get('still') and not G[i].get('tidal')}
    down = {}
    for a, sa in use.items():
        cand = [(len(sb), b) for b, sb in use.items() if b != a and sa < sb]
        if cand: down[a] = min(cand)[1]
    log('Downstream links: %d of %d northern gauges' % (len(down), len(use)))
    ids = sorted(set(down) | set(down.values()))
    q = KIWIS + urllib.parse.urlencode({'request': 'getTimeseriesList', 'station_no': ','.join(ids), 'ts_name': 'DMQaQc.Merged.HourlyMean.HR',
                                        'parametertype_name': 'Water Course Level', 'returnfields': 'station_no,ts_id'})
    tsid = {no: ts for no, ts in json.loads(get(q, timeout=240))[1:]}
    S = {}
    for k, sid in enumerate(ids):
        if sid not in tsid: continue
        try: S[sid] = series(sid, tsid[sid])
        except Exception as e:  # noqa: BLE001
            log('  %s not read: %s' % (sid, e)); continue
        log('  %d/%d %s %s: %d hours' % (k + 1, len(ids), sid, G[sid]['name'], len(S[sid])))
        time.sleep(0.5)
    out = {}
    for a, b in sorted(down.items()):
        if a not in S or b not in S: continue
        PA, R = peaks(S[a])
        m = match(PA, S[b])
        rec = {'to': b, 'peaks': len(PA), 'rise': round(R, 2)}
        if len(m) >= MIN_EVENTS: rec.update(stats(m))
        out[a] = rec
        log('%-30s -> %-30s peaks %3d matched %3d %s' % (G[a]['river'] + ' ' + G[a]['name'], G[b]['river'] + ' ' + G[b]['name'], len(PA), len(m),
            ('median %d h (%d-%d), big floods %d h' % (rec['med'], rec['lo'], rec['hi'], rec['big'])) if 'med' in rec else ''))
    json.dump({'built': dt.date.today().isoformat(), 'from': FROM, 'pairs': out}, open(out_path, 'w'), separators=(',', ':'), sort_keys=True, indent=0)
    log('Travel times: %d pairs with enough floods, %d without' % (sum('med' in r for r in out.values()), sum('med' not in r for r in out.values())))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'rd', sys.argv[2] if len(sys.argv) > 2 else 'data/rivers-travel.json')

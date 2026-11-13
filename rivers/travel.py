"""Flood travel times between river gauges, learnt from past floods (data/rivers-travel.json).

For each river gauge, the next gauge downstream comes from DWER's subcatchments (rivers-upstream.json: a gauge
is downstream of another when its catchment contains the other's). Then, from Water Data Online's quality-coded
hourly levels (DMQaQc.Merged.HourlyMean.HR) since 2006, each flood peak at the upstream gauge is matched to the
peak it produced at the downstream gauge, and the delay is recorded. Per pair: how many floods, the median delay,
the range most fell in (the middle half), and the median in the bigger floods (the top third by rise).

Run by travel.yml (weekly, or by hand). All WA gauges north of LAT_MAX (north first on 11 Nov 2026, then the southern rivers).
Usage: python rivers/travel.py <river-data dir with rivers.json and rivers-upstream.json> [out file]
"""
import datetime as dt, json, os, sys, time, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rivers import KIWIS, get, log

LAT_MAX = -36.0          # gauges north of this latitude (all of WA since 11 Nov 2026; the north first)
FROM = '2006-01-01'
MAX_LAG_H = 240          # a downstream peak more than 10 days later isn't counted
MIN_EVENTS = 3           # fewer matched floods than this: no travel time
FIRST_GAP_D = 60         # a flood with no flood at the upstream gauge in the 60 days before = a first flow (dry bed, slower)
MIN_SHARE = 0.05         # a gauge draining less than this share of the downstream gauge's catchment isn't paired


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


def peaks(s, Rmin=None):
    """Flood peaks: the highest level within 48 h either side, risen at least R m from the lowest in the 72 h
    before, where R = max(0.3 m, a quarter of the gap between the gauge's median and 99.9th percentile).
    With Rmin: every peak rising at least Rmin instead (the smaller rises too), still returning the gauge's R."""
    if len(s) < 24 * 60: return [], 0
    vals = sorted(s.values()); med = vals[len(vals) // 2]; top = vals[min(len(vals) - 1, int(len(vals) * 0.999))]
    R = max(0.3, 0.25 * (top - med)); Rf = R
    if Rmin is not None: R = Rmin
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
    return out, Rf


def match(PA, sb, maxlag=MAX_LAG_H):
    """For each upstream peak, the downstream peak it produced: the highest downstream level within MAX_LAG_H
    after it, which must have risen 0.2 m+ above the level when the upstream gauge peaked and must not be at the
    window's end (still rising). Skipped when another big upstream peak follows within the window (two waves)."""
    out = []
    for n, (h, v, rise) in enumerate(PA):
        nxt = [p for p in PA[n + 1:] if p[0] - h <= maxlag]
        if nxt and max(p[2] for p in nxt) >= 0.5 * rise: continue
        base = sb.get(h)
        if base is None: continue
        win = [(k, sb[k]) for k in range(h, h + maxlag + 1) if k in sb]
        if len(win) < maxlag * 0.7: continue
        kb, vb = max(win, key=lambda x: x[1])
        if vb - base < 0.2 or kb >= h + maxlag - 6 or kb == h: continue
        gap = (h - PA[n - 1][0]) / 24 if n else 9999                      # days since the previous flood here
        out.append((kb - h, rise, h, round(gap)))
    return out


REACH_BINS = (0.5, 0.75, 1.0, 1.5)   # rise bins as shares of the gauge's flood size R: 0.5-0.75 R, 0.75-1 R, 1-1.5 R, 1.5 R+


def reach(PS, R, sb, win):
    """How often a rise at the upstream gauge got to the downstream one, by size: for every upstream peak of half the
    flood size R or more, did the downstream gauge rise 0.2 m+ within the pair's window? Small rises often soak into the
    bed or spread out on the way. Returns [[from m, to m (None = no top), rises, got there], ...] per REACH_BINS."""
    out = [[round(REACH_BINS[i] * R, 2), round(REACH_BINS[i + 1] * R, 2) if i + 1 < len(REACH_BINS) else None, 0, 0] for i in range(len(REACH_BINS))]
    first = [0, 0]                       # first flows (no rise of half the flood size in the FIRST_GAP_D days before), any size: [rises, got there]
    for n, (h, v, rise) in enumerate(PS):
        if rise < REACH_BINS[0] * R: continue
        if any(p[0] - h <= win and p[2] >= 0.5 * rise for p in PS[n + 1:]): continue     # another wave close behind: can't tell them apart
        before = [sb[k] for k in range(h - 6, h + 1) if k in sb]
        if not before: continue
        base = before[-1]
        w = [sb[k] for k in range(h, h + win + 1) if k in sb]
        if len(w) < win * 0.5: continue
        i = max(j for j in range(len(REACH_BINS)) if rise >= REACH_BINS[j] * R)
        got = max(w) - base >= 0.2
        out[i][2] += 1; out[i][3] += got
        if not n or h - PS[n - 1][0] >= FIRST_GAP_D * 24: first[0] += 1; first[1] += got
    return out, first


def stats(m):
    lags = sorted(x[0] for x in m)
    q = lambda p: lags[min(len(lags) - 1, int(p * (len(lags) - 1) + 0.5))]
    big = sorted(m, key=lambda x: -x[1])[:max(1, len(m) // 3)]
    bl = sorted(x[0] for x in big)
    return {'n': len(lags), 'med': q(0.5), 'lo': q(0.25), 'hi': q(0.75), 'big': bl[len(bl) // 2],
            'last': dt.datetime.utcfromtimestamp(max(x[2] for x in m) * 3600).strftime('%Y-%m-%d'),
            'ev': [[x[0], round(x[1], 2), x[2], min(x[3], 999)] for x in sorted(m, key=lambda x: x[2])]}    # each flood: [delay h, rise m, upstream peak hour, days since the last flood]


def split(m):
    """Travel times for first flows (no flood upstream in FIRST_GAP_D days: the bed is dry and soaks up the front of the
    wave) and for the others, when each has 3+ floods."""
    out = {}
    for k, sub in (('first', [x for x in m if x[3] >= FIRST_GAP_D]), ('wet', [x for x in m if x[3] < FIRST_GAP_D])):
        if len(sub) >= MIN_EVENTS:
            l = sorted(x[0] for x in sub); q = lambda p: l[min(len(l) - 1, int(p * (len(l) - 1) + 0.5))]
            out[k] = {'n': len(l), 'med': q(0.5), 'lo': q(0.25), 'hi': q(0.75)}
    return out


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
        share = round(len(use[a]) / len(use[b]), 2)                          # how much of the downstream catchment is above this gauge
        PA, R = peaks(S[a])
        m = match(PA, S[b])
        if len(m) >= MIN_EVENTS:                                             # second pass: a window fitted to this pair, to drop chance matches
            lags = sorted(x[0] for x in m); m = match(PA, S[b], min(MAX_LAG_H, int(2.5 * lags[len(lags) // 2] + 24)))
        rec = {'to': b, 'peaks': len(PA), 'rise': round(R, 2), 'share': share, 'lastpk': PA[-1][0] if PA else None}
        if share < MIN_SHARE: m = []                                         # a small side creek: the downstream peak mostly comes from elsewhere
        if len(m) >= MIN_EVENTS:
            rec.update(stats(m)); rec.update(split(m))
            PS, _ = peaks(S[a], Rmin=0.5 * R)
            rec['reach'], rec['reachf'] = reach(PS, R, S[b], min(MAX_LAG_H, int(2.5 * rec['med'] + 24)))
        out[a] = rec
        log('%-30s -> %-30s peaks %3d matched %3d %s%s' % (G[a]['river'] + ' ' + G[a]['name'], G[b]['river'] + ' ' + G[b]['name'], len(PA), len(m),
            ('median %d h (%d-%d), big floods %d h, reached by size %s, first flows %d/%d' % (rec['med'], rec['lo'], rec['hi'], rec['big'], ' '.join('%d/%d' % (x[3], x[2]) for x in rec['reach']), rec['reachf'][1], rec['reachf'][0])) if 'med' in rec else '',
            (' | first flows %d h (n %d) vs %s' % (rec['first']['med'], rec['first']['n'], ('%d h' % rec['wet']['med']) if 'wet' in rec else '-')) if 'first' in rec else ''))
    json.dump({'built': dt.date.today().isoformat(), 'from': FROM, 'pairs': out}, open(out_path, 'w'), separators=(',', ':'), sort_keys=True, indent=0)
    log('Travel times: %d pairs with enough floods, %d without' % (sum('med' in r for r in out.values()), sum('med' not in r for r in out.values())))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'rd', sys.argv[2] if len(sys.argv) > 2 else 'data/rivers-travel.json')

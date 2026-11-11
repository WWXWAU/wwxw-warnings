"""Bureau of Meteorology flood-warning rain gauges for the Rainfall page (bom-rain.json).

The Bureau publishes rain from about 550 WA gauges (its own and other agencies') on its FTP site:
  IDW65900  15-minute totals (each file holds the last ~2 hours, a new file every 15 minutes)
  IDW65901  hourly totals (last ~4 hours)
  IDW65902  daily totals to 9am (last 3 days, once a day ~10am), including manual (read by hand) gauges
Each value is the rain in the interval that ENDS at its time. Names and positions come from the Bureau's
site list (data/bom-rain-sites.csv). The files only cover a few hours, so a state file keeps the last
32 hours of 15-minute and hourly values and 10 days of daily totals.

Output per gauge: [id, name, lat, lng, manual, since 9am, 24 h to 9am, last reading (UTC ms), {9am date: mm}, rates]
  since 9am  - rain since the latest 9am (null for manual gauges, or when the record has a gap)
  to 9am     - the 9am-to-9am day that ended at the latest 9am
  rates      - from the Bureau's 15-minute values: 'n' rain in the latest 15 min / 1 / 3 / 6 hours sent, and the
               heaviest [15 min, 1 hour, when that hour ended (ms), 3 hours] since 9am ('d'), in 12 and 24 hours
               ('h12', 'h24') and in the day that ended at 9am ('y'). About a third of the gauges send their
               readings in hourly batches, so rates worked out from when readings arrive would be wrong.
  days       - 9am-to-9am totals, each dated the morning it ended (a reading made around 9am, as manual
               gauges are, counts for the day ending that 9am, never the day it comes through)
"""
import csv, datetime as dt, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rivers import hcs_rows, log

UTC = dt.timezone.utc
SITES = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'bom-rain-sites.csv')
H1, M15 = dt.timedelta(hours=1), dt.timedelta(minutes=15)


def nine_of(t):
    """The 9am (Perth, 01:00 UTC) nearest to t: a daily reading made around 9am belongs to the day ending then."""
    base = t.replace(hour=1, minute=0, second=0, microsecond=0)
    cands = [base + dt.timedelta(days=d) for d in (-1, 0, 1)]
    return min(cands, key=lambda c: abs((t - c).total_seconds()))


def dkey(nine):
    return (nine + dt.timedelta(hours=8)).strftime('%Y-%m-%d')


def last_nine(now):
    n = now.replace(hour=1, minute=0, second=0, microsecond=0)
    return n if n <= now else n - dt.timedelta(days=1)


def window(q, h, t0, t1):
    """Rain in (t0, t1] from 15-minute values (q) and hourly values (h), keyed by ISO end time.
    Each hour uses its hourly total when there is one, otherwise its 15-minute values. None if an hour
    that has ended has no data at all."""
    tot, t = 0.0, t0
    while t < t1:
        e = min(t + H1, t1); k = e.strftime('%Y-%m-%dT%H:%M')
        if e - t == H1 and k in h: tot += h[k]
        else:
            got = [q[x.strftime('%Y-%m-%dT%H:%M')] for x in (t + M15 * i for i in range(1, 5)) if x <= e and x.strftime('%Y-%m-%dT%H:%M') in q]
            if not got and e - t == H1: return None
            tot += sum(got)
        t = e
    return round(tot, 1)


def strict(q, h, t0, t1):
    """Rain in (t0, t1] only if every 15 minutes of it is known (a whole clock hour may come from its hourly
    total); None otherwise."""
    tot, t = 0.0, t0
    while t < t1:
        e = t + H1
        if t.minute == 0 and e <= t1 and e.strftime('%Y-%m-%dT%H:%M') in h:
            tot += h[e.strftime('%Y-%m-%dT%H:%M')]; t = e; continue
        k = (t + M15).strftime('%Y-%m-%dT%H:%M')
        if k not in q: return None
        tot += q[k]; t += M15
    return round(tot, 1)


def maxima(q, h, a, b):
    """Heaviest 15 minutes, 1 hour (and when it ended, ms) and 3 hours within (a, b], timed by the Bureau's own
    15-minute values, so gauges that send their readings in batches are timed right."""
    out = [None, None, None, None]
    t = a + M15
    while t <= b:
        for i, W in ((0, M15), (1, H1), (3, 3 * H1)):
            if t - W < a: continue
            v = strict(q, h, t - W, t)
            if v is not None and v > 0 and (out[i] is None or v > out[i]):
                out[i] = v
                if i == 1: out[2] = int(t.timestamp() * 1000)
        t += M15
    return out


def main(out_dir):
    now = dt.datetime.now(UTC)
    M = {r['BOM_STATION_NUMBER']: r for r in csv.DictReader(open(SITES))}
    sp = os.path.join(out_dir, 'bom-rain-state.json')
    try: S = json.load(open(sp))
    except Exception: S = {}  # noqa: BLE001
    for k in ('q', 'h', 'd'): S.setdefault(k, {})
    n = {}
    for part, prefix in (('q', 'IDW65900_'), ('h', 'IDW65901_'), ('d', 'IDW65902_')):
        try: rows = hcs_rows(prefix)
        except Exception as e:  # noqa: BLE001
            log('%s not read: %s' % (prefix, e)); rows = []
        n[part] = len(rows)
        for sid, t, v in rows:
            if sid not in M or v < 0 or v > 1000: continue
            key = dkey(nine_of(t)) if part == 'd' else t.strftime('%Y-%m-%dT%H:%M')
            S[part].setdefault(sid, {})[key] = round(v, 1)
    cut = (now - dt.timedelta(hours=32)).strftime('%Y-%m-%dT%H:%M'); dcut = dkey(last_nine(now) - dt.timedelta(days=10))
    for part, c in (('q', cut), ('h', cut), ('d', dcut)):
        for sid in list(S[part]):
            S[part][sid] = {k: v for k, v in S[part][sid].items() if k >= c}
            if not S[part][sid]: del S[part][sid]
    nine = last_nine(now); dk = dkey(nine); prev = nine - dt.timedelta(days=1)
    out = []
    for sid in sorted(set(S['q']) | set(S['h']) | set(S['d'])):
        m = M[sid]; q, h, d = S['q'].get(sid, {}), S['h'].get(sid, {}), dict(S['d'].get(sid, {}))
        manual = m['TYPE'] != 'Automatic'
        times = sorted(list(q) + list(h))
        last = dt.datetime.strptime(times[-1], '%Y-%m-%dT%H:%M').replace(tzinfo=UTC) if times else None
        since9 = None
        if not manual and last and now - last <= dt.timedelta(hours=2) and last > nine:
            since9 = window(q, h, nine, last)
        elif not manual and last and last <= nine and now - last <= dt.timedelta(hours=2):
            since9 = 0.0                                                  # just after 9am, before the first interval of the day
        if dk not in d and not manual:                                    # the day just ended, from our own record until the daily file has it
            v = window(q, h, prev, nine)
            if v is not None and h and min(h) <= prev.strftime('%Y-%m-%dT%H:%M'): d[dk] = v
        if since9 is None and not d: continue
        if manual and not d: continue
        rates = None
        if not manual and last:
            q15 = (now - dt.timedelta(minutes=now.minute % 15, seconds=now.second, microseconds=now.microsecond))
            rates = {'d': maxima(q, h, nine, last), 'h12': maxima(q, h, q15 - 12 * H1, last), 'h24': maxima(q, h, q15 - 24 * H1, last),
                     'y': maxima(q, h, prev, nine)}
            if now - last <= dt.timedelta(minutes=90):                    # rain in the latest 15 min / 1 / 3 / 6 hours the gauge has sent
                rates['n'] = [strict(q, h, last - W, last) for W in (M15, H1, 3 * H1, 6 * H1)]
            rates = {k: v for k, v in rates.items() if any(x for x in v)} or None
        out.append([sid, m['SHORT_NAME'], round(float(m['LATITUDE']), 4), round(float(m['LONGITUDE']), 4), 1 if manual else 0,
                    since9, d.get(dk), int(last.timestamp() * 1000) if last else None, {k: d[k] for k in sorted(d)[-8:]}, rates])
    json.dump(S, open(sp, 'w'), separators=(',', ':'), sort_keys=True)
    json.dump({'made': int(now.timestamp() * 1000), 'nine': dk, 'gauges': out}, open(os.path.join(out_dir, 'bom-rain.json'), 'w'), separators=(',', ':'))
    live = [g for g in out if g[5] is not None]
    log('Bureau rain: read %s; %d gauges (%d with rain since 9am, %d manual); wettest since 9am: %s' % (n, len(out), len(live), sum(g[4] for g in out),
        ', '.join('%s %.1f' % (g[1], g[5]) for g in sorted(live, key=lambda g: -g[5])[:5])))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'out')

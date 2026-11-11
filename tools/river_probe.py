"""Probe 26: what the Bureau HCS rain records mean (intervals, params, time spans)."""
import ftplib, io, collections
f = ftplib.FTP('ftp.bom.gov.au', timeout=60); f.login()
def raw(p):
    b = io.BytesIO(); f.retrbinary('RETR ' + p, b.write); return b.getvalue().decode('latin-1')
names = sorted(n.split('/')[-1] for n in f.nlst('/anon/gen/fwo'))
for pre in ('IDW65900_', 'IDW65901_', 'IDW65902_', 'IDW65910_'):
    fl = [n for n in names if n.startswith(pre)]
    print(pre, fl)
    t = raw('/anon/gen/fwo/' + fl[-1]); L = t.splitlines()
    print(' head:', L[:3])
    rows = [l.split(',') for l in L if l and l[0].isdigit()]
    ts = sorted({r[5] for r in rows}); print(' times', len(ts), ts[:3], ts[-3:])
    print(' fields 2,3,8,9,10,11:', collections.Counter((r[2], r[3], r[8], r[9], r[10], r[11] if len(r) > 11 else '') for r in rows).most_common(8))
    for sid in ('509488', '009172', '005007'):
        print(' ', sid, [(r[5][5:16], r[6], r[8], r[9], r[10]) for r in rows if r[4].strip('"') == sid][:30])

"""Probe 28: do 15-minute rain values arrive live, or late / revised in later files?"""
import ftplib, io, collections, datetime as dt
f = ftplib.FTP('ftp.bom.gov.au', timeout=60); f.login(); f.cwd('/anon/gen/fwo')
names = sorted(n for n in f.nlst() if n.startswith('IDW65900_') and n.endswith('.hcs'))
seen = {}; revised = []; late = collections.Counter(); first_file = {}
ftime = lambda n: dt.datetime.strptime(n[9:23], '%Y%m%d%H%M%S')
for n in names:
    b = io.BytesIO(); f.retrbinary('RETR ' + n, b.write)
    for l in b.getvalue().decode('latin-1').splitlines():
        c = [x.strip().strip('"') for x in l.split(',')]
        if len(c) < 7 or not c[0].isdigit(): continue
        k = (c[4], c[5]); v = float(c[6])
        if k not in seen:
            seen[k] = v; first_file[k] = n
        elif seen[k] != v:
            revised.append((c[4], c[5], seen[k], v, first_file[k][9:21], n[9:21])); seen[k] = v
print('files', [n[9:21] for n in names])
f0 = ftime(names[0])
for k, n in first_file.items():
    if n == names[0]: continue                       # can't tell for the first file
    end = dt.datetime.strptime(k[1], '%Y-%m-%dT%H:%M:%SZ')
    late[int((ftime(n) - end).total_seconds() // 60)] += 1
print('minutes from interval end to the first file that has it:', sorted(late.items()))
print('values revised in a later file:', len(revised), 'of', len(seen))
for r in revised[:25]: print(r)
wet = collections.Counter(k[0] for k, v in seen.items() if v > 0)
print('gauges with rain in these 2 hours:', len(wet))
# per file: how many gauges have their newest interval missing (i.e. not reported yet)
for n in names[-3:]:
    b = io.BytesIO(); f.retrbinary('RETR ' + n, b.write)
    rows = [l.split(',') for l in b.getvalue().decode('latin-1').splitlines() if l[:1].isdigit()]
    newest = max(r[5] for r in rows); per = collections.Counter(r[4] for r in rows if r[5] == newest)
    allsites = {r[4] for r in rows}
    print(n[9:21], 'newest', newest, 'sites with it', len(per), 'of', len(allsites))

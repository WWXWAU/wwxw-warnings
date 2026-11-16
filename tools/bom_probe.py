"""Probe: search every text product on the Bureau's public FTP for the tropical cyclone outlook (e.g. "01U")."""
import ftplib, io, re, time
f = ftplib.FTP('ftp.bom.gov.au', timeout=60); f.login(); f.cwd('/anon/gen/fwo')
names = [n for n in f.nlst() if n.endswith('.txt')]
print(len(names), 'text products'); t0 = time.time(); hits = 0
for n in names:
    b = io.BytesIO()
    try: f.retrbinary('RETR ' + n, b.write)
    except Exception: continue
    t = b.getvalue().decode('latin-1')
    if re.search(r'\b0\dU\b|tropical cyclone outlook|likelihood of .{0,40}tropical cyclone', t, re.I):
        hits += 1; print('\n=====', n, len(t)); print(t[:2000])
print('\ndone in %d s, %d hits' % (time.time() - t0, hits))

"""Probe: which WA warning products (flood, frost, etc.) are on BoM's anonymous FTP right now, with their titles."""
import ftplib, io, re
f = ftplib.FTP('ftp.bom.gov.au', timeout=60); f.login(); f.cwd('/anon/gen/fwo')
names = f.nlst()
w = sorted(n for n in names if re.match(r'IDW(2\d|3\d|5\d|6\d)\d{3}', n) and not re.search(r'\.(png|gif|jpg)$', n))
print('FILES:', ' '.join(w))
for n in [x for x in w if x.endswith('.txt')]:
    b = io.BytesIO()
    try: f.retrbinary('RETR ' + n, b.write)
    except Exception as e: print(n, 'ERR', e); continue
    t = b.getvalue().decode('latin-1')
    lines = [l.strip() for l in t.splitlines() if l.strip()][:8]
    print('\n###', n, '|', ' / '.join(lines)[:300])
f.quit()

"""Probe: find the Bureau's tropical cyclone outlook text among the public FTP's products."""
import ftplib, io, re
f = ftplib.FTP('ftp.bom.gov.au', timeout=60); f.login(); f.cwd('/anon/gen/fwo')
names = [n for n in f.nlst() if re.match(r'ID[WDQ]1\d{4}\.txt$', n)]
print(len(names), 'IDx1xxxx text products')
for n in names:
    b = io.BytesIO()
    try: f.retrbinary('RETR ' + n, b.write)
    except Exception as e: continue
    t = b.getvalue().decode('latin-1')
    if re.search(r'(?i)tropical cyclone outlook|tropical low|likelihood of', t):
        print('\n=====', n, len(t)); print(t[:1800])

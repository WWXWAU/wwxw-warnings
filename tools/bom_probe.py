"""Probe: is the WA land warnings RSS (IDZ00067) on BoM's anonymous FTP, and which WA warning products are there now?"""
import ftplib, io, re
f = ftplib.FTP('ftp.bom.gov.au', timeout=60); f.login(); f.cwd('/anon/gen/fwo')
names = f.nlst()
print('IDZ files:', [n for n in names if n.startswith('IDZ')][:60])
print('IDW warning-ish:', sorted(n for n in names if re.match(r'IDW(2|1[0-9]{4}|39|60)', n) and not n.endswith('.png'))[:200])
for n in ['IDZ00067.warnings_land_wa.xml', 'IDZ00067.xml']:
    if n in names:
        b = io.BytesIO(); f.retrbinary('RETR ' + n, b.write); print('\n=====', n, '\n', b.getvalue().decode('utf-8', 'replace')[:4000])
f.quit()

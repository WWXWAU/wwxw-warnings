import ftplib, io
f = ftplib.FTP('ftp.bom.gov.au', timeout=60); f.login(); f.cwd('/anon/gen/fwo')
names = f.nlst()
want = [n for n in names if n.startswith(('IDW108', 'IDW276', 'IDW602', 'IDW241', 'IDW242', 'IDD108', 'IDQ108', 'IDD2002', 'IDQ2002', 'IDW6028'))]
print('files:', sorted(want))
for n in sorted(want):
    if n.endswith(('.txt', '.xml')) and ('IDW108' in n or 'IDW6028' in n or 'IDW276' in n):
        b = io.BytesIO(); f.retrbinary('RETR ' + n, b.write); t = b.getvalue().decode('utf-8', 'replace')
        print('=====', n, len(t)); print(t[:2500])

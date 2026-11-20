import ftplib, io, re
f = ftplib.FTP('ftp.bom.gov.au', timeout=60); f.login(); f.cwd('/anon/gen/fwo')
b = io.BytesIO(); f.retrbinary('RETR IDW60281.xml', b.write); t = b.getvalue().decode('utf-8', 'replace')
i = t.find('intensit'); print(t[i-200:i+9000])
print('NAMES', sorted(n for n in f.nlst() if re.match(r'ID[DQWNT]\d{5}', n) and ('6028' in n or '1080' in n or '65' == n[3:5]))[:60])

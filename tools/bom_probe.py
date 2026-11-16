"""Probe: is the Bureau's tropical cyclone outlook text on its public FTP (anon/gen/fwo)?"""
import ftplib, io, re
f = ftplib.FTP('ftp.bom.gov.au', timeout=60); f.login(); f.cwd('/anon/gen/fwo')
names = f.nlst()
hits = [n for n in names if re.match(r'ID[WDQ]1(0800|0610|0810|0600)|IDW1080|IDD1061|IDQ1081|IDW2|IDD2|IDQ2', n)]
print(len(names), 'files; candidates:', hits[:60])
for n in [x for x in hits if re.match(r'(IDW10800|IDD10610|IDQ10810)\.txt$', x)]:
    b = io.BytesIO(); f.retrbinary('RETR ' + n, b.write); t = b.getvalue().decode('latin-1')
    print('\n=====', n, len(t)); print(t[:2500])

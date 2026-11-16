"""Probe: are the Bureau's cyclone technical bulletins (IDW27600 etc) and advices on the public FTP?"""
import ftplib, re
f = ftplib.FTP('ftp.bom.gov.au', timeout=60); f.login(); f.cwd('/anon/gen/fwo')
names = f.nlst()
print([n for n in names if re.match(r'ID[WDQ]2(76|43|02)\d\d|IDW10|IDD10|IDQ10|ID[WDQ]6', n)])

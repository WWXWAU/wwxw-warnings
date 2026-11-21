"""Probe: element names and text in the Bureau's tropical cyclone Forecast Track Map XML (IDW60281)."""
import ftplib, io, re
import xml.etree.ElementTree as ET
f = ftplib.FTP('ftp.bom.gov.au', timeout=60); f.login(); f.cwd('/anon/gen/fwo')
for n in ['IDW60281.xml']:
    b = io.BytesIO(); f.retrbinary('RETR ' + n, b.write); root = ET.fromstring(b.getvalue())
    for e in root.iter():
        if e.get('type') and not re.search(r'plus\d', e.get('type')):
            print('EL', e.tag, e.get('type'), '=', (e.text or '').strip()[:300].replace('\n', ' / '))
f.quit()

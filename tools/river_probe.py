"""Probe 12: DWER station discharge pages (dis/di5/di6/te2/g02) in full, and the 7-day zip for discharge."""
import re, sys, io, zipfile, urllib.request
sys.path.insert(0, 'rivers'); import rivers as RV
def body(c):
    c = re.sub(r'(?s)<(script|style|head)[^>]*>.*?</\1>', ' ', c)
    c = re.sub(r'(?s)Copyright &#169;.*', ' ', c)
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' | ', c))
for sid in ['616011', '614006']:
    P = 'https://kumina.water.wa.gov.au/waterinformation/wir/reports/publish/%s/' % sid
    for p in ['dis.htm', 'di6.htm', 'te2.htm', 'g02.htm', '%s.htm' % sid]:
        try: c = RV.get(P + p, 60, 1)
        except Exception as e: print('fail', sid, p, e); continue
        print('\n==', sid, p); print(body(c)[:2500])
    for z in ['zipdis.zip', 'zipflow.zip', 'zipdischarge.zip', 'zipstage.zip']:
        try:
            req = urllib.request.Request(P + z, headers=RV.UA); Z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(req, timeout=90).read()))
            for n in Z.namelist():
                d = Z.read(n).decode('latin-1').splitlines(); print('\nZIP', sid, z, n, len(d)); print('\n'.join(d[:3])); print('\n'.join([l for l in d if ',150' in l or ',1' in l][-30:]))
                print('vars:', sorted(set(l.split(',')[1] + '/' + l.split(',')[2] for l in d if l.count(',') > 4)))
        except Exception as e: print('zip', z, 'fail', e)

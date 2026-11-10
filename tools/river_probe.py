"""Probe 11: DWER 'other parameters' (ops.cfm) and the station sub-pages (discharge, telemetry series, zip)."""
import re, sys, io, zipfile, urllib.request
sys.path.insert(0, 'rivers'); import rivers as RV
B = RV.DWER
t = RV.get(B + '/telem/ops.cfm')
print('ops.cfm', len(t))
print('headers:', [RV.clean(x) for x in re.findall(r'<th[^>]*>(.*?)</th>', t, re.S)][:30])
rows = re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S)
print('rows', len(rows))
for row in rows[:12]: print('  ', [RV.clean(x)[:40] for x in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.S)])
units = {}
for row in rows:
    c = [RV.clean(x) for x in re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)]
    for x in c:
        if re.search(r'(?i)m3|cumec|discharge|flow|m\^3|ML', x): units[x[:50]] = units.get(x[:50], 0) + 1
print('flow-ish cells:', sorted(units.items(), key=lambda a: -a[1])[:30])
for sid in ['616011', '601001']:
    P = 'https://kumina.water.wa.gov.au/waterinformation/wir/reports/publish/%s/' % sid
    for p in ['dis.htm', 'di5.htm', 'di6.htm', 'te2.htm', 'te4.htm', 'te5.htm', 'te6.htm', 'td1.htm', 'g02.htm', 'sitesum.htm']:
        try: c = RV.get(P + p, 60, 1)
        except Exception as e: print('fail', sid, p, e); continue
        txt = RV.clean(re.sub(r'(?s)<(script|style)[^>]*>.*?</\1>', ' ', c))
        print('\n==', sid, p, len(c), txt[txt.find('Department of Water') + 60:][:700])
        print('   imgs/links:', sorted(set(re.findall(r'(?:href|src)="([^"]+)"', c)))[:20])
    try:
        req = urllib.request.Request(P + 'zipstage.zip', headers=RV.UA); z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(req, timeout=90).read()))
        for n in z.namelist():
            d = z.read(n).decode('latin-1'); print('\nZIP', sid, n, len(d)); print(d[:800]); print('...'); print(d[-600:])
    except Exception as e: print('zip fail', e)

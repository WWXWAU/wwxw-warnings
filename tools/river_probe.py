"""Probe 25: are the 17 Bureau water-level sites missing from the River page live anywhere?"""
import ftplib, io, re, sys, collections
sys.path.insert(0, 'rivers'); import rivers as RV
MISS = {'509516':'609039','509475':'609045','510503':'609021','109508':'610300','509531':'612032','508036':'701011','508042':'701016',
        '508039':'701014','509368':'','508035':'617013','510522':'614126','510506':'614105','509428':'614121','502014':'',
        '509525':'611006','509476':'616082','509492':''}
f = ftplib.FTP('ftp.bom.gov.au', timeout=60); f.login()
names = sorted(n.split('/')[-1] for n in f.nlst('/anon/gen/fwo'))
fl = [n for n in names if n.startswith('IDW65910') and n.endswith('.hcs')]
b = io.BytesIO(); f.retrbinary('RETR /anon/gen/fwo/' + fl[-1], b.write)
last = {}
for l in b.getvalue().decode('latin-1').splitlines():
    p = l.split(',')
    if len(p) > 6 and p[4].strip('"') in MISS: last[p[4].strip('"')] = (p[5].strip('"'), p[6])
print('IDW65910 file', fl[-1])
stage = RV.get('https://kumina.water.wa.gov.au/waterinformation/telem/stage.cfm', 60, 2)
for bom, dw in MISS.items():
    on = bool(dw) and dw in stage
    te = ''
    if dw:
        try: t = RV.get(RV.PUB % (dw, 'te2.htm'), 40, 1); te = 'te2 ok %d rows' % len(RV.hourly_table(t))
        except Exception as e: te = 'te2 ' + str(e)[:40]
    print(bom, dw or '-', 'BoM latest:', last.get(bom, 'none'), '| on DWER stage list:', on, '|', te)

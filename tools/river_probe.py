"""Probe 23: how many rain sites each Bureau product has, and which aren't on the Rainfall page."""
import ftplib, io, re, sys, json, collections, urllib.request
sys.path.insert(0, 'rivers'); import rivers as RV
f = ftplib.FTP('ftp.bom.gov.au', timeout=60); f.login()
def raw(p):
    b = io.BytesIO(); f.retrbinary('RETR ' + p, b.write); return b.getvalue().decode('latin-1')
names = sorted(n.split('/')[-1] for n in f.nlst('/anon/gen/fwo'))
last = [n for n in names if n.startswith('IDW65900_') and n.endswith('.hcs')][-1]
ids = collections.Counter(l.split(',')[4].strip('"') for l in raw('/anon/gen/fwo/' + last).splitlines() if l and l[0].isdigit())
print('IDW65900 15-min rain sites:', len(ids), collections.Counter(('BoM station' if k.startswith('0') else 'other (DWER/agency)') for k in ids))
# manual daily reports (24 h to 9 am)
man = set()
for p in ('IDW60042.txt', 'IDW60043.txt', 'IDW60044.txt', 'IDW60045.txt'):
    t = raw('/anon/gen/fwo/' + p); head = t[:160].replace('\n', ' ')
    body = re.sub(r'\s+', ' ', t)
    sites = re.findall(r"([A-Z][A-Za-z'\.\- ]+?(?: \[[A-Z]+\])?) (\d+(?:\.\d)?(?:/\d)?)(?= [A-Z]| Rainfall)", body)
    print(p, head[:120], '| sites with rain listed:', len(sites)); man |= {s[0].strip() for s in sites}
# hourly bulletins: station names by area
st = set()
for i in range(200, 230):
    try: t = raw('/anon/gen/fwo/IDW60%d.html' % i)
    except Exception: continue
    title = re.search(r'(One|Three) Hourly Rainfall Bulletin for ([^<|]+)', re.sub(r'<[^>]+>', ' ', t))
    rows = re.findall(r'<tr[^>]*>\s*<td[^>]*>([^<]+)</td>', t)
    st |= {r.strip() for r in rows}
    if i < 230: print('IDW60%d' % i, title.group(0)[:70] if title else '?', len(rows))
print('hourly/3-hourly bulletin stations (all areas):', len(st))
src = collections.Counter('DPIRD' if '(Dpird)' in s else 'DWER/other' if re.search(r'\(D[Ww]\w*\)|Dwer', s) else 'BoM/other' for s in st)
print(src)
# the Rainfall page's own list
t = RV.get('https://script.google.com/macros/s/AKfycbyoxJApPxqA86gVVXen0USujHH7OAz3_nEwonfV-8j1G4pWAyKU7aIBRCRxsYZ5DcdJ/exec', 150, 2)
for _ in range(3): t = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), t).replace('\\\\', '\\').replace('\\/', '/').replace('\\"', '"')
pts = [json.loads(m.group(0)) for m in re.finditer(r'\{[^{}]*?"m60_daily"[^{}]*\}', t)]
print('Rainfall page now:', len(pts), collections.Counter(p.get('source') for p in pts))
have = {re.sub(r'\s*\(.*?\)\s*$', '', p.get('name', '')).lower() for p in pts}
nb = sorted(s for s in st if re.sub(r'\s*\(.*?\)\s*$', '', s).lower() not in have)
print('bulletin stations not on the Rainfall page:', len(nb)); print(nb[:150])

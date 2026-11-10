"""Probe 10: DWER station pages — discharge (m3/s), recent series, and the rain gauge list."""
import re, sys
sys.path.insert(0, 'rivers'); import rivers as RV
B = RV.DWER
t = RV.get(B + '/telem/stage.cfm')
print('stage.cfm', len(t))
print('header:', [RV.clean(x) for x in re.findall(r'<th[^>]*>(.*?)</th>', t, re.S)][:20])
rows = re.findall(r'<tr class=(\w+)>(.*?)</tr>', t, re.S)
for cls, row in rows[:2]:
    print(cls, row[:1500].replace('\n', ' '))
links = sorted(set(re.findall(r'href="([^"]+)"', t)))
print('links:', links[:80])
sid = re.search(r'publish/(\d+)/', t).group(1)
for u in [l for l in links if sid in l][:6]:
    full = u if u.startswith('http') else (B + '/telem/' + u if not u.startswith('/') else 'https://kumina.water.wa.gov.au' + u)
    try: c = RV.get(full, 60, 1)
    except Exception as e: print('fail', full, e); continue
    print('\n==', full, len(c)); print(RV.clean(c)[:2500])
    print('sub-links:', sorted(set(re.findall(r'(?:href|src)="([^"]+)"', c)))[:60])
for u in ['/telem/flow.cfm', '/telem/discharge.cfm', '/telem/index.cfm', '/telem/', '/telem/rain.cfm']:
    try: c = RV.get(B + u, 60, 1); print('\n==', u, len(c)); print(RV.clean(c)[:1500]); print('links', sorted(set(re.findall(r'href="([^"]+)"', c)))[:60])
    except Exception as e: print('fail', u, e)

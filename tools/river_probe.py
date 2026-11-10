"""Probe 13: raw HTML of DWER station pages."""
import re, sys
sys.path.insert(0, 'rivers'); import rivers as RV
for sid in ['616011']:
    P = 'https://kumina.water.wa.gov.au/waterinformation/wir/reports/publish/%s/' % sid
    for p in ['%s.htm' % sid, 'dis.htm', 'di6.htm', 'te2.htm', 'g02.htm', 'sitesum.htm']:
        c = RV.get(P + p, 60, 1)
        i = c.find('<body'); c = c[i:]
        c = re.sub(r'(?s)Copyright &#169;.*?</p>', '', c)
        c = re.sub(r'\s+', ' ', c)
        print('\n==', p, len(c)); print(c[:5000])

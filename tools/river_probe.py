"""Probe 32: shire road report pages (northern WA): format, links, latest report."""
import sys, re, urllib.parse
sys.path.insert(0, 'rivers'); import rivers as RV
PAGES = {
  'SWEK': ['https://www.swek.wa.gov.au/road-conditions.aspx'],
  'Broome': ['https://www.broome.wa.gov.au/Shire-Services/Infrastructure/Road-Condition-Report-and-Planned-Maintenance'],
  'SDWK': ['https://www.sdwk.wa.gov.au/road-conditions', 'https://www.sdwk.wa.gov.au/services/road-conditions', 'https://www.sdwk.wa.gov.au/road-condition-report', 'https://www.sdwk.wa.gov.au/'],
  'HallsCreek': ['https://www.hallscreek.wa.gov.au/services/road-conditions'],
  'EastPilbara': ['https://eastpilbara.wa.gov.au/roadreport'],
  'Ashburton': ['https://www.ashburton.wa.gov.au/road-conditions', 'https://www.ashburton.wa.gov.au/'],
}
for shire, urls in PAGES.items():
    for u in urls:
        try: t = RV.get(u, 60, 1)
        except Exception as e: print('\n##', shire, u, 'ERR', str(e)[:80]); continue
        links = re.findall(r'href="([^"]+)"[^>]*>(.*?)</a>', t, re.S)
        rl = [(urllib.parse.urljoin(u, h), RV.clean(x)[:80]) for h, x in links if re.search(r'(?i)road|condition|closure', h + x) and not re.search(r'(?i)facebook|twitter|mailto', h)]
        body = RV.clean(re.sub(r'(?is)<(script|style|nav|header|footer).*?</\1>', ' ', t))
        i = body.lower().find('road')
        print('\n##', shire, u, len(t)); print(' links:', rl[:25]); print(' text:', body[max(0, i - 200):i + 1800])
        break

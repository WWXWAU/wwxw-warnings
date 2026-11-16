"""Probe: how do Broome, Halls Creek, Ashburton and Laverton publish their road reports (document links, page text)?"""
import urllib.request, urllib.parse, re, subprocess, sys
subprocess.run(['sudo', 'apt-get', 'install', '-y', '-qq', 'poppler-utils'], check=False, capture_output=True)
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36'}
PAGES = [('Broome', 'https://www.broome.wa.gov.au/Shire-Services/Infrastructure/Road-Condition-Report-and-Planned-Maintenance'),
         ('Halls Creek', 'https://www.hallscreek.wa.gov.au/services/road-conditions'),
         ('Ashburton', 'https://www.ashburton.wa.gov.au/services/emergency-safety/road-report.aspx'),
         ('Laverton', 'https://laverton.wa.gov.au/services/roads/road-condition-reports.aspx')]
def get(u): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60)
for name, url in PAGES:
    print('\n=====', name, url)
    try: r = get(url); html = r.read().decode('utf-8', 'replace'); print('final', r.geturl(), len(html))
    except Exception as e: print('ERR', e); continue
    body = re.sub(r'(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>', ' ', html)
    txt = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', body))
    i = txt.lower().find('road'); print('TEXT:', txt[max(0, i - 200):i + 2500])
    links = sorted(set(re.findall(r'(?i)(?:href|src)="([^"]+\.(?:pdf|jpe?g|png|docx?)[^"]*)"', html)))
    print('DOCS:'); [print('  ', l) for l in links[:40]]
    pdfs = [l for l in links if '.pdf' in l.lower() and re.search(r'(?i)road|condition|report', l)]
    for l in pdfs[:2]:
        u = l if l.startswith('http') else urllib.parse.urljoin(url, l)
        try:
            open('/tmp/r.pdf', 'wb').write(get(u).read())
            t = subprocess.run(['pdftotext', '-layout', '/tmp/r.pdf', '-'], capture_output=True, text=True).stdout
            print('PDF', u, 'chars', len(t)); print(t[:3000])
        except Exception as e: print('PDF ERR', u, e)

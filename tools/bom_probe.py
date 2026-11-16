"""Probe: where the Bureau's tropical cyclone outlook lives now (old IDW10800 product vs the new website)."""
import urllib.request, re
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36'}
URLS = ['https://reg.bom.gov.au/products/IDW10800.shtml', 'https://reg.bom.gov.au/fwo/IDW10800.txt', 'https://www.bom.gov.au/fwo/IDW10800.txt',
        'https://www.bom.gov.au/cyclone/tropical-cyclone-outlook/', 'https://www.bom.gov.au/weather-and-climate/specialised-forecasts-and-observations/tropical-cyclone']
for u in URLS:
    print('\n=====', u)
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40); b = r.read().decode('utf-8', 'replace')
        print('HTTP', r.status, r.geturl(), len(b))
        t = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', ' ', b)))
        i = t.find('01U'); print('TEXT 01U:', t[max(0, i - 300):i + 800] if i >= 0 else t[:600])
        print('URLS:', sorted(set(re.findall(r'https?://[\w./-]*(?:api|json|data)[\w./?=&-]*', b)))[:30])
        j = b.find('01U'); print('RAW near 01U:', b[max(0, j - 400):j + 400] if j >= 0 else '-')
    except Exception as e: print('ERR', e)

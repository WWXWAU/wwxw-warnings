"""Probe: what a WeatherLink public bulletin page contains (is its data readable without the owner's API key?)."""
import urllib.request, re
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36'}
ID = 'a787caf4-e656-48b4-af39-e2e0efabdb79'
for u in ['https://www.weatherlink.com/bulletin/' + ID, 'https://www.weatherlink.com/bulletin/data/' + ID, 'https://www.weatherlink.com/embeddablePage/summaryData/' + ID]:
    print('\n=====', u)
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40); b = r.read().decode('utf-8', 'replace')
        print('HTTP', r.status, r.headers.get('content-type'), len(b))
        t = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', ' ', b)))
        print('TEXT:', t[:1500])
        print('URLS:', sorted(set(re.findall(r'["\'](/[\w/.-]*(?:data|api|json|summary)[\w/.?=&-]*)["\']', b)))[:30])
        print('RAW:', b[:1500] if 'json' in (r.headers.get('content-type') or '') else '')
    except Exception as e: print('ERR', e)

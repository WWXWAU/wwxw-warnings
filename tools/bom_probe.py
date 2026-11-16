"""Probe: what data the Bureau's new tropical cyclone page loads (to see whether the outlook comes from an open feed)."""
import re
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(); seen = []
    def resp(r):
        ct = r.headers.get('content-type', '')
        if 'json' in ct or 'xml' in ct or re.search(r'(?i)cyclone|tropical|outlook|tc', r.url):
            try: body = r.text()[:600]
            except Exception: body = ''
            seen.append((r.status, r.url, ct, body))
    pg.on('response', resp)
    r = pg.goto('https://www.bom.gov.au/weather-and-climate/specialised-forecasts-and-observations/tropical-cyclone', wait_until='networkidle', timeout=120000)
    print('page', r.status if r else None)
    t = pg.inner_text('body'); i = t.find('01U'); print('TEXT:', re.sub(r'\s+', ' ', t[max(0, i - 200):i + 900]) if i >= 0 else t[:300])
    for s in seen: print('\n', s[0], s[1], s[2]); print('   ', s[3].replace('\n', ' ')[:600])
    b.close()

"""Probe: Halls Creek's road conditions page in a browser (it comes back empty to a plain fetch), and pdftotext presence."""
import subprocess, re, shutil
print('pdftotext on runner before install:', shutil.which('pdftotext'))
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page()
    reqs = []
    pg.on('request', lambda r: reqs.append(r.url) if re.search(r'(?i)pdf|road|api|json', r.url) else None)
    r = pg.goto('https://www.hallscreek.wa.gov.au/services/road-conditions', wait_until='networkidle', timeout=90000)
    print('status', r.status if r else None, pg.url)
    txt = pg.inner_text('body'); i = txt.lower().find('road condition'); print('TEXT:', re.sub(r'\s+', ' ', txt[max(0, i - 100):i + 2500]))
    print('LINKS:'); [print('  ', h) for h in sorted(set(pg.eval_on_selector_all('a', 'els => els.map(e => e.href)'))) if re.search(r'(?i)pdf|road|report|repository', h)]
    print('REQS:'); [print('  ', u) for u in reqs[:40]]
    b.close()

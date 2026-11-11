"""Promo video footage: the four public pages filmed on a phone (1080 x 1920, dark and light) and desktop, as JPEGs.
Each shot is a page state after an action (tab, button, list click), plus full-length captures for scrolling.
Output: shots/<page>-<n>-<what>.jpg (pushed to the promo-shots branch by promo-capture.yml)."""
import asyncio, os, sys
from playwright.async_api import async_playwright

SITE = 'https://westweatherwatchers.com'
OUT = 'shots'


async def app_frame(pg, sel, wait=30000):
    """The frame (page or Apps Script iframe) holding sel."""
    t = 0
    while t < wait:
        for f in pg.frames:
            try:
                if await f.query_selector(sel): return f
            except Exception: pass
        await pg.wait_for_timeout(500); t += 500
    return None


async def click_text(f, text, wait=2500):
    try:
        el = f.get_by_role('button', name=text, exact=True)
        if await el.count() == 0: el = f.get_by_text(text, exact=True)
        await el.first.click(timeout=5000); await f.page.wait_for_timeout(wait) if hasattr(f, 'page') else None
        return True
    except Exception as e:
        print('  no click', text, str(e)[:80]); return False


async def shot(pg, name, full=False):
    p = os.path.join(OUT, name + '.jpg')
    await pg.screenshot(path=p, type='jpeg', quality=92, full_page=full)
    print('shot', p)


async def film(b, mode, opts):
    ctx = await b.new_context(**opts); pg = await ctx.new_page()
    pg.on('pageerror', lambda e: print('  page error:', str(e)[:120]))
    W = lambda ms: pg.wait_for_timeout(ms)
    # ---- Rainfall
    await pg.goto(SITE + '/rainfall/', wait_until='domcontentloaded'); f = await app_frame(pg, '#top10', 60000); await W(9000)
    await shot(pg, mode + '-rain-1-start')
    if f:
        for i, t in enumerate(('24 hrs', '7 Days', 'Max 1 hr', 'Lightning 24 hrs')):
            if await click_text(f, t): await W(3500); await shot(pg, '%s-rain-%d-%s' % (mode, i + 2, t.replace(' ', '')))
        await click_text(f, 'Total'); await click_text(f, '24 hrs'); await W(3000)
        try:
            await f.evaluate("document.getElementById('top10').scrollIntoView({block:'center'})"); await W(1200); await shot(pg, mode + '-rain-6-top10')
            await f.click('#top10 .t10.go', timeout=5000); await W(4500); await shot(pg, mode + '-rain-7-flyto')
        except Exception as e: print('  top10', str(e)[:100])
    await shot(pg, mode + '-rain-8-full', full=True)
    # ---- Live Obs
    await pg.goto(SITE + '/obs/', wait_until='domcontentloaded'); f = await app_frame(pg, '.t10, #map', 60000); await W(10000)
    await shot(pg, mode + '-obs-1-start')
    if f:
        for i, t in enumerate(('Temperature', 'Max gust (24 hrs)', 'Wind gust', 'Rain since 9am')):
            if await click_text(f, t): await W(3500); await shot(pg, '%s-obs-%d-%s' % (mode, i + 2, t.replace(' ', '').replace('(', '').replace(')', '')))
        try:
            await f.click('.t10.go', timeout=5000); await W(4500); await shot(pg, mode + '-obs-6-flyto')
        except Exception as e: print('  obs t10', str(e)[:100])
    await shot(pg, mode + '-obs-7-full', full=True)
    # ---- River Levels
    await pg.goto(SITE + '/rivers/', wait_until='domcontentloaded'); await W(12000)
    await shot(pg, mode + '-river-1-start')
    try:
        await pg.evaluate("window.riverMap && window.riverMap.jumpTo({center:[125.8,-18.0],zoom:6.6})"); await W(3500); await shot(pg, mode + '-river-2-kimberley')
        await pg.evaluate("window.riverPick && window.riverPick('802203')"); await W(3500); await shot(pg, mode + '-river-3-gauge')
        await pg.evaluate("window.riverMap && window.riverMap.jumpTo({center:[117.5,-21.8],zoom:6.0})"); await W(3500); await shot(pg, mode + '-river-4-pilbara')
    except Exception as e: print('  river', str(e)[:100])
    await shot(pg, mode + '-river-5-full', full=True)
    # ---- Ripper Weather
    await pg.goto(SITE + '/ripper/', wait_until='domcontentloaded'); await W(9000)
    await shot(pg, mode + '-ripper-1-start')
    try:
        await pg.click('#days button:nth-child(2)', timeout=4000); await W(2500); await shot(pg, mode + '-ripper-2-tomorrow')
    except Exception as e: print('  ripper', str(e)[:100])
    await shot(pg, mode + '-ripper-3-full', full=True)
    # ---- Home
    await pg.goto(SITE + '/', wait_until='domcontentloaded'); await W(4000); await shot(pg, mode + '-home-1', full=True)
    await ctx.close()


async def main():
    os.makedirs(OUT, exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch()
        phone = dict(viewport={'width': 400, 'height': 711}, device_scale_factor=2.7, is_mobile=True, has_touch=True,
                     user_agent='Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36')
        modes = {'phone-dark': dict(phone, color_scheme='dark'), 'phone-light': dict(phone, color_scheme='light'),
                 'desk-dark': dict(viewport={'width': 1600, 'height': 900}, device_scale_factor=1.2, color_scheme='dark')}
        for m in (sys.argv[1:] or modes):
            try: await film(b, m, modes[m])
            except Exception as e: print('mode failed', m, e)
        await b.close()

asyncio.run(main())

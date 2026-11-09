"""Screenshot a website page from this repo (served locally) on desktop and phone."""
import asyncio, sys, os, functools, threading, http.server
from playwright.async_api import async_playwright
page = sys.argv[1]   # e.g. site/ripper/index.html
srv = http.server.ThreadingHTTPServer(('127.0.0.1', 8765), functools.partial(http.server.SimpleHTTPRequestHandler, directory='.'))
threading.Thread(target=srv.serve_forever, daemon=True).start()
async def run():
    os.makedirs('previews', exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch()
        for name, opts in (('desktop', dict(viewport={'width': 1400, 'height': 900})), ('phone', p.devices['Pixel 7']),
                           ('desktop-dark', dict(viewport={'width': 1400, 'height': 900}, color_scheme='dark'))):
            ctx = await b.new_context(**opts); pg = await ctx.new_page()
            pg.on('console', lambda m: print('console:', m.text))
            pg.on('pageerror', lambda e: print('page error:', e))
            await pg.goto('http://127.0.0.1:8765/' + page); await pg.wait_for_timeout(5000)
            await pg.screenshot(path='previews/%s.png' % name, full_page=(name == 'phone'))
            if name == 'desktop':
                if await pg.evaluate("typeof window.ripperImage === 'function'"):
                    import base64
                    await pg.evaluate("document.fonts.ready")
                    data = await pg.evaluate("window.ripperImage()")
                    open('previews/share-image.png', 'wb').write(base64.b64decode(data.split(',', 1)[1]))
                dots = await pg.query_selector_all('.mk.dot')
                if dots:
                    await dots[0].hover(); await pg.wait_for_timeout(400)
                    await pg.screenshot(path='previews/desktop-hover.png')
                    mks = await pg.query_selector_all('.mk')
                    await mks[-1].click(); await pg.wait_for_timeout(300); await dots[1].click(force=True); await pg.wait_for_timeout(300)
                    print('popups open after two clicks:', await pg.evaluate("document.querySelectorAll('.maplibregl-popup:not(.tip)').length"))
                    await pg.mouse.click(300, 600); await pg.wait_for_timeout(300)
                    print('popups after a map click:', await pg.evaluate("document.querySelectorAll('.maplibregl-popup:not(.tip)').length"))
                await pg.click('#days button:nth-child(3)'); await pg.wait_for_timeout(1500)
                await pg.screenshot(path='previews/desktop-day3.png')
            await ctx.close()
        await b.close()
asyncio.run(run())

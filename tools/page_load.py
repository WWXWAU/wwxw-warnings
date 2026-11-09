"""Load each website page in a real browser; screenshots each second and the slowest requests."""
import asyncio, time, os
from playwright.async_api import async_playwright
PAGES = [('home', 'https://westweatherwatchers.com/'), ('rainfall', 'https://westweatherwatchers.com/rainfall/'),
         ('obs', 'https://westweatherwatchers.com/obs/')]
async def run():
    os.makedirs('previews', exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch()
        for name, url in PAGES:
            for visit in ('first', 'repeat'):
                ctx = await b.new_context(viewport={'width': 412, 'height': 860}, device_scale_factor=1) if visit == 'first' else ctx
                pg = await ctx.new_page(); reqs = {}; t0 = time.time()
                pg.on('request', lambda r: reqs.__setitem__(r, [time.time() - t0, None, 0]))
                def done(r):
                    if r in reqs: reqs[r][1] = time.time() - t0
                pg.on('requestfinished', done)
                await pg.goto(url, wait_until='commit')
                for s in range(1, 13):
                    await asyncio.sleep(max(0, s - (time.time() - t0)))
                    if visit == 'first' or s in (2, 4, 6):
                        await pg.screenshot(path='previews/%s-%s-%02ds.png' % (name, visit, s))
                rows = sorted(((v[1] or 99) - v[0], v[0], v[1], r.url[:110]) for r, v in reqs.items())[::-1]
                print('\n== %s (%s visit): %d requests, last finished at %.1fs' % (name, visit, len(reqs), max((v[1] or 0) for v in reqs.values())))
                for dur, st, en, u in sorted(rows, key=lambda x: x[1])[:60]:
                    if dur > 0.4: print('  %5.2f -> %5s  %s' % (st, ('%.2f' % en) if en else 'open', u))
                await pg.close()
        await b.close()
asyncio.run(run())

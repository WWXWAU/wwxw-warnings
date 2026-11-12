"""Probe: how MetEye loads its thunderstorm forecast layer (which image or tile URLs), to read it once a day for the
verification. Prints the requests the page makes."""
import asyncio, re
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(); pg = await b.new_page(viewport={'width': 1400, 'height': 900})
        seen = []
        pg.on('request', lambda r: seen.append(r.url))
        for url in ('https://www.bom.gov.au/australia/meteye/', 'https://www.bom.gov.au/australia/meteye/?loc=WA'):
            try:
                resp = await pg.goto(url, wait_until='domcontentloaded', timeout=60000); print('page', url, resp.status if resp else None, pg.url)
            except Exception as e: print('page failed', url, e); continue
            await pg.wait_for_timeout(12000)
            txt = await pg.content(); print('title:', await pg.title(), len(txt))
            for m in sorted(set(re.findall(r'[Tt]hunder[^<"]{0,60}', txt)))[:20]: print('  text:', m)
            for sel in ('text=Thunderstorms', 'text=Thunderstorm', 'text=Weather'):
                try: await pg.click(sel, timeout=4000); await pg.wait_for_timeout(6000); print('clicked', sel)
                except Exception: pass
        await b.close()
        hosts = {}
        for u in seen: h = u.split('/')[2] if '//' in u else u; hosts[h] = hosts.get(h, 0) + 1
        print('hosts:', hosts)
        for u in seen:
            if re.search(r'thund|wx|adfd|tile|layer|wms|grid|IDZ7|\.png|json', u, re.I) and 'google' not in u: print('  ', u[:300])

asyncio.run(main())

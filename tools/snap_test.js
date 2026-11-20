const { chromium } = require('playwright'); const http = require('http'), fs = require('fs'), path = require('path');
const root = path.join(process.cwd(), 'site');
http.createServer((q, r) => { let p = decodeURIComponent(q.url.split('?')[0]); if (p.endsWith('/')) p += 'index.html'; const f = path.join(root, p);
  if (!fs.existsSync(f)) { r.writeHead(404); return r.end(); } r.writeHead(200, { 'Content-Type': f.endsWith('.html') ? 'text/html' : 'application/octet-stream' }); r.end(fs.readFileSync(f)); }).listen(8765);
(async () => {
  const b = await chromium.launch();
  for (const pg of ['rainfall', 'obs']) {
    const p = await b.newPage({ viewport: { width: 412, height: 860 } });
    p.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') console.log(pg, 'console', m.type(), m.text().slice(0, 300)); });
    p.on('pageerror', e => console.log(pg, 'pageerror', e.message.slice(0, 300)));
    p.on('requestfailed', r => console.log(pg, 'failed', r.url().slice(0, 120), r.failure() && r.failure().errorText));
    p.on('response', r => { if (r.status() >= 400) console.log(pg, 'http', r.status(), r.url().slice(0, 120)); });
    await p.goto('http://localhost:8765/' + pg + '/'); await p.waitForTimeout(25000);
    for (const f of p.frames()) { console.log(pg, 'frame', f.url().slice(0, 80));
      if (/^(about:srcdoc|blob:)/.test(f.url())) console.log(pg, 'state', await f.evaluate(() => JSON.stringify({ map: typeof map, loaded: typeof map !== 'undefined' && map && map.loaded && map.loaded(), layers: typeof map !== 'undefined' && map && map.getStyle ? map.getStyle().layers.length : -1, tiles: typeof map !== 'undefined' && map && map.areTilesLoaded ? map.areTilesLoaded() : null, feats: typeof map !== 'undefined' && map && map.querySourceFeatures ? Object.keys(map.getStyle().sources).map(function(k){try{return k+':'+map.querySourceFeatures(k).length}catch(e){return k+':x'}}).join(' ') : '', canv: document.querySelectorAll('canvas').length, text: document.body.innerText.slice(0, 160) })).catch(e => 'eval ' + e.message)); }
    console.log(pg, 'parent', await p.evaluate(() => { const l = document.querySelector('.loading,.loader,#loading,[class*=load]'); return l ? (l.className + ' ' + getComputedStyle(l).display + ' ' + getComputedStyle(l).opacity) : 'no loader'; }));
    await p.screenshot({ path: 'shot-' + pg + '.png' });
  }
  await b.close(); process.exit(0);
})();

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
    await p.goto('http://localhost:8765/' + pg + '/'); await p.waitForTimeout(15000);
    for (const f of p.frames()) console.log(pg, 'frame', f.url().slice(0, 80));
    await p.screenshot({ path: 'shot-' + pg + '.png' });
  }
  await b.close(); process.exit(0);
})();

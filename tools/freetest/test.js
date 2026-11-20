const { chromium } = require('playwright'); const path = require('path');
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1280, height: 900 } });
  p.on('pageerror', e => console.log('pageerror', e.message)); p.on('console', m => { if (m.type() === 'error') console.log('console', m.text()); });
  await p.goto('file://' + path.resolve('tools/freetest/index.html'));
  await p.click('#freeBtn'); await p.waitForFunction(() => window.fabric, null, { timeout: 20000 }); await p.waitForTimeout(800);
  for (const k of ['text', 'rect', 'circle', 'arrow', 'line']) { await p.click('[data-add="' + k + '"]'); await p.waitForTimeout(200); }
  await p.click('#fLogo'); await p.waitForTimeout(500); await p.click('#fFoot'); await p.waitForTimeout(300);
  await p.selectOption('#fSize', '1080x1920'); await p.waitForTimeout(400);
  await p.click('#fMake'); await p.waitForTimeout(500);
  console.log('objects', await p.evaluate(() => document.querySelector('#fOut img') ? document.querySelector('#fOut img').naturalWidth + 'x' + document.querySelector('#fOut img').naturalHeight : 'no png'));
  console.log('fabric', await p.evaluate(() => fabric.version));
  await p.screenshot({ path: 'free-shot.png' });
  const png = await p.evaluate(() => document.querySelector('#fOut img').src); require('fs').writeFileSync('free-out.png', Buffer.from(png.split(',')[1], 'base64'));
  await b.close();
})();

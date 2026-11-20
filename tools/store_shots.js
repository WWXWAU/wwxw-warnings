// Phone screenshots of the live site in app mode, for the Google Play listing (1080 x 1920)
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=swiftshader', '--enable-unsafe-swiftshader'] });
  const shots = [['1-rainfall', '/rainfall/'], ['2-obs', '/obs/'], ['3-rivers', '/rivers/'], ['4-ripper', '/ripper/'], ['5-home', '/']];
  for (const [n, path] of shots) {
    const p = await b.newPage({ viewport: { width: 432, height: 768 }, deviceScaleFactor: 2.5, isMobile: true, hasTouch: true });
    await p.addInitScript(() => { try { localStorage.setItem('wwxw-theme', 'light'); } catch (e) {} });
    await p.goto('https://westweatherwatchers.com' + path + '?app=1', { waitUntil: 'load' }).catch(() => {});
    await p.waitForTimeout(20000);
    await p.screenshot({ path: 'shots/' + n + '.png' });
    console.log('shot', n);
    await p.close();
  }
  await b.close();
})();

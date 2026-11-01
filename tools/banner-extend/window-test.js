const h = require('/home/user/brave-newtab/tests/helpers.js');
const S = process.argv[2]; const fx = +process.argv[3], fy = +process.argv[4];
const SIZES = [['ultrawide',3440,1355],['27in',2560,1355],['half-27in',1280,1355],['quarter-27in',1280,630],['half-ultrawide',1720,1355],['third-ultrawide',1146,1355],['laptop',1512,860]];
(async () => {
  const { context } = await h.launch({ viewport: { width: 2560, height: 1355 } });
  const page = await h.openNewTab(context);
  await page.mouse.move(2520, 36); await page.waitForTimeout(400); await page.click('#gear');
  const before = await page.evaluate(() => document.body.dataset.uploaded || '');
  await page.setInputFiles('#upload', [S + '/frog-normal.webm', S + '/frog-wide.webm']);
  await page.waitForFunction(b => (document.body.dataset.uploaded || '') !== b, before, { timeout: 60000 });
  await page.click('.lib-item[title="frog-normal"]');
  const wideId = await page.getAttribute('.lib-item[title="frog-wide"]', 'data-id');
  await page.selectOption('#wideSelect', wideId);
  for (const [id, v] of [['focusX', fx], ['focusY', fy]]) await page.evaluate(([id, v]) => { const e = document.getElementById(id); e.value = v; e.dispatchEvent(new Event('input')); }, [id, v]);
  await page.waitForTimeout(500);
  await page.click('#closePanel'); await page.mouse.move(10, 600);
  for (const [name, w, hgt] of SIZES) {
    await page.setViewportSize({ width: w, height: hgt });
    await page.waitForTimeout(700);
    await page.waitForFunction(() => { const v = document.getElementById('bgVideo'); return v.classList.contains('ready') && v.readyState >= 2; }, null, { timeout: 15000 });
    await page.evaluate(async () => { const v = document.getElementById('bgVideo'); v.pause(); v.currentTime = 1.0; await new Promise(r => v.addEventListener('seeked', r, { once: true })); });
    await page.waitForTimeout(300);
    const src = await page.evaluate(() => document.getElementById('bgVideo').videoWidth);
    await page.screenshot({ path: `${S}/shot-${name}.png` });
    console.log(name, w + 'x' + hgt, 'video', src === 1720 ? 'WIDE' : 'NORMAL');
  }
  await context.close();
})().catch(e => { console.error(e); process.exit(1); });

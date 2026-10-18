// Run against the local public demo. No live runs or paid calls are created.
async (page) => {
  await page.unrouteAll();
  page.setDefaultTimeout(20000);
  const origin = new URL(page.url()).origin;
  const errors = [], mutations = [];
  const onError = error => errors.push(error.message);
  const onRequest = request => {
    if (/\/(disruptions|compare-intervention)(?:\?|$)/.test(request.url()))
      mutations.push(request.url());
  };
  page.on('pageerror', onError);
  page.on('request', onRequest);
  try {
    await page.setViewportSize({width:1440,height:900});
    await page.goto(origin);
    const ready = () => page.waitForFunction(() =>
      document.querySelector('iframe:not([hidden])')?.contentWindow.__uitaFrame?.source_id === 'arrival-flows-v1');
    await ready();
    const absent = async () => {
      if (await page.locator('[id^="sandbox-"], #close').count())
        throw Error('Disruption controls remain in the document');
    };
    await absent();
    await page.locator('#drawer-toggle').click();
    await page.locator('#step').click();
    await page.locator('#ds-play').click();
    await page.locator('#ds-play').click();
    await page.locator('#drawer-close').click();
    await page.getByRole('button', {name:'Tower cab',exact:true}).click();
    await ready();
    await page.getByRole('button', {name:'Historical',exact:true}).click();
    await page.waitForFunction(() => document.querySelector('iframe:not([hidden])')?.contentWindow.__uitaFrame?.mode === 'historical');
    await page.getByRole('button', {name:'Simulation',exact:true}).click();
    await ready();
    await page.locator('#drawer-toggle').click();
    await page.locator('#advanced').evaluate(el => {el.open = true});
    await page.getByRole('button', {name:'Compare',exact:true}).click();
    await page.waitForFunction(() => document.querySelector('#comparison-results').textContent.trim().length > 0);
    const download = page.waitForEvent('download');
    await page.locator('#export').click();
    await download;
    await page.locator('#drawer-close').click();
    await page.screenshot({path:'output/playwright/disruption-removed-desktop.png', animations:'disabled'});
    await page.setViewportSize({width:390,height:844});
    await absent();
    await page.screenshot({path:'output/playwright/disruption-removed-mobile.png', animations:'disabled'});
    await page.reload();
    await ready();
    await absent();
    if (errors.length) throw Error(errors.join('\n'));
    if (mutations.length) throw Error('Unexpected disruption requests: ' + mutations.join(', '));
    return {passed:true, errors, mutations};
  } finally {
    page.off('pageerror', onError);
    page.off('request', onRequest);
  }
}

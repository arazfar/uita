import { test } from '@e2e-dev/web';
import { expect } from 'e2e';

test('recorded overview keeps readable instruments at desktop and narrow widths', async ({ app, browser }) => {
  await browser.setViewport({ width: 1280, height: 720 });
  await app.open('/candidates/overview.html');
  await expect(browser.locator('.transport-state')).toHaveText('Paused · recorded observations');
  await expect(browser.locator('.fps-readout')).toContainText(/\d+ fps/);
  expect(await browser.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await app.screenshot('showcase-overview-1280');
  await browser.setViewport({ width: 320, height: 850 });
  expect(await browser.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await app.screenshot('showcase-overview-320');
  await browser.locator('.week-playback').scrollIntoView();
  await expect(browser.locator('.play-key')).toBeVisible();
  await app.screenshot('showcase-overview-320-controls');
});

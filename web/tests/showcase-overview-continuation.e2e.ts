import { test } from '@e2e-dev/web';
import { expect } from 'e2e';

const paused = 'Paused · recorded observations';

test('recorded overview clamps the start and keeps mobile playback usable', async ({ app, screen, browser }) => {
  await app.open('/candidates/overview.html');
  await expect(browser.locator('.transport-state')).toHaveText(paused);
  await browser.locator('#render-quality').selectOption({ value: 'balanced' });
  const catalog = await fetch(new URL('/uita/api/history/catalog', app.baseUrl)).then(result => result.json());

  await screen.getByRole('button', 'Restart week', { exact: true }).tap();
  await expect(browser.locator('.transport-state')).toHaveText(paused);
  await expect(browser.locator('.clock-inset strong')).toHaveText('00:00:00');
  await screen.getByRole('button', /^−15\s*min$/).tap();
  expect(Number(await browser.locator('#replay-position').inputValue())).toBe(catalog.start);

  await browser.setViewport({ width: 320, height: 850 });
  expect(await browser.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await screen.getByRole('button', /^Mon\s*24(?:\s|$)/).tap();
  await expect(browser.locator('.transport-state')).toHaveText(paused);
  await expect(screen.getByRole('button', 'Play', { exact: true })).toBeEnabled();
  await app.screenshot('showcase-threejs-start-and-320px');
});

test('showcase keeps a visible mobile exit from the tower simulation', async ({ app, screen, browser }) => {
  await browser.setViewport({ width: 320, height: 850 });
  await app.open('/sfo-overview/');
  await expect(screen.getByRole('button', 'Tower simulation', { exact: true })).toBeVisible();
  await screen.getByRole('button', 'Tower simulation', { exact: true }).tap();
  await expect(browser.locator('body')).toHaveAttribute('data-view', 'cab');
  await expect(screen.getByRole('button', /Recorded overview/)).toBeVisible();
  await screen.getByRole('button', /Recorded overview/).tap();
  await expect(browser.locator('body')).toHaveAttribute('data-view', 'dash');
  await expect(browser.frameLocator('#dash').locator('.transport-state')).toHaveText(paused);
  await app.screenshot('showcase-threejs-mobile-shell-exit');
});

test('recorded overview supports mobile day selection and playback', async ({ app, screen, browser }) => {
  await browser.setViewport({ width: 320, height: 850 });
  await app.open('/candidates/overview.html');
  await expect(browser.locator('.transport-state')).toHaveText(paused);
  expect(await browser.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await screen.getByRole('button', 'Restart week', { exact: true }).tap();
  await expect(browser.locator('.transport-state')).toHaveText(paused);
  await expect(browser.locator('.clock-inset strong')).toHaveText('00:00:00');
  await screen.getByRole('button', /^Mon\s*24(?:\s|$)/).tap();
  await expect(browser.locator('.transport-state')).toHaveText(paused);
  await expect(browser.locator('.clock-inset strong')).toHaveText('12:00:00');
  await screen.getByRole('combobox', 'Playback speed', { exact: true }).selectOption({ value: '1' });
  const before = Number(await browser.locator('#replay-position').inputValue());
  await screen.getByRole('button', 'Play', { exact: true }).tap();
  await expect.poll(async () => Number(await browser.locator('#replay-position').inputValue())).toBeGreaterThan(before);
  await screen.getByRole('button', 'Pause', { exact: true }).tap();
  await expect(browser.locator('.transport-state')).toHaveText(paused);
  await app.screenshot('showcase-threejs-mobile-day-playback');
});

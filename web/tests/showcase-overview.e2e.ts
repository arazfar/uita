import { test } from '@e2e-dev/web';
import { expect } from 'e2e';

const overviewPath = '/candidates/overview.html';
const paused = 'Paused · recorded observations';
type SourcePoint = [number, number, number, number | null, number | null, number | null, boolean | null, boolean, string, string | null, string | null];
type WindowResponse = { flights: Array<{ id: string; points: SourcePoint[] }> };

// Uses the real showcase proxy and PostgreSQL. Aircraft, timestamps, and the
// evidence comparison are taken from the same original recorded observation.
test('Three.js overview replays all seven days and preserves source evidence', async ({ app, screen, browser }) => {
  await app.open(overviewPath);
  await expect(browser.locator('.transport-state')).toHaveText(paused);
  await expect(browser.locator('.fps-readout')).toContainText(/\d+ fps/);
  await expect(browser.locator('.scene-error')).toBeHidden();
  // Software WebGL is slow in headless Chromium. Use the real detail control
  // after high-detail readiness; playback assertions do not measure performance.
  await browser.locator('#render-quality').selectOption({ value: 'balanced' });
  await expect(browser.locator('.traffic-row').first()).toBeVisible();
  await expect(screen.getByRole('button', 'SFO overview', { exact: true })).toHaveAttribute('aria-pressed', 'true');

  await browser.locator('.traffic-row').first().tap();
  await expect(browser.locator('.evidence-note')).toContainText('Original ADSB.lol sample. No extrapolation.');
  await browser.locator('.source-observation-details summary').tap();
  const identifier = await browser.locator('.aircraft-identifier').textContent();
  const selectedId = identifier.replace(/^Target ID\s*/, '').trim();
  const replayEpoch = Number(await browser.locator('#replay-position').inputValue());
  const response = await fetch(new URL(`/uita/api/history/window?start=${Math.floor(replayEpoch)}`, app.baseUrl));
  expect(response.ok).toBe(true);
  const source: WindowResponse = await response.json();
  const flight = source.flights.find(item => item.id === selectedId);
  expect(Boolean(flight)).toBe(true);
  const point = flight!.points.filter(item => item[0] <= replayEpoch).at(-1)!;
  expect(Boolean(point)).toBe(true);
  expect(replayEpoch - point[0]).toBeLessThanOrEqual(15);
  await expect(browser.locator('.source-observation-details dd').nth(1)).toHaveText(`${point[1].toFixed(6)}°`);
  await expect(browser.locator('.source-observation-details dd').nth(2)).toHaveText(`${point[2].toFixed(6)}°`);
  await expect(browser.locator('.traffic-row[aria-pressed="true"] .traffic-callsign')).toContainText(point[8]);

  await browser.locator('#target-search').fill(selectedId);
  await expect(browser.locator('.traffic-row')).toHaveCount(1);
  await expect(browser.locator('.traffic-row')).toHaveAttribute('aria-pressed', 'true');
  await browser.locator('#target-search').fill('no-such-recorded-aircraft');
  await expect(browser.locator('.traffic-row')).toHaveCount(0);
  await expect(browser.locator('.empty-selection')).toContainText('No fresh observations match');
  await screen.getByRole('button', 'Clear aircraft search', { exact: true }).tap();
  await expect(browser.locator('.traffic-row').first()).toBeVisible();

  const before = Number(await browser.locator('#replay-position').inputValue());
  await screen.getByRole('button', /^\+10\s*s$/).tap();
  await expect(browser.locator('.transport-state')).toHaveText(paused);
  expect(Number(await browser.locator('#replay-position').inputValue()) - before).toBe(10);
  await browser.locator('#playback-rate').selectOption({ value: '600' });
  await screen.getByRole('button', 'Play', { exact: true }).tap();
  await expect.poll(async () => Number(await browser.locator('#replay-position').inputValue()) - before).toBeGreaterThan(20);
  await screen.getByRole('button', 'Pause', { exact: true }).tap();
  await expect(browser.locator('.transport-state')).toHaveText(paused);
  await screen.getByRole('button', 'SFO overview', { exact: true }).tap();
  await app.screenshot('showcase-threejs-recorded-desktop');

  const catalog = await fetch(new URL('/uita/api/history/catalog', app.baseUrl)).then(result => result.json());
  for (let day = 24; day <= 30; day++) {
    const button = screen.getByRole('button', new RegExp(`${day}.*Loaded`));
    await button.tap();
    await expect(browser.locator('.transport-state')).toHaveText(paused);
    await expect(button).toHaveAttribute('aria-pressed', 'true');
    await expect(browser.locator('.clock-inset')).toContainText(`Aug ${day}`);
    await expect(browser.locator('.traffic-count')).not.toContainText('—');
  }

  await screen.getByRole('button', 'Week end', { exact: true }).tap();
  await expect(browser.locator('.transport-state')).toHaveText(paused);
  await expect(browser.locator('.clock-inset strong')).toHaveText('23:59:59');
  await expect(screen.getByRole('button', 'Play', { exact: true })).toBeDisabled();
  await screen.getByRole('button', /^\+15\s*min$/).tap();
  expect(Number(await browser.locator('#replay-position').inputValue())).toBe(catalog.end - 1);
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
  await app.screenshot('showcase-threejs-recorded-320px');
});

test('Three.js overview shows archive failure and retries the real source', async ({ app, screen, browser }) => {
  await browser.route('**/uita/api/history/catalog', route => route.fulfill({
    status: 503,
    json: { detail: 'Database temporarily unavailable' },
  }));
  await app.open(overviewPath);
  await expect(browser.locator('.data-connection-error')).toContainText('Database temporarily unavailable');
  await expect(screen.getByRole('button', 'Play', { exact: true })).toBeDisabled();
  await expect(browser.locator('.traffic-count')).toContainText('—');
  await browser.unroute('**/uita/api/history/catalog');
  await screen.getByRole('button', 'Retry data connection', { exact: true }).tap();
  await expect(browser.locator('.transport-state')).toHaveText(paused);
  await expect(browser.locator('.traffic-row').first()).toBeVisible();
  await expect(browser.locator('.data-connection-error')).toBeHidden();
});

test('Three.js overview retains recorded evidence when a landscape asset fails', async ({ app, browser }) => {
  await browser.route('**/candidates/assets/overview/airport-detail.glb', route => route.fulfill({ status: 404, body: '' }));
  await app.open(overviewPath);
  await expect(browser.locator('.scene-error')).toContainText('Map unavailable');
  await expect(browser.locator('.transport-state')).toHaveText(paused);
  await expect(browser.locator('.traffic-row').first()).toBeVisible();
  await browser.locator('.traffic-row').first().tap();
  await expect(browser.locator('.evidence-note')).toContainText('Original ADSB.lol sample');
  await app.screenshot('showcase-threejs-map-unavailable-evidence');
});

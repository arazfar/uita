import { test } from '@e2e-dev/web';
import { expect } from 'e2e';

const paused = 'Paused · recorded observations';
type SourcePoint = [number, number, number, ...unknown[]];
type RecordedWindow = { flights: Array<{ id: string; points: SourcePoint[] }> };

test('packaged overview preserves real replay and exposes mobile controls', async ({ app, screen, browser }) => {
  await browser.setViewport({ width: 1280, height: 800 });
  await app.open('/sfo-overview/');
  await expect(screen.getByRole('button', /Recorded overview/)).toHaveAttribute('aria-pressed', 'true');
  await expect(screen.getByRole('link', 'Current UI', { exact: true })).toHaveAttribute('href', '/');
  const overview = browser.frameLocator('#dash');
  await expect(overview.locator('.transport-state')).toHaveText(paused);
  await expect(overview.locator('.fps-readout')).toContainText(/\d+ fps/);
  await expect(overview.locator('.scene-error')).toBeHidden();
  await overview.locator('#render-quality').selectOption({ value: 'balanced' });

  const moduleSources = await browser.evaluate(() => {
    const frame = document.querySelector('#dash') as HTMLIFrameElement;
    return [document, frame.contentDocument!].flatMap(doc =>
      Array.from(doc.querySelectorAll<HTMLScriptElement>('script[type="module"][src]'), script => script.src));
  });
  expect(moduleSources.length).toBe(2);
  expect(moduleSources.every(url => new URL(url).pathname.startsWith('/candidates/overview-assets/'))).toBe(true);

  await expect(overview.locator('.evidence-note')).toContainText('Original ADSB.lol sample. No extrapolation.');
  await overview.locator('.source-observation-details summary').tap();
  const selectedId = (await overview.locator('.aircraft-identifier').textContent()).replace(/^Target ID\s*/, '').trim();
  const epoch = Number(await overview.locator('#replay-position').inputValue());
  const response = await fetch(new URL(`/uita/api/history/window?start=${Math.floor(epoch)}`, app.baseUrl));
  expect(response.ok).toBe(true);
  const source: RecordedWindow = await response.json();
  const point = source.flights.find(flight => flight.id === selectedId)?.points.filter(sample => sample[0] <= epoch).at(-1);
  expect(Boolean(point)).toBe(true);
  expect(epoch - point![0]).toBeLessThanOrEqual(15);
  await expect(overview.locator('.source-observation-details dd').nth(1)).toHaveText(`${point![1].toFixed(6)}°`);
  await expect(overview.locator('.source-observation-details dd').nth(2)).toHaveText(`${point![2].toFixed(6)}°`);

  await overview.getByRole('button', /^\+10\s*s$/).tap();
  await expect(overview.locator('.transport-state')).toHaveText(paused);
  expect(Number(await overview.locator('#replay-position').inputValue())).toBe(epoch + 10);
  await overview.getByRole('combobox', 'Playback speed', { exact: true }).selectOption({ value: '1' });
  await overview.getByRole('button', 'Play', { exact: true }).tap();
  await expect.poll(async () => Number(await overview.locator('#replay-position').inputValue())).toBeGreaterThan(epoch + 10);
  await overview.getByRole('button', 'Pause', { exact: true }).tap();
  await expect(overview.locator('.transport-state')).toHaveText(paused);
  await app.screenshot('packaged-overview-desktop');

  await browser.setViewport({ width: 320, height: 850 });
  expect(await browser.evaluate(() => {
    const frame = (document.querySelector('#dash') as HTMLIFrameElement).contentWindow!;
    return document.documentElement.scrollWidth <= innerWidth && frame.document.documentElement.scrollWidth <= frame.innerWidth;
  })).toBe(true);
  await overview.locator('.week-playback').scrollIntoView();
  await expect(overview.getByRole('button', 'Play', { exact: true })).toBeVisible();
  await expect(overview.getByRole('combobox', 'Playback speed', { exact: true })).toBeVisible();
  await app.screenshot('packaged-overview-mobile-controls');
});

test('packaged overview supports mobile tower and keyboard round trips', async ({ app, screen, browser }) => {
  await browser.setViewport({ width: 320, height: 850 });
  await app.open('/sfo-overview/');
  const overview = browser.frameLocator('#dash');
  await expect(overview.locator('.transport-state')).toHaveText(paused);
  await overview.locator('#render-quality').selectOption({ value: 'balanced' });
  const stoppedAt = await overview.locator('#replay-position').inputValue();

  // A real key press in each frame verifies both existing message protocols.
  // The heading focuses the document without targeting a moving aircraft label.
  await overview.getByRole('heading', 'San Francisco Bay', { exact: true }).tap();
  await browser.keyboard.press('t');
  await expect(browser.locator('body')).toHaveAttribute('data-view', 'cab');
  await expect(screen.getByRole('button', /Recorded overview/)).toBeVisible();
  const tower = browser.frameLocator('#cab');
  await expect.poll(() => browser.evaluate(() => {
    const frame = (document.querySelector('#cab') as HTMLIFrameElement).contentWindow as Window & { __sky?: unknown };
    return Boolean(frame.__sky);
  })).toBe(true);
  await tower.locator('#gl').tap();
  await browser.keyboard.press('t');
  await expect(browser.locator('body')).toHaveAttribute('data-view', 'dash');
  await expect(overview.locator('.transport-state')).toHaveText(paused);
  expect(await overview.locator('#replay-position').inputValue()).toBe(stoppedAt);

  await screen.getByRole('button', 'Tower simulation', { exact: true }).tap();
  await expect(screen.getByRole('button', /Recorded overview/)).toBeVisible();
  await screen.getByRole('button', /Recorded overview/).tap();
  await expect(browser.locator('body')).toHaveAttribute('data-view', 'dash');
  await expect(overview.locator('.transport-state')).toHaveText(paused);
  await app.screenshot('packaged-overview-mobile-return');
});

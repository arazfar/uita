import { test } from '@e2e-dev/web';
import { expect } from 'e2e';

const paused = 'Paused · recorded observations';

test('recorded overview can pause while an automatic interval is loading', async ({ app, screen, browser }) => {
  await app.open('/candidates/overview.html');
  await expect(browser.locator('.transport-state')).toHaveText(paused);
  await browser.locator('#render-quality').selectOption({ value: 'balanced' });
  await browser.locator('#replay-local-time').fill('12:14:59');
  await expect(browser.locator('.clock-inset strong')).toHaveText('12:14:59');
  await expect(browser.locator('.transport-state')).toHaveText(paused);
  await screen.getByRole('combobox', 'Playback speed', { exact: true }).selectOption({ value: '60' });

  let release!: () => void;
  let requested = false;
  const held = new Promise<void>(resolve => { release = resolve; });
  await browser.route('**/uita/api/history/window*', async route => {
    requested = true;
    await held;
    await route.continue();
  });
  try {
    await screen.getByRole('button', 'Play', { exact: true }).tap();
    await expect.poll(() => requested).toBe(true);
    await expect(browser.locator('.transport-state')).toHaveText('Loading interval · clock held');
    await expect(screen.getByRole('button', 'Pause', { exact: true })).toBeEnabled();
    await screen.getByRole('button', 'Pause', { exact: true }).tap();
    await expect(screen.getByRole('button', 'Play', { exact: true })).toBeDisabled();
  } finally {
    release();
  }
  await expect(browser.locator('.transport-state')).toHaveText(paused);
  await browser.unroute('**/uita/api/history/window*');
  await expect(browser.locator('.traffic-row').first()).toBeVisible();
  const before = await browser.locator('#replay-position').inputValue();
  const after = await browser.evaluate(async () => {
    await new Promise(resolve => setTimeout(resolve, 1000));
    return (document.querySelector('#replay-position') as HTMLInputElement).value;
  });
  expect(after).toBe(before);
  await browser.setViewport({ width: 320, height: 850 });
  await expect(screen.getByRole('combobox', 'Playback speed', { exact: true })).toBeEnabled();
});

test('recorded overview keeps rendering suspended until the shell resumes it', async ({ app, browser }) => {
  // Count browser graphics calls without exposing or replacing application state.
  await browser.addInitScript(() => {
    const observedWindow = window as typeof window & { __uitaDrawCalls: number };
    observedWindow.__uitaDrawCalls = 0;
    const prototype = WebGL2RenderingContext.prototype as unknown as Record<string, (...args: unknown[]) => unknown>;
    for (const name of ['drawArrays', 'drawElements', 'drawArraysInstanced', 'drawElementsInstanced']) {
      const original = prototype[name];
      prototype[name] = function (...args: unknown[]) {
        observedWindow.__uitaDrawCalls++;
        return Reflect.apply(original, this, args);
      };
    }
  });
  await app.open('/sfo-overview/');
  const frame = browser.frameLocator('#dash');
  await expect(frame.locator('.transport-state')).toHaveText(paused);
  await expect(frame.locator('.fps-readout')).toContainText(/\d+ fps/);
  await frame.locator('#render-quality').selectOption({ value: 'balanced' });
  await expect.poll(() => browser.evaluate(() => {
    const view = (document.querySelector('#dash') as HTMLIFrameElement).contentWindow as Window & { __uitaDrawCalls: number };
    return view.__uitaDrawCalls;
  })).toBeGreaterThan(0);

  // The real parent sends its normal pause message. A later document visibility
  // event must not cancel that independent shell state.
  const sample = await browser.evaluate(async () => {
    const view = (document.querySelector('#dash') as HTMLIFrameElement).contentWindow as Window & { __uitaDrawCalls: number };
    view.postMessage({ skyflow: 'pause' }, location.origin);
    await new Promise(resolve => setTimeout(resolve, 250));
    const before = view.__uitaDrawCalls;
    const documentHidden = view.document.hidden;
    view.document.dispatchEvent(new Event('visibilitychange'));
    await new Promise(resolve => setTimeout(resolve, 1200));
    return { before, after: view.__uitaDrawCalls, documentHidden };
  });
  expect(sample.documentHidden).toBe(false);
  expect(sample.after).toBe(sample.before);

  await browser.evaluate(() => {
    const view = (document.querySelector('#dash') as HTMLIFrameElement).contentWindow!;
    view.postMessage({ skyflow: 'resume' }, location.origin);
  });
  await expect.poll(() => browser.evaluate(() => {
    const view = (document.querySelector('#dash') as HTMLIFrameElement).contentWindow as Window & { __uitaDrawCalls: number };
    return view.__uitaDrawCalls;
  })).toBeGreaterThan(sample.after);
});

test('recorded overview clamps week boundaries and stays usable at 320 pixels', async ({ app, screen, browser }) => {
  await app.open('/candidates/overview.html');
  await expect(browser.locator('.transport-state')).toHaveText(paused);
  await browser.locator('#render-quality').selectOption({ value: 'balanced' });
  const catalog = await fetch(new URL('/uita/api/history/catalog', app.baseUrl)).then(result => result.json());

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
  await app.screenshot('showcase-threejs-boundaries-320px');
});

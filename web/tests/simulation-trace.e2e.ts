import { test } from '@e2e-dev/web';
import { expect } from 'e2e';

test('simulation trace follows real recording playback and preserves tower controls', async ({ app, browser }) => {
  await app.open('/candidates/app.html');
  await browser.locator('#drawer-toggle').tap();
  await expect.poll(() => browser.evaluate(() => document.querySelector('#agent-trace')?.textContent)).toContain('Agent thinking trace');
  await expect.poll(() => browser.evaluate(() => document.querySelector('#agent-trace')?.textContent)).toContain('Authored fixture');
  const options = await browser.evaluate(() => Array.from(document.querySelectorAll<HTMLOptionElement>('#recordings option')).map(option => ({value: option.value, text: option.textContent})));
  const target = options.find(option => option.text?.includes('Nemotron'))!;
  expect(Boolean(target)).toBe(true);
  await browser.evaluate((id) => {
    const select = document.querySelector<HTMLSelectElement>('#recordings')!;
    select.value = id;
    select.dispatchEvent(new Event('change', { bubbles: true }));
  }, target.value);
  await browser.locator('#recorded').tap();
  await browser.evaluate(() => {
    const seek = document.querySelector<HTMLInputElement>('#seek')!;
    seek.value = seek.max;
    seek.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await expect.poll(() => browser.evaluate(() => document.querySelector('#agent-trace')?.textContent)).toContain('Agent proposal returned');
  await expect.poll(() => browser.evaluate(() => document.querySelector('#agent-trace')?.textContent)).toContain('No provider reasoning was recorded');
  await browser.locator('.chain-of-thought-header').tap();
  expect(await browser.evaluate(() => document.querySelector('.chain-of-thought-header')?.getAttribute('aria-expanded'))).toBe('false');
  await browser.keyboard.press('Enter');
  expect(await browser.evaluate(() => document.querySelector('.chain-of-thought-header')?.getAttribute('aria-expanded'))).toBe('true');
  await browser.evaluate(() => {
    const seek = document.querySelector<HTMLInputElement>('#seek')!;
    seek.value = seek.min;
    seek.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await expect.poll(() => browser.evaluate(() => document.querySelector('#agent-trace')?.textContent?.includes('Agent proposal returned'))).toBe(false);
  await browser.locator('#drawer-close').tap();
  await browser.locator('[data-camera="tower"]').tap();
  await expect.poll(() => browser.evaluate(() => {
    const doc = document.querySelector<HTMLIFrameElement>('iframe[title="SFO tower cab"]')?.contentDocument;
    return !!doc?.querySelector('#controls');
  })).toBe(true);
  await browser.locator('#drawer-toggle').tap();
  await app.screenshot('simulation-agent-trace');
});

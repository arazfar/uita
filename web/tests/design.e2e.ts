import { test } from '@e2e-dev/web'
import { expect } from 'e2e'

test('reflows at 320px and keeps selected aircraft and playback reachable', async ({ app, screen, browser }) => {
  await browser.setViewport({ width: 320, height: 740 })
  await app.open('/')
  await expect(screen.getByRole('button', 'Play replay')).toBeVisible()
  expect(await browser.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await expect.poll(() => browser.evaluate(() => document.querySelector('.map-status')?.textContent !== 'Loading basemap…')).toBe(true)
  await app.screenshot('sfo-tempelhof-320-map')
  await screen.getByRole('button', 'Sun', { exact: true }).tap()
  await expect(browser.locator('.clock')).toContainText('Aug 9 07:00:00 PDT')
  await screen.getByRole('button', 'Mon', { exact: true }).tap()
  await screen.getByRole('link', /View feed/).tap()
  await screen.getByRole('button', /UAL689, departure.*path available/).tap()
  await expect(screen.getByRole('region', 'Flight details for UAL689')).toBeVisible()
  expect(await browser.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await app.screenshot('sfo-tempelhof-320-flight-strip')
  await screen.getByRole('button', 'Close flight details').tap()
  await screen.getByRole('button', 'Play replay').tap()
  await expect(screen.getByRole('button', 'Pause replay')).toBeVisible()
  await screen.getByRole('button', 'Pause replay').tap()
})

test('keeps keyboard controls visible with reduced motion and zoom-sized layouts', async ({ app, screen, browser }) => {
  await browser.emulateMedia({ reducedMotion: 'reduce' })
  await app.open('/')
  await expect(screen.getByRole('button', 'Play replay')).toBeVisible()
  await screen.getByRole('button', 'Play replay').press('Tab')
  expect(await browser.evaluate(() => {
    const focused = document.activeElement as HTMLElement
    const rect = focused.getBoundingClientRect()
    return focused.matches(':focus-visible') && getComputedStyle(focused).outlineStyle !== 'none'
      && rect.left >= 0 && rect.right <= innerWidth
  })).toBe(true)
  expect(await browser.evaluate(() => getComputedStyle(document.querySelector('.play')!).transitionDuration)).toBe('0s')
  await screen.getByRole('button', 'Play replay').press('Space')
  await expect(screen.getByRole('button', 'Pause replay')).toBeVisible()
  await screen.getByRole('button', 'Pause replay').press('Space')
  // 640px and 320px are the CSS viewport widths of a 1280px window at 200% and 400% zoom.
  for (const width of [800, 640, 320]) {
    await browser.setViewport({ width, height: 800 })
    await screen.getByRole('button', 'Sun', { exact: true }).tap()
    await expect(browser.locator('.clock')).toContainText('Aug 9 07:00:00 PDT')
    expect(await browser.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  }
  await app.screenshot('sfo-tempelhof-reduced-motion-controls')
})

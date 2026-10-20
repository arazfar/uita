import { test } from '@e2e-dev/web'
import { expect } from 'e2e'

test('loads the real week, renders the map, and shows hourly traffic for the full roster', async ({ app, screen, browser }) => {
  const response = await fetch(new URL('/data/flights.json', app.baseUrl))
  const data = await response.json()
  expect(data.flights.length).toBe(8439)
  expect(data.flights.filter((flight: { has_track: boolean }) => flight.has_track).length).toBe(4128)
  await app.open('/')
  await expect(screen.getByRole('heading', 'Up in the Air · SFO')).toBeVisible()
  await expect(screen.getByRole('region', 'SFO tracked flight map')).toBeVisible()
  await expect(browser.locator('canvas').first()).toBeVisible()
  const stats = browser.locator('.stats')
  await expect(stats).toContainText('on map now')
  await expect(stats).toContainText('arrivals, last hr')
  await expect(stats).toContainText('departures, last hr')
  await expect(stats).toContainText('28L / 28R, last hr')
  await expect(stats).not.toContainText('NaN')
  await expect(browser.locator('.feed-caption')).toContainText('8,439 roster operations')
  // Capture the settled basemap state, whether tiles loaded or the fallback appears.
  await expect.poll(() => browser.evaluate(() => document.querySelector('.map-status')?.textContent !== 'Loading basemap…')).toBe(true)
  await app.screenshot('sfo-replay-desktop')
})

test('plays, pauses, changes speed, and jumps across all seven days', async ({ app, screen, browser }) => {
  await app.open('/')
  const timeline = screen.getByRole('slider', 'Replay timeline')
  await expect(timeline).toBeVisible()
  const start = Number(await timeline.inputValue())
  await screen.getByRole('button', '300 times normal speed').tap()
  await expect(screen.getByRole('button', '300 times normal speed')).toHaveAttribute('aria-pressed', 'true')
  await screen.getByRole('button', 'Play replay').tap()
  await expect.poll(async () => Number(await timeline.inputValue())).toBeGreaterThan(start)
  await screen.getByRole('button', 'Pause replay').tap()
  await expect(screen.getByRole('button', 'Play replay')).toBeVisible()
  for (const [label, date] of [['Mon', 'Aug 3'], ['Tue', 'Aug 4'], ['Wed', 'Aug 5'], ['Thu', 'Aug 6'], ['Fri', 'Aug 7'], ['Sat', 'Aug 8'], ['Sun', 'Aug 9']]) {
    await screen.getByRole('button', label, { exact: true }).tap()
    await expect(browser.locator('.clock')).toContainText(`${date} 07:00:00 PDT`)
    await expect(screen.getByRole('button', label, { exact: true })).toHaveAttribute('aria-pressed', 'true')
  }
  // Space on a native button must activate that button, without a second global toggle.
  await screen.getByRole('button', 'Play replay').press('Space')
  await expect(screen.getByRole('button', 'Pause replay')).toBeVisible()
  await screen.getByRole('button', 'Pause replay').press('Space')
  await expect(screen.getByRole('button', 'Play replay')).toBeVisible()
})

test('lists only tracked flights and opens their details', async ({ app, screen, browser }) => {
  await app.open('/')
  const feed = screen.getByRole('list', 'Recent tracked flights, newest first')
  await expect(feed).toBeVisible()
  await expect(feed.getByRole('button', /SKW4763, arrival/)).toBeHidden()
  await feed.getByRole('button', /UAL689, departure/).tap()
  await expect(screen.getByRole('region', 'Flight details for UAL689')).toContainText('Track points')
  await expect(browser.locator('.inspector')).not.toContainText('This roster operation has no map path.')
  await screen.getByRole('button', 'Close flight details').tap()
  await expect(screen.getByRole('region', 'Flight details for UAL689')).toBeHidden()
  await app.screenshot('sfo-replay-flight-details')
})

test('handles week boundaries without empty or broken counts', async ({ app, screen, browser }) => {
  await app.open('/')
  const timeline = screen.getByRole('slider', 'Replay timeline')
  await expect(timeline).toBeVisible()
  await timeline.press('Home')
  await expect(browser.locator('.clock')).toContainText('Aug 3 00:00:00 PDT')
  await expect(screen.getByText('No tracked flights yet. Select a day to jump to 07:00.')).toBeVisible()
  await expect(browser.locator('.stats')).not.toContainText('NaN')
  await timeline.press('End')
  await expect(browser.locator('.clock')).toContainText('Aug 9 23:59:59 PDT')
  await expect(browser.locator('.stats')).not.toContainText('NaN')
})

test('keeps map, controls, and feed usable on a phone width', async ({ app, screen, browser }) => {
  await browser.setViewport({ width: 390, height: 844 })
  await app.open('/')
  await expect(screen.getByRole('region', 'SFO tracked flight map')).toBeVisible()
  await expect(screen.getByRole('button', 'Sun', { exact: true })).toBeVisible()
  expect(await browser.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await screen.getByRole('heading', 'Tracked flights').scrollIntoView()
  await expect(screen.getByRole('list', 'Recent tracked flights, newest first')).toBeVisible()
  await app.screenshot('sfo-replay-mobile')
})

test('shows a recovery action if a required data file is missing', async ({ app, screen, browser }) => {
  await browser.route('**/data/tracks.json', (route) => route.fulfill({ status: 404, body: 'missing' }))
  await app.open('/')
  await expect(screen.getByRole('alert')).toContainText('Failed to load replay data')
  await expect(screen.getByRole('alert')).toContainText('bun run data')
})

test('keeps aircraft and traffic counts available when the basemap request fails', async ({ app, screen, browser }) => {
  await browser.route('**/gl/dark-matter-gl-style/style.json', (route) => route.abort())
  await app.open('/')
  await expect(screen.getByRole('status')).toContainText('Basemap is slow or unavailable. Aircraft paths remain available.')
  await expect(screen.getByRole('region', 'SFO tracked flight map')).toBeVisible()
  await expect(browser.locator('canvas#deckgl-overlay')).toBeVisible()
  await expect(browser.locator('.stats')).toContainText('11')
  await expect(browser.locator('.stats')).toContainText('on map now')
  await app.screenshot('sfo-replay-basemap-unavailable')
})

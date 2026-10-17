import { test } from "@e2e-dev/web";
import { expect } from "e2e";

// Uses the real showcase proxy and PostgreSQL. No synthetic aircraft fixtures.
test("replays the real week, inspects a source observation and controls time", async ({
  app,
  screen,
  browser,
}) => {
  await app.open("/candidates/11-photoreal-sfo.html");
  await expect(browser.locator("#hr-status")).toHaveText(
    "Paused · recorded observations",
  );
  await expect(browser.locator("#hr-targets")).not.toHaveText("—");
  await expect(browser.locator("#banner")).toBeHidden();
  await expect(browser.locator("#hr-list button").first()).toBeVisible();
  await browser.locator("#hr-list button").first().tap();
  await expect(browser.locator("#hr-detail")).toContainText(
    "Original ADSB.lol measurement",
  );
  await expect(browser.locator("#hr-detail")).toContainText(
    "Barometric altitude",
  );
  const t = () => browser.locator("#hr-clock").getAttribute("datetime");
  // Prove the inspector uses the same original point returned by the real API.
  const selectedId = await browser
    .locator("#hr-list button")
    .first()
    .getAttribute("data-flight");
  const replayEpoch = Date.parse((await t())!) / 1000;
  const source = await fetch(
    "http://127.0.0.1:5190/uita/api/history/window?start=" +
      Math.floor(replayEpoch),
  ).then((r) => r.json());
  const sourceFlight = source.flights.find(
    (f: { id: string }) => f.id === selectedId,
  );
  const sourcePoint = sourceFlight.points
    .filter((p: number[]) => p[0] <= replayEpoch)
    .at(-1);
  await expect(browser.locator("#hr-detail dd").nth(3)).toHaveText(
    sourcePoint[1].toFixed(6) + "°",
  );
  await expect(browser.locator("#hr-detail dd").nth(4)).toHaveText(
    sourcePoint[2].toFixed(6) + "°",
  );
  const before = await t();
  await screen.getByRole("button", "+10 sec", { exact: true }).tap();
  expect(Date.parse((await t())!) - Date.parse(before!)).toBe(10000);
  await screen
    .getByRole("combobox", "Playback speed")
    .selectOption({ value: "600" });
  await screen.getByRole("button", "Play", { exact: true }).tap();
  await expect
    .poll(async () => Date.parse((await t())!) - Date.parse(before!))
    .toBeGreaterThan(20000);
  await screen.getByRole("button", "Pause", { exact: true }).tap();
  await expect(browser.locator("#hr-status")).toHaveText(
    "Paused · recorded observations",
  );
  await screen.getByRole("button", "SFO overview", { exact: true }).tap();
  await app.screenshot("showcase-recorded-desktop");
  for (let day = 24; day <= 30; day++) {
    await screen.getByRole("button", new RegExp(`Aug ${day} Loaded`)).tap();
    await expect(browser.locator("#hr-status")).toHaveText(
      "Paused · recorded observations",
    );
    await expect(browser.locator("#hr-clock")).toContainText(`Aug ${day}`);
    await expect(browser.locator("#hr-targets")).not.toHaveText("—");
  }
  await screen.getByRole("button", "Week end", { exact: true }).tap();
  await expect(browser.locator("#hr-clock")).toContainText("23:59:59");
  await expect(
    screen.getByRole("button", "Play", { exact: true }),
  ).toBeDisabled();
  await screen.getByRole("button", "+15 min", { exact: true }).tap();
  await expect(browser.locator("#hr-clock")).toContainText("Aug 30, 23:59:59");
  await screen.getByRole("button", "Restart week", { exact: true }).tap();
  await expect(browser.locator("#hr-clock")).toContainText("Aug 24, 00:00:00");
  await screen.getByRole("button", "−15 min", { exact: true }).tap();
  await expect(browser.locator("#hr-clock")).toContainText("Aug 24, 00:00:00");
  await browser.setViewport({ width: 320, height: 850 });
  expect(
    await browser.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await screen.getByRole("button", /Aug 24 Loaded/).tap();
  await expect(browser.locator("#hr-status")).toHaveText(
    "Paused · recorded observations",
  );
  await app.screenshot("showcase-recorded-320px");
});

test("shows an honest error when recorded traffic is unavailable", async ({
  app,
  screen,
  browser,
}) => {
  await browser.route("**/uita/api/history/catalog", (route) =>
    route.fulfill({
      status: 503,
      json: { detail: "Database temporarily unavailable" },
    }),
  );
  await app.open("/candidates/11-photoreal-sfo.html");
  await expect(screen.getByRole("alert")).toContainText(
    "Database temporarily unavailable",
  );
  await expect(
    screen.getByRole("button", "Play", { exact: true }),
  ).toBeDisabled();
  await expect(browser.locator("#banner")).toBeHidden();
  await expect(browser.locator("#hr-targets")).toHaveText("—");
  await browser.unroute("**/uita/api/history/catalog");
  await screen
    .getByRole("button", "Retry data connection", { exact: true })
    .tap();
  await expect(browser.locator("#hr-status")).toHaveText(
    "Paused · recorded observations",
  );
});

test("opens the shipped showcase on recorded traffic", async ({
  app,
  screen,
  browser,
}) => {
  // The recorded shell must not depend on another candidate's optional theme.
  await browser.route('**/atc-theme.css', route=>route.fulfill({status:404,body:''}));
  await app.open("/candidates/app.html");
  await expect(screen.getByRole("button", /Recorded week/)).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  const frame = browser.frameLocator("#dash");
  await expect(frame.locator("#hr-status")).toHaveText(
    "Paused · recorded observations",
  );
  await expect(
    frame.getByRole("heading", "SFO · August 24–30, 2026"),
  ).toBeVisible();
  await app.screenshot("showcase-shipped-app");
});

test("returns to a cached time while another interval is still loading", async ({
  app,
  screen,
  browser,
}) => {
  await app.open("/candidates/11-photoreal-sfo.html");
  await expect(browser.locator("#hr-status")).toHaveText(
    "Paused · recorded observations",
  );
  const original = await browser.locator("#hr-clock").getAttribute("datetime");
  let release!: () => void;
  let started = false;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await browser.route("**/uita/api/history/window*", async (route) => {
    started = true;
    await held;
    // Seeking back aborts this request. Chromium may dispose its intercepted
    // route before our deliberately held response is released.
    try {
      await route.fulfill({status:503,json:{detail:'Delayed interval unavailable'}});
    } catch (error) {
      if (!String(error).includes('Route is already handled')) throw error;
    }
  });
  try {
    await screen.getByRole("button", "+15 min", { exact: true }).tap();
    await expect.poll(() => started).toBe(true);
    await expect(browser.locator("#hr-status")).toContainText(
      "Loading interval",
    );
    await screen.getByRole("button", "−15 min", { exact: true }).tap();
    await expect(browser.locator("#hr-status")).toHaveText(
      "Paused · recorded observations",
    );
    await expect(browser.locator("#hr-clock")).toHaveAttribute(
      "datetime",
      original!,
    );
    await expect(browser.locator("#hr-targets")).not.toHaveText("—");
  } finally {
    release();
  }
  await browser.unroute("**/uita/api/history/window*");
  await screen.getByRole("button", "+10 sec", { exact: true }).tap();
  await expect(browser.locator("#hr-status")).toHaveText(
    "Paused · recorded observations",
  );
  await expect(screen.getByRole("alert")).toBeHidden();
});

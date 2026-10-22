import { test } from "@e2e-dev/web";
import { expect } from "e2e";

test("detailed tower scenery survives camera changes and pauses its water with the demo", async ({
  app,
  browser,
  screen,
}) => {
  await browser.addInitScript(() => {
    (window as any).__sceneryErrors = [];
    addEventListener("error", (e) =>
      (window as any).__sceneryErrors.push(e.message),
    );
    addEventListener("unhandledrejection", (e) =>
      (window as any).__sceneryErrors.push(String(e.reason)),
    );
  });
  await app.open("/candidates/19-tower-cab-interior.html?mode=runway-demo");
  await expect
    .poll(() =>
      browser.evaluate(() => (window as any).__sky?.scenery.userData.quality),
    )
    .toBe("detailed");
  const geometry = await browser.evaluate(() => {
    const s = (window as any).__sky.scenery;
    let highest = 0,
      invalid = 0;
    s.traverse((o: any) => {
      const p = o.geometry?.attributes.position;
      if (!p) return;
      for (let i = 0; i < p.count; i++) {
        if (![p.getX(i), p.getY(i), p.getZ(i)].every(Number.isFinite))
          invalid++;
        if (o.name.startsWith("Terrain ridge"))
          highest = Math.max(highest, p.getY(i));
      }
    });
    const detail = s.getObjectByName("SFO detailed scenery");
    return {
      highest,
      invalid,
      info: detail.userData,
      buildings: Boolean(s.getObjectByName("Blender airport architecture")),
    };
  });
  expect(geometry.highest).toBeGreaterThan(300);
  expect(geometry.invalid).toBe(0);
  expect(geometry.info.terrain.size).toBe(401);
  expect(geometry.info.ready).toBe(true);
  expect(geometry.buildings).toBe(true);
  await screen.getByRole("button", "Pause", { exact: true }).tap();
  const offset = () =>
    browser.evaluate(() =>
      (window as any).__sky.scenery
        .getObjectByName("San Francisco Bay · sky reflections")
        .material.normalMap.offset.toArray(),
    );
  const before = await offset();
  await screen.getByRole("button", "Apron", { exact: true }).tap();
  await expect
    .poll(() => browser.evaluate(() => (window as any).__sky.camera.fov))
    .toBeCloseTo(48, 1);
  await app.screenshot("tower-scenery-apron");
  expect(await offset()).toEqual(before);
  await screen.getByRole("button", "Tower desk", { exact: true }).tap();
  await expect
    .poll(() => browser.evaluate(() => (window as any).__sky.camera.fov))
    .toBeCloseTo(58, 1);
  await app.screenshot("tower-scenery-desk");
  await screen.getByRole("button", "Watch landing", { exact: true }).tap();
  await expect.poll(async () => (await offset())[0]).not.toBe(before[0]);
  await screen.getByRole("button", "Pause", { exact: true }).tap();
  await app.screenshot("tower-scenery-landing");
  await browser.setViewport({ width: 390, height: 844 });
  await expect(
    screen.getByRole("button", "Watch landing", { exact: true }),
  ).toBeVisible();
  expect(
    await browser.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await app.screenshot("tower-scenery-mobile");
  expect(await browser.evaluate(() => (window as any).__sceneryErrors)).toEqual(
    [],
  );
});

test("a missing detail asset preserves the runway demo with honest base-imagery credits", async ({
  app,
  browser,
  screen,
}) => {
  await browser.route("**/airport-detail.glb", (route) => route.abort());
  await app.open("/candidates/19-tower-cab-interior.html?mode=runway-demo");
  await expect
    .poll(() =>
      browser.evaluate(() => (window as any).__sky?.scenery.userData.quality),
    )
    .toBe("fallback");
  await expect(browser.locator("#attrib")).toContainText("Imagery USGS NAIP");
  await expect(browser.locator("#attrib")).not.toContainText(
    "authored airport detail",
  );
  await screen.getByRole("button", "Watch landing", { exact: true }).tap();
  await expect
    .poll(() =>
      browser.evaluate(
        () =>
          (window as any).__sky.actors.find((a: any) => a.cs === "AAL173")
            ?.flightState.phase,
      ),
    )
    .toBe("flare");
  expect(
    await browser.evaluate(() => (window as any).__sky.scenery.visible),
  ).toBe(true);
  await app.screenshot("tower-scenery-fallback");
});

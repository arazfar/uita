import { test } from "@e2e-dev/web";
import { expect } from "e2e";

test("first-person input, daylight, and gesture-enabled spatial sound work together", async ({
  app,
  browser,
}) => {
  await app.open("/candidates/19-tower-cab-interior.html");
  await expect
    .poll(() => browser.evaluate(() => Boolean((window as any).__sky)))
    .toBe(true);
  const initial = await browser.evaluate(() => {
    const s = (window as any).__sky;
    return {
      x: s.camera.position.x,
      q: s.camera.quaternion.toArray(),
      fov: s.camera.fov,
      settings: s.atmosphere.settings,
      audio: s.spatialAudio.getSnapshot(),
    };
  });
  expect(initial.audio.enabled).toBe(false);
  expect(initial.settings.sunElevation).toBe(28);
  expect(initial.fov).toBe(58);
  await browser.locator("#gl").tap();
  await browser.keyboard.down("ArrowRight");
  await expect
    .poll(() =>
      browser.evaluate(() => (window as any).__sky.camera.quaternion.y),
    )
    .not.toBe(initial.q[1]);
  await browser.keyboard.up("ArrowRight");
  await browser.keyboard.down("e");
  await expect
    .poll(() => browser.evaluate(() => (window as any).__sky.camera.position.x))
    .toBeGreaterThan(initial.x + 0.1);
  await browser.keyboard.up("e");
  await expect
    .poll(() =>
      browser.evaluate(() =>
        Math.abs(
          (window as any).__sky.camera.position.x -
            (0.02 * Math.cos(-Math.PI / 10) + 0.32 * Math.sin(-Math.PI / 10)),
        ),
      ),
    )
    .toBeLessThan(0.005);
  await browser.locator('[data-p="desk"]').tap();
  await expect
    .poll(() =>
      browser.evaluate(() =>
        Math.abs((window as any).__sky.camera.quaternion.y),
      ),
    )
    .toBeLessThan(0.21);
  await browser.locator("#bSound").tap();
  await expect
    .poll(() =>
      browser.evaluate(
        () => (window as any).__sky.spatialAudio.getSnapshot().outputRms,
      ),
    )
    .toBeGreaterThan(0);
  const audio = await browser.evaluate(() =>
    (window as any).__sky.spatialAudio.getSnapshot(),
  );
  expect(audio.error).toBe(null);
  expect(audio.voices.length).toBeGreaterThan(0);
  expect(audio.voices.length).toBeLessThan(7);
  await browser.locator("#bPlay").tap();
  await expect
    .poll(() =>
      browser.evaluate(
        () => (window as any).__sky.spatialAudio.getSnapshot().state,
      ),
    )
    .toBe("suspended");
  expect(
    await browser.evaluate(
      () => (window as any).__sky.spatialAudio.getSnapshot().outputRms,
    ),
  ).toBe(0);
  await browser.locator("#bPlay").tap();
  await expect
    .poll(() =>
      browser.evaluate(
        () => (window as any).__sky.spatialAudio.getSnapshot().outputRms,
      ),
    )
    .toBeGreaterThan(0);
  await browser.locator("#bSound").tap();
  await expect
    .poll(() =>
      browser.evaluate(
        () => (window as any).__sky.spatialAudio.getSnapshot().state,
      ),
    )
    .toBe("suspended");
  await app.screenshot("tower-immersive-daylight");
});

test("real saved backend traffic keeps authority in the existing tower shell", async ({
  app,
  browser,
}) => {
  await app.open("/candidates/app.html#cab");
  await browser.locator('[data-camera="tower"]').tap();
  await expect
    .poll(() =>
      browser.evaluate(() => {
        const win = Array.from(document.querySelectorAll("iframe")).find((f) =>
          f.src.includes("19-tower"),
        )?.contentWindow as any;
        return win?.__uitaFrame?.aircraft?.length || 0;
      }),
    )
    .toBeGreaterThan(0);
  await browser.locator("#speed").selectOption({ value: "1" });
  await browser.frameLocator('iframe[src*="19-tower"]').locator("#gl").tap();
  await browser.keyboard.press("m");
  await browser.locator("#play").tap();
  await expect
    .poll(() =>
      browser.evaluate(() => {
        const w = Array.from(document.querySelectorAll("iframe")).find((f) =>
          f.src.includes("19-tower"),
        )?.contentWindow as any;
        return w?.__sky?.actors?.filter((a) => a.vis).length || 0;
      }),
    )
    .toBeGreaterThan(0);
  const result = await browser.evaluate(() => {
    const w = Array.from(document.querySelectorAll("iframe")).find((f) =>
      f.src.includes("19-tower"),
    )!.contentWindow as any;
    const s = w.__sky,
      f = w.__uitaFrame;
    return {
      flights: Object.keys(s.flights),
      actors: s.actors
        .filter((a) => a.vis)
        .map((a) => ({ id: a.cs, y: a.pos.y })),
      tracks: f.aircraft.map((a) => ({ id: a.id, altitude: a.altitude_ft })),
      buttons: w.document.querySelectorAll("#controls button").length,
      controlsBottom: w.document.querySelector("#controls").getBoundingClientRect().bottom,
      timelineTop: document.querySelector("footer")!.getBoundingClientRect().top,
      visible: w.getComputedStyle(w.document.querySelector("#controls"))
        .display,
      audio: s.spatialAudio.getSnapshot(),
    };
  });
  expect(result.flights).toEqual([]);
  expect(result.buttons).toBe(15);
  expect(result.controlsBottom).toBeLessThan(result.timelineTop);
  expect(result.visible).not.toBe("none");
  for (const a of result.actors) {
    expect(result.tracks.some((t) => t.id === a.id)).toBe(true);
  }
  expect(result.audio.enabled).toBe(true);
  await expect
    .poll(() =>
      browser.evaluate(() => {
        const w = Array.from(document.querySelectorAll("iframe")).find((f) =>
          f.src.includes("19-tower"),
        )!.contentWindow as any;
        return w.__sky.spatialAudio.getSnapshot().outputRms;
      }),
    )
    .toBeGreaterThan(0);
  await app.screenshot("tower-backend-preserved");
  await browser.locator("#play").tap();
  await expect
    .poll(() =>
      browser.evaluate(() => {
        const w = Array.from(document.querySelectorAll("iframe")).find((f) =>
          f.src.includes("19-tower"),
        )?.contentWindow as any;
        return w?.__sky.spatialAudio.getSnapshot().paused;
      }),
    )
    .toBe(true);
  const discrepancy = await browser.evaluate(() => {
    const w = Array.from(document.querySelectorAll("iframe")).find((f) =>
      f.src.includes("19-tower"),
    )!.contentWindow as any;
    return Math.max(
      ...w.__sky.actors
        .filter((a) => a.vis)
        .map((a) => {
          const t = w.__uitaFrame.aircraft.find((t) => t.id === a.cs);
          return Math.hypot(
            a.pos.x - (t.longitude + 122.3826) * 88288.08474587766,
            a.pos.z + (t.latitude - 37.6164) * 110989.20390546018,
            a.pos.y - t.altitude_ft * 0.3048,
          );
        }),
    );
  });
  expect(discrepancy).toBeLessThan(0.01);
  await browser.locator('[data-camera="dashboard"]').tap();
  await browser.locator('[data-camera="tower"]').tap();
  await expect(browser.locator('[data-camera="tower"]')).toBeVisible();
});

test(
  "arrival vacates the runway and taxis to a clear hold in real time",
  { timeout: 360000, tags: ["long"] },
  async ({ app, browser }) => {
    await app.open("/candidates/19-tower-cab-interior.html");
    await expect
      .poll(() => browser.evaluate(() => Boolean((window as any).__sky)))
      .toBe(true);
    await browser.locator('[data-p="runway"]').tap();
    const read = () =>
      browser.evaluate(() => {
        const a = (window as any).__sky.actors.find((a) => a.cs === "AAL173");
        return {
          phase: a.flightState.phase,
          pos: a.pos.toArray(),
          speed: a.spd,
          clear: a.flightState.runwayClear,
        };
      });
    await expect
      .poll(async () => (await read()).phase, {
        timeout: 180000,
        interval: 1000,
      })
      .toBe("runway-exit");
    const exit = await read();
    expect(exit.speed).toBeLessThan(8);
    await app.screenshot("tower-runway-exit");
    await expect
      .poll(async () => (await read()).phase, {
        timeout: 100000,
        interval: 1000,
      })
      .toBe("taxi");
    expect((await read()).clear).toBe(true);
    await app.screenshot("tower-taxi-clear");
    await expect
      .poll(async () => (await read()).phase, {
        timeout: 130000,
        interval: 1000,
      })
      .toBe("holding");
    const hold = await read();
    expect(hold.speed).toBe(0);
    expect(hold.clear).toBe(true);
    expect(
      Math.hypot(hold.pos[0] - exit.pos[0], hold.pos[2] - exit.pos[2]),
    ).toBeGreaterThan(100);
    await app.screenshot("tower-taxi-hold");
  },
);

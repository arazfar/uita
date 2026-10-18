import { test } from "@e2e-dev/web";
import { expect } from "e2e";

test("tower integrates runway flight phases and renders articulated aircraft", async ({
  app,
  browser,
}) => {
  await app.open("/candidates/19-tower-cab-interior.html");
  await expect
    .poll(() => browser.evaluate(() => Boolean((window as any).__sky?.flights)))
    .toBe(true);
  const results = await browser.evaluate(() => {
    const sky = (window as any).__sky;
    return Object.entries(sky.flights).map(([cs, f]: any) => {
      const samples = Array.from({ length: 2401 }, (_, i) => f.sample(i / 10));
      return {
        cs,
        events: f.events,
        runway: f.runway.length,
        invalid: samples.some(
          (s) => !Number.isFinite(s.x + s.y + s.z + s.airspeed) || s.y < 0,
        ),
        maxJump: Math.max(
          ...samples
            .slice(1)
            .map((s, i) =>
              Math.hypot(
                s.x - samples[i].x,
                s.y - samples[i].y,
                s.z - samples[i].z,
              ),
            ),
        ),
        maxPitch: Math.max(...samples.map((s) => Math.abs(s.pitch))),
        end: f.sample(240),
        start: f.sample(0),
        rig: Boolean(
          sky.actors.find((a) => a.cs === cs).model.userData.updateFlight,
        ),
      };
    });
  });
  for (const f of results) {
    expect(f.invalid).toBe(false);
    expect(f.maxJump).toBeLessThan(15);
    expect(f.maxPitch).toBeLessThan(0.25);
    expect(f.rig).toBe(true);
  }
  const dep = results.find((f) => f.cs === "UAL900")!;
  const rotation = dep.events.find((e) => e.phase === "rotation")!,
    climb = dep.events.find((e) => e.phase === "climb")!;
  expect(rotation.speed).toBeGreaterThan(65);
  expect(climb.distance).toBeLessThan(dep.runway);
  expect(climb.time).toBeGreaterThan(rotation.time);
  expect(dep.end.gear).toBe(0);
  expect(dep.end.y).toBeGreaterThan(500);
  const arr = results.find((f) => f.cs === "AAL173")!,
    touch = arr.events.find((e) => e.phase === "touchdown")!;
  expect(arr.events.map((e) => e.phase)).toEqual([
    "approach",
    "flare",
    "touchdown",
    "landing-roll",
    "stopped",
  ]);
  expect(touch.distance).toBeGreaterThan(150);
  expect(touch.distance).toBeLessThan(900);
  expect(touch.verticalSpeed).toBeGreaterThan(-1.5);
  expect(touch.verticalSpeed).toBeLessThan(0);
  expect(arr.end.distance).toBeLessThan(arr.runway);
  expect(arr.end.speed).toBe(0);
  expect(arr.end.spoilers).toBe(1);
  await expect(browser.locator("#controls")).toBeVisible();
  const time = await browser.evaluate(() => (window as any).__sky.flightTime);
  await expect
    .poll(() => browser.evaluate(() => (window as any).__sky.flightTime))
    .toBeGreaterThan(time + 0.5);
  await app.screenshot("tower-physics-climb");
  await expect
    .poll(() =>
      browser.evaluate(
        () =>
          (window as any).__sky.actors.find((a) => a.cs === "AAL173")
            .flightState.phase,
      ),
    )
    .toBe("flare");
  await app.screenshot("tower-physics-flare");
  await expect
    .poll(() =>
      browser.evaluate(
        () =>
          (window as any).__sky.actors.find((a) => a.cs === "AAL173")
            .flightState.phase,
      ),
    )
    .toBe("landing-roll");
  const landed = await browser.evaluate(() => {
    const a = (window as any).__sky.actors.find((a) => a.cs === "AAL173");
    return {
      height: a.flightState.y,
      onGround: a.onGround,
      pitch: a.flightState.pitch,
      gear: a.flightState.gear,
    };
  });
  expect(landed.height).toBe(0);
  expect(landed.onGround).toBe(true);
  expect(landed.gear).toBe(1);
  await app.screenshot("tower-physics-touchdown");
  await expect
    .poll(() =>
      browser.evaluate(
        () =>
          (window as any).__sky.actors.find((a) => a.cs === "AAL173")
            .flightState.phase,
      ),
    )
    .toBe("stopped");
  await app.screenshot("tower-physics-stopped");
  // R starts the actual simulation from lineup; no fixture aircraft or mocked dynamics.
  await browser.locator("#bRestart").tap();
  await expect
    .poll(() =>
      browser.evaluate(
        () =>
          (window as any).__sky.actors.find((a) => a.cs === "UAL900")
            .flightState.phase,
      ),
    )
    .toBe("line-up");
  await browser.locator("#bPlay").tap();
  const paused = await browser.evaluate(() => (window as any).__sky.flightTime);
  expect(await browser.evaluate(() => (window as any).__sky.S.paused)).toBe(
    true,
  );
  await app.screenshot("tower-physics-lineup");
  expect(await browser.evaluate(() => (window as any).__sky.flightTime)).toBe(
    paused,
  );
});

test("wind changes the force model without moving the runway or fabricating tracks", async ({
  app,
  browser,
}) => {
  await app.open("/candidates/19-tower-cab-interior.html");
  await expect
    .poll(() => browser.evaluate(() => Boolean((window as any).__sky?.flights)))
    .toBe(true);
  const values = await browser.evaluate(async () => {
    const { createFlight, AIRFRAMES } = await import(
      "/candidates/tower-flight-dynamics.js"
    );
    const runway = (window as any).__sky.flights.UAL900.runway;
    return [-8, 0, 8].map((along) => {
      const f = createFlight({
        operation: "departure",
        runway,
        profile: AIRFRAMES.heavy,
        weather: { along, cross: 4, density: 1.225, source: "verification" },
      });
      return {
        roll: f.events.find((e) => e.phase === "climb").distance,
        crab: f.sample(60).crab,
        air: f.sample(60).airspeed,
        ground: f.sample(60).speed,
      };
    });
  });
  expect(values[0].roll).toBeLessThan(values[1].roll);
  expect(values[1].roll).toBeLessThan(values[2].roll);
  expect(values[0].crab).toBeLessThan(0);
  expect(values[0].air).toBeGreaterThan(values[0].ground);
  await browser.setViewport({ width: 748, height: 754 });
  expect(
    await browser.evaluate(() => ({
      w: document.querySelector("canvas")!.clientWidth,
      h: document.querySelector("canvas")!.clientHeight,
    })),
  ).toEqual({ w: 748, h: 754 });
  await app.screenshot("tower-physics-lightbox");
});

test("connected tower preserves backend authority and camera buttons", async ({app,browser}) => {
  await app.open('/candidates/19-tower-cab-interior.html?mode=connected');
  await expect.poll(()=>browser.evaluate(()=>Boolean((window as any).__sky))).toBe(true);
  expect(await browser.evaluate(()=>Object.keys((window as any).__sky.flights))).toEqual([]);
  expect(await browser.evaluate(()=>(window as any).__sky.actors.length)).toBe(0);
  await expect(browser.locator('#controls')).toBeVisible();
  await expect(browser.locator('[data-p="desk"]')).toBeVisible();
  await expect(browser.locator('#bPlay')).toBeHidden();
});

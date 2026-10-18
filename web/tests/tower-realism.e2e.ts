import { test } from "@e2e-dev/web";
import { expect } from "e2e";

const demoFrame = 'iframe[src*="mode=runway-demo"]';

test(
  "the shipped shell separates recorded traffic from a complete runway demonstration",
  { timeout: 240000 },
  async ({ app, browser }) => {
    await browser.addInitScript(() => {
      (window as any).__runtimeErrors = [];
      addEventListener("error", (e) =>
        (window as any).__runtimeErrors.push(e.message),
      );
      addEventListener("unhandledrejection", (e) =>
        (window as any).__runtimeErrors.push(String(e.reason)),
      );
    });
    await app.open("/candidates/app.html");
    await expect(browser.locator("#play")).toBeEnabled();
    await expect(browser.locator("#play")).toContainText("Play recording");
    const recordedTime = await browser.locator("#seek").inputValue();
    await browser.locator("#sandbox-toggle").tap();
    await expect(browser.locator("#sandbox-panel")).toBeVisible();
    await browser.locator('[data-camera="runway"]').tap();
    const demo = browser.frameLocator(demoFrame);
    await expect(
      demo.getByRole("heading", "SFO · Runway demonstration"),
    ).toBeVisible();
    await expect(
      demo.getByText(
        "Simulated aircraft · snapshot weather · 28L arrival / 28R departure",
      ),
    ).toBeVisible();
    await expect(browser.locator("footer")).toBeHidden();
    await expect(browser.locator("#source-controls")).toBeHidden();
    await expect(browser.locator("#sandbox-panel")).toBeHidden();
    const state = () =>
      browser.evaluate(() => {
        const w = document.querySelector('iframe[src*="mode=runway-demo"]')!
          .contentWindow as any;
        return {
          time: w.__sky.flightTime,
          paused: w.__sky.S.paused,
          errors: w.__runtimeErrors,
          aircraft: w.__sky.actors.map((a: any) => ({
            id: a.cs,
            phase: a.flightState.phase,
            height: a.flightState.y,
            pitch: a.flightState.pitch,
            gear: a.flightState.gear,
            speed: a.flightState.speed,
            onGround: a.onGround,
            runwayClear: a.flightState.runwayClear,
          })),
        };
      });
    await demo.getByRole("button", "Pause", { exact: true }).tap();
    const paused = await state();
    expect(paused.paused).toBe(true);
    await demo.getByLabel("Demonstration speed").selectOption({ value: "10" });
    expect((await state()).time).toBe(paused.time);
    await demo.getByRole("button", "Watch takeoff").tap();
    await expect
      .poll(
        async () =>
          (await state()).aircraft.find((a) => a.id === "UAL900")?.phase,
      )
      .toBe("climb");
    await demo.getByRole("button", "Pause", { exact: true }).tap();
    const departure = (await state()).aircraft.find((a) => a.id === "UAL900")!;
    expect(departure.height).toBeGreaterThan(0);
    expect(departure.pitch).toBeGreaterThan(0.04);
    expect(departure.onGround).toBe(false);
    await app.screenshot("tower-runway-takeoff");

    await demo.getByLabel("Demonstration speed").selectOption({ value: "1" });
    await demo.getByRole("button", "Watch landing").tap();
    await expect
      .poll(
        async () =>
          (await state()).aircraft.find((a) => a.id === "AAL173")?.phase,
      )
      .toBe("flare");
    await demo.getByRole("button", "Pause", { exact: true }).tap();
    expect((await state()).aircraft.find((a) => a.id === "AAL173")!.gear).toBe(
      1,
    );
    await app.screenshot("tower-runway-flare");
    await demo.getByRole("button", "Play", { exact: true }).tap();
    await expect
      .poll(
        async () =>
          (await state()).aircraft.find((a) => a.id === "AAL173")?.phase,
      )
      .toBe("landing-roll");
    await demo.getByRole("button", "Pause", { exact: true }).tap();
    const landing = (await state()).aircraft.find((a) => a.id === "AAL173")!;
    expect(landing.height).toBe(0);
    expect(landing.onGround).toBe(true);
    expect(landing.gear).toBe(1);
    await app.screenshot("tower-runway-touchdown");

    await demo.getByLabel("Demonstration time").press("End");
    await expect(demo.locator("[data-demo-time]")).toContainText(
      "Sequence complete",
    );
    expect((await state()).paused).toBe(true);
    expect(
      (await state()).aircraft.find((a) => a.id === "AAL173")!.runwayClear,
    ).toBe(true);
    await demo.getByRole("button", "Restart", { exact: true }).tap();
    expect((await state()).time).toBeLessThan(2);
    await demo.getByRole("button", "Pause", { exact: true }).tap();
    await demo.getByRole("button", "Tower desk").tap();
    await app.screenshot("tower-runway-desk");
    expect((await state()).errors).toEqual([]);

    await browser.setViewport({ width: 390, height: 844 });
    await expect(demo.getByRole("button", "Watch landing")).toBeVisible();
    await demo.getByRole("button", "Watch landing").tap();
    await demo.getByRole("button", "Pause", { exact: true }).tap();
    expect(
      await browser.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    expect(
      await browser.evaluate(() => {
        const w = document.querySelector(
          'iframe[src*="mode=runway-demo"]',
        )!.contentWindow!;
        return w.document.documentElement.scrollWidth <= w.innerWidth;
      }),
    ).toBe(true);
    await app.screenshot("tower-runway-mobile");

    await browser.locator('[data-camera="tower"]').tap();
    await expect(browser.locator("footer")).toBeVisible();
    await expect(browser.locator("#source-controls")).toBeVisible();
    await expect(browser.locator("#sandbox-toggle")).toBeVisible();
    await expect(browser.locator("#sandbox-panel")).toBeVisible();
    await expect(browser.locator("#play")).toContainText("Play recording");
    expect(await browser.locator("#seek").inputValue()).toBe(recordedTime);
    await expect
      .poll(() =>
        browser.evaluate(() => {
          const w = document.querySelector(
            'iframe[src*="19-tower"][src*="connected"]',
          )!.contentWindow as any;
          return Boolean(w.__sky && w.__uitaFrame);
        }),
      )
      .toBe(true);
    expect(
      await browser.evaluate(() => {
        const w = document.querySelector(
          'iframe[src*="19-tower"][src*="connected"]',
        )!.contentWindow as any;
        return Object.keys(w.__sky.flights);
      }),
    ).toEqual([]);
  },
);

test("the tower loads its Blender equipment and renders a measured five-second flight sample", async ({
  app,
  browser,
}) => {
  await app.open("/candidates/19-tower-cab-interior.html?mode=runway-demo");
  await expect
    .poll(() =>
      browser.evaluate(() => (window as any).__sky?.cabDetails?.userData.ready),
    )
    .toBe(true);
  const details = await browser.evaluate(() => {
    const s = (window as any).__sky;
    let meshCount = 0;
    s.cabDetails.traverse((o: any) => {
      if (o.isMesh) meshCount++;
    });
    return {
      source: s.cabDetails.userData.source,
      meshCount,
      error: s.cabDetails.userData.error || null,
    };
  });
  expect(details.source).toContain("cab-equipment.glb");
  expect(details.meshCount).toBeGreaterThan(0);
  expect(details.error).toBeNull();
  await browser.locator("[data-demo-tower]").tap();
  await expect
    .poll(() => browser.evaluate(() => (window as any).__sky.camera.fov))
    .toBeCloseTo(58, 1);
  await app.screenshot("tower-blender-cab-equipment");
  const performance = await browser.evaluate(
    () =>
      new Promise((resolve) => {
        const samples: number[] = [];
        let first = 0,
          previous = 0;
        function frame(now: number) {
          if (!first) first = now;
          if (previous) samples.push(now - previous);
          previous = now;
          if (now - first < 5000) return requestAnimationFrame(frame);
          const sorted = [...samples].sort((a, b) => a - b),
            renderer = (window as any).__sky.renderer;
          const gl = renderer.getContext(),
            debug = gl.getExtension("WEBGL_debug_renderer_info");
          resolve({
            elapsedMs: now - first,
            frames: samples.length,
            fps: samples.length / ((now - first) / 1000),
            medianMs: sorted[Math.floor(sorted.length / 2)],
            p95Ms: sorted[Math.floor(sorted.length * 0.95)],
            drawCalls: renderer.info.render.calls,
            triangles: renderer.info.render.triangles,
            viewport: [innerWidth, innerHeight],
            renderer: renderer.isWebGLRenderer ? "WebGL2" : "WebGPU",
            gpu: debug
              ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL)
              : "unavailable",
          });
        }
        requestAnimationFrame(frame);
      }),
  );
  console.log("TOWER_RENDER_SAMPLE", JSON.stringify(performance));
  expect((performance as any).frames).toBeGreaterThan(0);
});

test("a runway view that finishes loading while hidden stays paused until selected", async ({
  app,
  browser,
}) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let requested = false;
  await browser.route("**/tower-flight-dynamics.js", async (route) => {
    requested = true;
    await gate;
    await route.continue();
  });
  await app.open("/candidates/app.html");
  await expect(browser.locator("#play")).toBeEnabled();
  await browser.locator('[data-camera="runway"]').tap();
  await expect.poll(() => requested).toBe(true);
  await browser.locator('[data-camera="dashboard"]').tap();
  release();
  await expect
    .poll(() =>
      browser.evaluate(() =>
        Boolean(
          (
            document.querySelector('iframe[src*="mode=runway-demo"]')!
              .contentWindow as any
          ).__sky,
        ),
      ),
    )
    .toBe(true);
  const result = await browser.evaluate(
    () =>
      new Promise((resolve) => {
        const w = document.querySelector('iframe[src*="mode=runway-demo"]')!
          .contentWindow as any;
        const initial = w.__sky.flightTime;
        let start = 0;
        function frame(time: number) {
          if (!start) start = time;
          if (time - start < 1500) return requestAnimationFrame(frame);
          resolve({
            initial,
            final: w.__sky.flightTime,
            hidden: w.frameElement.hidden,
          });
        }
        requestAnimationFrame(frame);
      }),
  );
  expect((result as any).hidden).toBe(true);
  expect((result as any).final).toBe((result as any).initial);
  await browser.locator('[data-camera="runway"]').tap();
  await expect
    .poll(() =>
      browser.evaluate(
        () =>
          (
            document.querySelector('iframe[src*="mode=runway-demo"]')!
              .contentWindow as any
          ).__sky.flightTime,
      ),
    )
    .toBeGreaterThan((result as any).final + 0.5);
});

test("historical tower aircraft retain measured altitude and omit unknown heights", async ({
  app,
  browser,
}) => {
  await app.open("/candidates/app.html");
  await expect(browser.locator('[data-mode="historical"]')).toBeEnabled();
  await browser.locator('[data-mode="historical"]').tap();
  await browser.locator('[data-camera="tower"]').tap();
  await expect
    .poll(() =>
      browser.evaluate(() => {
        const w = document.querySelector(
          'iframe[src*="19-tower"][src*="connected"]',
        )!.contentWindow as any;
        return (
          w.__uitaFrame?.mode === "historical" &&
          w.__sky?.actors.some((a: any) => a.vis)
        );
      }),
    )
    .toBe(true);
  const observations = await browser.evaluate(() => {
    const w = document.querySelector(
      'iframe[src*="19-tower"][src*="connected"]',
    )!.contentWindow as any;
    return w.__sky.actors
      .filter((a: any) => a.vis)
      .map((a: any) => {
        const source = w.__uitaFrame.aircraft.find((s: any) => s.id === a.cs);
        return {
          height: a.pos.y,
          sourceHeight: source?.altitude_ft,
          source: source?.provenance.kind,
        };
      });
  });
  expect(observations.length).toBeGreaterThan(0);
  for (const a of observations) {
    expect(a.source).toBe("observed");
    expect(typeof a.sourceHeight).toBe("number");
    expect(a.height).toBeCloseTo(a.sourceHeight * 0.3048, 5);
  }
});

test("mobile runway controls remain above the shell camera switch", async ({
  app,
  browser,
}) => {
  await browser.setViewport({ width: 390, height: 844 });
  await app.open("/candidates/app.html");
  await expect(browser.locator("#play")).toBeEnabled();
  await browser.locator('[data-camera="runway"]').tap();
  const demo = browser.frameLocator(demoFrame);
  await expect(demo.getByRole("button", "Watch landing")).toBeVisible();
  await demo.getByRole("button", "Watch landing").tap();
  await demo.getByRole("button", "Pause", { exact: true }).tap();
  const layout = await browser.evaluate(() => {
    const frame = document.querySelector(
      'iframe[src*="mode=runway-demo"]',
    ) as HTMLIFrameElement;
    const w = frame.contentWindow!;
    const controls = w.document
      .querySelector("#controls")!
      .getBoundingClientRect();
    const cameras = document
      .querySelector(".view-controls")!
      .getBoundingClientRect();
    return {
      controlsBottom: controls.bottom + frame.getBoundingClientRect().top,
      camerasTop: cameras.top,
      fits:
        w.document.documentElement.scrollWidth <= w.innerWidth &&
        document.documentElement.scrollWidth <= innerWidth,
    };
  });
  expect(layout.fits).toBe(true);
  expect(layout.controlsBottom).toBeLessThan(layout.camerasTop);
  await app.screenshot("tower-runway-mobile-final");
});

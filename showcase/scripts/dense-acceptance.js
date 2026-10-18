async (page) => {
  await page.unrouteAll();
  const origin = new URL(page.url()).origin;
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(origin);
  await page.waitForFunction(
    () =>
      document.querySelector("#scene").contentWindow.__uitaFrame?.source_id ===
      "dense-demo-v1",
  );
  const start = Number(await page.locator("#seek").inputValue());
  const frame = await page.evaluate(
    () => document.querySelector("#scene").contentWindow.__uitaFrame,
  );
  const airborne = frame.aircraft.filter(
    (a) =>
      a.altitude_ft !== null &&
      ["approach", "holding", "go_around"].includes(a.status),
  );
  if (airborne.length < 6) throw Error("Sparse default traffic");
  await page.waitForFunction(
    () => document.querySelector("#arrivals-queue").children.length === 4,
  );
  // Allow the deliberate initial overview camera transition to finish.
  await page.waitForTimeout(1200);
  await page.screenshot({ path: "output/playwright/dense-desktop.png" });
  const fps = await page.evaluate(async () => {
    const scene = document.querySelector("#scene").contentWindow;
    const before = scene.__uitaPaintedFrame.count,
      start = performance.now();
    await new Promise((resolve) => setTimeout(resolve, 2000));
    return (
      ((scene.__uitaPaintedFrame.count - before) * 1000) /
      (performance.now() - start)
    );
  });
  await page.locator("#seek").fill(String(start + 90));
  await page.locator("#seek").dispatchEvent("input");
  await page.waitForFunction(() =>
    document
      .querySelector("#decision-aircraft")
      .textContent.includes("Disruption"),
  );
  if (
    !(await page.locator("#decision-origin").textContent()).includes(
      "At this playback time",
    )
  )
    throw Error("Seek replayed old notification");
  await page.locator("#decision-overlay").hover();
  await page.waitForTimeout(8200);
  if (!(await page.locator("#decision-overlay").isVisible()))
    throw Error("Hover did not retain evidence");
  await page.mouse.move(700, 500);
  await page.waitForTimeout(8500);
  if (await page.locator("#decision-overlay").isVisible())
    throw Error("Old decision did not dismiss");
  // Locate an actual landing issuance from the immutable export, not a fabricated UI action.
  const data = await page.evaluate(
    async () =>
      await (await fetch("/api/v2/recordings/dense-demo-v1/export")).json(),
  );
  const event = data.events.find(
    (e) => e.clock > start && e.kind === "clearance_issued",
  );
  if (!event) throw Error("Missing issued landing");
  await page.locator("#seek").fill(String(event.clock));
  await page.locator("#seek").dispatchEvent("input");
  await page.waitForFunction(() =>
    document
      .querySelector("#decision-aircraft")
      .textContent.startsWith("Issued"),
  );
  await page.locator("#decision-aircraft").click();
  await page
    .frameLocator("#scene")
    .locator("#fcard")
    .waitFor({ state: "visible" });
  await page.locator("#decision-follow").click();
  await page.getByRole("button", { name: "Tower cab", exact: true }).click();
  await page.waitForFunction(
    () =>
      document.querySelector("iframe:not([hidden])").contentWindow.__uitaFrame
        ?.source_id === "dense-demo-v1",
  );
  await page.screenshot({ path: "output/playwright/dense-tower.png" });
  await page.getByRole("button", { name: "Historical", exact: true }).click();
  await page.waitForFunction(
    () =>
      document.querySelector("iframe:not([hidden])").contentWindow.__uitaFrame
        ?.mode === "historical",
  );
  if (await page.locator("#decision-overlay").isVisible())
    throw Error("Simulation evidence leaked to history");
  await page.getByRole("button", { name: "Simulation", exact: true }).click();
  await page
    .getByRole("button", { name: "3D simulation T", exact: true })
    .click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.frameLocator("#scene").locator("#fcClose").click();
  await page.frameLocator("#scene").locator("#fcard").waitFor({state:"hidden"});
  await page.screenshot({ path: "output/playwright/dense-mobile.png" });
  return { passed: true, airborne: airborne.length, rendererFps: fps };
}

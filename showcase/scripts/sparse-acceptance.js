// Run via playwright-cli run-code --filename showcase/scripts/sparse-acceptance.js.
async (page) => {
  const base = new URL(page.url()).origin;
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(base);
  const scene = page.frameLocator("#scene");
  await scene.locator("#cambar").waitFor();
  await page.waitForFunction(
    () =>
      document.querySelector("#scene").contentWindow.__uitaFrame?.aircraft
        .length,
  );
  if (await page.locator("#evidence-drawer").isVisible())
    throw Error("Drawer must start closed");
  await scene.getByRole("button", { name: "More", exact: true }).click();
  await scene.getByRole("menuitem", { name: "Details", exact: false }).click();
  await scene.locator("#striplist button").first().click();
  await scene.locator("#fcard").waitFor({ state: "visible" });
  const selected = await scene.locator("#fcCs").innerText();
  if(!(await scene.locator("#fcGrid").innerText()).includes("Assigned runway")) throw Error("Runway destination missing");
  await page.locator("#decision-overlay").waitFor({state:"visible"});
  if(!(await page.locator("#decision-verdict").innerText()).includes("verification")) throw Error("Decision verification missing");
  await scene
    .getByRole("button", { name: "Follow selected aircraft", exact: true })
    .click();
  await scene.getByRole("radio", { name: "5×", exact: true }).click();
  await page.waitForFunction(()=>document.querySelector("#speed").value === "5");
  const before = await page.locator("#clock").innerText();
  const t = Date.now();
  await page.getByRole("button", { name: "Tower cab", exact: true }).click();
  await page.waitForFunction(
    () =>
      document.querySelector("iframe:not([hidden])").contentWindow.__uitaFrame,
  );
  await page
    .getByRole("button", { name: "3D simulation T", exact: true })
    .click();
  await scene.locator("#fcard").waitFor({ state: "visible" });
  if ((await scene.locator("#fcCs").innerText()) !== selected)
    throw Error("Selection lost");
  if ((await page.locator("#clock").innerText()) !== before)
    throw Error("Camera changed playback clock");
  if ((await page.locator("iframe").count()) !== 2)
    throw Error("Camera iframe re-created");
  const switchMs = Date.now() - t;
  const cachedStart=Date.now();
  await page.getByRole("button",{name:"Tower cab",exact:true}).click();
  await page.getByRole("button",{name:"3D simulation T",exact:true}).click();
  const cachedSwitchMs=Date.now()-cachedStart;
  const fps=await page.evaluate(()=>new Promise(resolve=>{let n=0;const start=performance.now();function tick(t){n++;if(t-start>=3000)resolve(n*1000/(t-start));else requestAnimationFrame(tick);}requestAnimationFrame(tick);}));
  await scene.getByRole("button", { name: "Close (Esc)", exact: true }).click();
  await page.screenshot({
    path: "output/playwright/sparse-confirm-desktop.png",
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "output/playwright/sparse-confirm-mobile.png",
  });
  await page.locator("#drawer-toggle").click();
  await page.getByRole("button", { name: "Historical", exact: true }).click();
  await page.waitForFunction(
    () =>
      document.querySelector("#scene").contentWindow.__uitaFrame?.mode ===
      "historical",
  );
  await page.getByRole("button", { name: "Compare", exact: true }).click();
  await page.locator("#render-controller").selectOption("baseline");
  await page.waitForFunction(
    () =>
      document.querySelector("#scene").contentWindow.__uitaFrame?.source_id ===
      "baseline",
  );
  const download = page.waitForEvent("download");
  await page.locator("#export").click();
  await (await download).saveAs("output/playwright/sparse-export.json");
  return { selected, firstCameraRoundTripMs: switchMs, cachedCameraRoundTripMs:cachedSwitchMs, fps, passed: true };
}

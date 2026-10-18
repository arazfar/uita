// Run with playwright-cli run-code --filename showcase/scripts/browser-acceptance.js
// against a public-demo or signed-in local/staging page with its worker running. No paid calls.
async (page) => {
  await page.unrouteAll();
  const origin = new URL(page.url()).origin;
  await page.setViewportSize({width:1440,height:900});
  const identity = await (await page.request.get(origin + "/api/v2/me")).json();
  await page.goto(origin + "/");
  await page
    .locator("#recordings option")
    .first()
    .waitFor({ state: "attached" });
  await page.locator("#drawer-toggle").click();
  await page.locator("#recordings").selectOption("nemotron-aug06-closure-v1");
  await page.locator("#recorded").click();
  // A rejected source change must retain the current recording and export.
  await page.waitForFunction(() => !document.querySelector("#create").disabled);
  const oldSource = await page.locator("#source").innerText();
  await page.locator("#live-options summary").click();
  await page.route("**/api/v2/runs", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Injected create failure" }),
    }),
  );
  await page.locator("#create").click();
  await page.locator("#error").waitFor({ state: "visible" });
  await page.waitForFunction(()=>!document.querySelector('#create').disabled);
  if (
    (await page.locator("#source").innerText()) !== oldSource ||
    (await page.locator("#export").isDisabled())
  )
    throw Error(`Failed create discarded recording: ${JSON.stringify({oldSource,current:await page.locator("#source").innerText(),exportDisabled:await page.locator("#export").isDisabled()})}`);
  await page.unroute("**/api/v2/runs");
  await page.locator("#live-options summary").click();
  await page.locator("#seek").fill("1786052820");
  await page.locator("#seek").dispatchEvent("input");
  await page.getByRole("button", { name: "Compare", exact: true }).click();
  await page.locator("#render-controller").selectOption("baseline");
  await page.getByRole("button", { name: "Tower cab", exact: true }).click();
  await page.waitForFunction(
    () =>
      document
        .querySelector("iframe:not([hidden])")
        .contentWindow.location.pathname.includes("19-tower") &&
      document.querySelector("iframe:not([hidden])").contentWindow.__uitaFrame
        ?.source_id === "baseline",
  );
  const inspection = await page.evaluate(() => {
    const f = document.querySelector("iframe:not([hidden])").contentWindow
      .__uitaFrame;
    return {
      ids: f.aircraft.map((a) => a.id),
      table: [...document.querySelectorAll("#traffic [data-id]")].map(
        (e) => e.dataset.id,
      ),
      metrics: document.querySelector("#metrics").textContent,
      controller: f.controller,
    };
  });
  if (
    JSON.stringify(inspection.ids) !== JSON.stringify(inspection.table) ||
    !inspection.metrics.includes(inspection.controller) ||
    inspection.metrics.includes("Deterministic fallback")
  )
    throw Error("Comparison inspection uses the wrong controller");
  const tower = page.frames().find((f) => f.url().includes("19-tower"));
  if (await tower.locator("#score").isVisible())
    throw Error("Scripted score visible");
  if (await tower.evaluate(() => window.__loops?.length))
    throw Error("Scripted scenario running");
  await page.setViewportSize({ width: 390, height: 844 });
  if (
    await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
  )
    throw Error("Mobile overflow");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: "Historical", exact: true }).focus();
  await page.keyboard.press("Enter");
  await page.waitForFunction(() =>
    document
      .querySelector("#source")
      .textContent.includes("Historical observations"),
  );
  await page.getByRole("button", { name: "Simulation", exact: true }).click();
  const download = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Export evidence", exact: true })
    .click();
  await download;
  await page.locator("#live-options summary").click();
  await page.locator("#controller").selectOption("fixture");
  await page.locator("#scenarios").selectOption("fixture-august-v2");
  const clickMutation = async (name, suffix) => {
    const response = page.waitForResponse(
      (r) => r.request().method() === "POST" && r.url().endsWith(suffix),
    );
    await page.getByRole("button", { name, exact: true }).click();
    const r = await response;
    if (!r.ok()) throw Error(`Mutation failed: ${r.status()}`);
    return r.json();
  };
  for (const fault of ["provider_timeout", "budget_exhausted"]) {
    await page.locator("#fault").selectOption(fault);
    await clickMutation("Create isolated run", "/runs");
    await clickMutation("+10 seconds", "/control");
    await page.waitForFunction(() =>
      document
        .querySelector("#events")
        .textContent.includes("controller fallback"),
    );
  }
  const activeUrl = page.url();
  const activeSource = await page.locator("#source").innerText();
  await page.route("**/recordings/*/window?*", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Injected recording failure" }),
    }),
  );
  // Select an uncached recording: a cache hit correctly needs no request.
  const uncached=await page.locator('#recordings option').last().getAttribute('value');
  await page.locator('#recordings').selectOption(uncached);
  await page.locator("#switch-retry").waitFor({ state: "visible" });
  if (page.url() !== activeUrl || (await page.locator("#source").innerText()) !== activeSource)
    throw Error("Failed recording load discarded live run");
  await page.unroute("**/recordings/*/window?*");
  // Exercise an unsafe structured proposal through the authenticated API, then
  // verify its rejection is inspectable in the same UI. Never commit it.
  const rejected = await page.evaluate(async () => {
    const id = new URLSearchParams(location.search).get("run");
    const run = await (await fetch(`/api/v2/runs/${id}`)).json();
    const response = await fetch(`/api/v2/runs/${id}/proposals`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        expected_revision: run.revision,
        idempotency_key: crypto.randomUUID(),
        proposal: {
          clearances: [
            {
              aircraft_id: run.state.aircraft[0].id,
              kind: "speed",
              value: 5000,
            },
          ],
          explanation: "Acceptance test: deliberately infeasible speed",
        },
      }),
    });
    if (!response.ok) throw Error("Proposal request failed");
    return (await response.json()).state.pending_proposal.verdict.status;
  });
  if (rejected !== "fail") throw Error("Unsafe proposal was not rejected");
  await page.waitForFunction(() =>
    document.querySelector("#events").textContent.includes("5000"),
  );
  await clickMutation("Close 28R", "/disruptions");
  await page.getByRole("button", { name: "Compare", exact: true }).click();
  await clickMutation("Freeze and compare live run", "/compare");
  await page.waitForFunction(() =>
    document
      .querySelector("#comparison-results")
      .textContent.includes("static"),
  );
  await page.reload();
  await page.locator("#drawer-toggle").click();
  await page.waitForFunction(() =>
    document.querySelector("#connection").textContent.includes("Live backend"),
  );
  await page.context().setOffline(true);
  try {
    await page.locator("#retry").waitFor({ state: "visible", timeout: 20000 });
  } finally {
    await page.context().setOffline(false);
  }
  // Polling may already have recovered after the network returns.
  await page.locator("#retry").evaluate(b => { if(!b.hidden) b.click(); });
  await page.locator("#error").waitFor({ state: "hidden" });
  await page.locator("#live-options summary").click();
  const previousSignature = await page
    .locator("#events")
    .getAttribute("data-signature");
  await page.locator("#scenarios").selectOption("2026-08-06-1500-research-v2");
  await page.locator("#fault").selectOption("none");
  await clickMutation("Create isolated run", "/runs");
  await page.waitForFunction(() => !document.querySelector("#create").disabled);
  if (
    !(await page.locator("#comparison-results").innerText()).includes(
      "No comparison",
    )
  )
    throw Error("Previous comparison leaked into new run");
  if (
    (await page.locator("#events").getAttribute("data-signature")) ===
    previousSignature
  )
    throw Error("Event source identity was reused");
  const exportedDownload = page.waitForEvent("download");
  await page.locator("#export").click();
  const exportStream = await (await exportedDownload).createReadStream();
  let exportText = "";
  for await (const chunk of exportStream) exportText += chunk.toString();
  const exported = JSON.parse(exportText);
  if (exported.comparison !== null)
    throw Error("Export contains another run's comparison");
  let run;
  for (let i = 0; i < 16; i++)
    run = await clickMutation("+10 seconds", "/control");
  if (run.status !== "failed" || run.state.clock - run.state.start !== 151)
    throw Error("Failed scenario was not preserved");
  await page
    .getByRole("button", { name: "Load recording", exact: true })
    .click();
  await page.locator("#recordings").selectOption("nemotron-aug06-closure-v1");
  await page.locator("#recorded").click();
  await page.locator("#seek").fill("1786053900");
  await page.locator("#seek").dispatchEvent("input");
  await page.waitForFunction(() =>
    document
      .querySelector("#metrics")
      .textContent.includes("Deterministic fallback"),
  );
  await page.route("**/vendor/cesium/Cesium.js", (r) => r.abort());
  await page.reload();
  await page.locator("#drawer-toggle").click();
  await page.waitForFunction(() =>
    document
      .querySelector("#render-status")
      .textContent.includes("unavailable"),
  );
  const dashboard = page.frames().find((f) => f.url().includes("11-photoreal"));
  for (const id of ["banner", "feedp", "score", "card"]) {
    if (await dashboard.locator(`#${id}`).isVisible())
      throw Error(`Legacy overlay ${id} visible with renderer failure`);
  }
  await page.waitForFunction(
    () => document.querySelector("#traffic").textContent.length > 0,
  );
  if (!(await page.locator("#traffic").innerText()))
    throw Error("Accessible traffic table missing");
  await page.unroute("**/vendor/cesium/Cesium.js");
  await page.context().clearCookies();
  await page
    .getByRole("button", { name: "Load recording", exact: true })
    .click();
  if (identity.access_mode === "public_demo") {
    await page.reload();
    await page
      .locator("#recordings option")
      .first()
      .waitFor({ state: "attached" });
    if (await page.locator("#logout").isVisible())
      throw Error("Public demo shows sign out");
    if (
      !(await page.locator("#access-mode").textContent()).includes("Public demo")
    )
      throw Error("Missing public identity");
  } else {
    await page.waitForFunction(() =>
      document.querySelector("#error").textContent.includes("Session expired"),
    );
  }
}

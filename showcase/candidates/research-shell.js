import {
  api,
  mutation,
  displayFrame,
  uniqueEvents,
  timeLabel,
  validMessage,
} from "./research-client.js";
const $ = (id) => document.getElementById(id),
  scene = $("scene");
let mode = "simulation",
  camera = "dashboard",
  frame = null,
  baseline = null,
  selected = null,
  recording = null,
  run = null,
  events = [],
  playing = false,
  busy = false,
  stream = null,
  clock = 0,
  job = null,
  sourceGeneration = 0;
let recordings = [],
  windowData = null,
  lastWindow = -Infinity,
  lastSpoken = 0;
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const message = (type, extra = {}) =>
  scene.contentWindow?.postMessage({ type, ...extra }, location.origin);
function fail(error) {
  $("error").hidden = false;
  $("error").textContent = error.message;
  $("connection").textContent =
    "Disconnected / request failed · last state retained";
  $("retry").hidden = false;
  playing = false;
  if (error.status === 401) {
    $("error").append(document.createTextNode(" "));
    const a = document.createElement("a");
    a.href = "/login";
    a.textContent = "Sign in";
    $("error").append(a);
  }
}
let actionQueue = Promise.resolve();
function action(fn) {
  const execute = async () => {
    busy = true;
    controls();
    try {
      await fn();
      $("error").hidden = true;
      $("retry").hidden = true;
    } catch (e) {
      fail(e);
    } finally {
      busy = false;
      controls();
    }
  };
  actionQueue = actionQueue.then(execute, execute);
  return actionQueue;
}

function controls() {
  const live = !!run;
  const terminal = frame && ["failed", "complete"].includes(frame.status);
  $("close").disabled = !live || terminal || mode === "historical" || busy;
  $("compare").disabled = !live || busy;
  $("seek").disabled = busy || live || !recording;
  $("create").disabled = busy;
  $("recorded").disabled = busy || !recordings.length;
  $("play").disabled = busy || (!live && !recording) || (terminal && live);
  $("play").textContent = live
    ? frame?.status === "running"
      ? "Pause run"
      : "Run simulation"
    : playing
      ? "Pause recording"
      : "Play recording";
  $("step").disabled =
    busy || !frame || (live && (terminal || frame.status === "running"));
  $("export").disabled = busy || (!recording && !run);
  document.querySelectorAll("[data-mode]").forEach((b) => (b.disabled = busy));
  $("speed").disabled = busy;
  if (live && mode === "historical") {
    for (const id of ["play", "step", "speed", "close"]) $(id).disabled = true;
  }
  $("render-controller").disabled = !baseline;
}
function sendFrame() {
  const shown =
    mode === "compare" && $("render-controller").value === "baseline"
      ? baseline
      : frame;
  if (shown) message("uita:frame", { frame: shown, selected });
}
function render() {
  if (!frame) return;
  if (recording && mode !== "historical")
    $("source").textContent =
      `${recording.title} · ${recording.model} · ${recording.model_responses} response, ${recording.fallback_count} fallback. No model-issued flight clearance or efficiency improvement in this capture.`;
  $("clock").textContent = timeLabel(clock || frame.clock);
  $("seek").value = String(clock);
  $("connection").textContent =
    `${run ? "Live backend" : "Recorded playback"} · ${frame.status} · revision ${frame.revision}`;
  if (
    run &&
    frame.status === "running" &&
    frame.runtime?.next_tick_due_at &&
    Date.now() / 1000 - frame.runtime.next_tick_due_at > 15
  ) {
    $("connection").textContent =
      "Worker delayed · waiting for recovery · last committed state retained";
  }
  const m = frame.metrics || {};
  const metricRows =
    mode === "historical"
      ? [
          ["Observed targets", frame.aircraft.length],
          ["Source", "Historical context"],
        ]
      : [
          ["Executed completions", m.completed ?? "—"],
          ["Unfinished backlog", m.backlog ?? "—"],
          [
            "Completed-only mean delay · s",
            Number(m.mean_delay_seconds ?? 0).toFixed(1),
          ],
          [
            "Completed-only P95 delay · s",
            Number(m.p95_delay_seconds ?? 0).toFixed(1),
          ],
          ["Executed violations", m.violations ?? "—"],
          ["Diversions", m.diverted ?? 0],
          [
            "Controller at this time",
            events.some(
              (e) => e.kind === "controller_fallback" && e.clock <= clock,
            )
              ? "Deterministic fallback"
              : frame.controller,
          ],
          ["Unavailable runways", frame.closed_runways.join(", ") || "None"],
          [
            "Reserved / run cap · USD",
            frame.spend?.cap_usd != null
              ? `${frame.spend.reserved_usd.toFixed(4)} / ${frame.spend.cap_usd.toFixed(2)}`
              : "Recorded; see export",
          ],
        ];
  $("metrics").innerHTML = metricRows
    .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`)
    .join("");
  $("traffic-count").textContent = `(${frame.aircraft.length})`;
  $("traffic").innerHTML = frame.aircraft
    .map(
      (a) =>
        `<tr><td><button data-id="${esc(a.id)}" aria-pressed="${selected === a.id}">${esc(a.callsign)}</button></td><td>${a.altitude_ft == null ? "Unknown" : Math.round(a.altitude_ft)}</td><td>${esc(a.status)}</td></tr>`,
    )
    .join("");
  const aircraft = frame.aircraft.find((a) => a.id === selected);
  $("aircraft-detail").textContent = aircraft
    ? JSON.stringify(aircraft, null, 2)
    : "Select an aircraft on the map or in this table.";
  const visible = events.filter((e) => e.clock <= clock).slice(-35);
  const focused = document.activeElement?.closest("#events details");
  const open = new Set(
    [...$("events").querySelectorAll("details[open]")].map(
      (x) => x.dataset.seq,
    ),
  );
  const sig = visible.map((e) => e.sequence).join(",");
  if ($("events").dataset.signature !== sig && !focused) {
    $("events").dataset.signature = sig;
    $("events").innerHTML =
      visible
        .reverse()
        .map(
          (e) =>
            `<details data-seq="${e.sequence}" ${open.has(String(e.sequence)) ? "open" : ""}><summary>${esc(e.kind.replaceAll("_", " "))} · ${esc(timeLabel(e.clock))}</summary><pre>${esc(JSON.stringify(e.payload, null, 2))}</pre></details>`,
        )
        .join("") || "<p>No events at this playback time.</p>";
  }
  if (run && $("speech").checked) {
    for (const e of visible.filter(
      (e) => e.sequence > lastSpoken && e.kind === "clearance_issued",
    )) {
      const text = e.payload.text;
      if (typeof text === "string")
        speechSynthesis.speak(new SpeechSynthesisUtterance(text));
    }
    lastSpoken = Math.max(lastSpoken, ...visible.map((e) => e.sequence));
  }
  controls();
  sendFrame();
}
function disconnect() {
  stream?.close();
  stream = null;
  playing = false;
  lastSpoken = 0;
  windowData = null;
  sourceGeneration++;
  events = [];
  lastWindow = -Infinity;
}
async function loadRecording() {
  disconnect();
  history.replaceState(null, "", location.pathname);
  run = null;
  job = null;
  recording = recordings.find((r) => r.id === $("recordings").value);
  if (!recording)
    throw Error(
      "No authentic Nemotron recording is installed. Use the explicitly labeled fixture to test the interface.",
    );
  clock = recording.start;
  $("seek").min = recording.start;
  $("seek").max = recording.end;
  $("source").textContent =
    `${recording.title} · ${recording.model} · ${recording.model_responses} model responses · ${recording.fallback_count} fallbacks. Synthetic metered variant; model returned no clearance before fallback. No efficiency improvement demonstrated.`;
  $("timeline-label").textContent =
    "Saved model decisions · read-only · closure at +90 seconds · historical observations are contextual";
  await replay();
  await loadComparison();
}
async function replay() {
  const gen = sourceGeneration;
  const data = await api(
    `/recordings/${recording.id}/window?clock=${clock}&seconds=120`,
  );
  if (gen !== sourceGeneration) return;
  windowData = data;
  lastWindow = clock;
  events = uniqueEvents([...events, ...data.events]);
  const f = displayFrame(data.frames, clock);
  baseline = displayFrame(data.baseline_frames, clock);
  if (mode === "historical") await historical();
  else if (f) frame = f;
  render();
}
async function historical() {
  const scenario = recording?.scenario_id || run?.state.scenario_id;
  if (!scenario) return;
  const gen = sourceGeneration;
  const data = await api(
    `/replay?scenario_id=${encodeURIComponent(scenario)}&clock=${clock}&window_seconds=120`,
  );
  if (gen !== sourceGeneration) return;
  frame = {
    ...frame,
    mode: "historical",
    clock,
    aircraft: data.aircraft.map((a) => ({
      id: a.id,
      callsign: a.callsign,
      longitude: a.longitude,
      latitude: a.latitude,
      altitude_ft: a.altitude_ft,
      track_deg_true: a.track_deg_true,
      status: a.status,
      source_time: clock - a.age_seconds,
      age_seconds: a.age_seconds,
      provenance: a.provenance,
    })),
    metrics: {},
    closed_runways: [],
    provenance: data.provenance,
  };
  $("source").textContent =
    "Historical observations · gaps and unknown altitude retained. The metered simulation changes demand timing; paths are contextual, not matched human-controller outcomes.";
}
async function refreshLive() {
  if (!run) return;
  const gen = sourceGeneration;
  const [next, journal] = await Promise.all([
    api(`/runs/${run.id}/presentation`),
    api(`/runs/${run.id}/events?after=${events.at(-1)?.sequence || 0}`),
  ]);
  if (gen !== sourceGeneration) return;
  frame = next;
  clock = next.clock;
  events = uniqueEvents([...events, ...journal]);
  if (mode === "historical") await historical();
  render();
}
function connect() {
  stream?.close();
  stream = new EventSource(
    `/api/v2/runs/${run.id}/stream?after=${events.at(-1)?.sequence || 0}`,
  );
  stream.onmessage = () => {
    if (!busy) action(refreshLive);
  };
  stream.addEventListener("event", () => {
    if (!busy) action(refreshLive);
  });
  stream.onerror = () => {
    $("connection").textContent = "Reconnecting · last state retained";
  };
  stream.onopen = () => action(refreshLive);
}
async function command(path, body) {
  const latest = await api(`/runs/${run.id}`);
  run = await api(`/runs/${run.id}/${path}`, mutation(latest, body));
  await refreshLive();
}
async function loadComparison() {
  let data;
  if (recording) data = await api(`/recordings/${recording.id}/comparison`);
  else if (job) {
    const j = await api(`/jobs/${job}`);
    if (j.status === "failed")
      throw Error("Comparison failed. Evidence is retained.");
    if (j.status !== "complete") {
      $("comparison-results").textContent =
        "Deterministic comparison is running…";
      return;
    }
    data = j.result;
  } else return;
  const rows = data.results || [];
  $("comparison-results").innerHTML =
    "<table><thead><tr><th>Controller</th><th>Completed</th><th>Backlog</th><th>Mean delay · s</th></tr></thead><tbody>" +
    rows
      .map(
        (r) =>
          `<tr><td>${esc(r.controller)}</td><td>${r.metrics.completed}</td><td>${r.metrics.backlog}</td><td>${Number(r.metrics.mean_delay_seconds).toFixed(1)}</td></tr>`,
      )
      .join("") +
    "</tbody></table><p>Delay includes completed aircraft only. Compare it with backlog and the full exported evidence; lower delay alone is not an improvement.</p><details><summary>All results and limitations</summary><pre>" +
    esc(JSON.stringify(data, null, 2)) +
    "</pre></details>";
}
$("traffic").onclick = (e) => {
  const b = e.target.closest("[data-id]");
  if (b) {
    selected = b.dataset.id;
    render();
  }
};
$("recorded").onclick = () => action(loadRecording);
$("create").onclick = () =>
  action(async () => {
    disconnect();
    recording = null;
    baseline = null;
    mode = "simulation";
    setModeButtons();
    run = await api("/runs", {
      scenario_id: $("scenarios").value,
      controller: $("controller").value,
      fixture_fault:
        $("controller").value === "fixture" ? $("fault").value : "none",
      spend_cap_usd: 0.5,
      idempotency_key: crypto.randomUUID(),
    });
    history.replaceState(null, "", `/?run=${encodeURIComponent(run.id)}`);
    $("source").textContent =
      $("controller").selectedOptions[0].textContent +
      " · isolated research run";
    await refreshLive();
    connect();
  });
$("play").onclick = () =>
  action(async () => {
    if (run)
      await command("control", {
        action: frame.status === "running" ? "pause" : "play",
      });
    else playing = !playing;
  });
$("step").onclick = () =>
  action(async () => {
    if (run) await command("control", { action: "step", seconds: 10 });
    else {
      clock = Math.min(recording.end, clock + 10);
      await replay();
    }
  });
$("speed").onchange = () => {
  if (run)
    action(() =>
      command("control", { action: "speed", speed: Number($("speed").value) }),
    );
};
$("close").onclick = () =>
  action(() =>
    command("disruptions", { kind: "runway_closure", runway: "28R" }),
  );
$("seek").oninput = () =>
  action(async () => {
    playing = false;
    clock = Number($("seek").value);
    events = [];
    await replay();
  });
$("compare").onclick = () =>
  action(async () => {
    if (frame.status === "running")
      await command("control", { action: "pause" });
    const latest = await api(`/runs/${run.id}`);
    const j = await api(`/runs/${run.id}/compare`, mutation(latest, {}));
    job = j.id;
    await loadComparison();
  });
$("export").onclick = () =>
  action(async () => {
    const result = recording
      ? await api(`/recordings/${recording.id}/export`)
      : {
          run: await api(`/runs/${run.id}/export`),
          comparison: job ? await api(`/jobs/${job}`) : null,
        };
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "uita-evidence.json";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
$("retry").onclick = () =>
  action(async () => {
    if (run) {
      await refreshLive();
      connect();
    } else await loadRecording();
  });
$("logout").onclick = () =>
  action(async () => {
    await api("/logout", {});
    location.href = "/login";
  });
function setModeButtons() {
  document
    .querySelectorAll("[data-mode]")
    .forEach((b) => b.setAttribute("aria-pressed", b.dataset.mode === mode));
  $("comparison").hidden = mode !== "compare";
}
document.querySelectorAll("[data-mode]").forEach(
  (b) =>
    (b.onclick = () =>
      action(async () => {
        mode = b.dataset.mode;
        setModeButtons();
        if (run) await refreshLive();
        else if (recording) await replay();
        if (mode === "compare") await loadComparison();
      })),
);
document.querySelectorAll("[data-camera]").forEach(
  (b) =>
    (b.onclick = () => {
      camera = b.dataset.camera;
      document
        .querySelectorAll("[data-camera]")
        .forEach((x) => x.setAttribute("aria-pressed", x === b));
      $("render-status").hidden = false;
      $("render-status").textContent =
        "Loading renderer · shared clock continues";
      scene.src =
        camera === "tower"
          ? "19-tower-cab-interior.html?mode=connected"
          : "11-photoreal-sfo.html?mode=connected";
      scene.title = camera === "tower" ? "SFO tower cab" : "SFO dashboard";
    }),
);
$("render-controller").onchange = sendFrame;
addEventListener("message", (e) => {
  if (validMessage(e, scene.contentWindow, "uita:ready")) {
    $("render-status").hidden = true;
    sendFrame();
  }
  if (
    validMessage(e, scene.contentWindow, "uita:select") &&
    (e.data.id === null || frame?.aircraft.some((a) => a.id === e.data.id))
  ) {
    selected = e.data.id;
    render();
  }
  if (validMessage(e, scene.contentWindow, "uita:renderer-error")) {
    $("render-status").hidden = false;
    $("render-status").textContent =
      "Renderer unavailable · use the aircraft table and evidence";
  }
});
let previous = performance.now();
setInterval(() => {
  const now = performance.now(),
    dt = Math.min(1, (now - previous) / 1000);
  previous = now;
  if (playing && recording && !busy) {
    clock = Math.min(recording.end, clock + dt * Number($("speed").value));
    if (clock === recording.end) playing = false;
    if (clock - lastWindow > 20 || mode === "historical") action(replay);
    else {
      frame = displayFrame(windowData?.frames || [], clock) || frame;
      baseline =
        displayFrame(windowData?.baseline_frames || [], clock) || baseline;
      render();
    }
  }
}, 250);
setInterval(() => {
  if (run && !busy)
    action(async () => {
      await refreshLive();
      if (job) await loadComparison();
    });
}, 2000);
await action(async () => {
  const [catalog, scenarios, benchmark, identity] = await Promise.all([
    api("/recordings"),
    api("/scenarios"),
    api("/published-benchmark"),
    api("/me"),
  ]);
  $("logout").hidden = identity.access_mode === "public_demo";
  $("access-mode").textContent = identity.access_mode === "public_demo" ? "Public demo" : identity.username;
  recordings = catalog;
  $("recordings").innerHTML = catalog
    .map((r) => `<option value="${esc(r.id)}">${esc(r.title)}</option>`)
    .join("");
  $("scenarios").innerHTML = scenarios
    .map((s) => `<option value="${esc(s.id)}">${esc(s.id)}</option>`)
    .join("");
  $("scenarios").value = "2026-08-06-1500-research-v2-metered";
  $("benchmark").textContent = benchmark.text;
  const resumeId = new URLSearchParams(location.search).get("run");
  if (resumeId) {
    run = await api(`/runs/${encodeURIComponent(resumeId)}`);
    $("source").textContent = `Resumed ${run.state.controller} research run`;
    await refreshLive();
    connect();
  } else if (catalog.length) await loadRecording();
  else
    throw Error(
      "No verified Nemotron recording installed. Free fixtures remain available under Run a new simulation.",
    );
});

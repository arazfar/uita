import {
  api,
  mutation,
  displayFrame,
  uniqueEvents,
  timeLabel,
  validMessage,
} from "./research-client.js";
const $ = (id) => document.getElementById(id);
let scene = $("scene");
const cameras = new Map([["dashboard", scene]]);
let historyCatalog = [],
  historyDataset = null,
  simulationClock = 0,
  liveFrames = [],
  loadingWindow = false,
  seekAbort = null;
const sentBuffers = new WeakMap();
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
  const live = !!run && mode !== "historical";
  const terminal = frame && ["failed", "complete"].includes(frame.status);
  $("close").disabled = !live || terminal || mode === "historical" || busy;
  $("compare").disabled = !live || busy;
  $("seek").disabled = busy || live || (!recording && !historyDataset);
  $("create").disabled = busy;
  $("recorded").disabled = busy || !recordings.length;
  $("play").disabled =
    busy || (!live && !recording && !historyDataset) || (terminal && live);
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
  if (mode === "historical") {
    for (const id of ["close", "compare"]) $(id).disabled = true;
  }
  $("render-controller").disabled = !baseline;
}
function shownFrame() {
  return mode === "compare" &&
    $("render-controller").value === "baseline" &&
    baseline
    ? baseline
    : frame;
}
function sendFrame() {
  const shown = shownFrame();
  if (!shown) return;
  const frames =
    mode === "historical"
      ? windowData?.frames
      : run
        ? liveFrames
        : mode === "compare" && $("render-controller").value === "baseline"
          ? windowData?.baseline_frames
          : windowData?.frames;
  const buffer = frames?.length ? frames : [shown];
  if (sentBuffers.get(scene) !== buffer) {
    message("uita:buffer", { frames: buffer });
    sentBuffers.set(scene, buffer);
  }
  const running =
    mode === "historical" || !run ? playing : frame.status === "running";
  message("uita:playhead", {
    clock,
    rate: running
      ? run && mode !== "historical"
        ? run.state.speed || 1
        : Number($("speed").value)
      : 0,
    selected,
    active: true,
  });
}
function render() {
  if (!frame) return;
  const shown = shownFrame();
  if (!shown.aircraft.some((a) => a.id === selected)) selected = null;
  if (recording && mode !== "historical")
    $("source").textContent =
      `${recording.title} · ${recording.model} · ${recording.model_responses} model responses · ${recording.fallback_count} fallbacks. ${recording.limitations.join(". ")}`;
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
  const m = shown.metrics || {};
  const metricRows =
    mode === "historical"
      ? [
          ["Observed targets", shown.aircraft.length],
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
            shown === frame &&
            events.some(
              (e) => e.kind === "controller_fallback" && e.clock <= clock,
            )
              ? "Deterministic fallback"
              : shown.controller,
          ],
          ["Unavailable runways", shown.closed_runways.join(", ") || "None"],
          [
            "Reserved / run cap · USD",
            shown.spend?.cap_usd != null
              ? `${shown.spend.reserved_usd.toFixed(4)} / ${shown.spend.cap_usd.toFixed(2)}`
              : "Recorded; see export",
          ],
        ];
  $("metrics").innerHTML = metricRows
    .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`)
    .join("");
  $("traffic-count").textContent = `(${shown.aircraft.length})`;
  const table = $("traffic");
  const rows = new Map([...table.rows].map(row => [row.querySelector("button").dataset.id, row]));
  const keep = new Set(shown.aircraft.map(a => a.id));
  for (const [id, row] of rows) if (!keep.has(id)) row.remove();
  shown.aircraft.forEach((a, index) => {
    let row = rows.get(a.id);
    if (!row) {
      row = document.createElement("tr");
      row.innerHTML = "<td><button></button></td><td></td><td></td>";
      row.querySelector("button").dataset.id = a.id;
    }
    const button = row.querySelector("button");
    if (button.textContent !== a.callsign) button.textContent = a.callsign;
    button.setAttribute("aria-pressed", String(selected === a.id));
    row.cells[1].textContent = a.altitude_ft == null ? "Unknown" : Math.round(a.altitude_ft);
    row.cells[2].textContent = a.status;
    if (table.children[index] !== row) table.insertBefore(row, table.children[index] || null);
  });
  $("scene-source").textContent =
    mode === "historical"
      ? "Recorded SFO traffic · observed positions"
      : recording
        ? `${recording.title} · ${recording.provenance === "fixture" ? "Scripted demo" : "Recorded Nemotron attempt"}`
        : "Live research simulation";
  $("scene-state").textContent =
    `${timeLabel(clock)} · ${shown.aircraft.length} aircraft · ${mode === "historical" ? "Unknown heights remain unplotted" : shown.controller} ${run && mode !== "historical" ? "· buffered committed motion" : ""}`;
  const aircraft = shown.aircraft.find((a) => a.id === selected);
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
  const sig = `${run?.id || recording?.id}:${visible.map((e) => e.sequence).join(",")}`;
  $("evidence-source").textContent =
    mode === "compare"
      ? "Candidate decision evidence · independent of the displayed controller"
      : "Selected run decision evidence";
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
function resetSource() {
  disconnect();
  selected = null;
  job = null;
  baseline = null;
  $("render-controller").value = "candidate";
  $("comparison-results").textContent = "No comparison for this run yet.";
  $("events").replaceChildren();
  delete $("events").dataset.signature;
  globalThis.speechSynthesis?.cancel();
}
async function loadRecording() {
  const nextRecording = recordings.find((r) => r.id === $("recordings").value);
  if (!nextRecording)
    throw Error("No authentic Nemotron recording is installed.");
  const [data, comparison, historyData] = await Promise.all([
    api(
      `/recordings/${nextRecording.id}/window?clock=${nextRecording.recommended_start || nextRecording.start}&seconds=120`,
    ),
    api(`/recordings/${nextRecording.id}/comparison`),
    null,
  ]);
  const nextFrame = displayFrame(
    data.frames,
    nextRecording.recommended_start || nextRecording.start,
  );
  if (!nextFrame) throw Error("Recording has no initial frame.");
  resetSource();
  history.replaceState(null, "", location.pathname);
  run = null;
  job = null;
  recording = nextRecording;
  clock = recording.recommended_start || recording.start;
  $("seek").min = recording.start;
  $("seek").max = recording.end;
  $("source").textContent =
    `${recording.title} · ${recording.model} · ${recording.model_responses} model responses · ${recording.fallback_count} fallbacks. Synthetic metered demand; inspect comparison before drawing conclusions.`;
  $("timeline-label").textContent =
    "Recorded simulation · read-only · closure at +90 seconds from demo opening · inspect source label";
  windowData = data;
  lastWindow = clock;
  frame = nextFrame;
  baseline = displayFrame(data.baseline_frames, clock);
  events = uniqueEvents(data.events);
  if (mode === "historical") {
    mode = "simulation";
    setModeButtons();
  }
  renderComparison(comparison);
  render();
}
async function replay() {
  if (mode === "historical") {
    await historical();
    render();
    return;
  }
  const gen = sourceGeneration;
  const data = await api(
    `/recordings/${recording.id}/window?clock=${clock}&seconds=120`,
    undefined,
    seekAbort?.signal,
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
  if (!historyDataset) throw Error("Historical demo data is not installed");
  const gen = sourceGeneration;
  const target = clock;
  const data = await api(
    `/history/${historyDataset.id}/window?clock=${clock}&seconds=120`,
    undefined,
    seekAbort?.signal,
  );
  if (gen !== sourceGeneration) return;
  windowData = data;
  lastWindow = target;
  frame = displayFrame(data.frames, clock);
  baseline = null;
  $("source").textContent =
    `Historical observations · ${historyDataset.coverage.tracks} tracks, ${historyDataset.coverage.measured_altitude_points} measured altitude samples. Unknown heights are not drawn in 3D.`;
}
async function refreshLive() {
  if (!run || mode === "historical") return;
  const gen = sourceGeneration;
  const [next, journal, motion] = await Promise.all([
    api(`/runs/${run.id}/presentation`),
    api(`/runs/${run.id}/events?after=${events.at(-1)?.sequence || 0}`),
    api(`/runs/${run.id}/motion`),
  ]);
  if (gen !== sourceGeneration) return;
  frame = next;
  liveFrames = motion.frames;
  clock =
    next.status === "running"
      ? Math.max(
          liveFrames[0]?.clock || next.clock,
          next.clock - 2 * (run.state.speed || 1),
        )
      : next.clock;
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
    $("retry").hidden = false;
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
  renderComparison(data);
}
function renderComparison(data) {
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
    const nextRun = await api("/runs", {
      scenario_id: $("scenarios").value,
      controller: $("controller").value,
      fixture_fault:
        $("controller").value === "fixture" ? $("fault").value : "none",
      spend_cap_usd: 0.5,
      idempotency_key: crypto.randomUUID(),
    });
    const [nextFrame, journal] = await Promise.all([
      api(`/runs/${nextRun.id}/presentation`),
      api(`/runs/${nextRun.id}/events?after=0`),
    ]);
    resetSource();
    run = nextRun;
    recording = null;
    mode = "simulation";
    frame = nextFrame;
    clock = frame.clock;
    events = uniqueEvents(journal);
    setModeButtons();
    $("timeline-label").textContent = "Live research run · worker-owned clock";
    history.replaceState(null, "", `/?run=${encodeURIComponent(run.id)}`);
    $("source").textContent =
      $("controller").selectedOptions[0].textContent +
      " · isolated research run";
    render();
    connect();
  });
$("play").onclick = () =>
  action(async () => {
    if (run && mode !== "historical")
      await command("control", {
        action: frame.status === "running" ? "pause" : "play",
      });
    else {
      playing = !playing;
      // Pausing stops the render timer, so send the final zero-rate playhead now.
      sendFrame();
    }
  });
$("step").onclick = () =>
  action(async () => {
    if (run && mode !== "historical")
      await command("control", { action: "step", seconds: 10 });
    else {
      clock = Math.min(
        mode === "historical" ? historyDataset.end : recording.end,
        clock + 10,
      );
      await replay();
    }
  });
$("speed").onchange = () => {
  if (run && mode !== "historical")
    action(() =>
      command("control", { action: "speed", speed: Number($("speed").value) }),
    );
};
$("close").onclick = () =>
  action(() =>
    command("disruptions", { kind: "runway_closure", runway: "28R" }),
  );
let seekTimer;
$("seek").oninput = () => {
  playing = false;
  clearTimeout(seekTimer);
  seekAbort?.abort();
  sourceGeneration++;
  clock = Number($("seek").value);
  sendFrame();
  seekTimer = setTimeout(() => {
    seekAbort = new AbortController();
    action(async () => {
      events = [];
      await replay();
    });
  }, 80);
};
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
  document.body.classList.toggle("historical", mode === "historical");
}
document.querySelectorAll("[data-mode]").forEach(
  (b) =>
    (b.onclick = () =>
      action(async () => {
        if (mode !== "historical") simulationClock = clock;
        const previousMode = mode;
        mode = b.dataset.mode;
        sourceGeneration++;
        windowData = null;
        lastWindow = -Infinity;
        if (mode === "historical") {
          clock = historyDataset.recommended_start || historyDataset.start;
          $("seek").min = historyDataset.start;
          $("seek").max = historyDataset.end;
          await historical();
          render();
        } else {
          if (previousMode === "historical") clock = simulationClock;
          if (recording) {
            $("seek").min = recording.start;
            $("seek").max = recording.end;
          }
          if (run) await refreshLive();
          else if (recording) await replay();
        }
        setModeButtons();
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
      scene.contentWindow?.postMessage(
        { type: "uita:visibility", active: false },
        location.origin,
      );
      scene.contentWindow?.postMessage({ uita: "pause" }, location.origin);
      scene.hidden = true;
      if (!cameras.has(camera)) {
        const next = document.createElement("iframe");
        next.title = camera === "tower" ? "SFO tower cab" : "SFO dashboard";
        next.src =
          camera === "tower"
            ? "19-tower-cab-interior.html?mode=connected"
            : "11-photoreal-sfo.html?mode=connected";
        scene.parentElement.prepend(next);
        cameras.set(camera, next);
      }
      scene = cameras.get(camera);
      scene.hidden = false;
      scene.contentWindow?.postMessage({type:"uita:visibility",active:true},location.origin);
      scene.contentWindow?.postMessage({ uita: "resume" }, location.origin);
      if (sentBuffers.has(scene)) {
        $("render-status").hidden = true;
        sendFrame();
      }
    }),
);
$("render-controller").onchange = render;
addEventListener("message", (e) => {
  if (validMessage(e, scene.contentWindow, "uita:ready")) {
    $("render-status").hidden = true;
    sentBuffers.delete(scene);
    sendFrame();
  }
  if (
    validMessage(e, scene.contentWindow, "uita:select") &&
    (e.data.id === null ||
      shownFrame()?.aircraft.some((a) => a.id === e.data.id))
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
  if (playing && (recording || mode === "historical") && !busy) {
    const end = mode === "historical" ? historyDataset.end : recording.end;
    const bufferedEnd = windowData?.frames.at(-1)?.clock || clock;
    clock = Math.min(end, bufferedEnd, clock + dt * Number($("speed").value));
    if (clock === end) playing = false;
    if (clock - lastWindow > 30 && !loadingWindow) {
      loadingWindow = true;
      replay()
        .catch((e) => {
          if (e.name !== "AbortError") fail(e);
        })
        .finally(() => (loadingWindow = false));
    } else {
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
action(async () => {
  const [catalog, scenarios, benchmark, identity, histories] =
    await Promise.all([
      api("/recordings"),
      api("/scenarios"),
      api("/published-benchmark"),
      api("/me"),
      api("/history/catalog"),
    ]);
  $("logout").hidden = identity.access_mode === "public_demo";
  $("access-mode").textContent =
    identity.access_mode === "public_demo" ? "Public demo" : identity.username;
  histories.sort((a,b) => b.coverage.measured_altitude_points - a.coverage.measured_altitude_points);
  historyCatalog = histories;
  historyDataset = histories[0];
  $("history-datasets").innerHTML = histories
    .map(
      (h) =>
        `<option value="${esc(h.id)}">${esc(timeLabel(h.start))} · ${h.coverage.tracks} tracks</option>`,
    )
    .join("");
  catalog.sort((a, b) =>
    a.id === "guided-demo-v1"
      ? -1
      : b.id === "guided-demo-v1"
        ? 1
        : a.id.localeCompare(b.id),
  );
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

function drawer(open) {
  document.body.classList.toggle("drawer-open", open);
  $("evidence-drawer").inert = !open;
  $("drawer-toggle").setAttribute("aria-expanded", String(open));
  if (!open) $("drawer-toggle").focus();
}
$("drawer-toggle").onclick = () =>
  drawer(!document.body.classList.contains("drawer-open"));
$("drawer-close").onclick = () => drawer(false);
addEventListener("keydown", (e) => {
  if (e.key === "Escape") drawer(false);
});
$("history-datasets").onchange = () =>
  action(async () => {
    historyDataset = historyCatalog.find(
      (h) => h.id === $("history-datasets").value,
    );
    clock = historyDataset.recommended_start;
    await historical();
    render();
  });

addEventListener("offline", () =>
  fail(new Error("Offline · last committed state retained")),
);

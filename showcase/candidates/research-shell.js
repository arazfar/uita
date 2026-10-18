import { PlaybackWindows } from "./research-windows.js";
import { arrivalLabel, arrivalTone, TONE_CSS, landingCandidates } from "./research-arrivals.js";
import { decisionAt, DecisionVisibility } from "./research-decision.js";
import {
  api,
  mutation,
  displayFrame,
  uniqueEvents,
  timeLabel,
  validMessage,
  plottable,
} from "./research-client.js";
const $ = (id) => document.getElementById(id);
// A failed optional panel must never stop traffic playback or tower controls.
let renderAgentTrace;
import("./trace-assets/agent-trace.js")
  .then((module) => {
    renderAgentTrace = module.renderAgentTrace;
    render();
  })
  .catch(() => {
    $("agent-trace").textContent =
      "Agent trace unavailable. Raw decision evidence remains below.";
  });

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
const windows = new PlaybackWindows((kind, id, clock, signal) =>
  api(
    `/${kind}/${encodeURIComponent(id)}/window?clock=${clock}&seconds=120`,
    undefined,
    AbortSignal.any([signal, AbortSignal.timeout(15000)]),
  ),
);
const sessions = new Map();
const decisionVisibility = new DecisionVisibility();
let decisionSeeking = true;
let highlightedAircraft = null;
let transition = null,
  transitionId = 0,
  retryTransition = null;
const sessionKey = (value) =>
  value === "historical" ? "historical" : "simulation";
function captureSession() {
  return {
    speed: $("speed").value,
    frame,
    baseline,
    selected,
    recording,
    run,
    events,
    playing,
    clock,
    job,
    windowData,
    lastWindow,
    liveFrames,
    historyDataset,
    comparison: $("comparison-results").innerHTML,
    controller: $("render-controller").value,
    source: $("source").textContent,
    timeline: $("timeline-label").textContent,
  };
}
function restoreSession(s) {
  ({
    frame,
    baseline,
    selected,
    recording,
    run,
    events,
    playing,
    clock,
    job,
    windowData,
    lastWindow,
    liveFrames,
  } = s);
  if (mode === "historical") historyDataset = s.historyDataset;
  if (recording) $("recordings").value = recording.id;
  if (historyDataset) $("history-datasets").value = historyDataset.id;
  if (s.speed) $("speed").value = s.speed;
  $("comparison-results").innerHTML = s.comparison;
  $("render-controller").value = s.controller;
  $("source").textContent = s.source;
  $("timeline-label").textContent = s.timeline;
  const source = mode === "historical" ? historyDataset : recording;
  if (source) {
    $("seek").min = source.start;
    $("seek").max = source.end;
  }
}
async function switchMode(nextMode, source = null) {
  const id = ++transitionId;
  transition?.abort();
  transition = new AbortController();
  const signal = transition.signal;
  seekAbort?.abort();
  clearTimeout(seekTimer);
  sourceGeneration++;
  $("switch-status").textContent =
    `Loading ${nextMode === "historical" ? "historical traffic" : "simulation"}…`;
  retryTransition = () => switchMode(nextMode, source);
  sendFrame();
  controls();
  try {
    let target =
      sessionKey(nextMode) === sessionKey(mode)
        ? captureSession()
        : sessions.get(sessionKey(nextMode));
    if (nextMode === "historical") {
      const dataset = source || target?.historyDataset || historyDataset;
      if (!dataset) throw Error("Historical demo data is not installed");
      if (!target || target.historyDataset.id !== dataset.id)
        target = {
          ...captureSession(),
          historyDataset: dataset,
          clock: dataset.recommended_start || dataset.start,
          selected: null,
          playing: false,
          events: [],
          recording: null,
          run: null,
          job: null,
          baseline: null,
          comparison: "",
          controller: "candidate",
        };
      const data = await windows.load("history", dataset, target.clock, signal);
      target = {
        ...target,
        windowData: data,
        frame: displayFrame(data.frames, target.clock),
        baseline: null,
        events: [],
        lastWindow: target.clock,
      };
      target.source = `Historical observations · ${dataset.coverage.tracks} tracks · inferred approaches are presentation heuristics`;
      target.timeline = "Historical observations · read-only";
    } else if (source || !target) {
      const nextRecording = source || recording || recordings[0];
      if (!nextRecording) throw Error("No simulation recording installed");
      const at = nextRecording.recommended_start || nextRecording.start;
      const data = await windows.load("recordings", nextRecording, at, signal);
      target = {
        ...captureSession(),
        recording: nextRecording,
        run: null,
        job: null,
        selected: null,
        playing: false,
        clock: at,
        frame: displayFrame(data.frames, at),
        baseline: displayFrame(data.baseline_frames, at),
        events: uniqueEvents(data.events),
        windowData: data,
        lastWindow: at,
        comparison: "",
        controller: "candidate",
        timeline: "Recorded simulation · read-only",
      };
    } else if (target.run) {
      const runId = target.run.id;
      const [latest, next, journal, motion] = await Promise.all([
        api(`/runs/${runId}`, undefined, signal),
        api(`/runs/${runId}/presentation`, undefined, signal),
        api(`/runs/${runId}/events?after=0`, undefined, signal),
        api(`/runs/${runId}/motion`, undefined, signal),
      ]);
      target = {
        ...target,
        run: latest,
        frame: next,
        clock: next.clock,
        events: uniqueEvents(journal),
        liveFrames: motion.frames,
      };
    } else {
      const data = await windows.load(
        "recordings",
        target.recording,
        target.clock,
        signal,
      );
      target = {
        ...target,
        frame: displayFrame(data.frames, target.clock),
        baseline: displayFrame(data.baseline_frames, target.clock),
        events: uniqueEvents([...target.events, ...data.events]),
        windowData: data,
        lastWindow: target.clock,
      };
    }
    if (id !== transitionId) return;
    if (!target.frame) throw Error("No usable traffic frame at this time");
    sessions.set(sessionKey(mode), captureSession());
    stream?.close();
    stream = null;
    mode = nextMode;
    decisionSeeking = true;
    restoreSession(target);
    sourceGeneration++;
    transition = null;
    retryTransition = null;
    $("switch-status").textContent = "";
    $("switch-retry").hidden = true;
    $("error").hidden = true;
    $("events").replaceChildren();
    delete $("events").dataset.signature;
    globalThis.speechSynthesis?.cancel();
    lastSpoken = 0;
    setModeButtons();
    render();
    if (run) {
      history.replaceState(null, "", `/?run=${encodeURIComponent(run.id)}`);
      connect();
    } else history.replaceState(null, "", location.pathname);
    if (mode === "compare" || (source && mode !== "historical")) {
      const generation = sourceGeneration;
      loadComparison().catch((e) => {
        if (generation === sourceGeneration) fail(e);
      });
    }
  } catch (e) {
    if (id !== transitionId) return;
    transition = null;
    sendFrame();
    $("switch-status").textContent =
      `Unable to load ${nextMode} · current view retained${e.status === 401 ? " · session expired" : ""}`;
    if (e.status === 401) fail(e);
    $("switch-retry").hidden = false;
    if (recording) $("recordings").value = recording.id;
    if (historyDataset) $("history-datasets").value = historyDataset.id;
    controls();
  }
}
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
    const generation = sourceGeneration;
    busy = true;
    controls();
    try {
      await fn();
      $("error").hidden = true;
      $("retry").hidden = true;
    } catch (e) {
      if (generation === sourceGeneration && e.name !== "AbortError") fail(e);
    } finally {
      busy = false;
      controls();
    }
  };
  actionQueue = actionQueue.then(execute, execute);
  return actionQueue;
}

function controls() {
  const locked = busy || !!transition;
  const live = !!run && mode !== "historical";
  $("speed").querySelector('[value="60"]').disabled = live;
  if (live && Number($("speed").value) > 30)
    $("speed").value = String(run.state.speed || 1);
  const terminal = frame && ["failed", "complete"].includes(frame.status);
  $("close").disabled = !live || terminal || mode === "historical" || locked;
  $("compare").disabled = !live || locked;
  $("seek").disabled = locked || live || (!recording && !historyDataset);
  $("create").disabled = locked;
  $("recorded").disabled = locked || !recordings.length;
  $("play").disabled =
    locked || (!live && !recording && !historyDataset) || (terminal && live);
  $("play").textContent = live
    ? frame?.status === "running"
      ? "Pause run"
      : "Run simulation"
    : playing
      ? "Pause recording"
      : "Play recording";
  $("ds-play").disabled = $("play").disabled;
  $("step").disabled =
    locked || !frame || (live && (terminal || frame.status === "running"));
  $("export").disabled = locked || (!recording && !run);
  document
    .querySelectorAll("[data-mode]")
    .forEach((b) => (b.disabled = !frame));
  $("speed").disabled = locked;
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
  renderAgentTrace?.({
    events,
    clock,
    sourceKey: `${sourceGeneration}:${run?.id || recording?.id}`,
    source: recording?.title || run?.id || "Selected run",
    live: !!run,
    controller:
      run?.state?.controller ||
      (recording?.provenance === "fixture" ? "fixture" : frame.controller),
    status: frame.status,
    comparison: mode === "compare",
    hidden: mode === "historical",
  });
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
    (mode === "historical" || !run ? playing : frame.status === "running") &&
    !transition;
  message("uita:ui", {
    speed: Number($("speed").value),
    maxSpeed: run && mode !== "historical" ? 30 : 60,
    playing: running,
    speech: $("speech").checked,
  });
  message("uita:playhead", {
    highlightedAircraft,
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
  renderSandbox();
  const arrivals = landingCandidates(shown);
  $("arrival-status").textContent = arrivals.length
    ? `${arrivals.length} approaching · ${arrivalLabel(arrivals[0])}`
    : "No landing activity identified at this time";
  $("follow-landing").disabled = !arrivals.length;
  const decision = decisionAt(
    events,
    shown,
    clock,
    mode === "compare" && $("render-controller").value === "baseline",
  );
  const overlay = $("decision-overlay");
  const decisionKey = decision ? `${shown.source_id}:${decision.key}` : null;
  const visibleDecision = decisionVisibility.update(
    decisionKey,
    performance.now(),
    document.hidden ||
      overlay.matches(":hover") ||
      overlay.contains(document.activeElement),
    decisionSeeking,
  );
  if (decision) decisionSeeking = false;
  overlay.hidden = !visibleDecision;
  highlightedAircraft = visibleDecision ? decision?.aircraft_id : null;
  if (decision) {
    $("decision-origin").textContent =
      `${decision.origin} · ${decisionVisibility.seek ? "At this playback time · " : ""}${timeLabel(decision.clock)}`;
    $("decision-aircraft").textContent =
      `${decision.phase} · ${decision.callsign || "Airport"} · ${decision.action}`;
    $("decision-aircraft").disabled = !decision.aircraft_id;
    $("decision-aircraft").onclick = () => {
      selected = decision.aircraft_id;
      render();
    };
    $("decision-explanation").textContent = decision.explanation;
    $("decision-cause").textContent = decision.cause || "";
    $("decision-verdict").textContent = decision.has_verification
      ? `Proposal verification · ${decision.verdict}`
      : "Executed simulation event · inspect evidence for details";
    $("decision-clearance").textContent = decision.clearance || "";
    $("decision-follow").disabled = !shown.aircraft.some(
      (a) => a.id === decision.aircraft_id,
    );
    $("decision-follow").onclick = () => {
      selected = decision.aircraft_id;
      render();
      message("uita:camera", { action: "follow", id: selected });
    };
    $("decision-batch").hidden = decision.actions.length < 2;
    if ($("decision-batch").dataset.key !== decisionKey) {
      $("decision-batch").dataset.key = decisionKey;
      $("decision-batch").querySelector("ul").innerHTML = decision.actions
        .map((a) => `<li>${esc(a.text)}</li>`)
        .join("");
    }
  }
  const queue = $("arrivals-queue");
  const queueKey = JSON.stringify(
    arrivals
      .slice(0, 3)
      .map((a) => [a.id, a.callsign, arrivalLabel(a), a.arrival_cue.runway]),
  );
  if (queue.dataset.key !== queueKey) {
    queue.dataset.key = queueKey;
    queue.innerHTML =
      arrivals
        .slice(0, 3)
        .map(
          (a) =>
            `<button data-aircraft="${esc(a.id)}"><strong>${esc(a.callsign)}</strong> <span style="color:${TONE_CSS[arrivalTone(a)]}">${esc(arrivalLabel(a))}${a.arrival_cue.runway ? " · assigned " + esc(a.arrival_cue.runway) : ""}</span></button>`,
        )
        .join("") +
      (arrivals.length
        ? "<button data-all>All traffic & evidence →</button>"
        : "");
    queue.querySelectorAll("[data-aircraft]").forEach(
      (b) =>
        (b.onclick = () => {
          selected = b.dataset.aircraft;
          render();
        }),
    );
    const all = queue.querySelector("[data-all]");
    if (all)
      all.onclick = () => {
        drawer(true);
        $("traffic-count").scrollIntoView({ block: "nearest" });
      };
  }
  if (!shown.aircraft.some((a) => a.id === selected)) selected = null;
  document.body.classList.toggle(
    "aircraft-inspected",
    !!selected && camera === "dashboard",
  );
  if (recording && mode !== "historical")
    $("source").textContent =
      `${recording.title} · ${recording.model} · ${recording.model_responses} model responses · ${recording.fallback_count} fallbacks. ${recording.limitations.join(". ")}`;
  $("clock").textContent = timeLabel(clock || frame.clock);
  $("seek").value = String(clock);
  // Status strip: readable summary; the raw status and revision stay in the tooltip for researchers.
  const what = mode === "historical" ? "observed traffic" : String(recording?.title || run?.state?.scenario || "simulation").replace(/^San Francisco · /, "").replace(/ · synthetic$/, "");
  const hhmm = new Intl.DateTimeFormat("en-US", { timeZone: "America/Los_Angeles", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date((clock || frame.clock) * 1000));
  $("connection").textContent =
    `${run && mode !== "historical" ? "Live backend" : "Recorded playback"} · SFO · ${what} · ${hhmm} PDT`;
  $("connection").title = `${recording?.title || run?.state?.scenario || ""} · ${timeLabel(clock || frame.clock)} · ${frame.status} · revision ${frame.revision}`;
  const moving = run && mode !== "historical" ? frame.status === "running" : playing;
  $("ds-dot").classList.toggle("on", !!moving);
  $("ds-play").textContent = moving ? "⏸" : "▶";
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
  renderPanel(shown, metricRows, m, arrivals);
  $("traffic-count").textContent = `(${shown.aircraft.length})`;
  const table = $("traffic");
  const rows = new Map(
    [...table.rows].map((row) => [row.querySelector("button").dataset.id, row]),
  );
  const keep = new Set(shown.aircraft.map((a) => a.id));
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
    row.cells[1].textContent =
      a.altitude_ft == null ? "Unknown" : Math.round(a.altitude_ft);
    row.cells[2].textContent = arrivalLabel(a);
    row.cells[2].style.color = TONE_CSS[arrivalTone(a)];
    if (table.children[index] !== row)
      table.insertBefore(row, table.children[index] || null);
  });
  $("scene-source").textContent =
    mode === "historical"
      ? "Recorded SFO traffic · observed positions"
      : recording
        ? `${recording.title} · ${recording.provenance === "fixture" ? "Scripted demo" : "Recorded Nemotron attempt"}`
        : "Live research simulation";
  $("scene-state").textContent =
    `${timeLabel(clock)} · ${shown.aircraft.filter(plottable).length} visible aircraft · ${mode === "historical" ? "Unknown heights remain unplotted" : shown.controller} ${run && mode !== "historical" ? "· buffered committed motion" : ""}`;
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
  if (
    mode !== "historical" &&
    (run || playing) &&
    $("speech").checked &&
    globalThis.speechSynthesis
  ) {
    for (const e of visible
      .filter(
        (e) =>
          e.sequence > lastSpoken &&
          e.kind === "clearance_issued" &&
          e.clock >= clock - 2,
      )
      .sort((a, b) => a.sequence - b.sequence)) {
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
  return switchMode(
    "simulation",
    recordings.find((r) => r.id === $("recordings").value),
  );
}
async function replay() {
  if (mode === "historical") {
    await historical();
    render();
    return;
  }
  const gen = sourceGeneration;
  const data = await windows.load(
    "recordings",
    recording,
    clock,
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
  const data = await windows.load(
    "history",
    historyDataset,
    target,
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
  if (!run || mode === "historical" || transition) return;
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
  const runId = run.id,
    gen = sourceGeneration;
  let latest = await api(`/runs/${runId}`);
  let updated;
  const key = crypto.randomUUID();
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      updated = await api(`/runs/${runId}/${path}`, {
        ...mutation(latest, body),
        idempotency_key: key,
      });
      break;
    } catch (error) {
      if (
        attempt ||
        error.status !== 409 ||
        !error.message.startsWith("Stale revision")
      )
        throw error;
      latest = await api(`/runs/${runId}`);
    }
  }
  if (gen !== sourceGeneration || run?.id !== runId) return updated;
  run = updated;
  await refreshLive();
  return updated;
}
async function loadComparison() {
  const gen = sourceGeneration;
  let data;
  if (recording) data = await api(`/recordings/${recording.id}/comparison`);
  else if (job) {
    const j = await api(`/jobs/${job}`);
    if (gen !== sourceGeneration) return;
    if (j.status === "failed")
      throw Error("Comparison failed. Evidence is retained.");
    if (j.status !== "complete") {
      $("comparison-results").textContent =
        "Deterministic comparison is running…";
      return;
    }
    data = j.result;
  } else return;
  if (gen === sourceGeneration) renderComparison(data);
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
    const creationGeneration = sourceGeneration;
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
    if (creationGeneration !== sourceGeneration) {
      sessions.set("simulation", {
        ...captureSession(),
        run: nextRun,
        recording: null,
        job: null,
        selected: null,
        playing: false,
        clock: nextFrame.clock,
        frame: nextFrame,
        baseline: null,
        events: uniqueEvents(journal),
        windowData: null,
        liveFrames: [nextFrame],
        lastWindow: -Infinity,
        comparison: "No comparison for this run yet.",
        controller: "candidate",
        source: `${nextRun.state.controller} · isolated research run`,
        timeline: "Live research run · worker-owned clock",
      });
      return;
    }
    sessions.set(sessionKey(mode), captureSession());
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
  decisionSeeking = true;
  playing = false;
  clearTimeout(seekTimer);
  seekAbort?.abort();
  sourceGeneration++;
  clock = Number($("seek").value);
  sendFrame();
  const seekGeneration = sourceGeneration;
  seekTimer = setTimeout(() => {
    seekAbort = new AbortController();
    action(async () => {
      if (seekGeneration !== sourceGeneration) return;
      events = [];
      await replay();
    });
  }, 80);
};
$("compare").onclick = () =>
  action(async () => {
    const runId = run.id,
      gen = sourceGeneration;
    if (frame.status === "running")
      await command("control", { action: "pause" });
    const latest = await api(`/runs/${runId}`);
    const j = await api(`/runs/${runId}/compare`, mutation(latest, {}));
    if (gen !== sourceGeneration || run?.id !== runId) {
      const saved = sessions.get("simulation");
      if (saved?.run?.id === runId) saved.job = j.id;
      return;
    }
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
    .forEach((b) =>
      b.setAttribute(
        "aria-pressed",
        b.dataset.mode === mode ||
          (b.dataset.mode === "simulation" && mode === "compare"),
      ),
    );
  $("comparison").hidden = mode !== "compare";
  document.body.classList.toggle("historical", mode === "historical");
}
document
  .querySelectorAll("[data-mode]")
  .forEach((b) => (b.onclick = () => switchMode(b.dataset.mode)));
$("switch-retry").onclick = () => retryTransition?.();
$("recordings").onchange = () =>
  switchMode(
    "simulation",
    recordings.find((r) => r.id === $("recordings").value),
  );
document.querySelectorAll("[data-camera]").forEach(
  (b) =>
    (b.onclick = () => {
      camera = b.dataset.camera;
      document.body.classList.toggle(
        "aircraft-inspected",
        !!selected && camera === "dashboard",
      );
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
      scene.contentWindow?.postMessage(
        { type: "uita:visibility", active: true },
        location.origin,
      );
      scene.contentWindow?.postMessage({ uita: "resume" }, location.origin);
      if (sentBuffers.has(scene)) {
        $("render-status").hidden = true;
        sendFrame();
      }
    }),
);
$("render-controller").onchange = render;
function presentationAction(name, value) {
  if (name === "speed-step" && [-1, 1].includes(value)) {
    const rates = [1, 5, 10, 20, 30, 60];
    presentationAction(
      "speed",
      rates[
        Math.max(
          0,
          Math.min(
            rates.length - 1,
            rates.indexOf(Number($("speed").value)) + value,
          ),
        )
      ],
    );
  }
  if (name === "view")
    document
      .querySelector(
        `[data-camera="${camera === "dashboard" ? "tower" : "dashboard"}"]`,
      )
      .click();
  if (name === "play") $("play").click();
  if (
    name === "speed" &&
    [1, 5, 10, 20, 30, 60].includes(value) &&
    !(run && mode !== "historical" && value > 30) &&
    !$("speed").disabled
  ) {
    $("speed").value = String(value);
    $("speed").dispatchEvent(new Event("change"));
  }
  if (name === "speech" && typeof value === "boolean")
    $("speech").checked = value;
  if (name === "restart" && !run && !$("seek").disabled) {
    $("seek").value = $("seek").min;
    $("seek").dispatchEvent(new Event("input"));
  }
}
addEventListener("keydown", (e) => {
  if (e.repeat || e.target.closest?.("input,select,textarea")) return;
  if (e.key.toLowerCase() === "t") {
    e.preventDefault();
    presentationAction("view");
  }
  if (e.key === " " && !e.target.closest?.("button")) {
    e.preventDefault();
    presentationAction("play");
  }
});
addEventListener("message", (e) => {
  if (validMessage(e, scene.contentWindow, "uita:action"))
    presentationAction(e.data.action, e.data.value);
  if (
    e.origin === location.origin &&
    e.source === scene.contentWindow &&
    e.data?.uita === "toggle"
  )
    presentationAction("view");
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
setInterval(() => {
  if (frame && !playing) render();
}, 250);
let previous = performance.now();
setInterval(() => {
  const now = performance.now(),
    dt = Math.min(1, (now - previous) / 1000);
  previous = now;
  if (playing && (recording || mode === "historical") && !transition) {
    const end = mode === "historical" ? historyDataset.end : recording.end;
    const bufferedEnd = windowData?.frames.at(-1)?.clock || clock;
    clock = Math.min(end, bufferedEnd, clock + dt * Number($("speed").value));
    if (clock === end) playing = false;
    frame = displayFrame(windowData?.frames || [], clock) || frame;
    baseline =
      displayFrame(windowData?.baseline_frames || [], clock) || baseline;
    render();
    if (
      bufferedEnd - clock <=
        Math.min(120, Math.max(1, Number($("speed").value)) * 10) &&
      !loadingWindow &&
      bufferedEnd < end
    ) {
      loadingWindow = true;
      prefetchPlayback()
        .catch((e) => {
          if (e.name !== "AbortError") fail(e);
        })
        .finally(() => (loadingWindow = false));
    }
  }
}, 250);
setInterval(() => {
  if (run && mode !== "historical" && !busy && !transition)
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
  histories.sort(
    (a, b) =>
      b.coverage.measured_altitude_points - a.coverage.measured_altitude_points,
  );
  historyCatalog = histories;
  historyDataset = histories[0];
  $("history-datasets").innerHTML = histories
    .map(
      (h) =>
        `<option value="${esc(h.id)}">${esc(timeLabel(h.start))} · ${h.coverage.tracks} tracks</option>`,
    )
    .join("");
  catalog.sort((a, b) =>
    a.id === "dense-demo-v1"
      ? -1
      : b.id === "dense-demo-v1"
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
  if (historyDataset)
    windows.prefetch(
      "history",
      historyDataset,
      historyDataset.recommended_start || historyDataset.start,
    );
});

// "Traffic & decisions" panel: KPI tiles, More stats, runway chips, controller badge, landing queue.
// #metrics keeps every metric's text (acceptance reads the controller name from it).
const RUNWAYS = ["28L", "28R", "01L", "01R", "19L", "19R"];
const KPI = {
  "Executed completions": ["Landed", "kpi"],
  "Unfinished backlog": ["Waiting", "kpi"],
  "Completed-only mean delay · s": ["Avg delay · s", "kpi"],
  "Executed violations": ["Safety violations", "kpi safety"],
};
function renderPanel(shown, metricRows, m, arrivals) {
  const box = $("metrics");
  if (!box.querySelector(".ds-kpis")) {
    box.innerHTML =
      '<dl class="ds-kpis"></dl><details class="ds-more"><summary>More stats</summary><dl class="ds-more-dl"></dl></details>';
  }
  const tiles = metricRows.filter(([k]) => KPI[k] || mode === "historical");
  const rest = metricRows.filter(([k]) => !KPI[k] && mode !== "historical");
  box.querySelector(".ds-kpis").innerHTML = tiles
    .map(([k, v]) => {
      const [label, cls] = KPI[k] || [k, "kpi"];
      const bad = cls.includes("safety") && Number(v) > 0;
      const shownV = cls.includes("safety") && v !== "—" ? (bad ? v : `${v} ✓`) : v;
      return `<div class="${cls}${cls.includes("safety") ? (bad ? " bad" : " ok") : ""}" title="${esc(k)}"><dt>${esc(label)}</dt><dd>${esc(shownV)}</dd></div>`;
    })
    .join("");
  box.querySelector(".ds-more-dl").innerHTML = rest
    .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`)
    .join("");
  box.querySelector(".ds-more").hidden = !rest.length;
  // runway chips
  const closed = new Set(shown.closed_runways || []);
  const chips = RUNWAYS.map(
    (r) => `<span class="ds-rwy${closed.has(r) ? " off" : ""}" title="${closed.has(r) ? "Unavailable" : "Available"}">${r}</span>`,
  ).join("");
  if ($("ds-runways").innerHTML !== chips) $("ds-runways").innerHTML = chips;
  // controller badge
  const fixture = recording?.provenance === "fixture";
  const ctrl = String(shown.controller || "—");
  const model = !fixture && /nemotron|crusoe|model|llm/i.test(ctrl + " " + (recording?.model || ""));
  const lat = events
    .filter((e) => e.clock <= clock)
    .map((e) => e.payload?.latency_ms ?? e.payload?.elapsed_ms ?? e.payload?.model_latency_ms)
    .filter((x) => Number.isFinite(x))
    .pop();
  $("ds-controller").textContent =
    mode === "historical"
      ? "Observed traffic · no controller"
      : model
        ? `Nemotron${lat != null ? ` · decided in ${(lat / 1000).toFixed(1)} s` : ` · ${recording?.model || ctrl}`}`
        : `Controller: ${ctrl}${fixture ? " · scripted" : ""}`;
  // landing queue (same data-aircraft selection as the floating queue)
  const qKey = JSON.stringify(arrivals.slice(0, 6).map((a) => [a.id, arrivalLabel(a), a.arrival_cue.runway, a.arrival_cue.distance_nm, selected === a.id]));
  const q = $("ds-queue");
  if (q.dataset.key !== qKey) {
    q.dataset.key = qKey;
    q.innerHTML = arrivals.length
      ? arrivals
          .slice(0, 6)
          .map(
            (a) =>
              `<li><button data-aircraft="${esc(a.id)}" aria-pressed="${selected === a.id}"><strong>${esc(a.callsign)}</strong><span class="ds-pill" style="--tone:${TONE_CSS[arrivalTone(a)]}">${esc(arrivalLabel(a).split(" · ")[0])}</span><span class="ds-q-meta">${esc(a.arrival_cue.runway || "—")}${a.arrival_cue.distance_nm != null ? ` · ${Number(a.arrival_cue.distance_nm).toFixed(0)} NM` : ""}</span></button></li>`,
          )
          .join("")
      : '<li class="ds-empty">No arrivals in the landing queue</li>';
    q.querySelectorAll("[data-aircraft]").forEach(
      (b) =>
        (b.onclick = () => {
          selected = b.dataset.aircraft;
          render();
        }),
    );
  }
}
$("ds-play").onclick = () => $("play").click();
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
  switchMode(
    "historical",
    historyCatalog.find((h) => h.id === $("history-datasets").value),
  );

addEventListener("offline", () =>
  fail(new Error("Offline · last committed state retained")),
);

$("decision-evidence").onclick = () => {
  drawer(true);
  $("events").scrollIntoView({ block: "nearest" });
};

async function prefetchPlayback() {
  const gen = sourceGeneration,
    source = mode === "historical" ? historyDataset : recording,
    kind = mode === "historical" ? "history" : "recordings";
  if (!source || !windowData) return;
  const end = windowData.frames.at(-1)?.clock;
  if (end >= source.end) return;
  let data;
  try {
    data = await windows.load(
      kind,
      source,
      Math.min(source.end, windowData.window_start + 120),
    );
  } catch (e) {
    if (gen !== sourceGeneration) return;
    throw e;
  }
  if (gen !== sourceGeneration) return;
  const merge = (a, b) =>
    [...new Map([...a, ...b].map((f) => [f.clock, f])).values()]
      .sort((a, b) => a.clock - b.clock)
      .filter((f) => f.clock >= clock - 120);
  windowData = {
    window_start: data.window_start,
    frames: merge(windowData.frames, data.frames),
    baseline_frames: merge(
      windowData.baseline_frames || [],
      data.baseline_frames || [],
    ),
    events: [],
  };
  events = uniqueEvents([...events, ...data.events]);
  render();
}
$("follow-landing").onclick = () => {
  const a = landingCandidates(shownFrame())[0];
  if (!a) return;
  selected = a.id;
  render();
  message("uita:camera", { action: "follow", id: a.id });
};
$("traffic-overview").onclick = () =>
  message("uita:camera", { action: "overview" });

$("airport-view").onclick = () => message("uita:camera", { action: "airport" });

let sandboxPreparing = false,
  sandboxPending = null;
$("sandbox-toggle").onclick = () => {
  $("sandbox-panel").hidden = !$("sandbox-panel").hidden;
  document.body.classList.toggle("sandbox-open", !$("sandbox-panel").hidden);
  renderSandbox();
};
$("sandbox-dismiss").onclick = () => {
  $("sandbox-panel").hidden = true;
  document.body.classList.remove("sandbox-open");
};
async function startSandbox(reset = false) {
  if (sandboxPreparing) return;
  sandboxPreparing = true;
  renderSandbox();
  const generation = sourceGeneration;
  try {
    if (reset) sandboxPending = null;
    sandboxPending ||= await api("/runs", {
      scenario_id: "early-august-sandbox-v1",
      sandbox: true,
      controller: "static",
      seed: 42,
      spend_cap_usd: 0,
      idempotency_key: crypto.randomUUID(),
    });
    const until = performance.now() + 60000;
    let next = sandboxPending;
    while (next.state.initialization_until && next.status === "running") {
      $("sandbox-status").textContent =
        `Preparing traffic · ${Math.floor(next.state.clock - next.state.start)} / 300 simulated seconds`;
      if (performance.now() > until)
        throw Error(
          "Worker preparation is taking longer than expected. Retry resumes the same sandbox.",
        );
      await new Promise((resolve) => setTimeout(resolve, 500));
      next = await api(`/runs/${next.id}`);
    }
    if (next.status === "failed")
      throw Error(
        "Sandbox preparation failed; evidence retained in run " + next.id,
      );
    const [nextFrame, journal] = await Promise.all([
      api(`/runs/${next.id}/presentation`),
      api(`/runs/${next.id}/events?after=0`),
    ]);
    const target = {
      ...captureSession(),
      run: next,
      recording: null,
      job: null,
      selected: null,
      playing: false,
      clock: nextFrame.clock,
      frame: nextFrame,
      baseline: null,
      events: uniqueEvents(journal),
      windowData: null,
      liveFrames: [nextFrame],
      lastWindow: -Infinity,
      comparison: "No comparison for this sandbox yet.",
      controller: "candidate",
      source: "Live deterministic sandbox · synthetic conditions",
      timeline: "Live sandbox · worker-owned clock",
    };
    if (generation !== sourceGeneration) {
      sessions.set("simulation", target);
      $("sandbox-status").textContent = "Sandbox ready. Return to Simulation.";
      return;
    }
    sessions.set(sessionKey(mode), captureSession());
    stream?.close();
    resetSource();
    mode = "simulation";
    restoreSession(target);
    sourceGeneration++;
    setModeButtons();
    render();
    connect();
    history.replaceState(null, "", `/?run=${encodeURIComponent(run.id)}`);
    await command("control", { action: "play" });
    $("sandbox-status").textContent =
      "Ready · interventions affect this live run only";
    sandboxPending = null;
  } catch (error) {
    $("sandbox-status").textContent = error.message;
  } finally {
    sandboxPreparing = false;
    renderSandbox();
  }
}
function renderSandbox() {
  const live =
    !!run &&
    mode !== "historical" &&
    frame?.simulator_version === "kinematic-sandbox-3";
  const ready =
    live &&
    !frame.initialization_until &&
    !["failed", "complete"].includes(frame.status);
  $("sandbox-start").hidden = live;
  $("sandbox-reset").hidden = !live;
  $("sandbox-start").disabled = sandboxPreparing;
  $("sandbox-reset").disabled = sandboxPreparing;
  $("sandbox-actions").disabled = !ready || busy || sandboxPreparing;
  const effects = live ? frame.interventions || [] : [];
  $("sandbox-weather").disabled = effects.some(
    (i) => i.kind === "weather_restriction" && i.status === "active",
  );
  $("sandbox-delay").disabled = effects.some(
    (i) => i.kind === "pilot_delay" && i.status === "active",
  );
  $("sandbox-extra").disabled = (frame?.admission_requests || []).length >= 3;
  const eligible = ready
    ? frame.aircraft.filter(
        (a) =>
          a.status === "approach" &&
          a.arrival_cue?.phase !== "landing_authorized",
      )
    : [];
  const selection = $("sandbox-aircraft").value;
  const signature = JSON.stringify(eligible.map((a) => [a.id, a.callsign]));
  if ($("sandbox-aircraft").dataset.signature !== signature) {
    $("sandbox-aircraft").dataset.signature = signature;
    $("sandbox-aircraft").innerHTML = eligible
      .map((a) => `<option value="${esc(a.id)}">${esc(a.callsign)}</option>`)
      .join("");
    if (eligible.some((a) => a.id === selection))
      $("sandbox-aircraft").value = selection;
  }
  $("sandbox-priority").disabled = !eligible.length;
  const previous = $("sandbox-comparison").value;
  const effectKey = JSON.stringify([
    effects.map((i) => [
      i.id,
      i.status,
      Math.max(0, Math.ceil((i.expires_at || 0) - frame.clock)),
    ]),
    frame?.admission_requests,
  ]);
  if ($("sandbox-effects").dataset.key !== effectKey) {
    $("sandbox-effects").dataset.key = effectKey;
    $("sandbox-effects").innerHTML =
      effects
        .map(
          (i) =>
            `<p>${esc(i.kind)} · ${esc(i.status)}${i.status === "active" && i.expires_at ? " · " + Math.max(0, Math.ceil(i.expires_at - frame.clock)) + "s remaining" : ""}${i.status === "active" && i.expires_at ? ` <button data-recover="${esc(i.id)}">Recover now</button>` : ""}</p>`,
        )
        .join("") +
      (live
        ? (frame.admission_requests || [])
            .map(
              (r) =>
                `<p>Extra arrival · ${esc(r.status)}${["queued", "deferred"].includes(r.status) ? " · earliest " + timeLabel(r.scheduled_at) : ""}</p>`,
            )
            .join("")
        : "");
    $("sandbox-effects")
      .querySelectorAll("[data-recover]")
      .forEach(
        (b) =>
          (b.onclick = () =>
            action(() =>
              command("disruptions", {
                kind: "recover",
                intervention_id: b.dataset.recover,
              }),
            )),
      );
    $("sandbox-comparison").innerHTML = effects
      .filter((i) => i.kind !== "recover")
      .map(
        (i) =>
          `<option value="${esc(i.id)}">${esc(i.kind)} · ${timeLabel(i.clock)}</option>`,
      )
      .join("");
    if (effects.some((i) => i.id === previous))
      $("sandbox-comparison").value = previous;
  }
  $("sandbox-compare").disabled =
    !live || !$("sandbox-comparison").value || busy;
  if (
    ready &&
    frame.last_decision?.clock >= Math.max(0, ...effects.map((i) => i.clock))
  )
    $("sandbox-status").textContent =
      "Controller reassessed traffic · inspect the map card or full evidence";
  if (live && ["failed", "complete"].includes(frame.status))
    $("sandbox-status").textContent =
      `Scenario ${frame.status} · evidence retained. Reset starts a separate run.`;
}
$("sandbox-start").onclick = () => startSandbox();
$("sandbox-reset").onclick = () => startSandbox(true);
const sandboxInject = (body) =>
  action(async () => {
    await command("disruptions", body);
    $("sandbox-status").textContent =
      "Condition changed · awaiting controller response";
  });
$("sandbox-weather").onclick = () =>
  sandboxInject({
    kind: "weather_restriction",
    runway: $("sandbox-runway").value,
  });
$("sandbox-priority").onclick = () =>
  sandboxInject({
    kind: "emergency",
    aircraft_id: $("sandbox-aircraft").value,
  });
$("sandbox-delay").onclick = () => sandboxInject({ kind: "pilot_delay" });
$("sandbox-extra").onclick = () => sandboxInject({ kind: "extra_arrival" });
$("sandbox-guided").onclick = () =>
  action(async () => {
    const preset = $("sandbox-preset").value;
    if (preset === "weather")
      await command("disruptions", {
        kind: "weather_restriction",
        runway: $("sandbox-runway").value,
      });
    else if (preset === "priority")
      await command("disruptions", {
        kind: "emergency",
        aircraft_id: $("sandbox-aircraft").value,
      });
    else {
      await command("disruptions", { kind: "pilot_delay" });
      await command("disruptions", { kind: "extra_arrival" });
    }
  });
$("sandbox-compare").onclick = () =>
  action(async () => {
    const runId = run.id,
      generation = sourceGeneration;
    const latest = await api(`/runs/${runId}`);
    const result = await api(
      `/runs/${runId}/compare-intervention`,
      mutation(latest, {
        intervention_id: $("sandbox-comparison").value,
        seconds: 300,
      }),
    );
    if (generation !== sourceGeneration || run?.id !== runId) return;
    job = result.id;
    drawer(true);
    await loadComparison();
  });

addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !$("sandbox-panel").hidden)
    $("sandbox-dismiss").click();
});

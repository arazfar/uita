"use strict";
const BASE = "/candidates/data/arena/";
const NS = "http://www.w3.org/2000/svg";
const $ = (id) => document.getElementById(id);
const state = { lb: null, agent: null, task: null, rollout: null, step: 0, req: 0 };
const safe = (s) => String(s).replace(/[^A-Za-z0-9._-]/g, "_");
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const f3 = (x) => (x == null || Number.isNaN(+x) ? "n/a" : (+x).toFixed(3));
const mean = (a) => (a.length ? a.reduce((s, x) => s + x, 0) / a.length : null);
const clock = (epoch) => new Intl.DateTimeFormat("en-GB", { timeZone: "America/Los_Angeles", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(epoch * 1000));
const dur = (s) => (s == null ? "n/a" : `${Math.round(s)} s`);

async function getJSON(path) {
  const r = await fetch(BASE + path, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} for ${BASE + path}`);
  return r.json();
}
function el(tag, attrs = {}, text) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text != null) e.textContent = text;
  return e;
}
function svg(tag, attrs = {}, text) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text != null) e.textContent = text;
  return e;
}
function showMsg(text, info) {
  const m = $("msg");
  m.hidden = !text;
  m.textContent = text || "";
  m.className = "msg" + (info ? " info" : "");
}

/* ---------- header / leaderboard / matrix ---------- */
function renderHeader() {
  const lb = state.lb;
  const meta = $("meta");
  meta.textContent = "";
  for (const [k, v] of [["Env", lb.environment], ["Split", lb.split], ["Reference", lb.reference], ["Generated", lb.generated_at]]) {
    const wrap = el("div");
    wrap.append(el("dt", {}, k), el("dd", {}, v ?? "n/a"));
    meta.append(wrap);
  }
  $("formula").textContent = lb.reward_formula || "not provided";
}
const taskIds = () => [...new Set(state.lb.agents.flatMap((a) => a.tasks.map((t) => t.task_id)))];
const taskRow = (agent, id) => agent.tasks.find((t) => t.task_id === id);

function renderLeaderboard() {
  const tb = document.querySelector("#leaderboard tbody");
  tb.textContent = "";
  const total = taskIds().length;
  [...state.lb.agents].sort((a, b) => b.mean_reward - a.mean_reward).forEach((a, i) => {
    const tr = el("tr");
    if (a.agent === state.agent) tr.className = "sel";
    const gap = mean(a.tasks.map((t) => t.gap).filter((g) => g != null));
    const rej = a.tasks.reduce((s, t) => s + (t.rejected_plans || 0), 0);
    tr.innerHTML = `<td class="num">${i + 1}</td><td></td><td><span class="kind ${esc(a.kind)}">${esc(a.kind)}</span></td>
      <td><div class="bar-cell"><div class="bar-track"><div class="bar-fill" style="width:${Math.max(0, Math.min(1, a.mean_reward)) * 100}%"></div></div><span class="bar-val">${f3(a.mean_reward)}</span></div></td>
      <td class="num">${a.safety_eligible_tasks}/${total}</td><td class="num">${f3(gap)}</td><td class="num">${rej}</td>`;
    const b = el("button", { type: "button", class: "agent-btn", "aria-pressed": a.agent === state.agent }, a.label);
    b.onclick = () => selectAgent(a.agent);
    tr.children[1].append(b);
    tb.append(tr);
  });
}
function renderMatrix() {
  const ids = taskIds();
  const head = document.querySelector("#matrix thead");
  head.textContent = "";
  const hr = el("tr");
  hr.append(el("th", { scope: "col" }, "Agent"));
  for (const id of ids) {
    const any = state.lb.agents.flatMap((a) => a.tasks).find((t) => t.task_id === id);
    hr.append(el("th", { scope: "col", title: id }, any?.local_date || id));
  }
  head.append(hr);
  const body = document.querySelector("#matrix tbody");
  body.textContent = "";
  for (const a of state.lb.agents) {
    const tr = el("tr");
    if (a.agent === state.agent) tr.className = "sel";
    tr.append(el("th", { scope: "row", class: "rowh" }, a.label));
    for (const id of ids) {
      const t = taskRow(a, id);
      const td = el("td");
      if (!t) {
        td.append(el("span", { class: "cell missing", title: "no result" }, "n/a"));
      } else {
        const b = el("button", { type: "button", class: "cell", style: `--v:${Math.max(0, Math.min(1, t.reward))}`, "aria-pressed": a.agent === state.agent && id === state.task, "aria-label": `${a.label}, ${t.local_date || id}, reward ${f3(t.reward)}${t.safety_eligible ? "" : ", not safety eligible"}` });
        b.textContent = f3(t.reward);
        if (!t.safety_eligible) b.append(el("span", { class: "warn-mark", "aria-hidden": "true" }, "!"));
        b.onclick = () => select(a.agent, id);
        td.append(b);
      }
      tr.append(td);
    }
    body.append(tr);
  }
}

/* ---------- selection ---------- */
function selectAgent(agent) {
  const a = state.lb.agents.find((x) => x.agent === agent);
  const keep = a.tasks.some((t) => t.task_id === state.task) ? state.task : a.tasks[0]?.task_id;
  select(agent, keep);
}
function select(agent, task) {
  state.agent = agent;
  state.task = task;
  history.replaceState(null, "", `#${encodeURIComponent(agent)}/${encodeURIComponent(task ?? "")}`);
  renderLeaderboard();
  renderMatrix();
  loadRollout();
}
async function loadRollout() {
  const my = ++state.req;
  const a = state.lb.agents.find((x) => x.agent === state.agent);
  $("rv-id").textContent = `${a?.label ?? state.agent} / ${state.task ?? "no task"}`;
  state.rollout = null;
  $("timeline-wrap").hidden = false;
  if (!state.task) return clearViewer("This agent has no tasks in leaderboard.json.");
  const path = `rollouts/${encodeURIComponent(safe(state.agent))}/${encodeURIComponent(safe(state.task))}.json`;
  try {
    const r = await getJSON(path);
    if (my !== state.req) return;
    state.rollout = r;
    showMsg("");
    const n = r.steps?.length || 0;
    const s = $("scrub");
    s.max = Math.max(0, n - 1);
    state.step = 0;
    s.value = 0;
    renderStats();
    renderTimeline();
    renderStep();
  } catch (e) {
    if (my !== state.req) return;
    clearViewer(`Rollout not available: ${e.message}`);
  }
}
function clearViewer(text) {
  $("stats").textContent = "";
  $("axis").textContent = "";
  $("rows").textContent = "";
  $("inspector").textContent = "";
  $("step-readout").textContent = "-";
  $("scrub").max = 0;
  $("prev").disabled = $("next").disabled = true;
  showMsg(text);
}

/* ---------- viewer ---------- */
function renderStats() {
  const r = state.rollout;
  const a = state.lb.agents.find((x) => x.agent === state.agent);
  const row = a && taskRow(a, state.task);
  const done = r.aircraft.filter((x) => x.completed).length;
  const pen = row?.penalized_added_delay_seconds;
  const ref = row?.reference_penalized_added_delay_seconds;
  const rej = row?.rejected_plans ?? r.steps.filter((s) => s.status !== "pass").length;
  const items = [
    ["Reward", f3(r.reward), "0-1, vs reference"],
    ["Completed", `${row?.completed ?? done}/${row?.spawned ?? r.aircraft.length}`, "landed / spawned"],
    ["Backlog", row?.backlog ?? r.aircraft.length - done, "unfinished at horizon"],
    ["Penalized delay", pen == null ? "n/a" : `${Math.round(pen)} s`, ref == null ? "reference n/a" : `reference ${Math.round(ref)} s`],
    ["Rejected plans", rej, `of ${row?.decisions ?? r.steps.length} decisions`],
  ];
  const box = $("stats");
  box.textContent = "";
  for (const [k, v, sub] of items) {
    const d = el("div", { class: "stat" });
    d.append(el("b", {}, k), el("span", {}, String(v)), document.createElement("br"), el("small", {}, sub));
    box.append(d);
  }
}

const W = 1000, LBL = 150, PADR = 24, ROW = 20;
function renderTimeline() {
  const r = state.rollout;
  const H = r.horizon_seconds || 1;
  const x = (s) => LBL + (Math.max(0, Math.min(H, s)) / H) * (W - LBL - PADR);
  const t0 = r.window?.warmup_start_epoch;
  const acs = [...r.aircraft].sort((a, b) => a.nominal_landing_seconds - b.nominal_landing_seconds);
  state.layout = { x, acs, H };
  // axis
  const stepS = H > 7200 ? 1800 : H > 2400 ? 600 : 300;
  const ax = svg("svg", { viewBox: `0 0 ${W} 28`, role: "img", "aria-label": "Time axis" });
  for (let s = 0; s <= H; s += stepS) {
    ax.append(svg("line", { x1: x(s), x2: x(s), y1: 18, y2: 28, stroke: "var(--atc-rule-strong)" }));
    ax.append(svg("text", { x: x(s), y: 13, "text-anchor": "middle" }, t0 != null ? clock(t0 + s) : `${s}s`));
  }
  $("axis").textContent = "";
  $("axis").append(ax);
  // rows
  const h = acs.length * ROW + 4;
  const g = svg("svg", { viewBox: `0 0 ${W} ${h}`, role: "img", "aria-label": `${acs.length} aircraft, nominal vs agent vs reference landing times` });
  const bands = svg("g");
  const grid = svg("g");
  for (let s = 0; s <= H; s += stepS) grid.append(svg("line", { x1: x(s), x2: x(s), y1: 0, y2: h, stroke: "var(--atc-rule)", "stroke-width": 1 }));
  g.append(grid, bands);
  state.bands = {};
  acs.forEach((a, i) => {
    const y = i * ROW + 2, cy = y + ROW / 2;
    const band = svg("rect", { x: 0, y, width: W, height: ROW, fill: "var(--atc-selection)", opacity: 0 });
    bands.append(band);
    state.bands[a.id] = band;
    const heavy = /heavy/i.test(a.wake);
    const syn = /synth/i.test(a.position_provenance || "");
    const row = svg("g");
    row.append(svg("title", {}, `${a.id} ${a.type} wake ${a.wake}; nominal ${t0 != null ? clock(t0 + a.nominal_landing_seconds) : a.nominal_landing_seconds}; ` +
      `agent ${a.landing_seconds == null ? "unfinished" : (t0 != null ? clock(t0 + a.landing_seconds) : a.landing_seconds)}; ` +
      `reference ${a.reference_landing_seconds == null ? "n/a" : (t0 != null ? clock(t0 + a.reference_landing_seconds) : a.reference_landing_seconds)}; ` +
      `added delay ${dur(a.added_delay_seconds)}; position ${a.position_provenance || "unknown"}`));
    row.append(svg("text", { x: 6, y: cy + 4, fill: "var(--atc-text)", style: "fill:var(--atc-text)" }, `${a.id}`));
    row.append(svg("text", { x: 76, y: cy + 4 }, a.type));
    if (heavy) {
      row.append(svg("rect", { x: 118, y: cy - 7, width: 14, height: 14, fill: "none", stroke: "var(--atc-orange)" }));
      row.append(svg("text", { x: 125, y: cy + 4, "text-anchor": "middle", style: "fill:var(--atc-orange)" }, "H"));
    } else row.append(svg("text", { x: 125, y: cy + 4, "text-anchor": "middle" }, (a.wake || "?")[0].toUpperCase()));
    if (syn) row.append(svg("text", { x: 138, y: cy + 4, style: "fill:var(--atc-amber)", "font-size": 9 }, "SYN"));
    const nx = x(a.nominal_landing_seconds);
    if (a.landing_seconds != null) {
      const lx = x(a.landing_seconds);
      const late = a.landing_seconds > a.nominal_landing_seconds;
      row.append(svg("line", { x1: nx, x2: lx, y1: cy, y2: cy, stroke: late ? "var(--atc-amber)" : "var(--atc-green)", "stroke-width": 3 }));
      row.append(svg("line", { x1: lx, x2: lx, y1: cy - 5, y2: cy + 5, stroke: late ? "var(--atc-amber)" : "var(--atc-green)", "stroke-width": 2 }));
      if (a.added_delay_seconds > 0) row.append(svg("text", { x: lx + 6, y: cy + 4 }, `+${Math.round(a.added_delay_seconds)}s`));
    } else {
      const ex = x(H);
      row.append(svg("line", { x1: nx, x2: ex, y1: cy, y2: cy, stroke: "var(--atc-red)", "stroke-width": 2, "stroke-dasharray": "4 3" }));
      row.append(svg("line", { x1: ex, x2: ex, y1: cy - 6, y2: cy + 6, stroke: "var(--atc-red)", "stroke-width": 3 }));
      row.append(svg("text", { x: ex - 6, y: cy - 6, "text-anchor": "end", style: "fill:var(--atc-red)", "font-size": 9 }, "▲ unfinished"));
    }
    row.append(svg("rect", { x: nx - 3, y: cy - 3, width: 6, height: 6, fill: "var(--atc-text)" }));
    if (a.reference_landing_seconds != null) {
      const rx = x(a.reference_landing_seconds);
      row.append(svg("path", { d: `M${rx} ${cy - 5}L${rx + 5} ${cy}L${rx} ${cy + 5}L${rx - 5} ${cy}Z`, fill: "none", stroke: "var(--atc-cyan)", "stroke-width": 1.5 }));
    }
    g.append(row);
  });
  // decision lines
  const dl = svg("g");
  state.decLines = r.steps.map((s) => {
    const l = svg("line", { x1: x(s.clock_seconds), x2: x(s.clock_seconds), y1: 0, y2: h, stroke: "var(--atc-vector)", "stroke-width": 1, "stroke-dasharray": "2 4", opacity: 0.55 });
    dl.append(l);
    return l;
  });
  g.append(dl);
  $("rows").textContent = "";
  $("rows").append(g);
}

function renderStep() {
  const r = state.rollout;
  if (!r) return;
  const n = r.steps.length;
  const insp = $("inspector");
  insp.textContent = "";
  $("prev").disabled = state.step <= 0;
  $("next").disabled = state.step >= n - 1;
  if (!n) {
    $("step-readout").textContent = "no decisions";
    insp.append(el("p", {}, "This rollout recorded no decision steps."));
    return;
  }
  const s = r.steps[state.step];
  const t0 = r.window?.warmup_start_epoch;
  const clk = t0 != null ? clock(t0 + s.clock_seconds) : `${s.clock_seconds}s`;
  $("step-readout").textContent = `${state.step + 1}/${n} ${clk}`;
  const pend = new Set(s.pending || []);
  for (const [id, band] of Object.entries(state.bands)) band.setAttribute("opacity", pend.has(id) ? 1 : 0);
  state.decLines.forEach((l, i) => {
    const cur = i === state.step;
    l.setAttribute("opacity", cur ? 1 : 0.4);
    l.setAttribute("stroke-width", cur ? 2 : 1);
    l.setAttribute("stroke-dasharray", cur ? "" : "2 4");
  });
  const sec = (title, html) => {
    const d = el("section");
    d.append(el("h3", {}, title));
    const b = el("div");
    b.innerHTML = html;
    d.append(b);
    insp.append(d);
  };
  const mark = s.status === "pass" ? "✓ " : "▲ ";
  sec("Decision", `<code>${esc(clk)}</code> local, t=${esc(s.clock_seconds)} s from warmup start<br>Status <span class="st ${esc(s.status)}">${mark}${esc(s.status)}</span><br>Fallback: <code>${esc(s.fallback ?? "none")}</code>`);
  sec(`Pending aircraft (${pend.size})`, pend.size ? `<div class="ids">${[...pend].map((i) => `<span>${esc(i)}</span>`).join("")}</div>` : "none");
  sec(`Tool calls (${(s.tool_calls || []).length})`, (s.tool_calls || []).length
    ? `<ol>${s.tool_calls.map((c) => `<li><code>${esc(c.tool)}</code> <span class="st ${c.status === "ok" || c.status === "pass" ? "pass" : "rejected"}">${esc(c.status)}</span><br><small>${esc((c.order || []).join(", "))}</small></li>`).join("")}</ol>`
    : "none");
  sec("Submitted order", (s.submitted_order || []).length ? `<ol>${s.submitted_order.map((i) => `<li><code>${esc(i)}</code></li>`).join("")}</ol>` : "none");
  sec("Slots", (s.slots || []).length
    ? `<table><thead><tr><th>Aircraft</th><th>Rwy</th><th class="num">Time</th></tr></thead><tbody>${s.slots.map((x) => `<tr><td>${esc(x.aircraft_id)}</td><td>${esc(x.runway)}</td><td class="num">${t0 != null ? esc(clock(t0 + x.time)) : esc(x.time)}</td></tr>`).join("")}</tbody></table>`
    : "none");
}
function setStep(i) {
  if (!state.rollout) return;
  state.step = Math.max(0, Math.min(state.rollout.steps.length - 1, i));
  $("scrub").value = state.step;
  renderStep();
}

/* ---------- init ---------- */
$("scrub").addEventListener("input", (e) => setStep(+e.target.value));
$("prev").onclick = () => setStep(state.step - 1);
$("next").onclick = () => setStep(state.step + 1);
(async function init() {
  try {
    state.lb = await getJSON("leaderboard.json");
  } catch (e) {
    $("formula").textContent = "unavailable";
    clearViewer(`Leaderboard not available: ${e.message}. Run the SFOArrivalEnv evaluation to write leaderboard.json.`);
    return;
  }
  if (!state.lb.agents?.length) {
    renderHeader();
    return clearViewer("leaderboard.json contains no agents.");
  }
  renderHeader();
  const [ha, ht] = location.hash.slice(1).split("/").map(decodeURIComponent);
  const best = [...state.lb.agents].sort((a, b) => b.mean_reward - a.mean_reward)[0];
  const ag = state.lb.agents.find((a) => a.agent === ha) || best;
  state.agent = ag.agent;
  state.task = ag.tasks.some((t) => t.task_id === ht) ? ht : ag.tasks[0]?.task_id;
  select(state.agent, state.task);
})();

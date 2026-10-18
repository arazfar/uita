// Agent-controlled SFO arrivals: recorded ADS-B arrivals are re-spawned as simulated aircraft at
// 25 NM; an LLM agent (POST /api/sequence) proposes landing slots and holds, and a deterministic
// kernel accepts or vetoes every decision. Agent OFF = kernel first-come-first-served.
const SFO = [-122.375, 37.619];
const GATE_M = 46300; // 25 NM
const V_APP = 80, V_DIRECT = 120, V_HOLD = 100; // m/s
const HEAVY_RE = /^(B77|B74|A35|B78|A38|A34|B76|MD11)/;
// Published SFO arrival fixes; coordinates are approximate and labelled as such.
const FIXES = { MENLO: [-122.153, 37.464], DUMBA: [-122.096, 37.503], ARCHI: [-121.985, 37.425], BDEGA: [-122.62, 37.9] };
const HOLD_LEG = 6000, HOLD_R = 2500, HOLD_BASE_FT = 6000, HOLD_STEP_FT = 1000;
const TEL = { UAL: 'United', SWA: 'Southwest', ASA: 'Alaska', DAL: 'Delta', AAL: 'American', SKW: 'SkyWest', JBU: 'JetBlue', FFT: 'Frontier', NKS: 'Spirit', HAL: 'Hawaiian', ACA: 'Air Canada', BAW: 'Speedbird', DLH: 'Lufthansa', AFR: 'Air France', KLM: 'KLM', UAE: 'Emirates', CPA: 'Cathay', EVA: 'Eva', JAL: 'Japan Air', ANA: 'All Nippon', KAL: 'Korean Air', QFA: 'Qantas', FDX: 'FedEx', UPS: 'UPS', AMX: 'Aeromexico', VOI: 'Volaris', JSX: 'JetSuite', ASH: 'Air Shuttle', RPA: 'Brickyard', ENY: 'Envoy' };
const esc = x => String(x ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const DIG = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine'];

export function mountLanding(ctx) {
  const { C, viewer, scene } = ctx;
  const mLon = ctx.mPerLon, mLat = ctx.mPerLat;
  const dist = (a, b) => Math.hypot((a[0] - b[0]) * mLon, (a[1] - b[1]) * mLat);
  const off = (p, e, n) => [p[0] + e / mLon, p[1] + n / mLat];
  const bearing = (a, b) => (Math.atan2((b[0] - a[0]) * mLon, (b[1] - a[1]) * mLat) * 180 / Math.PI + 360) % 360;
  const spoken = cs => { const m = /^([A-Z]{3})(\d+)/.exec(cs || ''); return m && TEL[m[1]] ? `${TEL[m[1]]} ${[...m[2]].map(d => DIG[d]).join(' ')}` : [...(cs || '')].join(' '); };
  const fmtT = t => ctx.fmtTime(t);
  const fmtD = s => `${Math.floor(Math.max(0, s) / 60)}:${String(Math.round(Math.max(0, s) % 60)).padStart(2, '0')}`;

  // ---------- geometry ----------
  function thr(rwy) { return ctx.rwyGeo(rwy); }
  const alongRwy = (rwy, s) => { const g = thr(rwy); return [g.a[0] + g.ux * s / mLon, g.a[1] + g.uy * s / mLat]; };
  const FAF = rwy => alongRwy(rwy, -18500); // ~10 NM final at 3,000 ft
  const fixCourse = f => bearing(FIXES[f], SFO); // inbound leg points at SFO
  function holdPos(fix, s) { // racetrack: inbound leg ends at the fix, right turns
    const c = fixCourse(fix) * Math.PI / 180, fe = Math.sin(c), fn = Math.cos(c), re = Math.cos(c), rn = -Math.sin(c);
    const P = 2 * HOLD_LEG + 2 * Math.PI * HOLD_R; s = ((s % P) + P) % P;
    let x, y;
    if (s < HOLD_LEG) { x = -HOLD_LEG + s; y = 0; }
    else if ((s -= HOLD_LEG) < Math.PI * HOLD_R) { const th = -Math.PI / 2 + s / HOLD_R; x = HOLD_R * Math.cos(th); y = HOLD_R + HOLD_R * Math.sin(th); }
    else if ((s -= Math.PI * HOLD_R) < HOLD_LEG) { x = -s; y = 2 * HOLD_R; }
    else { s -= HOLD_LEG; const th = Math.PI / 2 + s / HOLD_R; x = -HOLD_LEG + HOLD_R * Math.cos(th); y = HOLD_R + HOLD_R * Math.sin(th); }
    return off(FIXES[fix], x * fe + y * re, x * fn + y * rn);
  }
  const nearestFix = p => Object.keys(FIXES).sort((a, b) => dist(p, FIXES[a]) - dist(p, FIXES[b]))[0];

  // fix markers + racetracks
  for (const f of Object.keys(FIXES)) {
    const ring = []; for (let s = 0; s <= 2 * HOLD_LEG + 2 * Math.PI * HOLD_R + 1; s += 600) { const p = holdPos(f, s); ring.push(C.Cartesian3.fromDegrees(p[0], p[1], ctx.height(HOLD_BASE_FT))); }
    viewer.entities.add({ polyline: { positions: ring, width: 1.5, material: C.Color.fromCssColorString('#ffb547').withAlpha(0.45), arcType: C.ArcType.NONE } });
    viewer.entities.add({ position: C.Cartesian3.fromDegrees(FIXES[f][0], FIXES[f][1], ctx.height(HOLD_BASE_FT)),
      point: { pixelSize: 6, color: C.Color.fromCssColorString('#ffb547'), disableDepthTestDistance: Number.POSITIVE_INFINITY },
      label: ctx.label(`${f} · hold (approx)`, { font: '600 10.5px Inter,-apple-system,sans-serif', fillColor: C.Color.fromCssColorString('#ffd38a'), pixelOffset: new C.Cartesian2(0, -16) }) });
  }

  // ---------- state ----------
  const S = { arr: new Map(), mode: 'agent', closure: null, startT: null, lastT: null, lastScan: null, lastCall: -1e9, lastCallWall: 0, inflight: false,
    landed: 0, delaySum: 0, log: [], agentInfo: 'agent idle', seq: 0, autoDisrupted: false, prevRows: new Map(), flagged: { MEDICAL: false, LOW_FUEL: false } };

  function posOf(a, T) {
    const L = a.leg;
    if (L.type === 'direct') { const D = dist(L.from, L.to), k = Math.min(1, (T - L.t0) * L.v / Math.max(1, D)); return { ll: [L.from[0] + (L.to[0] - L.from[0]) * k, L.from[1] + (L.to[1] - L.from[1]) * k], ft: L.ft0 + (L.ft1 - L.ft0) * k }; }
    if (L.type === 'hold') return { ll: holdPos(L.fix, HOLD_LEG + (T - L.t0) * V_HOLD), ft: HOLD_BASE_FT + L.level * HOLD_STEP_FT };
    if (L.type === 'final') {
      let d = (T - L.t0) * L.v;
      for (let i = 1; i < L.pts.length; i++) {
        const seg = dist(L.pts[i - 1], L.pts[i]);
        if (d <= seg || i === L.pts.length - 1) { const k = Math.min(1, d / Math.max(1, seg)); return { ll: [L.pts[i - 1][0] + (L.pts[i][0] - L.pts[i - 1][0]) * k, L.pts[i - 1][1] + (L.pts[i][1] - L.pts[i - 1][1]) * k], ft: L.fts[i - 1] + (L.fts[i] - L.fts[i - 1]) * k }; }
        d -= seg;
      }
    }
    if (L.type === 'roll') { const e = Math.min(35, T - L.t0); return { ll: alongRwy(a.slot.rwy, 300 + V_APP * e - 1.1 * e * e), ft: 0, gnd: true }; }
    return { ll: L.ll || SFO, ft: L.ft || 0 };
  }
  const finalLen = (a, T, rwy) => { const p = posOf(a, T).ll; return dist(p, FAF(rwy)) + dist(FAF(rwy), alongRwy(rwy, 300)); };
  const minSlot = (a, T, rwy = '28R') => T + finalLen(a, T, rwy) / 110; // fastest legal arrival
  const holdLevel = fix => { const used = new Set([...S.arr.values()].filter(a => a.leg.type === 'hold' && a.leg.fix === fix).map(a => a.leg.level)); let l = 0; while (used.has(l)) l++; return l; };
  function sendToHold(a, T, fix) {
    fix = FIXES[fix] ? fix : nearestFix(posOf(a, T).ll);
    if ((a.leg.type === 'hold' || a.leg.type === 'direct') && a.holdFix === fix) return;
    const p = posOf(a, T); a.holdFix = fix;
    a.leg = { type: 'direct', from: p.ll, to: FIXES[fix], t0: T, v: V_DIRECT, ft0: p.ft, ft1: HOLD_BASE_FT + holdLevel(fix) * HOLD_STEP_FT };
  }

  // ---------- kernel ----------
  const gapAfter = lead => (lead.wake === 'heavy' ? 120 : 90);
  function slotProblem(a, rwy, t, T) {
    if (!['28L', '28R'].includes(rwy)) return `unknown runway ${rwy}`;
    if (S.closure && S.closure.rwy === rwy && t >= S.closure.t0 && t <= S.closure.t1) return `${rwy} closed until ${fmtT(S.closure.t1)}`;
    const ms = minSlot(a, T, rwy);
    if (t < ms - 5) return `cannot make ${fmtT(t)} (earliest ${fmtT(ms)})`;
    for (const o of S.arr.values()) {
      if (o === a || !o.slot || o.slot.rwy !== rwy || o.done) continue;
      if (Math.abs(o.slot.t - t) < 1) return `double booking with ${o.cs}`;
      const need = o.slot.t <= t ? gapAfter(o) : gapAfter(a);
      if (Math.abs(o.slot.t - t) < need) return `${Math.round(Math.abs(o.slot.t - t))} s from ${o.cs} (needs ${need} s${need === 120 ? ', wake' : ''})`;
    }
    return null;
  }
  function earliestLegal(a, T, from) {
    let best = null;
    for (const rwy of ['28R', '28L']) {
      for (let t = Math.ceil(Math.max(from || 0, minSlot(a, T, rwy))); t < T + 7200; t += 5) if (!slotProblem(a, rwy, t, T)) { if (!best || t < best.t) best = { rwy, t }; break; }
    }
    return best;
  }
  const frozen = a => a.leg.type === 'final' || a.leg.type === 'roll' || (a.slot && a.slot.t - (S.lastT || 0) < 240); // within 4 min of its slot: no churn

  // ---------- spawning from recorded arrivals ----------
  function scan(T) {
    const win = ctx.window(T); if (!win) return;
    const from = S.lastScan ?? T - 1;
    for (const f of win.flights) {
      if (S.arr.has(f.id) || S.arr.size >= 16) continue;
      const pts = f.points; let hit = null;
      for (let i = 1; i < pts.length; i++) {
        const p = pts[i], q = pts[i - 1];
        if (p[6] === true || !Number.isFinite(p[3])) continue;
        const dp = dist([p[2], p[1]], SFO), dq = dist([q[2], q[1]], SFO);
        const crossing = dq > GATE_M && dp <= GATE_M && p[0] > from && p[0] <= T;
        const inside = S.lastScan == null && p[0] <= T && (pts[i + 1]?.[0] ?? 1e12) > T && dp < GATE_M && dp > 15000;
        if (!crossing && !inside) continue;
        const toward = Math.abs(((bearing([p[2], p[1]], SFO) - (p[5] ?? 0)) + 540) % 360 - 180) < 45;
        const desc = Number.isFinite(q[3]) && p[3] <= q[3] && p[3] < 15000 && p[3] > 2500;
        if (toward && desc) { hit = { p, dp }; break; }
      }
      if (!hit) continue;
      const p = hit.p, ll = [p[2], p[1]];
      const type = p[10] || f.type || 'A320', cs = String(p[8] || f.callsign || f.id).trim();
      const a = { id: f.id, cs, type, wake: HEAVY_RE.test(type) ? 'heavy' : 'medium', reg: p[9] || f.registration, tGate: T, eta: T + dist(ll, FAF('28R')) / 105 + 231,
        flag: null, slot: null, efc: null, holdFix: null, leg: { type: 'direct', from: ll, to: ll, t0: T, v: 1, ft0: p[3], ft1: p[3] }, last: null, verdict: null };
      if (!S.flagged.MEDICAL && S.arr.size >= 1) { a.flag = 'MEDICAL'; S.flagged.MEDICAL = true; }
      else if (!S.flagged.LOW_FUEL && S.arr.size >= 3) { a.flag = 'LOW_FUEL'; S.flagged.LOW_FUEL = true; }
      sendToHold(a, T, nearestFix(ll)); // safe default until sequenced
      makeEntity(a); S.arr.set(a.id, a); ctx.suppress(a.id, true);
      if (S.mode === 'fcfs') fcfs(T);
    }
    S.lastScan = T;
  }

  // ---------- rendering ----------
  function makeEntity(a) {
    const heavy = a.wake === 'heavy', uri = heavy ? 'assets/boeing747-mihalunar/model.glb' : 'assets/airplane-google/model.glb';
    const cart = () => { const p = a.cur; return p && C.Cartesian3.fromDegrees(p.ll[0], p.ll[1], p.gnd ? ctx.height(0, true) : ctx.height(p.ft)); };
    a.entity = viewer.entities.add({
      position: new C.CallbackProperty(cart, false),
      orientation: new C.CallbackProperty(() => { const p = cart(); return p && C.Transforms.headingPitchRollQuaternion(p, new C.HeadingPitchRoll(((a.hdg || 0) - 90 + (ctx.yawFix(uri))) * Math.PI / 180, 0, 0)); }, false),
      model: { uri, scale: heavy ? 46 : 0.4, minimumPixelSize: 30, maximumScale: 4000, silhouetteColor: C.Color.fromCssColorString('#ffb547'), silhouetteSize: new C.CallbackProperty(() => (a.leg.type === 'hold' ? 1.5 : 0), false) },
      label: ctx.label(new C.CallbackProperty(() => `${a.cs}${a.flag ? ' · ' + (a.flag === 'MEDICAL' ? 'MED' : 'FUEL') : ''}`, false), {
        fillColor: new C.CallbackProperty(() => C.Color.fromCssColorString(a.slot ? '#9ff0bf' : '#ffd38a'), false), pixelOffset: new C.Cartesian2(0, -26) }),
    });
    ctx.pick(a.entity, () => describe(a));
  }
  function describe(a) {
    const T = ctx.now(), p = a.cur || posOf(a, T), L = a.leg.type;
    const step = L === 'roll' ? 3 : L === 'final' ? 2 : L === 'hold' ? 1 : 0;
    return { cs: a.cs, type: a.type, op: 'SIM · seeded from ADS-B', status: L === 'roll' ? 'Landing roll' : L === 'final' ? 'Cleared to land' : L === 'hold' ? `Holding ${a.leg.fix}` : a.slot ? 'Cleared, inbound' : `To ${a.holdFix}`,
      route: a.slot ? `Runway ${a.slot.rwy} · slot ${fmtT(a.slot.t)}` : `Hold ${a.holdFix}${a.efc ? ' · EFC ' + fmtT(a.efc) : ''}`, alt: p.ft, spd: (a.spd || 0) * 1.944, hdg: a.hdg || 0,
      cell4: ['Delay', fmtD((a.slot ? a.slot.t : T) - a.eta)], steps: ['Descend', 'Hold', 'Approach', 'Land', 'Vacate'], step,
      clr: { txt: a.last || 'Awaiting sequence', check: a.verdict || (a.flag ? a.flag.replace('_', ' ') + ' priority' : 'kernel default hold'), bad: /VETO/.test(a.verdict || '') } };
  }

  // ---------- per-frame motion ----------
  scene.preRender.addEventListener(() => {
    const T = ctx.now(); if (!T) return;
    for (const a of S.arr.values()) {
      if (a.done) continue;
      const p = posOf(a, T), q = posOf(a, T + 2);
      a.cur = p; a.spd = dist(p.ll, q.ll) / 2;
      if (a.spd > 1) a.hdg = bearing(p.ll, q.ll);
    }
  });

  // ---------- slow tick: transitions, spawning, sequencing ----------
  function tick() {
    const T = ctx.now(); if (!T || !ctx.ready()) return;
    if (S.lastT != null && T < S.lastT - 30) reset(); // recorded hour looped
    if (S.startT == null) S.startT = T;
    S.lastT = T;
    scan(T);
    if (!S.autoDisrupted && T - S.startT > 120) { S.autoDisrupted = true; disrupt(T); }
    if (S.closure && T > S.closure.t1 + 1) { logLine(`28L reopened`, 'acc'); S.closure = null; requestCycle(T, true); }
    for (const a of S.arr.values()) {
      if (a.done) continue;
      const L = a.leg;
      if (L.type === 'direct' && (T - L.t0) * L.v >= dist(L.from, L.to)) a.leg = { type: 'hold', fix: a.holdFix, level: holdLevel(a.holdFix), t0: T };
      if (a.slot && !frozen(a)) { // leave the hold in time to make the slot
        const D = finalLen(a, T, a.slot.rwy), need = D / V_APP;
        if (T >= a.slot.t - need - 3) {
          const p = posOf(a, T), faf = FAF(a.slot.rwy), th = alongRwy(a.slot.rwy, 300);
          a.leg = { type: 'final', pts: [p.ll, faf, th], fts: [p.ft, 3000, 50], t0: T, v: Math.max(60, Math.min(130, D / Math.max(20, a.slot.t - T))) };
          if (!a.spoke) { a.spoke = true; say(`${spoken(a.cs)}, runway two eight ${a.slot.rwy === '28R' ? 'right' : 'left'}, cleared to land.`, a.cs); }
        }
      }
      if (L.type === 'final' && (T - L.t0) * L.v >= dist(L.pts[0], L.pts[1]) + dist(L.pts[1], L.pts[2])) {
        a.leg = { type: 'roll', t0: T }; S.landed++; S.delaySum += Math.max(0, T - a.eta);
      }
      if (L.type === 'roll' && T - L.t0 > 40) { a.done = true; a.entity.show = false; ctx.suppress(a.id, false); }
    }
    if (S.mode === 'fcfs') fcfs(T);
    else if (T - S.lastCall > 90) requestCycle(T);
    render(T);
  }
  setInterval(tick, 250);

  function reset() {
    for (const a of S.arr.values()) { viewer.entities.remove(a.entity); ctx.suppress(a.id, false); }
    Object.assign(S, { arr: new Map(), closure: null, startT: null, lastScan: null, lastCall: -1e9, landed: 0, delaySum: 0, autoDisrupted: false, flagged: { MEDICAL: false, LOW_FUEL: false }, prevRows: new Map() });
  }

  function disrupt(T = ctx.now()) {
    S.closure = { rwy: '28L', t0: T, t1: T + 600 };
    logLine(`28L closed for 10 min · single runway`, 'rej');
    for (const a of S.arr.values()) if (a.slot && a.slot.rwy === '28L' && !frozen(a) && a.slot.t <= S.closure.t1) {
      a.slot = null; a.verdict = 'kernel: 28L closed, slot revoked'; sendToHold(a, T, a.holdFix);
    }
    if (S.mode === 'fcfs') fcfs(T); else requestCycle(T, true);
  }

  // Agent OFF: kernel first-come-first-served by ETA, no priorities.
  function fcfs(T) {
    const q = [...S.arr.values()].filter(a => !a.done && !a.slot).sort((x, y) => x.eta - y.eta);
    for (const a of q) {
      const s = earliestLegal(a, T, a.eta);
      if (s) { a.slot = s; a.efc = null; a.last = `FCFS · ${s.rwy} ${fmtT(s.t)}`; a.verdict = 'kernel FCFS'; }
    }
  }

  // Agent ON: real LLM call, then kernel validation of every decision.
  async function requestCycle(T, urgent) {
    if (S.mode !== 'agent' || S.inflight) return;
    if (!urgent && performance.now() - S.lastCallWall < 6000) return;
    const live = [...S.arr.values()].filter(a => !a.done && a.leg.type !== 'roll');
    S.lastCall = T; S.lastCallWall = performance.now();
    if (!live.some(a => !frozen(a))) return;
    // min_slot_s carries a margin for the agent's own latency (sim time keeps running while it thinks)
    const margin = Math.round(Math.min(120, 8 * ctx.speed()));
    const queue = live.map(a => ({ id: a.id, callsign: a.cs, type: a.type, wake: a.wake, flag: a.flag, frozen: frozen(a), ...(a.slot ? { runway: a.slot.rwy, slot_s: Math.round(a.slot.t - T) } : {}),
      eta_s: Math.round(a.eta - T), min_slot_s: Math.round(minSlot(a, T) - T) + margin, suggested_fix: a.holdFix || nearestFix(posOf(a, T).ll),
      status: frozen(a) ? `on final ${a.slot.rwy} slot ${Math.round(a.slot.t - T)} s` : a.slot ? `cleared ${a.slot.rwy} slot ${Math.round(a.slot.t - T)} s` : a.leg.type === 'hold' ? `holding ${a.leg.fix}` : 'inbound' }));
    const runways = ['28L', '28R'].map(id => ({ id, open: !(S.closure && S.closure.rwy === id), ...(S.closure && S.closure.rwy === id ? { closed_for_s: Math.round(S.closure.t1 - T) } : {}) }));
    S.inflight = true; S.agentInfo = 'agent thinking…'; render(T);
    let res;
    try { const r = await fetch('/api/sequence', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ queue, runways, now: fmtT(T) + ' PDT' }) }); res = await r.json(); if (!r.ok) throw new Error(res.error || r.status); }
    catch (e) { S.inflight = false; S.agentInfo = `agent unavailable (${String(e.message || e).slice(0, 40)}) → kernel FCFS`; fcfs(ctx.now()); render(ctx.now()); return; }
    S.inflight = false;
    const Tn = ctx.now(), seq = ++S.seq;
    S.agentInfo = `${res.provider} · ${String(res.model).split('/').pop()} · ${(res.ms / 1000).toFixed(1)} s${res.fallbacks?.length ? ' (fallback)' : ''}`;
    let spokeHold = false;
    for (const d of res.decisions || []) {
      const a = S.arr.get(d.args.id); if (!a || a.done || frozen(a)) continue;
      const why = String(d.args.reason || '').slice(0, 80);
      if (d.name === 'clear_to_land') {
        const t = T + Number(d.args.slot_time), prob = Number.isFinite(t) ? slotProblem(a, d.args.runway, t, T) : 'no slot time'; // feasibility judged at request time
        if (!prob) { a.slot = { rwy: d.args.runway, t }; a.efc = null; a.verdict = 'kernel ACCEPT'; a.last = `${d.args.runway} ${fmtT(t)} · ${why}`; logLine(`${a.cs} → ${d.args.runway} ${fmtT(t)} · ${why}`, 'acc', 'ACCEPT'); }
        else {
          a.slot = null; sendToHold(a, Tn, a.holdFix); const e = earliestLegal(a, Tn); a.efc = e ? e.t : null;
          a.verdict = `kernel VETO · ${prob}`; a.last = `${d.args.runway} ${fmtT(t)} · ${why}`;
          logLine(`${a.cs} ${d.args.runway} ${fmtT(t)} vetoed: ${prob} → hold ${a.holdFix}`, 'rej', 'VETO');
        }
      } else if (d.name === 'hold') {
        a.slot = null; sendToHold(a, Tn, d.args.fix); a.efc = Tn + 60 * Math.max(1, Math.min(20, Number(d.args.minutes) || 3));
        a.verdict = 'kernel ACCEPT (hold is always safe)'; a.last = `hold ${a.holdFix} ${d.args.minutes} min · ${why}`;
        logLine(`${a.cs} holds ${a.holdFix} ${d.args.minutes} min · ${why}`, 'acc', 'ACCEPT');
        if (!spokeHold) { spokeHold = true; const efc = fmtT(a.efc).slice(0, 5).replace(':', ''); say(`${spoken(a.cs)}, hold at ${a.holdFix} as published, expect further clearance ${[...efc].map(x => DIG[x]).join(' ')}.`, a.cs); }
      }
    }
    for (const a of S.arr.values()) if (!a.done && !a.slot && !frozen(a) && !(res.decisions || []).some(d => d.args.id === a.id)) a.verdict = 'no agent decision → kernel default hold';
    render(Tn, seq);
  }

  // ---------- radio ----------
  let spokenCount = 0;
  function say(text, cs) { if (spokenCount >= 3 || !window.SkyRadio) return; spokenCount++; window.SkyRadio.say(text, 'atc'); }

  // ---------- panel ----------
  const css = document.createElement('style');
  css.textContent = `#landp{position:absolute;right:14px;bottom:36px;width:330px;z-index:11;background:rgba(10,13,16,.78);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);border-radius:10px;font:12px/1.35 Inter,-apple-system,sans-serif;color:#eef1f3;overflow:hidden}
#landp .h{display:flex;align-items:center;gap:6px;padding:8px 10px 4px;font:600 10.5px/1 Inter,sans-serif;letter-spacing:.1em;text-transform:uppercase;color:#8e989f}
#landp .h .sp{flex:1}
#landp button{white-space:nowrap;font:600 10.5px/1 Inter,sans-serif;border:0;border-radius:999px;padding:5px 9px;cursor:pointer;background:rgba(255,255,255,.08);color:#eef1f3}
#landp button.on{background:#4fdc8a;color:#06240f}
#landp button.off{background:#ffb547;color:#1b1408}
#landp .st{display:flex;gap:12px;padding:2px 10px 6px;font:600 11px/1.2 ui-monospace,Menlo,monospace;color:#cfd6db}
#landp .st b{font-size:15px;color:#fff}
#landp .rw{padding:0 10px 6px;font:600 10.5px/1.2 ui-monospace,Menlo,monospace;color:#8e989f}
#landp .rw .x{color:#ff5a4f}
#landp ol{list-style:none;margin:0;padding:0 6px 6px;max-height:200px;overflow:hidden}
#landp li{display:grid;grid-template-columns:16px 1fr auto;gap:6px;align-items:center;padding:3px 4px;border-radius:5px;font:500 11.5px/1.25 ui-monospace,Menlo,monospace;transition:background .6s}
#landp li .n{color:#8e989f}
#landp li .w{color:#9ff0bf}
#landp li.hold .w{color:#ffd38a}
#landp li.fin .w{color:#5fd4ff}
#landp li.chg{background:rgba(255,181,71,.22)}
#landp .tag{font:700 9px/1 Inter,sans-serif;padding:2px 4px;border-radius:3px;margin-left:4px;background:#ff5a4f;color:#1b0b09}
#landp .tag.f{background:#ffb547;color:#1b1408}
#landp .ag{padding:6px 10px 8px;border-top:1px solid rgba(255,255,255,.08);font:11px/1.35 Inter,sans-serif;color:#c9d0d5}
#landp .ag i{font-style:normal;color:#5fd4ff;font:600 10px/1.3 ui-monospace,Menlo,monospace}
#landp .ag div{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#landp .ag .rej{color:#ffb3ad}
#landp .ag .k{font:700 9px/1 ui-monospace,Menlo,monospace;margin-right:4px;color:#4fdc8a}
#landp .ag .rej .k{color:#ff5a4f}
#feedp{max-height:calc(100% - 470px)!important}`;
  document.head.appendChild(css);
  const el = document.createElement('div'); el.id = 'landp';
  el.innerHTML = `<div class="h"><span>Landing sequence</span><span class="sp"></span><button id="lpDis" title="Disruption: close 28L for 10 minutes">Close 28L</button><button id="lpMode" class="on" title="Agent ON / first-come-first-served">Agent ON</button></div>
<div class="st"><span>Landed <b id="lpL">0</b></span><span>Holding <b id="lpH">0</b></span><span>Avg delay <b id="lpD">0:00</b></span></div>
<div class="rw" id="lpRw"></div><ol id="lpList"></ol><div class="ag"><i id="lpAI">agent idle</i><div id="lpLog"></div></div>`;
  document.body.appendChild(el);
  el.querySelector('#lpDis').onclick = () => { if (ctx.ready()) disrupt(); };
  el.querySelector('#lpMode').onclick = () => {
    const T = ctx.now(); S.mode = S.mode === 'agent' ? 'fcfs' : 'agent';
    const b = el.querySelector('#lpMode'); b.textContent = S.mode === 'agent' ? 'Agent ON' : 'Agent OFF · FCFS'; b.className = S.mode === 'agent' ? 'on' : 'off';
    for (const a of S.arr.values()) if (!a.done && !frozen(a)) { a.slot = null; a.efc = null; }
    logLine(S.mode === 'agent' ? 'Agent ON: LLM sequences, kernel verifies' : 'Agent OFF: kernel first-come-first-served', S.mode === 'agent' ? 'acc' : 'rej');
    if (S.mode === 'fcfs') fcfs(T); else requestCycle(T, true);
  };
  function logLine(txt, cls, k) { S.log.push({ txt: esc(txt), cls, k }); if (S.log.length > 4) S.log.shift(); }
  function render(T, seq) {
    const live = [...S.arr.values()].filter(a => !a.done);
    const holding = live.filter(a => !a.slot && a.leg.type !== 'roll').length;
    el.querySelector('#lpL').textContent = S.landed;
    el.querySelector('#lpH').textContent = holding;
    el.querySelector('#lpD').textContent = fmtD(S.landed ? S.delaySum / S.landed : 0);
    el.querySelector('#lpRw').innerHTML = !ctx.ready() ? 'waiting for recorded arrivals…' : S.closure ? `<span class="x">28L CLOSED until ${fmtT(S.closure.t1)}</span> · 28R open · 90 s / 120 s heavy` : '28L · 28R open · 90 s spacing · 120 s behind heavy';
    const rows = live.filter(a => a.leg.type !== 'roll').sort((x, y) => (x.slot ? x.slot.t : 1e12 + (x.efc || x.eta)) - (y.slot ? y.slot.t : 1e12 + (y.efc || y.eta)));
    const now = performance.now();
    el.querySelector('#lpList').innerHTML = rows.slice(0, 9).map((a, i) => {
      const w = a.slot ? `${a.slot.rwy} ${fmtT(a.slot.t)}` : `HOLD ${a.holdFix}${a.efc ? ' · EFC ' + fmtT(a.efc).slice(0, 5) : ''}`;
      const key = w.replace(/ · EFC.*/, '') + i;
      const prev = S.prevRows.get(a.id); if (prev && prev.key !== key) S.prevRows.set(a.id, { key, at: now }); else if (!prev) S.prevRows.set(a.id, { key, at: 0 });
      const chg = now - S.prevRows.get(a.id).at < 2500;
      const tag = a.flag ? `<span class="tag${a.flag === 'LOW_FUEL' ? ' f' : ''}">${a.flag === 'MEDICAL' ? 'MED' : 'FUEL'}</span>` : '';
      return `<li class="${a.slot ? (frozen(a) ? 'fin' : '') : 'hold'}${chg ? ' chg' : ''}"><span class="n">${i + 1}</span><span>${esc(a.cs)}${a.wake === 'heavy' ? ' H' : ''}${tag}</span><span class="w">${esc(w)}</span></li>`;
    }).join('') || '<li><span></span><span style="color:#8e989f">no arrivals inside 25 NM yet</span><span></span></li>';
    el.querySelector('#lpAI').textContent = `${S.mode === 'agent' ? 'AGENT' : 'KERNEL FCFS'} · ${S.mode === 'agent' ? S.agentInfo : 'no LLM'}`;
    el.querySelector('#lpLog').innerHTML = S.log.map(l => `<div class="${l.cls || ''}">${l.k ? `<span class="k">${l.k}</span>` : ''}${l.txt}</div>`).join('');
  }
  return { state: S, disrupt, requestCycle };
}

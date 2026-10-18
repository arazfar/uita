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
  const S = { qn: 0, arr: new Map(), mode: 'agent', closure: null, startT: null, lastT: null, lastScan: null, lastCall: -1e9, lastCallWall: 0, inflight: false,
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
      if (Math.abs(o.slot.t - t) < need - 2) return `${Math.round(Math.abs(o.slot.t - t))} s from ${o.cs} (needs ${need} s${need === 120 ? ', wake' : ''})`;
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
  // free for a medium arrival on rwy at t, judged only against slots already held (closures included)
  function freeAt(rwy, t) {
    if (S.closure && S.closure.rwy === rwy && t >= S.closure.t0 && t <= S.closure.t1) return false;
    for (const o of S.arr.values()) if (!o.done && o.slot && o.slot.rwy === rwy && frozen(o) && Math.abs(o.slot.t - t) < (o.slot.t <= t ? gapAfter(o) : 90) - 2) return false;
    return true;
  }
  // MEDICAL then LOW FUEL must hold the earliest legal slots; if the agent's plan does not, the kernel re-orders.
  function enforcePriority(T) {
    let note = '';
    const pri = [...S.arr.values()].filter(a => !a.done && !frozen(a) && a.flag).sort((x, y) => (x.flag === 'MEDICAL' ? 0 : 1) - (y.flag === 'MEDICAL' ? 0 : 1));
    for (const p of pri) {
      const parked = [];
      for (const o of S.arr.values()) if (o !== p && !o.done && !frozen(o) && !o.flag && o.slot) { parked.push([o, o.slot]); o.slot = null; }
      const best = earliestLegal(p, T);
      for (const [o, sl] of parked) o.slot = sl;
      if (best && (!p.slot || p.slot.t > best.t + 10)) {
        p.slot = best; p.efc = null; p.verdict = 'kernel ACCEPT'; p.reorder = `kernel re-ordered: ${p.flag === 'MEDICAL' ? 'MEDICAL' : 'LOW FUEL'} first`;
        note = note || p.reorder;
        for (const o of [...S.arr.values()].filter(o => o !== p && !o.done && !frozen(o) && o.slot).sort((x, y) => x.slot.t - y.slot.t)) {
          if (!slotProblem(o, o.slot.rwy, o.slot.t, T)) continue;
          const e = earliestLegal(o, T, o.slot.t); o.slot = e; o.bumped = p.cs;
          if (!e) sendToHold(o, T, o.holdFix);
        }
      }
    }
    return note;
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
      const a = { id: f.id, qid: 'A' + (++S.qn), cs, type, wake: HEAVY_RE.test(type) ? 'heavy' : 'medium', reg: p[9] || f.registration, tGate: T, eta: T + dist(ll, FAF('28R')) / 105 + 231,
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
      model: { uri, scale: heavy ? 46 : 0.4, minimumPixelSize: 30, maximumScale: 4000, silhouetteColor: new C.CallbackProperty(() => C.Color.fromCssColorString(a.hover || (ctx.pickedEntity && ctx.pickedEntity() === a.entity) ? '#ffffff' : '#ffb547'), false),
        silhouetteSize: new C.CallbackProperty(() => (a.hover || (ctx.pickedEntity && ctx.pickedEntity() === a.entity) ? 3 : a.leg.type === 'hold' ? 1.2 : 0), false) },
      // status chip matching the panel pill: green LAND, amber HOLD
      label: ctx.label(new C.CallbackProperty(() => `${a.cs}${a.flag ? (a.flag === 'MEDICAL' ? ' · MED' : ' · FUEL') : ''}  ${status(a, ctx.now()).chip}`, false), {
        fillColor: new C.CallbackProperty(() => C.Color.fromCssColorString(status(a, ctx.now()).kind === 'land' ? '#ffffff' : '#1b1408'), false),
        backgroundColor: new C.CallbackProperty(() => C.Color.fromCssColorString(status(a, ctx.now()).kind === 'land' ? 'rgba(31,157,85,0.92)' : 'rgba(255,181,71,0.92)'), false),
        pixelOffset: new C.Cartesian2(0, -26) }),
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
        a.leg = { type: 'roll', t0: T }; a.landedAt = T; S.landed++; S.delaySum += Math.max(0, T - a.eta);
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
    for (const a of S.arr.values()) if (a.slot && a.slot.rwy === '28L' && a.leg.type !== 'roll' && a.slot.t <= S.closure.t1) { // incl. aircraft on final: go around
      a.slot = null; a.verdict = 'kernel VETO · 28L closed, slot revoked'; a.holdFix = null; sendToHold(a, T, nearestFix(posOf(a, T).ll));
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
    const up = (v, n) => String(v || '').toUpperCase().replace(/[^A-Z0-9-]/g, '').slice(0, n) || 'UNK';
    const queue = live.map(a => ({ id: a.qid, callsign: up(a.cs, 12), type: up(a.type, 6).replace(/-/g, ''), wake: a.wake, flag: a.flag === 'MEDICAL' ? 'MED' : a.flag === 'LOW_FUEL' ? 'FUEL' : null,
      frozen: !!frozen(a), ...(a.slot ? { runway: a.slot.rwy, slot_s: Math.round(a.slot.t - T) } : {}),
      eta_s: Math.round(a.eta - T), min_slot_s: Math.round(minSlot(a, T) - T) + margin, suggested_fix: a.holdFix || nearestFix(posOf(a, T).ll),
      state: frozen(a) ? 'final' : a.slot ? 'cleared' : a.leg.type === 'hold' ? 'holding' : 'inbound' }));
    // the kernel's legal free slots, so the agent picks from times that will pass (no veto storms)
    const free_slots = {};
    for (const rwy of ['28L', '28R']) {
      if (S.closure && S.closure.rwy === rwy) continue;
      const out = []; let t = T + Math.min(...queue.map(q => q.min_slot_s), 600);
      for (; out.length < 10 && t < T + 3600; t += 5) if (freeAt(rwy, t)) { out.push(Math.round(t - T)); t += 85; }
      free_slots[rwy] = out;
    }
    const runways = ['28L', '28R'].map(id => ({ id, open: !(S.closure && S.closure.rwy === id), ...(S.closure && S.closure.rwy === id ? { closed_for_s: Math.round(S.closure.t1 - T) } : {}) }));
    S.inflight = true; S.inflightN = queue.filter(q => !q.frozen).length; S.agentInfo = 'agent thinking…'; render(T);
    let res;
    try { const r = await fetch('/api/sequence', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ queue, runways, free_slots, now: Math.round(T) }) }); res = await r.json(); if (!r.ok) throw new Error(res.error || r.status); }
    catch (e) { S.inflight = false; S.agentInfo = `agent unavailable (${String(e.message || e).slice(0, 40)}) → kernel FCFS`; fcfs(ctx.now()); render(ctx.now()); return; }
    S.inflight = false;
    const Tn = ctx.now(), seq = ++S.seq;
    S.agentInfo = `${res.provider} · ${String(res.model).split('/').pop()} · ${(res.ms / 1000).toFixed(1)} s${res.fallbacks?.length ? ' (fallback)' : ''}`;
    let spokeHold = false, ok = 0, veto = 0, vetoWhy = '';
    for (const d of res.decisions || []) {
      const a = [...S.arr.values()].find(x => x.qid === d.args.id); if (!a || a.done || frozen(a)) continue;
      const why = String(d.args.reason || '').slice(0, 80);
      if (d.name === 'clear_to_land') {
        const t = T + Number(d.args.slot_time), prob = Number.isFinite(t) ? slotProblem(a, d.args.runway, t, T) : 'no slot time'; // feasibility judged at request time
        a.why = why;
        if (!prob) { ok++; a.slot = { rwy: d.args.runway, t }; a.efc = null; a.verdict = 'kernel ACCEPT'; a.last = `${d.args.runway} ${fmtT(t)} · ${why}`; logLine(`${a.cs} → ${d.args.runway} ${fmtT(t)}`, 'acc', 'ACCEPT'); }
        else {
          a.slot = null; sendToHold(a, Tn, a.holdFix); const e = earliestLegal(a, Tn); a.efc = e ? e.t : null;
          veto++; vetoWhy = vetoWhy || `${a.cs} ${prob}`;
          a.verdict = `kernel VETO · ${prob}`; a.last = `${d.args.runway} ${fmtT(t)} · ${why}`;
          logLine(`${a.cs} ${d.args.runway} ${fmtT(t)} vetoed: ${prob} → hold ${a.holdFix}`, 'rej', 'VETO');
        }
      } else if (d.name === 'hold') {
        ok++; a.why = why; a.slot = null; sendToHold(a, Tn, d.args.fix); a.efc = Tn + 60 * Math.max(1, Math.min(20, Number(d.args.minutes) || 3));
        a.verdict = 'kernel ACCEPT (hold is always safe)'; a.last = `hold ${a.holdFix} ${d.args.minutes} min · ${why}`;
        logLine(`${a.cs} holds ${a.holdFix} ${d.args.minutes} min`, 'acc', 'ACCEPT');
        if (!spokeHold) { spokeHold = true; const efc = fmtT(a.efc).slice(0, 5).replace(':', ''); say(`${spoken(a.cs)}, hold at ${a.holdFix} as published, expect further clearance ${[...efc].map(x => DIG[x]).join(' ')}.`, a.cs); }
      }
    }
    for (const a of S.arr.values()) if (!a.done && !a.slot && !frozen(a) && !(res.decisions || []).some(d => d.args.id === a.qid)) a.verdict = 'no agent decision → kernel default hold';
    const reord = enforcePriority(Tn);
    logLine(`Nemotron: ${ok} accepted${veto ? `, ${veto} vetoed` : ''}${reord ? ` · ${reord}` : ''}`, veto ? 'rej' : 'acc');
    const nice = { crusoe: 'Crusoe', openai: 'OpenAI' }, mdl = /nemotron/i.test(res.model) ? 'Nemotron' : String(res.model).split('/').pop();
    S.cycle = { label: `${mdl} · ${nice[res.provider] || res.provider}${res.fallbacks?.length && res.provider !== 'crusoe' ? ' (fallback)' : ''}`, ms: res.ms, ok, veto, vetoWhy };
    render(Tn, seq);
  }

  // ---------- radio ----------
  let spokenCount = 0;
  function say(text, cs) { if (spokenCount >= 3 || !window.SkyRadio) return; spokenCount++; window.SkyRadio.say(text, 'atc'); }

  // ---------- status shared by the panel pills and the 3D label chips ----------
  const leaveAt = (a, T) => a.slot ? a.slot.t - finalLen(a, T, a.slot.rwy) / V_APP : null;
  function status(a, T) {
    if (a.leg.type === 'roll') return { kind: 'land', pill: `LANDED · ${a.slot.rwy}`, chip: `LANDED ${a.slot.rwy}` };
    if (a.slot && (frozen(a) && a.leg.type === 'final' || leaveAt(a, T) - T < 60))
      return { kind: 'land', pill: `LAND NOW · ${a.slot.rwy} · ${fmtT(a.slot.t)}`, chip: `LAND ${a.slot.rwy} ${fmtT(a.slot.t).slice(0, 5)}` };
    const until = a.slot ? leaveAt(a, T) : a.efc;
    const mins = until ? Math.max(1, Math.ceil((until - T) / 60)) : null;
    return { kind: 'wait', pill: `WAIT · HOLD ${a.holdFix}${mins ? ` · +${mins} min` : ''}`, chip: `HOLD ${a.holdFix}` };
  }
  function llmWhy(a) {
    const w = (a.why || '').trim(); if (!w) return null;
    if (/heavy/i.test(w) && !leadOf(a)?.wake?.startsWith('heavy') && a.wake !== 'heavy') return null;
    if (/\bmed(ical)?\b/i.test(w) && a.flag !== 'MEDICAL') return null;
    if (/priority/i.test(w) && !a.flag) return null;
    if (/fuel/i.test(w) && a.flag !== 'LOW_FUEL') return null;
    if (/closed/i.test(w) && !S.closure) return null;
    if (/[A-Z_]{5,}/.test(w)) return null; // echoes of field names
    return w.replace(/\.$/, '') + '.';
  }
  const leadOf = a => a.slot ? [...S.arr.values()].filter(o => o !== a && o.slot && o.slot.rwy === a.slot.rwy && o.slot.t < a.slot.t).sort((x, y) => y.slot.t - x.slot.t)[0] : null;
  const hm = t => fmtT(t).slice(0, 5), hms = t => fmtT(t);
  function reason(a, T) {
    if (a.leg.type === 'roll') return `Landed ${a.slot.rwy} · delay ${fmtD(a.landedAt - a.eta)}`;
    if (/VETO/.test(a.verdict || '') && !a.slot) {
      const e = earliestLegal(a, T);
      return `Kernel veto: ${a.verdict.replace(/^kernel VETO · /, '')}${e ? `; next legal ${e.rwy} ${hms(e.t)}` : ''} → hold ${a.holdFix}`;
    }
    if (a.slot) {
      const r = a.slot.rwy, at = hms(a.slot.t), pre = a.reorder ? `${a.reorder} · ` : '';
      if (a.flag) {
        const first = !leadOf(a) || [...S.arr.values()].every(o => o === a || o.done || !o.slot || o.slot.t > a.slot.t || frozen(o));
        return `${pre}${a.flag === 'MEDICAL' ? 'MED' : 'LOW FUEL'} priority: ${first ? 'first' : 'earliest legal'} slot ${r} ${at}`;
      }
      const lead = leadOf(a), gap = lead ? a.slot.t - lead.slot.t : 1e9;
      if (leaveAt(a, T) - T >= 60) return `Slot ${r} ${at}; holds ${a.holdFix} until ${hm(leaveAt(a, T))}`;
      if (lead && lead.wake === 'heavy' && gap < 140) return `120 s wake behind ${lead.cs} (heavy) on ${r} → ${at}`;
      if (lead && gap < 100) return `90 s behind ${lead.cs} on ${r} → ${at}${a.bumped ? ` (moved for ${a.bumped})` : ''}`;
      return lead ? `Next free ${r} slot ${at}, after ${lead.cs}` : `First slot ${r} ${at}`;
    }
    const e = earliestLegal(a, T);
    if (S.closure) return `28L closed until ${hm(S.closure.t1)}; next 28R slot ${e ? hms(e.t) : '—'} → hold ${a.holdFix}`;
    return `Next legal slot ${e ? `${e.rwy} ${hms(e.t)}` : '—'} → hold ${a.holdFix}`;
  }

  // ---------- NEMOTRON DECISIONS panel (right side) ----------
  const css = document.createElement('style');
  css.textContent = `#nemo{position:absolute;right:14px;top:14px;bottom:84px;width:360px;z-index:11;display:flex;flex-direction:column;background:rgba(10,13,16,.8);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);border-radius:12px;color:#eef1f3;font:12px/1.35 Inter,-apple-system,sans-serif;overflow:hidden}
#nemo .hd{padding:12px 14px 8px}
#nemo .t{display:flex;align-items:center;gap:6px;font:700 11px/1 Inter,sans-serif;letter-spacing:.14em;color:#76b900}
#nemo .t .sp{flex:1}
#nemo button{white-space:nowrap;font:600 10.5px/1 Inter,sans-serif;border:0;border-radius:999px;padding:6px 10px;cursor:pointer;background:rgba(255,255,255,.08);color:#eef1f3;letter-spacing:0}
#nemo button.on{background:#4fdc8a;color:#06240f}
#nemo button.off{background:#ffb547;color:#1b1408}
#nemo .who{margin-top:8px;font:600 13px/1.3 Inter,sans-serif}
#nemo .who.busy{color:#8e989f}
#nemo .kv{margin-top:3px;font:600 11px/1.35 ui-monospace,Menlo,monospace;color:#4fdc8a}
#nemo .kv .x{color:#ff7a6e}
#nemo .meta{margin-top:6px;display:flex;gap:10px;font:600 10.5px/1.2 ui-monospace,Menlo,monospace;color:#8e989f}
#nemo .meta b{color:#eef1f3}
#nemo .meta .cl{color:#ff7a6e}
#nemo ol{position:relative;list-style:none;margin:0;padding:4px 8px 10px;overflow:hidden;flex:1}
#nemo li{padding:8px 8px 9px;margin-bottom:4px;border-radius:9px;background:rgba(255,255,255,.035);cursor:pointer;transition:transform .45s cubic-bezier(.2,.8,.2,1),background .3s}
#nemo li:hover,#nemo li.sel{background:rgba(255,255,255,.1)}
#nemo li.sel{box-shadow:inset 0 0 0 1.5px #4c7dff}
#nemo .r1{display:flex;align-items:baseline;gap:6px;font:600 13px/1.2 Inter,sans-serif}
#nemo .r1 .ty{font:500 11px/1 ui-monospace,Menlo,monospace;color:#8e989f}
#nemo .tag{font:700 9px/1 Inter,sans-serif;padding:3px 5px;border-radius:4px;background:#ff5a4f;color:#1b0b09}
#nemo .tag.f{background:#ffb547;color:#1b1408}
#nemo .pill{display:inline-block;margin-top:6px;padding:6px 10px;border-radius:7px;font:700 12.5px/1 ui-monospace,Menlo,monospace;letter-spacing:.02em;transition:box-shadow .3s}
#nemo .pill.land{background:#1f9d55;color:#fff}
#nemo .pill.wait{background:#ffb547;color:#1b1408}
#nemo .pill.flash{box-shadow:0 0 0 3px rgba(255,255,255,.85)}
#nemo .why{margin-top:5px;color:#c9d0d5;font-size:12px}
#nemo .why.v{color:#ffb3ad}
#nemo .why.o{color:#9fc3ff}
#nemo .q{margin-top:3px;font:italic 11px/1.3 Inter,sans-serif;color:#8e989f}
#nemo .q:empty{display:none}
#nemo .lg{margin-top:6px;font:500 10.5px/1.35 ui-monospace,Menlo,monospace;color:#8e989f}
#nemo .lg .rej{color:#ff9a8f}
#nemo .lg .acc{color:#9ff0bf}
#nemo .empty{padding:14px;color:#8e989f}`;
  document.head.appendChild(css);
  const el = document.createElement('div'); el.id = 'nemo';
  el.innerHTML = `<div class="hd"><div class="t"><span>NEMOTRON DECISIONS</span><span class="sp"></span><button id="lpDis" title="Disruption: close 28L for 10 minutes">Close 28L</button><button id="lpMode" class="on" title="Agent ON / first-come-first-served">Agent ON</button></div>
<div class="who busy" id="lpWho">Waiting for arrivals inside 25 NM…</div><div class="kv" id="lpKv"></div><div class="lg" id="lpLg"></div>
<div class="meta"><span>Landed <b id="lpL">0</b></span><span>Holding <b id="lpH">0</b></span><span>Avg delay <b id="lpD">0:00</b></span><span id="lpRw"></span></div></div><ol id="lpList"></ol>`;
  document.body.appendChild(el);
  el.querySelector('#lpDis').onclick = () => { if (ctx.ready()) disrupt(); };
  el.querySelector('#lpMode').onclick = () => {
    const T = ctx.now(); S.mode = S.mode === 'agent' ? 'fcfs' : 'agent';
    const b = el.querySelector('#lpMode'); b.textContent = S.mode === 'agent' ? 'Agent ON' : 'Agent OFF · FCFS'; b.className = S.mode === 'agent' ? 'on' : 'off';
    for (const a of S.arr.values()) if (!a.done && !frozen(a)) { a.slot = null; a.efc = null; a.why = null; a.verdict = null; }
    if (S.mode === 'fcfs') fcfs(T); else requestCycle(T, true);
  };
  function logLine(txt, cls, k) { S.log.push({ txt, cls, k }); if (S.log.length > 6) S.log.shift(); }
  const list = el.querySelector('#lpList'), rowsEl = new Map();
  function render(T) {
    const live = [...S.arr.values()].filter(a => !a.done);
    el.querySelector('#lpL').textContent = S.landed;
    el.querySelector('#lpH').textContent = live.filter(a => status(a, T).kind === 'wait').length;
    el.querySelector('#lpD').textContent = fmtD(S.landed ? S.delaySum / S.landed : 0);
    el.querySelector('#lpLg').innerHTML = S.log.slice(-3).map(l => `<div class="${l.cls || ''}">${esc(l.txt)}</div>`).join('');
    el.querySelector('#lpRw').innerHTML = S.closure ? `<span class="cl">28L CLOSED → ${esc(fmtT(S.closure.t1).slice(0, 5))}</span>` : '28L · 28R open';
    const who = el.querySelector('#lpWho'), kv = el.querySelector('#lpKv');
    if (S.mode === 'fcfs') { who.className = 'who'; who.textContent = 'Agent OFF · kernel first-come-first-served'; kv.textContent = 'No priorities: ETA order only'; }
    else if (S.inflight) { who.className = 'who busy'; who.textContent = `Nemotron is deciding ${S.inflightN} arrivals…`; }
    else if (S.cycle) {
      who.className = 'who'; who.textContent = `${S.cycle.label} · decided in ${(S.cycle.ms / 1000).toFixed(1)} s`;
      kv.innerHTML = `✓ ${S.cycle.ok} verified by kernel${S.cycle.veto ? ` · <span class="x">✗ ${S.cycle.veto} veto: ${esc(S.cycle.vetoWhy)}</span>` : ''}`;
    } else if (S.agentInfo && /unavailable/.test(S.agentInfo)) { who.className = 'who'; who.textContent = S.agentInfo; }
    // order: landing slots first (by slot), then holds (by expected release)
    const rows = live.sort((x, y) => (x.slot ? x.slot.t : 1e12 + (x.efc || x.eta)) - (y.slot ? y.slot.t : 1e12 + (y.efc || y.eta))).slice(0, 9);
    if (!rows.length) { list.innerHTML = `<div class="empty">${ctx.ready() ? 'No arrivals inside 25 NM yet.' : 'Loading recorded arrivals…'}</div>`; rowsEl.clear(); return; }
    list.querySelector('.empty')?.remove();
    const first = new Map([...rowsEl].map(([id, li]) => [id, li.getBoundingClientRect().top]));
    const sel = ctx.pickedEntity && ctx.pickedEntity();
    rows.forEach(a => {
      let li = rowsEl.get(a.id);
      if (!li) {
        li = document.createElement('li'); rowsEl.set(a.id, li);
        li.innerHTML = '<div class="r1"><span class="cs"></span><span class="ty"></span></div><div class="pill"></div><div class="why"></div><div class="q"></div>';
        li.onmouseenter = () => { a.hover = true; }; li.onmouseleave = () => { a.hover = false; };
        li.onclick = () => ctx.select(a.entity);
      }
      const st = status(a, T), why = reason(a, T);
      li.querySelector('.cs').innerHTML = `${esc(a.cs)}${a.flag ? ` <span class="tag${a.flag === 'LOW_FUEL' ? ' f' : ''}">${a.flag === 'MEDICAL' ? 'MEDICAL' : 'LOW FUEL'}</span>` : ''}`;
      li.querySelector('.ty').textContent = `${a.type}${a.wake === 'heavy' ? ' · heavy' : ''}`;
      const pill = li.querySelector('.pill');
      if (pill.textContent !== st.pill) {
        const changedKind = pill.dataset.kind && pill.dataset.kind !== st.kind;
        pill.textContent = st.pill; pill.className = `pill ${st.kind}`; pill.dataset.kind = st.kind;
        if (changedKind || pill.dataset.slot !== String(a.slot && a.slot.t)) { pill.classList.add('flash'); setTimeout(() => pill.classList.remove('flash'), 1200); }
        pill.dataset.slot = String(a.slot && a.slot.t);
      }
      const w = li.querySelector('.why'); w.textContent = why; w.className = `why${/^Kernel veto/.test(why) ? ' v' : /re-ordered/.test(why) ? ' o' : ''}`;
      const qt = llmWhy(a); li.querySelector('.q').textContent = qt ? `“${qt.replace(/\.$/, '')}” — Nemotron` : '';
      li.classList.toggle('sel', !!sel && sel === a.entity);
      list.appendChild(li); // appends in sorted order
    });
    for (const [id, li] of rowsEl) if (!rows.some(a => a.id === id)) { li.remove(); rowsEl.delete(id); }
    // FLIP: animate reordering
    for (const [id, li] of rowsEl) {
      const f = first.get(id); if (f == null) continue;
      const dy = f - li.getBoundingClientRect().top; if (Math.abs(dy) < 2) continue;
      li.style.transition = 'none'; li.style.transform = `translateY(${dy}px)`;
      requestAnimationFrame(() => { li.style.transition = ''; li.style.transform = ''; });
    }
  }
  return { state: S, disrupt, requestCycle, status };

}

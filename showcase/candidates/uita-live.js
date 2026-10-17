// uita-live.js: live data layer for the Uita FastAPI server, reached through the
// dev-server proxy at /uita/* (the proxy adds the mutation token; never put one here).
// Dependency-free. Exposes window.UitaLive. See UITA_LIVE.md.
(function () {
  "use strict";
  var BASE = "/uita";
  var NM = 1852;

  // ENU (nm) -> lon/lat. The backend frame has no geodetic origin, so it was fitted
  // to OSM SFO runway ends (candidates/data/airports.geojson). The backend places the
  // 01L/01R pair ~560 m away from the 28L/28R pair relative to reality, so one rigid
  // transform cannot fit all four: T28 fits 28L/28R to ~1 m, T01 fits 01L/01R to ~36 m.
  // Aircraft using runway 01L/01R (departures) use T01 for their whole path.
  var LON0 = -122.37, LAT0 = 37.615;
  var M_LON = 88289.74, M_LAT = 110989.21; // metres per degree at LAT0
  var FRAMES = {
    T28: { rot: -0.01418093985347451, tx: -352.66529146518087, ty: 172.51754752061282 },
    T01: { rot: -0.017021844371823937, tx: 61.754621101795124, ty: 546.892096637042 },
  };
  function frameFor(runway) {
    return runway && /^(01|19)/.test(String(runway)) ? FRAMES.T01 : FRAMES.T28;
  }
  function toLonLat(x, y, runway) {
    var f = frameFor(runway), c = Math.cos(f.rot), s = Math.sin(f.rot);
    var e = x * NM, n = y * NM;
    var E = c * e - s * n + f.tx, N = s * e + c * n + f.ty;
    return [LON0 + E / M_LON, LAT0 + N / M_LAT];
  }

  function normalize(s) {
    var aircraft = (s.aircraft || []).map(function (a) {
      var ll = toLonLat(a.x, a.y, a.runway);
      return {
        id: a.id, callsign: a.callsign, type: a.type, wake: a.wake,
        op: a.operation, status: a.status,
        lon: ll[0], lat: ll[1], altFt: a.altitude,
        heading: a.heading, speedKt: a.speed, runway: a.runway,
        delayS: a.delay, emergency: !!a.emergency,
        path: (a.trajectory || []).map(function (p) {
          var q = toLonLat(p.x, p.y, a.runway);
          return [q[0], q[1], p.altitude, p.t];
        }),
      };
    });
    var runways = (s.runways || []).map(function (r) {
      return {
        id: r.id, closed: !!r.closed, lengthFt: r.length_ft,
        a: toLonLat(r.start[0], r.start[1], r.id),
        b: toLonLat(r.end[0], r.end[1], r.id),
      };
    });
    return {
      aircraft: aircraft, runways: runways,
      metrics: s.metrics || {}, events: s.events || [],
      proposals: s.proposals || [], reservations: s.runway_reservations || [],
      weather: s.weather || null, disruptions: s.disruptions || [],
      time: s.time, running: !!s.running, speed: s.speed,
      revision: s.revision, scenario: s.scenario, receivedAt: Date.now(),
      raw: s,
    };
  }

  var handlers = {};
  function on(ev, fn) { (handlers[ev] = handlers[ev] || []).push(fn); return api; }
  function off(ev, fn) { handlers[ev] = (handlers[ev] || []).filter(function (h) { return h !== fn; }); return api; }
  function emit(ev, arg) {
    (handlers[ev] || []).forEach(function (fn) {
      try { fn(arg); } catch (e) { console.warn("[UitaLive]", ev, e); }
    });
  }

  function request(method, path, body, timeoutMs) {
    var ctl = typeof AbortController === "function" ? new AbortController() : null;
    var t = ctl && setTimeout(function () { ctl.abort(); }, timeoutMs || 15000);
    return fetch(BASE + path, {
      method: method,
      // The proxy only forwards same-origin JSON POSTs, so always send a JSON body.
      headers: method === "GET" ? undefined : { "content-type": "application/json" },
      body: method === "GET" ? undefined : JSON.stringify(body || {}),
      signal: ctl ? ctl.signal : undefined,
      cache: "no-store",
    }).then(function (r) {
      return r.text().then(function (txt) {
        var data; try { data = txt ? JSON.parse(txt) : null; } catch (e) { data = txt; }
        if (!r.ok) {
          var err = new Error("Uita " + method + " " + path + " -> " + r.status);
          err.status = r.status; err.data = data; throw err;
        }
        return data;
      });
    }).finally(function () { if (t) clearTimeout(t); });
  }
  function key(prefix) {
    return prefix + "-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
  }

  // Polling. One request in flight at a time; the server can take 5-10 s per state.
  var started = false, pausedByMsg = false, timer = null, inflight = false;
  var intervalMs = 1000, failures = 0;
  var api_online = null; // tri-state: null unknown, true, false
  var last = null;

  function schedule(ms) {
    clearTimeout(timer);
    if (!started || pausedByMsg || document.hidden) return;
    timer = setTimeout(poll, ms);
  }
  function setOnline(v, err) {
    if (api_online === v) return;
    api_online = v;
    emit(v ? "online" : "offline", err || null);
  }
  function poll() {
    if (inflight) return;
    inflight = true;
    request("GET", "/api/state", null, 15000).then(function (s) {
      failures = 0;
      last = normalize(s);
      setOnline(true);
      emit("state", last);
      schedule(intervalMs);
    }, function (e) {
      failures++;
      if (failures >= 2 || api_online === null) setOnline(false, e);
      schedule(Math.min(10000, intervalMs * Math.pow(2, failures))); // back off quietly
    }).finally(function () { inflight = false; });
  }

  function start(opts) {
    opts = opts || {};
    if (opts.intervalMs) intervalMs = opts.intervalMs;
    if (opts.base) BASE = opts.base;
    started = true; pausedByMsg = false;
    if (!inflight) poll();
    return api;
  }
  function stop() { started = false; clearTimeout(timer); return api; }

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) clearTimeout(timer);
    else if (started && !pausedByMsg && !inflight) poll();
  });
  window.addEventListener("message", function (ev) {
    var m = ev.data && ev.data.uita;
    if (m === "pause") { pausedByMsg = true; clearTimeout(timer); }
    else if ((m === "play" || m === "resume") && pausedByMsg) {
      pausedByMsg = false; if (started && !inflight) poll();
    }
  });

  // Mutations return the new Snapshot where the API does; emit it as state.
  function absorb(s) {
    if (s && s.aircraft) { last = normalize(s); setOnline(true); emit("state", last); }
    return s;
  }
  function control(action, extra) {
    var body = Object.assign({ action: action }, extra || {});
    return request("POST", "/api/control", body).then(absorb);
  }
  function disrupt(body) {
    if (typeof body === "string") body = { kind: body };
    return request("POST", "/api/disruptions", body).then(absorb);
  }

  // Full kernel loop: agent proposes -> kernel verifies independently -> commit only on pass.
  function proposeVerifyCommit(opts) {
    opts = opts || {};
    var steps = { propose: null, verify: null, commit: null, ok: false };
    function step(name, fn) {
      var t0 = performance.now();
      emit("step", { step: name, phase: "start" });
      return fn().then(function (res) {
        steps[name] = { ok: true, ms: Math.round(performance.now() - t0), result: res };
        emit("step", { step: name, phase: "done", result: res });
        return res;
      }, function (e) {
        steps[name] = { ok: false, ms: Math.round(performance.now() - t0), error: e.message, status: e.status, detail: e.data };
        emit("step", { step: name, phase: "error", error: e });
        throw e;
      });
    }
    return step("propose", function () {
      return request("POST", "/api/proposals", {
        source: opts.source || "fixture",
        policy_id: opts.policyId || null,
        idempotency_key: key("prop"),
      }, 30000);
    }).then(function (p) {
      return step("verify", function () {
        return request("POST", "/api/proposals/" + encodeURIComponent(p.id) + "/verify", null, 30000);
      });
    }).then(function (v) {
      var status = v && v.verification && v.verification.status;
      if (status !== "pass") { steps.verdict = status || "unknown"; return steps; }
      steps.verdict = "pass";
      return step("commit", function () {
        return request("POST", "/api/proposals/" + encodeURIComponent(v.id) + "/commit",
          { idempotency_key: key("commit") }, 30000).then(absorb);
      }).then(function () { steps.ok = true; return steps; });
    }).catch(function () { return steps; });
  }

  var api = {
    start: start, stop: stop, on: on, off: off,
    toLonLat: toLonLat, normalize: normalize,
    control: control, disrupt: disrupt, proposeVerifyCommit: proposeVerifyCommit,
    replay: function (t) { return request("GET", "/api/replay?time=" + encodeURIComponent(t)).then(normalize); },
    health: function () { return request("GET", "/api/health", null, 8000); },
    get state() { return last; },
    get online() { return api_online; },
    frames: FRAMES,
  };
  window.UitaLive = api;
})();

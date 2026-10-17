// Recorded measurements stay separate from the scripted showcase and its clock.
const TZ = "America/Los_Angeles";
const stamp = (t) =>
  new Intl.DateTimeFormat("en-US", {
    timeZone: TZ,
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZoneName: "short",
  }).format(new Date(t * 1000));
const dayKey = (t) =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(t * 1000));
const esc = (x) =>
  String(x ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const measure = (n, unit) =>
  n == null ? "Not recorded" : `${Math.round(n).toLocaleString()} ${unit}`;
function latest(points, time) {
  let lo = 0,
    hi = points.length;
  while (lo < hi) {
    const m = (lo + hi) >>> 1;
    if (points[m][0] <= time) lo = m + 1;
    else hi = m;
  }
  return lo - 1;
}
async function json(path, signal) {
  const response = await fetch("/uita/api/history/" + path, { signal });
  const data = await response.json().catch(() => ({}));
  if (!response.ok)
    throw Error(
      data.detail ||
        data.error ||
        "Recorded traffic is unavailable. Retry the connection.",
    );
  return data;
}

export function mountHistory({
  C,
  viewer,
  altitudeOffset,
  ground,
  setPhotoreal,
  isPhotoreal,
}) {
  document.body.classList.add("recorded");
  document.title = "UITA · Recorded SFO traffic · August 24–30, 2026";
  const root = document.createElement("main");
  root.id = "history";
  root.innerHTML = `
    <header class="hr-head"><div><span class="hr-eyebrow">UITA / RECORDED TRAFFIC</span><h1>SFO · August 24–30, 2026</h1></div><div><time id="hr-clock">Connecting…</time><span id="hr-status" role="status">Loading PostgreSQL observations</span></div></header>
    <section class="hr-metrics" aria-label="Recorded data metrics">
      <div><span>Current observations</span><strong id="hr-targets">—</strong><small>Regional targets · ≤15 s old</small></div>
      <div><span>Map placement</span><strong id="hr-coverage">—</strong><small>Recorded altitude or ground flag</small></div>
      <div><span>SFO operations · day</span><strong id="hr-operations">—</strong><small>FAA OPSNET · arrivals + departures</small></div>
      <div><span>Safety events</span><strong class="hr-pending">Not evaluated</strong><small>Requires validated flight matching</small></div>
    </section>
    <aside class="hr-sidebar"><details open id="hr-inspector"><summary>Source observation</summary><div id="hr-detail">Select a target on the map or in the list.</div></details>
      <details open><summary>Observed targets <span id="hr-count"></span></summary><div id="hr-list"></div></details>
      <details><summary>Data and limits</summary><div class="hr-source"><p id="hr-loaded">Checking week coverage…</p><p id="hr-weather">Weather unavailable</p><p>One original sample per aircraft per 5 seconds. Targets disappear after 15 seconds without a measurement. No extrapolation.</p><p>These are regional observations, including nearby airports and overflights. They are not a complete SFO operation roster.</p><p>Altitude is barometric, not surveyed height. Ground targets use the map surface. Other targets without altitude remain in the list. Arrival rates, runway use, delay and safety counts are not inferred.</p><a href="https://github.com/adsblol/globe_history_2026" target="_blank" rel="noreferrer">ADSB.lol trace archive · ODbL-1.0</a><button id="hr-refresh">Refresh data coverage</button></div></details>
    </aside>
    <section class="hr-transport" aria-label="Replay controls"><div class="hr-days" role="group" aria-label="Replay day"></div>
      <div class="hr-actions"><button id="hr-play" disabled>Play</button><button id="hr-start" aria-label="Restart week" disabled>↤</button><button data-jump="-900" disabled>−15 min</button><button data-jump="10" disabled>+10 sec</button><button data-jump="900" disabled>+15 min</button>
      <label>Speed <select id="hr-speed" aria-label="Playback speed">${[1, 5, 15, 60, 120, 300, 600].map((v) => `<option value="${v}" ${v === 60 ? "selected" : ""}>${v}×</option>`).join("")}</select></label>
      <label>Time · PDT <input id="hr-time" aria-label="Replay time PDT" type="time" step="1" disabled></label><button id="hr-end" disabled>Week end</button></div>
      <input id="hr-seek" type="range" aria-label="Replay timeline" min="0" max="1" step="1" value="0" disabled>
      <div class="hr-timeline-caption"><span>Aug 24 · 00:00 PDT</span><span>Aug 30 · 23:59:59 PDT</span></div>
      <div class="hr-camera"><button id="hr-overview">SFO overview</button><button id="hr-region">Regional view</button><button id="hr-tower">Tower view</button><button id="hr-follow" disabled>Follow selected</button><button id="hr-photo">Photoreal</button><label><input type="checkbox" id="hr-trails" checked> Trails · 2 min</label><span>Recorded observations · schematic aircraft symbols</span></div>
      <div id="hr-error" role="alert" hidden></div><button id="hr-retry" hidden>Retry data connection</button>
    </section>`;
  document.body.append(root);
  const $ = (id) => root.querySelector("#hr-" + id);
  const clock = viewer.clock;
  clock.shouldAnimate = false;
  viewer.creditDisplay.addStaticCredit(
    new C.Credit(
      'Recorded traffic: <a href="https://github.com/adsblol/globe_history_2026">ADSB.lol</a> (ODbL-1.0) · Imagery: USGS NAIP · Buildings © OpenStreetMap contributors',
      true,
    ),
  );
  let catalog = null,
    frame = null,
    time = 0,
    playing = false,
    speed = 60,
    selected = null,
    targets = [],
    loading = false,
    error = "",
    hidden = document.hidden;
  let request = null,
    generation = 0,
    lastTick = performance.now(),
    lastPaint = 0,
    follow = false;
  const cache = new Map(),
    entities = new Map();
  const glyph =
    "data:image/svg+xml," +
    encodeURIComponent(
      '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 40 40"><path d="M20 3 24 16 36 24 36 27 23 23 23 32 28 36 28 38 20 35 12 38 12 36 17 32 17 23 4 27 4 24 16 16Z" fill="#b9e5ae" stroke="#07110c" stroke-width="2"/></svg>',
    );
  const anchor = () =>
    catalog.start + Math.floor((time - catalog.start) / 900) * 900;
  const ready = () =>
    catalog && frame && frame.start === anchor() && !error && !loading;
  function status() {
    $("play").textContent = playing ? "Pause" : "Play";
    $("play").disabled = !catalog || !!error || time >= catalog.end - 1;
    $("status").textContent = error
      ? "Data unavailable · replay paused"
      : loading
        ? "Loading interval · replay clock held"
        : playing
          ? `Playing · ${speed}×`
          : "Paused · recorded observations";
    $("error").hidden = !error;
    $("error").textContent = error;
    $("retry").hidden = !error;
  }
  function clearTargets() {
    targets = [];
    entities.forEach((e) => (e.show = false));
    $("targets").textContent = "—";
    $("coverage").textContent = "—";
    $("list").replaceChildren();
    delete $("list").dataset.key;
    $("count").textContent = "";
    $("detail").textContent = loading
      ? "Loading recorded observations…"
      : "No current observation selected.";
    $("follow").disabled = true;
    viewer.trackedEntity = undefined;
  }
  async function loadWindow() {
    if (!catalog) return;
    const start = anchor(),
      token = ++generation;
    request?.abort();
    request = new AbortController();
    error = "";
    loading = !cache.has(start);
    clearTargets();
    status();
    try {
      const result =
        cache.get(start) ||
        (await json("window?start=" + start, request.signal));
      if (token !== generation) return;
      frame = result;
      cache.set(start, frame);
      if (cache.size > 8) cache.delete(cache.keys().next().value);
      loading = false;
      paint();
      status();
    } catch (e) {
      if (token !== generation || e.name === "AbortError") return;
      loading = false;
      error = e.message;
      playing = false;
      clearTargets();
      status();
    }
  }
  function seek(next) {
    if (!catalog) return;
    playing = false;
    time = Math.max(catalog.start, Math.min(catalog.end - 1, next));
    if (!Number.isFinite(time)) time = catalog.start;
    updateTime();
    // Even a cached seek must invalidate the in-flight request for another interval.
    loadWindow();
  }
  function updateTime() {
    $("clock").textContent = stamp(time);
    $("clock").dateTime = new Date(time * 1000).toISOString();
    $("seek").value = Math.floor(time);
    if (document.activeElement !== $("time"))
      $("time").value = new Intl.DateTimeFormat("en-GB", {
        timeZone: TZ,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }).format(new Date(time * 1000));
    root
      .querySelectorAll("[data-day]")
      .forEach((b) =>
        b.setAttribute("aria-pressed", b.dataset.day === dayKey(time)),
      );
    $("operations").textContent =
      catalog.daily_operations
        .find((d) => d.date === dayKey(time))
        ?.total.toLocaleString() ?? "Unavailable";
  }
  function select(id) {
    selected = id;
    paint();
  }
  function paint() {
    if (!ready()) return;
    updateTime();
    clock.currentTime = C.JulianDate.fromDate(new Date(time * 1000));
    targets = [];
    for (const f of frame.flights) {
      const i = latest(f.points, time),
        p = f.points[i];
      if (!p || time - p[0] > 15) continue;
      targets.push({ f, p, i });
    }
    const ids = new Set();
    for (const { f, p, i } of targets) {
      // A reported ground flag permits surface placement. Never put an airborne
      // target at ground level just because its altitude is missing.
      if (p[6] !== true && (p[3] == null || !Number.isFinite(p[3]))) continue;
      ids.add(f.id);
      let e = entities.get(f.id);
      if (!e) {
        e = viewer.entities.add({
          id: "recorded-" + f.id,
          billboard: {
            image: glyph,
            width: 28,
            height: 28,
            disableDepthTestDistance: Infinity,
          },
          label: {
            text: "",
            font: "500 12px monospace",
            fillColor: C.Color.fromCssColorString("#b9e5ae"),
            showBackground: true,
            backgroundColor: C.Color.fromCssColorString("#060c0bee"),
            pixelOffset: new C.Cartesian2(18, -14),
            horizontalOrigin: C.HorizontalOrigin.LEFT,
            disableDepthTestDistance: Infinity,
          },
          polyline: {
            positions: [],
            width: 1.5,
            material: C.Color.fromCssColorString("#a8d5a355"),
          },
        });
        entities.set(f.id, e);
      }
      e.show = true;
      e.position = C.Cartesian3.fromDegrees(
        p[2],
        p[1],
        p[6] === true
          ? ground() + 2
          : Math.max(ground() + 2, p[3] * 0.3048 + altitudeOffset()),
      );
      e.billboard.rotation = (-(p[5] ?? 0) * Math.PI) / 180;
      e.billboard.show = p[5] != null && p[6] !== true;
      // A circle explicitly avoids inventing heading when it is missing.
      e.point =
        p[5] == null || p[6] === true
          ? {
              pixelSize: 9,
              color: C.Color.fromCssColorString("#a8d5a3"),
              outlineWidth: 1,
              outlineColor: C.Color.BLACK,
              disableDepthTestDistance: Infinity,
            }
          : undefined;
      e.label.text = p[8];
      e.label.show =
        selected === f.id ||
        (p[6] !== true &&
          C.Cartesian3.distance(
            viewer.camera.positionWC,
            e.position.getValue(clock.currentTime),
          ) < 18000);
      e.billboard.color =
        selected === f.id
          ? C.Color.fromCssColorString("#ffd16b")
          : C.Color.WHITE;
      const trail = [];
      if ($("trails").checked)
        for (let j = i; j >= 0; j--) {
          const q = f.points[j];
          if (p[0] - q[0] > 120 || (q[3] == null && q[6] !== true)) break;
          if (j < i && (f.points[j + 1][0] - q[0] > 15 || f.points[j + 1][7]))
            break;
          trail.unshift(
            C.Cartesian3.fromDegrees(
              q[2],
              q[1],
              q[6] === true
                ? ground() + 2
                : Math.max(ground() + 2, q[3] * 0.3048 + altitudeOffset()),
            ),
          );
        }
      e.polyline.positions = trail.length > 1 ? trail : [];
    }
    for (const [id, e] of entities)
      if (!ids.has(id)) {
        viewer.entities.remove(e);
        entities.delete(id);
      }
    $("targets").textContent = targets.length.toLocaleString();
    $("coverage").textContent = `${ids.size}/${targets.length}`;
    $("count").textContent = `(${targets.length})`;
    const order = [...targets].sort((a, b) => a.p[8].localeCompare(b.p[8]));
    // Preserve focused list buttons while time advances, for keyboard users.
    const key = order.map((t) => t.f.id + "|" + t.p[8]).join(",");
    if ($("list").dataset.key !== key) {
      $("list").dataset.key = key;
      $("list").innerHTML = order.length
        ? order
            .map(
              ({ f, p }) =>
                `<button data-flight="${esc(f.id)}"><b>${esc(p[8])}</b><span>${esc(f.id)}</span></button>`,
            )
            .join("")
        : "<p>No fresh observations in this interval.</p>";
    }
    $("list")
      .querySelectorAll("[data-flight]")
      .forEach((b) =>
        b.setAttribute("aria-pressed", b.dataset.flight === selected),
      );
    const chosen = targets.find((t) => t.f.id === selected);
    $("follow").disabled = !chosen || !ids.has(selected);
    if (follow)
      viewer.trackedEntity = ids.has(selected)
        ? entities.get(selected)
        : undefined;
    if (chosen) {
      const { f, p } = chosen;
      $("detail").innerHTML =
        `<h2>${esc(p[8])}</h2><p>${esc(p[10] || "Type not recorded")} · ${esc(p[9] || "Registration not recorded")}</p><dl>${[
          ["ICAO hex", f.id],
          ["Observation", stamp(p[0])],
          ["Sample age", `${(time - p[0]).toFixed(1)} s`],
          ["Latitude", p[1].toFixed(6) + "°"],
          ["Longitude", p[2].toFixed(6) + "°"],
          ["Barometric altitude", measure(p[3], "ft")],
          ["Ground speed", measure(p[4], "kt")],
          ["Track", measure(p[5], "°")],
          [
            "Ground flag",
            p[6] === null ? "Not recorded" : p[6] ? "On ground" : "Airborne",
          ],
        ]
          .map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`)
          .join(
            "",
          )}</dl><small>Original ADSB.lol measurement · no schedule or clearance inferred</small>`;
    } else
      $("detail").textContent = selected
        ? "Selected aircraft has no fresh observation at this time."
        : "Select a target on the map or in the list.";
    const w = frame.weather.filter((w) => w[0] <= time).at(-1);
    $("weather").textContent = w
      ? `SFO hourly weather · ${stamp(w[0])} · visibility ${measure(w[1], "mi")} · ceiling ${measure(w[2], "ft")} · wind ${measure(w[3], "kt")}`
      : "No hourly weather observation in this interval.";
    viewer.scene.requestRender();
  }
  async function loadCatalog() {
    playing = false;
    loading = true;
    error = "";
    ++generation;
    request?.abort();
    status();
    clearTargets();
    try {
      const c = await json("catalog");
      catalog = c;
      cache.clear();
      frame = null;
      $("loaded").textContent =
        `${c.days.reduce((s, d) => s + d.rows, 0).toLocaleString()} observations across ${c.days.length}/7 local dates. Last import: ${c.loaded_at ? new Date(c.loaded_at).toLocaleString() : "unknown"}.`;
      root.querySelector(".hr-days").innerHTML = Array.from(
        { length: 7 },
        (_, i) => {
          const t = c.start + i * 86400,
            d = dayKey(t),
            available = c.days.some((day) => day.date === d);
          return `<button data-day="${d}" data-start="${t}" aria-pressed="false" ${available ? "" : "disabled"}>Aug ${24 + i}<small>${available ? "Loaded" : "Unavailable"}</small></button>`;
        },
      ).join("");
      $("seek").min = c.start;
      $("seek").max = c.end - 1;
      root
        .querySelectorAll(".hr-actions button,.hr-actions input,#hr-seek")
        .forEach((e) => (e.disabled = false));
      time = time >= c.start && time < c.end ? time : c.start + 12 * 3600;
      seek(time);
    } catch (e) {
      loading = false;
      error = e.message;
      clearTargets();
      status();
    }
  }
  $("play").onclick = () => {
    if (time >= catalog.end - 1) return;
    playing = !playing;
    lastTick = performance.now();
    status();
  };
  $("start").onclick = () => seek(catalog.start);
  $("end").onclick = () => seek(catalog.end - 1);
  root
    .querySelectorAll("[data-jump]")
    .forEach((b) => (b.onclick = () => seek(time + Number(b.dataset.jump))));
  root.querySelector(".hr-days").onclick = (e) => {
    const b = e.target.closest("[data-start]");
    if (b && !b.disabled) seek(Number(b.dataset.start) + 12 * 3600);
  };
  $("speed").onchange = (e) => {
    speed = Number(e.target.value);
    status();
  };
  $("seek").oninput = (e) => seek(Number(e.target.value));
  $("time").onchange = (e) => {
    if (e.target.value) {
      const date = dayKey(time);
      seek(
        Date.parse(
          `${date}T${e.target.value.length === 5 ? e.target.value + ":00" : e.target.value}-07:00`,
        ) / 1000,
      );
    }
  };
  $("list").onclick = (e) => {
    const b = e.target.closest("[data-flight]");
    if (b) select(b.dataset.flight);
  };
  $("trails").onchange = paint;
  $("refresh").onclick = loadCatalog;
  $("retry").onclick = () => (catalog ? loadWindow() : loadCatalog());
  function camera(lon, lat, height, pitch, heading = 0) {
    follow = false;
    viewer.trackedEntity = undefined;
    viewer.camera.flyTo({
      destination: C.Cartesian3.fromDegrees(lon, lat, height),
      orientation: {
        heading: (heading * Math.PI) / 180,
        pitch: (pitch * Math.PI) / 180,
        roll: 0,
      },
      duration: 0.7,
    });
  }
  $("overview").onclick = () => camera(-122.379, 37.6213, 12000, -90);
  $("region").onclick = () => camera(-122.379, 37.6213, 125000, -90);
  $("tower").onclick = () => camera(-122.3788, 37.6157, 100, -8, 100);
  $("follow").onclick = () => {
    follow = true;
    paint();
  };
  $("photo").onclick = () => setPhotoreal(!isPhotoreal());
  viewer.screenSpaceEventHandler.setInputAction((click) => {
    const entity = viewer.scene.pick(click.position)?.id;
    if (entity?.id?.startsWith("recorded-")) select(entity.id.slice(9));
  }, C.ScreenSpaceEventType.LEFT_CLICK);
  const pauseVisibility = (value) => {
    hidden = value;
    lastTick = performance.now();
    viewer.useDefaultRenderLoop = !value;
  };
  document.addEventListener("visibilitychange", () =>
    pauseVisibility(document.hidden),
  );
  window.addEventListener("message", (e) => {
    if (e.origin !== location.origin) return;
    if (e.data?.uita === "pause") pauseVisibility(true);
    if (e.data?.uita === "resume") pauseVisibility(false);
  });
  window.addEventListener("keydown", (e) => {
    if (
      e.target.closest("input,select,button") ||
      e.metaKey ||
      e.ctrlKey ||
      e.altKey ||
      e.repeat
    )
      return;
    if (e.key === " ") {
      e.preventDefault();
      if (!$("play").disabled) $("play").click();
    }
    if (e.key.toLowerCase() === "t" && parent !== window)
      parent.postMessage({ uita: "toggle" }, location.origin);
  });
  function tick(now) {
    const dt = Math.min(0.5, (now - lastTick) / 1000);
    lastTick = now;
    if (playing && !hidden && ready()) {
      time = Math.min(catalog.end - 1, time + dt * speed);
      if (time >= catalog.end - 1) {
        playing = false;
        status();
      }
      if (frame.start !== anchor()) {
        updateTime();
        loadWindow();
      }
    }
    if (!hidden && now - lastPaint > 200) {
      paint();
      lastPaint = now;
    }
    requestAnimationFrame(tick);
  }
  $("overview").click();
  loadCatalog();
  requestAnimationFrame(tick);
}

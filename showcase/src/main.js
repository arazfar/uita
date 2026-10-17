import * as THREE from "three";
import { createIcons, Route, Cloud, ShieldCheck } from "lucide";
import { geoMercator } from "d3-geo";
import { polygonContains } from "d3-polygon";
import "./styles.css";
const d3 = { geoMercator, polygonContains };
import {
  nodes,
  edgePairs,
  byId,
  edgeKey,
  demand,
  schedule,
  metrics,
  position,
  validate,
} from "./scheduler.mjs";
import { createATC } from "./atc.mjs";
import geo from "./bay-geometry.json";
createIcons({ icons: { Route, Cloud, ShieldCheck } });
const root = document.getElementById("uita-demo");
const $ = (s) => root.querySelector(s),
  all = (s) => [...root.querySelectorAll(s)];
try {
  let mode = "adaptive",
    storm = true,
    time = 12,
    playing = false,
    speed = 1.2,
    selected = "SF-103";
  const saved = window.openai?.widgetState?.modelContent;
  if (saved) {
    mode = saved.mode === "fixed" ? "fixed" : "adaptive";
    storm = saved.storm !== false;
    time = Math.max(0, Math.min(120, Number(saved.time) || 12));
    selected = demand.some((f) => f.id === saved.selected)
      ? saved.selected
      : selected;
  }
  let plans = {},
    plan,
    base,
    m,
    highlight;
  const stamp = (t) =>
    `${String(Math.floor(t)).padStart(2, "0")}:${String(Math.floor((t % 1) * 60)).padStart(2, "0")}`;
  const persist = () =>
    window.openai
      ?.setWidgetState?.({
        modelContent: { mode, storm, time: +time.toFixed(2), selected },
        privateContent: null,
      })
      ?.catch(() => {});
  const frame = $("#sf-scene"),
    labels = $("#sf-labels");
  const scene = new THREE.Scene();
  scene.background = new THREE.Color("#e8f2f2");
  const camera = new THREE.OrthographicCamera(-65, 65, 58, -58, 0.1, 700);
  camera.position.set(53, 118, 127);
  camera.lookAt(0, 0, 0);
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  frame.append(renderer.domElement);
  scene.add(new THREE.AmbientLight(0xffffff, 1.35));
  const sun = new THREE.DirectionalLight(0xfff9ec, 2.1);
  sun.position.set(-45, 90, 35);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, {
    left: -80,
    right: 80,
    top: 80,
    bottom: -80,
  });
  sun.shadow.bias = -0.0007;
  sun.shadow.normalBias = 0.15;
  scene.add(sun);
  const material = (color, extra = {}) =>
    new THREE.MeshStandardMaterial({ color, roughness: 0.85, ...extra });
  const matLand = material("#e7ead9"),
    matSide = material("#cfdbc9"),
    matWater = new THREE.MeshBasicMaterial({ color: "#c7e5ec" }),
    matBuilding = material("#f8f4e9"),
    matRoof = material("#b2c8c2"),
    matTree = material("#8cbaa5"),
    matRoad = material("#c2cbc3"),
    matPad = material("#607b81");
  function mesh(geometry, mat, x = 0, y = 0, z = 0, parent = scene) {
    const o = new THREE.Mesh(geometry, mat);
    o.position.set(x, y, z);
    o.castShadow = true;
    o.receiveShadow = true;
    parent.add(o);
    return o;
  }
  const water = mesh(
    new THREE.BoxGeometry(110, 2.6, 119),
    matWater,
    0,
    -3.8,
    0,
  );
  water.castShadow = false;
  const projection = d3
    .geoMercator()
    .center([-122.365, 37.755])
    .scale(14950)
    .translate([0, 0]);
  const xy = (ll) => {
    const p = projection(ll);
    return [p[0], p[1]];
  };
  const coords = Object.fromEntries(nodes.map((n) => [n.id, xy(n.ll)]));
  function clip(poly) {
    let p = poly;
    for (const [axis, bound, sign] of [
      [0, -55, 1],
      [0, 55, -1],
      [1, -59.5, 1],
      [1, 59.5, -1],
    ]) {
      const out = [];
      for (let i = 0; i < p.length; i++) {
        const a = p[i],
          b = p[(i + 1) % p.length],
          ia = sign * (a[axis] - bound) >= 0,
          ib = sign * (b[axis] - bound) >= 0;
        if (ia) out.push(a);
        if (ia !== ib) {
          const t = (bound - a[axis]) / (b[axis] - a[axis]);
          out.push([a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])]);
        }
      }
      p = out;
      if (!p.length) break;
    }
    return p;
  }
  const landPolys = [];
  for (const f of geo.features)
    for (const poly of f.geometry.coordinates) {
      const p = clip(poly[0].map(xy));
      if (p.length < 3) continue;
      landPolys.push(p);
      const shape = new THREE.Shape();
      p.forEach(([x, z], i) => (i ? shape.lineTo(x, -z) : shape.moveTo(x, -z)));
      shape.closePath();
      const geom = new THREE.ExtrudeGeometry(shape, {
        depth: 2,
        bevelEnabled: false,
      });
      geom.rotateX(-Math.PI / 2);
      const land = mesh(geom, [matLand, matSide], 0, -2.1, 0);
      land.castShadow = false;
    }
  const onLand = (x, z) => landPolys.some((p) => d3.polygonContains(p, [x, z]));
  let seed = 91;
  const rnd = () => {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    return seed / 4294967296;
  };
  for (const n of nodes.filter((n) => n.pad)) {
    const [cx, cz] = coords[n.id];
    for (let i = 0; i < 64; i++) {
      const x = cx + (rnd() - 0.5) * 16,
        z = cz + (rnd() - 0.5) * 16;
      if (!onLand(x, z) || Math.hypot(x - cx, z - cz) < 3) continue;
      const h = 0.6 + rnd() * (n.id === "SF" ? 5 : 2.8),
        w = 0.65 + rnd() * 0.65;
      mesh(new THREE.BoxGeometry(w, h, w * 0.85), matBuilding, x, h / 2, z);
      mesh(
        new THREE.BoxGeometry(w + 0.05, 0.13, w * 0.85 + 0.05),
        matRoof,
        x,
        h + 0.08,
        z,
      );
    }
  }
  for (let i = 0; i < 400; i++) {
    const x = (rnd() - 0.5) * 107,
      z = (rnd() - 0.5) * 115;
    if (
      !onLand(x, z) ||
      nodes.some(
        (n) => Math.hypot(coords[n.id][0] - x, coords[n.id][1] - z) < 7,
      )
    )
      continue;
    const h = 0.8 + rnd() * 1.6;
    mesh(new THREE.ConeGeometry(0.5 + rnd() * 0.3, h, 5), matTree, x, h / 2, z);
  }
  const padLabels = [];
  for (const n of nodes) {
    const [x, z] = coords[n.id];
    if (n.pad) {
      mesh(
        new THREE.CylinderGeometry(2.25, 2.35, 0.25, 32),
        matPad,
        x,
        0.15,
        z,
      );
      mesh(
        new THREE.RingGeometry(1.7, 1.8, 32),
        material("#dbecef", { side: THREE.DoubleSide }),
        x,
        0.3,
        z,
      ).rotation.x = -Math.PI / 2;
      mesh(
        new THREE.BoxGeometry(0.2, 0.04, 1.6),
        material("#e5ece7"),
        x - 0.45,
        0.31,
        z,
      );
      mesh(
        new THREE.BoxGeometry(0.2, 0.04, 1.6),
        material("#e5ece7"),
        x + 0.45,
        0.31,
        z,
      );
      mesh(
        new THREE.BoxGeometry(0.9, 0.04, 0.18),
        material("#e5ece7"),
        x,
        0.31,
        z,
      );
      mesh(
        new THREE.CylinderGeometry(0.22, 0.34, 3.5, 8),
        material("#c9d5cc"),
        x + 2.7,
        1.75,
        z + 0.6,
      );
      mesh(
        new THREE.BoxGeometry(1.2, 0.7, 1.2),
        material("#4c7986"),
        x + 2.7,
        3.6,
        z + 0.6,
      );
      const el = document.createElement("div");
      el.className = "sf-pad-label";
      el.innerHTML = `<b>${n.id}</b><span>${n.name}</span>`;
      labels.append(el);
      padLabels.push({ el, p: new THREE.Vector3(x, 5, z) });
    } else {
      mesh(
        new THREE.RingGeometry(0.65, 0.82, 24),
        material("#79a5af", { side: THREE.DoubleSide }),
        x,
        0.12,
        z,
      ).rotation.x = -Math.PI / 2;
    }
  }
  // Model airport runways and buildings are illustrative, not airport survey geometry.
  for (const id of ["SFO", "OAK"]) {
    const [x, z] = coords[id];
    const runway = mesh(
      new THREE.BoxGeometry(1.5, 0.06, 9),
      matRoad,
      x + 4,
      0.06,
      z + 1,
    );
    runway.rotation.y = -0.25;
    for (let j = -3; j <= 3; j++)
      mesh(
        new THREE.BoxGeometry(0.13, 0.03, 0.55),
        material("#edf0e5"),
        x + 4 - j * 0.25,
        0.11,
        z + 1 + j,
      );
  }
  const curveFor = (a, b) => {
    const p = coords[a],
      q = coords[b];
    return new THREE.QuadraticBezierCurve3(
      new THREE.Vector3(p[0], 1.1, p[1]),
      new THREE.Vector3((p[0] + q[0]) / 2, 9, (p[1] + q[1]) / 2),
      new THREE.Vector3(q[0], 1.1, q[1]),
    );
  };
  const curves = {};
  const routeLines = {};
  for (const [a, b] of edgePairs) {
    const key = edgeKey(a, b),
      curve = curveFor(a, b);
    curves[key] = { curve, a, b };
    const line = mesh(
      new THREE.TubeGeometry(curve, 40, 0.065, 5, false),
      material("#8ab9ca", { transparent: true, opacity: 0.65 }),
    );
    line.castShadow = false;
    routeLines[key] = line;
  }
  const cloud = new THREE.Group();
  scene.add(cloud);
  const mid = curveFor("C", "E").getPoint(0.5);
  cloud.position.copy(mid);
  cloud.position.y = 9;
  const cloudMat = material("#d3d9d8", {
    transparent: true,
    opacity: 0.84,
    depthWrite: false,
  });
  for (let i = 0; i < 7; i++)
    mesh(
      new THREE.IcosahedronGeometry(2.3 + (i % 3) * 0.65, 1),
      cloudMat,
      ((i % 4) - 1.5) * 2.1,
      (i % 3) * 0.7,
      (Math.floor(i / 4) - 0.5) * 2.3,
      cloud,
    );
  const stormRing = mesh(
    new THREE.RingGeometry(6, 6.15, 64),
    material("#d5a46e", {
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.8,
    }),
    mid.x,
    0.14,
    mid.z,
  );
  stormRing.rotation.x = -Math.PI / 2;
  const fleet = new Map();
  const white = material("#fefdf5"),
    blue = material("#2b84b0"),
    glass = material("#345c6c"),
    rotor = material("#5d7a83", {
      transparent: true,
      opacity: 0.5,
      side: THREE.DoubleSide,
    });
  for (const f of demand) {
    const g = new THREE.Group();
    g.scale.setScalar(1.65);
    g.userData.flightId = f.id;
    scene.add(g);
    mesh(
      new THREE.CapsuleGeometry(0.32, 1.25, 3, 6),
      white,
      0,
      0,
      0,
      g,
    ).rotation.x = Math.PI / 2;
    mesh(new THREE.BoxGeometry(2.3, 0.12, 0.4), blue, 0, 0, 0.15, g);
    mesh(new THREE.BoxGeometry(1.1, 0.1, 0.25), white, 0, 0.05, 0.8, g);
    mesh(
      new THREE.SphereGeometry(0.3, 8, 6),
      glass,
      0,
      0.13,
      -0.4,
      g,
    ).scale.set(0.8, 0.7, 1.2);
    for (const x of [-0.95, 0.95])
      for (const z of [-0.45, 0.65]) {
        mesh(
          new THREE.CylinderGeometry(0.47, 0.47, 0.025, 16),
          rotor,
          x,
          0.22,
          z,
          g,
        );
        mesh(
          new THREE.BoxGeometry(0.09, 0.12, 0.7),
          white,
          x,
          0.05,
          z * 0.5,
          g,
        );
      }
    fleet.set(f.id, g);
  }
  const selectedLabel = document.createElement("div");
  selectedLabel.className = "sf-aircraft-label";
  labels.append(selectedLabel);
  function screen(p) {
    const v = p.clone().project(camera);
    return [
      ((v.x + 1) / 2) * frame.clientWidth,
      ((1 - v.y) / 2) * frame.clientHeight,
    ];
  }
  function resize() {
    const w = frame.clientWidth,
      h = frame.clientHeight;
    renderer.setSize(w, h);
    const a = w / h;
    const span = w < 450 ? 71 : 63;
    camera.left = -span * a;
    camera.right = span * a;
    camera.top = span;
    camera.bottom = -span;
    camera.updateProjectionMatrix();
    render();
  }
  const raycaster = new THREE.Raycaster();
  renderer.domElement.addEventListener("pointerdown", (e) => {
    const rect = renderer.domElement.getBoundingClientRect();
    raycaster.setFromCamera(
      new THREE.Vector2(
        ((e.clientX - rect.left) / rect.width) * 2 - 1,
        (-(e.clientY - rect.top) / rect.height) * 2 + 1,
      ),
      camera,
    );
    const hit = raycaster.intersectObjects(
      [...fleet.values()].filter((g) => g.visible),
      true,
    )[0];
    if (!hit) return;
    let o = hit.object;
    while (o && !o.userData.flightId) o = o.parent;
    if (o) {
      selected = o.userData.flightId;
      $("#sf-flight").value = selected;
      updateHighlight();
      updateInfo();
      render();
      persist();
    }
  });
  function updateHighlight() {
    if (highlight) {
      scene.remove(highlight);
      highlight.traverse((o) => {
        o.geometry?.dispose();
        o.material?.dispose();
      });
    }
    highlight = new THREE.Group();
    scene.add(highlight);
    const f = plan.flights.find((f) => f.id === selected);
    for (let i = 0; i < f.path.length - 1; i++) {
      const k = edgeKey(f.path[i], f.path[i + 1]);
      const o = mesh(
        new THREE.TubeGeometry(curves[k].curve, 40, 0.14, 6, false),
        material(mode === "adaptive" ? "#177ab2" : "#c08b45"),
        0,
        0,
        0,
        highlight,
      );
      o.castShadow = false;
    }
  }
  function updateInfo() {
    const f = plan.flights.find((f) => f.id === selected),
      status = position(f, time);
    $("#sf-from").textContent = f.from;
    $("#sf-to").textContent = f.to;
    $("#sf-trip-names").textContent =
      byId[f.from].name + " → " + byId[f.to].name;
    $("#sf-departure").textContent = stamp(f.departure);
    $("#sf-arrival").textContent = stamp(f.arrival) + " / " + stamp(f.deadline);
    $("#sf-route").textContent = f.path.join(" → ");
    $("#sf-flight-status").textContent = {
      scheduled: "Scheduled · awaiting release",
      queued: "Queued · waiting at origin",
      airborne: "Airborne · corridor reserved",
      arrived:
        "Arrived · " + (f.arrival <= f.deadline ? "on time" : "after deadline"),
    }[status.state];
    $("#sf-trace").innerHTML =
      `<li><strong>${f.from} · request</strong>Released ${stamp(f.release)} · deadline ${stamp(f.deadline)}</li><li><strong>Router · ${f.rerouted ? "alternate selected" : "shortest route"}</strong>${f.distance.toFixed(1)} km · ${(f.departure - f.release).toFixed(1)} min ground wait</li><li><strong>Validator · committed</strong>${f.slots.length} resource reservations accepted</li>`;
  }
  // Pilot requests accepted by the sector agent; cleared when the scenario changes.
  let requests = { priority: [], avoid: {}, notBefore: {} };
  function replan(request) {
    const before = metrics(plan);
    requests = {
      priority: [...requests.priority, ...(request.priority || [])],
      avoid: { ...requests.avoid, ...request.avoid },
      notBefore: { ...requests.notBefore, ...request.notBefore },
    };
    const next = schedule(mode, storm, {
      now: time,
      keep: plan.flights.filter((f) => f.departure <= time),
      ...requests,
    });
    const errors = validate(next);
    if (!errors.length) {
      plans[mode] = plan = next;
      refresh();
    }
    return {
      plan: errors.length ? plan : next,
      errors,
      before,
      after: metrics(next),
    };
  }
  function rebuild() {
    requests = { priority: [], avoid: {}, notBefore: {} };
    plans = {
      fixed: schedule("fixed", storm),
      adaptive: schedule("adaptive", storm),
    };
    plan = plans[mode];
    refresh();
    atc?.reset(time);
  }
  function refresh() {
    base = metrics(plans.fixed);
    m = metrics(plan);
    $("#sf-ontime").textContent = m.onTime;
    $("#sf-delay").textContent = m.delay.toFixed(1);
    $("#sf-distance").textContent = Math.round(m.distance);
    $("#sf-ontime-delta").textContent =
      mode === "adaptive"
        ? `+${m.onTime - base.onTime} vs fixed routes`
        : "Baseline · identical requests";
    $("#sf-delay-delta").textContent =
      mode === "adaptive"
        ? `${Math.abs(m.delay - base.delay).toFixed(1)} min ${m.delay <= base.delay ? "less" : "more"} vs fixed`
        : "Includes ground waiting";
    $("#sf-distance-delta").textContent =
      mode === "adaptive"
        ? `+${((m.distance / base.distance - 1) * 100).toFixed(1)}% vs fixed routes`
        : "Shortest-route distance";
    $("#sf-conflicts").textContent = m.violations + " reservation conflicts";
    $("#sf-weather").checked = storm;
    all("[data-mode]").forEach((el) =>
      el.setAttribute("aria-pressed", el.dataset.mode === mode),
    );
    $("#sf-weather-status").textContent = storm
      ? "Forecast closure · min 08–24"
      : "Clear conditions · all corridors open";
    updateHighlight();
    updateInfo();
    render();
  }
  let atc;
  let lastAnnouncement = -1;
  function render() {
    if (!plan) return;
    const current = plan.flights.map((f) => ({ f, p: position(f, time) }));
    let active = 0,
      done = 0,
      queue = 0;
    for (const { f, p } of current) {
      const g = fleet.get(f.id);
      g.visible = p.state === "airborne";
      if (p.state === "airborne") {
        active++;
        const info = curves[edgeKey(p.a, p.b)],
          u = p.a === info.a ? p.progress : 1 - p.progress;
        g.position.copy(info.curve.getPoint(u));
        const tangent = info.curve
          .getTangent(u)
          .multiplyScalar(p.a === info.a ? 1 : -1);
        g.rotation.y = Math.atan2(-tangent.x, -tangent.z);
      }
      if (p.state === "arrived") done++;
      if (p.state === "queued") queue++;
    }
    cloud.visible = storm && time < 24;
    stormRing.visible = storm && time >= 8 && time < 24;
    routeLines["C-E"].material.color.set(
      storm && time >= 8 && time < 24 ? "#c78f5c" : "#8ab9ca",
    );
    for (const { el, p } of padLabels) {
      const [x, y] = screen(p);
      el.style.left = x + "px";
      el.style.top = y + "px";
    }
    const chosen = fleet.get(selected);
    selectedLabel.hidden = !chosen.visible;
    if (chosen.visible) {
      const [x, y] = screen(chosen.position);
      selectedLabel.style.left = x + "px";
      selectedLabel.style.top = y + "px";
      selectedLabel.textContent = selected;
    }
    for (const { el } of padLabels) {
      const id = el.querySelector("b").textContent.split(" ")[0],
        q = current.filter(
          (x) => x.f.from === id && x.p.state === "queued",
        ).length;
      el.querySelector("b").textContent = id + (q ? " · " + q + " queued" : "");
    }
    $("#sf-airborne").textContent = active + " airborne";
    $("#sf-clock").textContent = stamp(time);
    $("#sf-time").value = time;
    $("#sf-play").textContent = playing ? "Pause" : "Play demo";
    if (Math.floor(time) !== lastAnnouncement) {
      $("#sf-progress").textContent =
        `${done}/28 arrived · ${queue} queued · synthetic traffic · rule-based coordination`;
      lastAnnouncement = Math.floor(time);
    }
    renderer.render(scene, camera);
  }
  $("#sf-flight").innerHTML = demand
    .map(
      (f) => `<option value="${f.id}">${f.id} · ${f.from} → ${f.to}</option>`,
    )
    .join("");
  $("#sf-flight").value = selected;
  all("[data-mode]").forEach((el) =>
    el.addEventListener("click", () => {
      mode = el.dataset.mode;
      lastAnnouncement = -1;
      rebuild();
      persist();
    }),
  );
  $("#sf-weather").addEventListener("change", (e) => {
    storm = e.target.checked;
    lastAnnouncement = -1;
    rebuild();
    persist();
  });
  $("#sf-flight").addEventListener("change", (e) => {
    selected = e.target.value;
    updateHighlight();
    updateInfo();
    render();
    persist();
  });
  $("#sf-play").addEventListener("click", () => {
    atc.unlock();
    if (time >= 120) time = 0;
    playing = !playing;
    render();
    persist();
  });
  $("#sf-time").addEventListener("input", (e) => {
    time = +e.target.value;
    playing = false;
    atc.reset(time);
    updateInfo();
    render();
  });
  $("#sf-time").addEventListener("change", persist);
  $("#sf-speed").addEventListener("change", (e) => {
    speed = +e.target.value;
  });
  $("#sf-end").addEventListener("click", () => {
    time = Math.min(
      120,
      Math.max(
        ...plans.fixed.flights.map((f) => f.arrival),
        ...plans.adaptive.flights.map((f) => f.arrival),
      ),
    );
    playing = false;
    atc.reset(time);
    updateInfo();
    render();
    persist();
  });
  window.addEventListener("openai:set_globals", (e) => {
    const s = e.detail?.globals?.widgetState?.modelContent;
    if (!s) return;
    mode = s.mode === "fixed" ? "fixed" : "adaptive";
    storm = s.storm !== false;
    time = Math.max(0, Math.min(120, Number(s.time) || 0));
    if (demand.some((f) => f.id === s.selected)) selected = s.selected;
    $("#sf-flight").value = selected;
    playing = false;
    lastAnnouncement = -1;
    rebuild();
  });
  rebuild();
  atc = createATC({
    root,
    getPlan: () => plan,
    getTime: () => time,
    replan,
    focus(id) {
      if (selected === id) return;
      selected = id;
      $("#sf-flight").value = id;
      updateHighlight();
      updateInfo();
      render();
    },
  });
  new ResizeObserver(resize).observe(frame);
  resize();
  $("#sf-loading").hidden = true;
  let last = performance.now(),
    lastInfo = -1;
  function animate(now) {
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    if (playing && !atc.holding) {
      time = Math.min(120, time + dt * speed);
      if (time >= 120) {
        playing = false;
        persist();
      }
      if (Math.floor(time * 2) !== lastInfo) {
        updateInfo();
        lastInfo = Math.floor(time * 2);
      }
      render();
    }
    if (playing) atc.tick(time, selected);
    requestAnimationFrame(animate);
  }
  requestAnimationFrame(animate);
} catch (error) {
  $("#sf-loading").hidden = true;
  $("#sf-error").hidden = false;
  $("#sf-error").textContent = "The 3D scene could not start. " + error.message;
  console.error(error);
}

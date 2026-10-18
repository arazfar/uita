// The sparse showcase's original controls, driven only by committed presentation frames.
export function mountSceneControls({ C, viewer, entities, setPhotoreal }) {
  const $ = (id) => document.getElementById(id);
  const send = (action, value) =>
    parent.postMessage({ type: "uita:action", action, value }, location.origin);
  let selected = null,
    frame = null,
    cinematic = false,
    photo = true,
    lastPaint = 0;
  const strips = new Map();
  const runwayMarkers = new Map();
  fetch("data/airports.geojson")
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      for (const f of data?.features || []) {
        if (
          f.properties?.airport !== "SFO" ||
          f.geometry?.type !== "LineString"
        )
          continue;
        const name = ["28L", "28R"].find((r) =>
          f.properties.ref?.split("/").includes(r),
        );
        if (!name) continue;
        const coords = f.geometry.coordinates;
        runwayMarkers.set(
          name,
          viewer.entities.add({
            id: `research-runway-${name}`,
            show: false,
            polyline: {
              positions: C.Cartesian3.fromDegreesArray(coords.flat()),
              width: 7,
              clampToGround: true,
              material: C.Color.fromCssColorString("#f6c45a"),
            },
            position: C.Cartesian3.fromDegrees(...coords[0]),
            label: {
              text: `RWY ${name} · assigned destination`,
              font: "12px monospace",
              showBackground: true,
              heightReference: C.HeightReference.CLAMP_TO_GROUND,
              disableDepthTestDistance: Infinity,
              pixelOffset: new C.Cartesian2(0, -20),
            },
          }),
        );
      }
    })
    .catch(() => {}); // Aircraft cards retain runway information if map geometry is unavailable.

  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const duration = reduced ? 0 : 0.8;
  function airport() {
    cinematic = false;
    viewer.trackedEntity = undefined;
    viewer.camera.flyToBoundingSphere(
      new C.BoundingSphere(C.Cartesian3.fromDegrees(-122.375, 37.62, 0), 2000),
      {
        duration,
        offset: new C.HeadingPitchRange(
          (300 * Math.PI) / 180,
          (-30 * Math.PI) / 180,
          6000,
        ),
      },
    );
  }
  function overview() {
    cinematic = false;
    viewer.trackedEntity = undefined;
    viewer.camera.flyTo({
      destination: C.Cartesian3.fromDegrees(-122.2, 37.53, 38000),
      orientation: { heading: 0, pitch: -Math.PI / 2, roll: 0 },
      duration,
    });
  }
  function follow() {
    cinematic = false;
    const e = entities.get(selected);
    if (e?.show) viewer.trackedEntity = e;
  }
  document.querySelectorAll("#more [data-preset]").forEach((b) => b.remove());
  document.querySelector('[data-preset="1"]').onclick = overview;
  document.querySelector('[data-preset="2"]').onclick = () => {
    cinematic = false;
    viewer.trackedEntity = undefined;
    viewer.camera.flyTo({
      destination: C.Cartesian3.fromDegrees(-122.378, 37.619, 100),
      orientation: {
        heading: (94 * Math.PI) / 180,
        pitch: (-4.5 * Math.PI) / 180,
        roll: 0,
      },
      duration,
    });
  };
  document.querySelector('[data-preset="3"]').onclick = follow;
  $("bCine").classList.remove("on");
  $("bCine").onclick = () => {
    cinematic = !cinematic;
    viewer.trackedEntity = undefined;
    $("bCine").classList.toggle("on", cinematic);
  };
  $("bMore").onclick = () => {
    const open = $("bMore").getAttribute("aria-expanded") !== "true";
    $("bMore").setAttribute("aria-expanded", String(open));
    $("more").classList.toggle("open", open);
  };
  $('more').addEventListener('click',e=>{if(e.target.closest('button')){$('more').classList.remove('open');$('bMore').setAttribute('aria-expanded','false');}});
  $("bZin").onclick = () =>
    viewer.camera.zoomIn(viewer.camera.positionCartographic.height * 0.25);
  $("bZout").onclick = () =>
    viewer.camera.zoomOut(viewer.camera.positionCartographic.height * 0.25);
  $("bDet").onclick = () => document.body.classList.toggle("details");
  $("bPhoto").onclick = () => {
    photo = !photo;
    setPhotoreal(photo);
  };
  $("bBox").onclick = () => document.body.classList.toggle("letterbox");
  $("bPlay").onclick = () => send("play");
  $("bRestart").onclick = () => send("restart");
  $("bSnd").onclick = () => {
    const on = $("bSnd").getAttribute("aria-pressed") !== "true";
    $("bSnd").setAttribute("aria-pressed", String(on));
    send("speech", on);
  };
  $("fcClose").onclick = () =>
    parent.postMessage({ type: "uita:select", id: null }, location.origin);
  document
    .querySelectorAll("#speedbar [data-speed]")
    .forEach((b) => (b.onclick = () => send("speed", Number(b.dataset.speed))));
  viewer.scene.canvas.addEventListener("pointerdown", () => {
    cinematic = false;
    $("bCine").classList.remove("on");
  });
  addEventListener("keydown", (e) => {
    if (e.target.closest?.("input,select,textarea") || e.repeat) return;
    if(e.key === " " && e.target.closest?.("button")) return;
    const key = e.key.toLowerCase();
    const actions = {
      1: overview,
      2: () => document.querySelector('[data-preset="2"]').click(),
      3: follow,
      c: () => $("bCine").click(),
      d: () => $("bDet").click(),
      g: () => $("bPhoto").click(),
      l: () => $("bBox").click(),
      "+": () => $("bZin").click(),
      "-": () => $("bZout").click(),
      " ": () => send("play"),
      t: () => send("view"),
      "[": () => send("speed-step", -1),
      "]": () => send("speed-step", 1),
      escape: () => $("fcClose").click(),
    };
    if (actions[key]) {
      e.preventDefault();
      actions[key]();
    }
  });
  addEventListener("message", (e) => {
    if (
      e.origin !== location.origin ||
      e.source !== parent ||
      e.data?.type !== "uita:ui"
    )
      return;
    const { speed, playing, speech } = e.data;
    $("bPlay").textContent = playing ? "Pause" : "Play";
    $("bSnd").setAttribute("aria-pressed", String(!!speech));
    document.querySelectorAll("#speedbar [data-speed]").forEach((b) => {
      const on = Number(b.dataset.speed) === speed;
      b.disabled = Number(b.dataset.speed) > (e.data.maxSpeed || 60);
      b.classList.toggle("on", on);
      b.setAttribute("aria-checked", String(on));
    });
  });
  airport();
  return (next, id) => {
    frame = next;
    selected = id;
    document.querySelector('[data-preset="3"]').disabled =
      !entities.get(id)?.show;
    if (cinematic && !reduced) {
      const t = performance.now() / 1000;
      viewer.camera.lookAt(
        C.Cartesian3.fromDegrees(-122.375, 37.62, 0),
        new C.HeadingPitchRange(
          ((300 + t * 1.2) * Math.PI) / 180,
          (-30 * Math.PI) / 180,
          6000,
        ),
      );
      viewer.camera.lookAtTransform(C.Matrix4.IDENTITY);
    }
    if (performance.now() - lastPaint < 200) return;
    lastPaint = performance.now();
    const a = frame.aircraft.find((a) => a.id === selected);
    for (const [name, marker] of runwayMarkers)
      marker.show = !!a && a.runway === name && frame.mode !== "historical";
    $("fcard").style.display = a ? "block" : "none";
    if (a) {
      $("fcCs").textContent = a.callsign;
      $("fcType").textContent = a.aircraft_type || "Type unavailable";
      $("fcRoute").textContent =
        frame.mode === "historical"
          ? "Historical observation"
          : "Research simulation";
      $("fcStatus").textContent = a.status;
      $("fcGrid").replaceChildren();
      for (const [label, value] of [
        ["Assigned runway", a.runway || "Unavailable"],
        [
          "Altitude",
          Number.isFinite(a.altitude_ft)
            ? `${Math.round(a.altitude_ft).toLocaleString()} ft`
            : "Unknown",
        ],
        [
          "Ground speed",
          Number.isFinite(a.groundspeed_kt)
            ? `${Math.round(a.groundspeed_kt)} kt`
            : "Unavailable",
        ],
        [
          "Track",
          Number.isFinite(a.track_deg_true)
            ? `${Math.round(a.track_deg_true)}° true`
            : "Unavailable",
        ],
      ]) {
        const el = document.createElement("div");
        el.textContent = `${label} · ${value}`;
        $("fcGrid").append(el);
      }
      $("fcClr").textContent =
        "Clearances and verifier findings are available in Traffic & decisions.";
      $("fcSteps").replaceChildren();
    }
    $("stripcount").textContent = `${frame.aircraft.length} active`;
    const visibleIds = new Set();
    for (const a of frame.aircraft.slice(0, 30)) {
      visibleIds.add(a.id);
      let b = strips.get(a.id);
      if (!b) {
        b = document.createElement("button");
        b.onclick = () =>
          parent.postMessage(
            { type: "uita:select", id: a.id },
            location.origin,
          );
        strips.set(a.id, b);
        $("striplist").append(b);
      }
      b.textContent = `${a.callsign} · ${a.status}`;
    }
    for (const [id, b] of strips)
      if (!visibleIds.has(id)) {
        b.remove();
        strips.delete(id);
      }
    const ctx = $("rc").getContext("2d");
    ctx.clearRect(0, 0, 300, 224);
    ctx.strokeStyle = "#35535b";
    ctx.beginPath();
    ctx.arc(150, 112, 100, 0, Math.PI * 2);
    ctx.stroke();
    for (const a of frame.aircraft) {
      if (!Number.isFinite(a.longitude) || !Number.isFinite(a.latitude))
        continue;
      const x = 150 + (a.longitude + 122.375) * 240,
        y = 112 - (a.latitude - 37.62) * 300;
      if (x < 0 || x > 300 || y < 0 || y > 224) continue;
      ctx.fillStyle = a.id === selected ? "#f6c45a" : "#b7d4d9";
      ctx.fillRect(x - 2, y - 2, 4, 4);
    }
  };
}

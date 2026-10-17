import { plottable, validMessage } from "./research-client.js";
export function connectRenderer(render) {
  addEventListener("message", (e) => {
    if (
      validMessage(e, parent, "uita:frame") &&
      e.data.frame &&
      Array.isArray(e.data.frame.aircraft) &&
      Number.isFinite(e.data.frame.clock)
    ) {
      render(e.data.frame, e.data.selected);
      window.__uitaFrame = e.data.frame;
    }
  });
  parent.postMessage({ type: "uita:ready" }, location.origin);
}
export function selectAircraft(id) {
  parent.postMessage({ type: "uita:select", id }, location.origin);
}
export function mountDashboard({ C, viewer, altitudeOffset, setPhotoreal }) {
  document.body.classList.add("connected");
  viewer.clock.shouldAnimate = false;
  const style = document.createElement("style");
  style.textContent =
    ".connected #topbar,.connected #score,.connected #feed,.connected .details,.connected #cambar,.connected #card{display:none!important}";
  document.head.append(style);
  const entities = new Map();
  const toolbar = document.createElement("div");
  toolbar.style.cssText =
    "position:fixed;left:14px;bottom:20px;display:flex;gap:6px;z-index:3";
  const button = (text, fn) => {
    const b = document.createElement("button");
    b.textContent = text;
    b.style.cssText =
      "background:#142027;color:#e6edf0;border:1px solid #526975;padding:9px;border-radius:4px;cursor:pointer";
    b.onclick = fn;
    toolbar.append(b);
  };
  const overview = () => {
    viewer.trackedEntity = undefined;
    viewer.camera.flyTo({
      destination: C.Cartesian3.fromDegrees(-122.375, 37.59, 6500),
      orientation: { heading: 0, pitch: -1.05, roll: 0 },
      duration: 0,
    });
  };
  let selectedId = null;
  button("Overview", overview);
  button("Follow selected", () => {
    const e = entities.get(selectedId);
    if (e && e.show) viewer.trackedEntity = e;
  });
  button("Photoreal", () => setPhotoreal(true));
  document.body.append(toolbar);
  connectRenderer((frame, selected) => {
    selectedId = selected;
    const ids = new Set();
    for (const a of frame.aircraft.filter(plottable)) {
      ids.add(a.id);
      let entity = entities.get(a.id);
      if (!entity) {
        entity = viewer.entities.add({
          id: "research-" + a.id,
          model: {
            uri: "assets/airplane-google/model.glb",
            scale: 0.4,
            minimumPixelSize: 24,
            maximumScale: 4000,
          },
          label: {
            text: a.callsign,
            font: "12px monospace",
            pixelOffset: new C.Cartesian2(0, -22),
            showBackground: true,
            backgroundColor: C.Color.BLACK.withAlpha(0.7),
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
        });
        entities.set(a.id, entity);
      }
      const position = C.Cartesian3.fromDegrees(
        a.longitude,
        a.latitude,
        a.altitude_ft * 0.3048 + altitudeOffset(),
      );
      entity.position = position;
      entity.orientation = C.Transforms.headingPitchRollQuaternion(
        position,
        new C.HeadingPitchRoll(
          (((a.track_deg_true ?? 0) - 90) * Math.PI) / 180,
          0,
          0,
        ),
      );
      entity.label.fillColor =
        selected === a.id ? C.Color.YELLOW : C.Color.WHITE;
      entity.show = true;
    }
    for (const [id, e] of entities) if (!ids.has(id)) e.show = false;
    viewer.scene.requestRender();
  });
  const handler = new C.ScreenSpaceEventHandler(viewer.scene.canvas);
  handler.setInputAction((e) => {
    const hit = viewer.scene.pick(e.position);
    const id = hit?.id?.id;
    if (typeof id === "string" && id.startsWith("research-"))
      selectAircraft(id.slice(9));
  }, C.ScreenSpaceEventType.LEFT_CLICK);
  overview();
  addEventListener("keydown", (e) => {
    if (e.key === "g") setPhotoreal(true);
  });
}

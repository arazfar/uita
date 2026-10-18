import { mountSceneControls } from "./research-scene-controls.js";
import { plottable, validMessage, displayFrame } from "./research-client.js";
export function connectRenderer(render, visibility = () => {}) {
  let frames = [],
    anchor = 0,
    received = 0,
    rate = 0,
    selected = null,
    active = true;
  const ready = setInterval(
    () => parent.postMessage({ type: "uita:ready" }, location.origin),
    500,
  );
  addEventListener("message", (e) => {
    if (validMessage(e, parent, "uita:buffer") && Array.isArray(e.data.frames))
      frames = e.data.frames;
    if (
      validMessage(e, parent, "uita:playhead") &&
      Number.isFinite(e.data.clock)
    ) {
      clearInterval(ready);
      anchor = e.data.clock;
      received = performance.now();
      rate = Number(e.data.rate) || 0;
      selected = e.data.selected;
      active = e.data.active !== false;
    }
    if (validMessage(e, parent, "uita:visibility")) { active = !!e.data.active; visibility(active); }
  });
  function animate() {
    if (active && frames.length) {
      const clock = Math.min(
        frames.at(-1).clock,
        anchor + ((performance.now() - received) / 1000) * rate,
      );
      const frame = displayFrame(frames, clock);
      if (frame) {
        render(frame, selected, frames, clock);
        window.__uitaFrame = frame;
      }
    }
    requestAnimationFrame(animate);
  }
  requestAnimationFrame(animate);
  parent.postMessage({ type: "uita:ready" }, location.origin);
}
export function selectAircraft(id) {
  parent.postMessage({ type: "uita:select", id }, location.origin);
}
export function mountDashboard({ C, viewer, altitudeOffset, setPhotoreal }) {
  document.body.classList.add("connected");
  viewer.clock.shouldAnimate = false;
  const entities = new Map();
  const unknownPositions = new Map();
  let sourceId = null;
  const updateControls = mountSceneControls({C, viewer, entities, setPhotoreal});
  let trailClock = -Infinity,
    trailSource = null;
  connectRenderer((frame, selected, frames, clock) => {
    updateControls(frame, selected);
    if (sourceId !== frame.source_id) {
      for (const entity of [...entities.values(), ...unknownPositions.values()])
        viewer.entities.remove(entity);
      entities.clear();
      unknownPositions.clear();
      sourceId = frame.source_id;
    }
    const unknownIds = new Set();
    for (const a of frame.aircraft) {
      if (
        a.status !== "observed" ||
        Number.isFinite(a.altitude_ft) ||
        !Number.isFinite(a.longitude) ||
        !Number.isFinite(a.latitude)
      )
        continue;
      unknownIds.add(a.id);
      let marker = unknownPositions.get(a.id);
      if (!marker) {
        marker = viewer.entities.add({
          id: "research-position-" + a.id,
          point: {
            pixelSize: 7,
            color: C.Color.fromCssColorString("#adc9ce"),
            heightReference: C.HeightReference.CLAMP_TO_GROUND,
            disableDepthTestDistance: Infinity,
          },
          label: {
            text: a.callsign + " · altitude unknown",
            font: "11px monospace",
            pixelOffset: new C.Cartesian2(0, -16),
            heightReference: C.HeightReference.CLAMP_TO_GROUND,
            showBackground: true,
            backgroundColor: C.Color.BLACK.withAlpha(0.7),
            disableDepthTestDistance: Infinity,
          },
        });
        unknownPositions.set(a.id, marker);
      }
      marker.position = C.Cartesian3.fromDegrees(a.longitude, a.latitude);
      marker.show = true;
      marker.label.show = selected === a.id || unknownIds.size <= 8;
    }
    for (const [id, marker] of unknownPositions)
      if (!unknownIds.has(id)) marker.show = false;
    const ids = new Set();
    for (const [index, a] of frame.aircraft.filter(plottable).entries()) {
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
      entity.label.show = index < 24 || selected === a.id;
      entity.label.fillColor =
        selected === a.id ? C.Color.YELLOW : C.Color.WHITE;
      entity.show = true;
      if (
        clock - trailClock >= 2 ||
        clock < trailClock ||
        trailSource !== frame.source_id
      ) {
        const positions = frames
          .filter((f) => f.clock <= clock && f.clock >= clock - 90)
          .map((f) => f.aircraft.find((x) => x.id === a.id))
          .filter((x) => x && plottable(x))
          .map((x) =>
            C.Cartesian3.fromDegrees(
              x.longitude,
              x.latitude,
              x.altitude_ft * 0.3048 + altitudeOffset(),
            ),
          );
        if (positions.length > 1)
          entity.polyline = {
            positions,
            width: 1.5,
            material: C.Color.fromCssColorString(
              selected === a.id ? "#ffdf8a" : "#8fcce0",
            ).withAlpha(0.6),
          };
        else entity.polyline = undefined;
      }
    }
    for (const [id, e] of entities) if (!ids.has(id)) e.show = false;
    if (
      clock - trailClock >= 2 ||
      clock < trailClock ||
      trailSource !== frame.source_id
    ) {
      trailClock = clock;
      trailSource = frame.source_id;
    }
    viewer.scene.requestRender();
  }, active => { viewer.useDefaultRenderLoop = active; });
  viewer.scene.renderError.addEventListener(() => parent.postMessage({type:"uita:renderer-error"},location.origin));
  viewer.scene.canvas.addEventListener("webglcontextlost", () => parent.postMessage({type:"uita:renderer-error"},location.origin));
  const handler = new C.ScreenSpaceEventHandler(viewer.scene.canvas);
  handler.setInputAction((e) => {
    const hit = viewer.scene.pick(e.position);
    const id = hit?.id?.id;
    if (typeof id === "string" && id.startsWith("research-"))
      selectAircraft(
        id.startsWith("research-position-") ? id.slice(18) : id.slice(9),
      );
  }, C.ScreenSpaceEventType.LEFT_CLICK);
  addEventListener("keydown", (e) => {
    if (e.key === "g") setPhotoreal(true);
  });
}

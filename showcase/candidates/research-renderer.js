import { arrivalLabel, arrivalTone, TONE_CSS } from "./research-arrivals.js";
import { mountSceneControls } from "./research-scene-controls.js";
import { plottable, validMessage, displayFrame } from "./research-client.js";
export function connectRenderer(render, visibility = () => {}) {
  let frames = [],
    anchor = 0,
    received = 0,
    rate = 0,
    selected = null,
    highlightedAircraft = null,
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
      highlightedAircraft = e.data.highlightedAircraft;
      active = e.data.active !== false;
    }
    if (validMessage(e, parent, "uita:visibility")) {
      active = !!e.data.active;
      visibility(active);
    }
  });
  function animate() {
    if (active && frames.length) {
      const clock = Math.min(
        frames.at(-1).clock,
        anchor + ((performance.now() - received) / 1000) * rate,
      );
      const frame = displayFrame(frames, clock);
      if (frame) {
        render(
          { ...frame, highlighted_aircraft_id: highlightedAircraft },
          selected,
          frames,
          clock,
        );
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
  let paintedFrame = null,
    paintedCount = 0;
  viewer.scene.postRender.addEventListener(() => {
    if (paintedFrame)
      window.__uitaPaintedFrame = {
        source_id: paintedFrame.source_id,
        clock: paintedFrame.clock,
        at: Date.now(),
        count: ++paintedCount,
      };
  });
  const entities = new Map();
  let routeKey = null,
    routePreview = null,
    mergeMarker = null;

  const unknownPositions = new Map();
  let sourceId = null;
  const updateControls = mountSceneControls({
    C,
    viewer,
    entities,
    setPhotoreal,
  });
  const trails = new Map(); // aircraft id -> { line, proj, positions, ahead, color, width }
  // Test hook: visible trail lengths and projections per aircraft.
  window.__uitaTrails = () => [...trails].map(([id, t]) => ({ id, points: t.line.show ? t.positions.length : 0, projection: t.proj.show }));
  // Per-aircraft position history (sim clock -> [clock, lon, lat, alt_ft]), up to 8 minutes.
  // Reset when the source changes or the playhead seeks backwards.
  const history = new Map();
  let trailClock = -Infinity,
    trailSource = null;
  function remember(frames, clock) {
    for (const f of frames) {
      if (f.clock > clock || f.clock < clock - 480) continue;
      for (const x of f.aircraft) {
        if (!plottable(x)) continue;
        let h = history.get(x.id);
        if (!h) history.set(x.id, (h = new Map()));
        if (!h.has(f.clock)) h.set(f.clock, [f.clock, x.longitude, x.latitude, x.altitude_ft]);
      }
    }
    for (const [id, h] of history) {
      for (const t of h.keys()) if (t < clock - 480) h.delete(t);
      if (!h.size) history.delete(id);
      else if (h.size > 1) history.set(id, new Map([...h].sort((p, q) => p[0] - q[0])));
    }
  }
  connectRenderer(
    (frame, selected, frames, clock) => {
      paintedFrame = frame;
      const trailDue =
        clock - trailClock >= 2 ||
        clock < trailClock ||
        trailSource !== frame.source_id;
      if (trailSource !== frame.source_id || clock < trailClock - 5) history.clear();
      if (trailDue) remember(frames, clock);
      updateControls(frame, selected);
      const routeAircraft = frame.aircraft.find((a) => a.id === selected);
      const route = routeAircraft?.route;
      const nextRouteKey = route
        ? `${frame.source_id}:${selected}:${route.id}:${route.version}:${routeAircraft.runway}`
        : null;
      if (nextRouteKey !== routeKey) {
        if (routePreview) viewer.entities.remove(routePreview);
        if (mergeMarker) viewer.entities.remove(mergeMarker);
        routePreview = mergeMarker = null;
        routeKey = nextRouteKey;
        if (route?.preview?.length > 1) {
          routePreview = viewer.entities.add({
            polyline: {
              positions: C.Cartesian3.fromDegreesArray(route.preview.flat()),
              width: 2,
              clampToGround: true,
              material: new C.PolylineDashMaterialProperty({
                color: C.Color.fromCssColorString("#b4d9ed").withAlpha(0.65),
              }),
            },
          });
          mergeMarker = viewer.entities.add({
            position: C.Cartesian3.fromDegrees(...route.merge),
            label: {
              text: "Intended merge · synthetic route",
              font: "11px monospace",
              showBackground: true,
              heightReference: C.HeightReference.CLAMP_TO_GROUND,
              disableDepthTestDistance: Infinity,
            },
          });
        }
      }

      if (sourceId !== frame.source_id) {
        if (viewer.trackedEntity) {
          const destination = viewer.camera.positionWC.clone(),
            direction = viewer.camera.directionWC.clone(),
            up = viewer.camera.upWC.clone();
          viewer.trackedEntity = undefined;
          viewer.camera.setView({
            destination,
            orientation: { direction, up },
          });
        }
        for (const entity of [
          ...entities.values(),
          ...unknownPositions.values(),
        ])
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
        entity.label.text = a.arrival_cue
          ? `${a.callsign} · ${arrivalLabel(a)}`
          : a.callsign;
        entity.label.show = index < 24 || selected === a.id || !!a.arrival_cue;
        entity.label.fillColor =
          selected === a.id || frame.highlighted_aircraft_id === a.id
            ? C.Color.YELLOW
            : C.Color.fromCssColorString(TONE_CSS[arrivalTone(a)]);
        entity.show = true;
        if (trailDue) {
          // Route trail: the last 8 minutes, coloured by what the aircraft is doing
          // (descending cyan, climbing amber, level grey, ground faint), plus a dashed
          // 2-minute projection ahead for airborne traffic. Points come from the
          // renderer's own history: the shell only buffers the current 2-minute window.
          const pts = [...(history.get(a.id)?.values() || [])].filter((p) => p[0] < clock);
          pts.push([clock, a.longitude, a.latitude, a.altitude_ft]);
          const toCart = (p) => C.Cartesian3.fromDegrees(p[1], p[2], p[3] * 0.3048 + altitudeOffset());
          const recent = pts.filter(([t]) => t >= clock - 60);
          const dAlt = recent.length > 1 ? recent.at(-1)[3] - recent[0][3] : 0;
          const onGround = a.altitude_ft < 150;
          const tone =
            selected === a.id
              ? "#ffdf8a"
              : onGround
                ? "rgba(255,255,255,0.35)"
                : dAlt < -150
                  ? "#5bc8ff"
                  : dAlt > 150
                    ? "#ffb547"
                    : "#c9d3da";
          // Created once with callback properties: Cesium draws dynamic polylines every
          // frame, whereas re-assigning static polylines rebuilds them asynchronously
          // and they can be replaced again before ever appearing.
          let t = trails.get(a.id);
          if (!t) {
            t = { positions: [], ahead: [], color: C.Color.WHITE, width: 2 };
            t.line = viewer.entities.add({
              polyline: {
                positions: new C.CallbackProperty(() => t.positions, false),
                width: new C.CallbackProperty(() => t.width, false),
                material: new C.ColorMaterialProperty(new C.CallbackProperty(() => t.color, false)),
                arcType: C.ArcType.NONE,
              },
            });
            t.proj = viewer.entities.add({
              polyline: {
                positions: new C.CallbackProperty(() => t.ahead, false),
                width: 1.5,
                material: new C.PolylineDashMaterialProperty({
                  color: new C.CallbackProperty(() => t.color.withAlpha(0.7), false),
                  dashLength: 12,
                }),
                arcType: C.ArcType.NONE,
              },
            });
            trails.set(a.id, t);
          }
          t.positions = pts.length > 1 ? pts.map(toCart) : [];
          t.color = C.Color.fromCssColorString(tone).withAlpha(onGround ? 0.35 : 0.85);
          t.width = selected === a.id ? 3 : 2;
          t.line.show = t.positions.length > 1;
          const last = pts.at(-1), prev = recent.length > 1 ? recent[0] : null;
          if (!onGround && prev && last[0] > prev[0]) {
            const k = 120 / (last[0] - prev[0]);
            t.ahead = [toCart(last), toCart([0, last[1] + (last[1] - prev[1]) * k, last[2] + (last[2] - prev[2]) * k, Math.max(0, last[3] + (last[3] - prev[3]) * k)])];
            t.proj.show = true;
          } else t.proj.show = false;
        }
      }
      for (const [id, e] of entities) if (!ids.has(id)) e.show = false;
      for (const [id, t] of trails) if (!ids.has(id)) t.line.show = t.proj.show = false;
      if (
        clock - trailClock >= 2 ||
        clock < trailClock ||
        trailSource !== frame.source_id
      ) {
        trailClock = clock;
        trailSource = frame.source_id;
      }
      viewer.scene.requestRender();
    },
    (active) => {
      viewer.useDefaultRenderLoop = active;
    },
  );
  viewer.scene.renderError.addEventListener(() =>
    parent.postMessage({ type: "uita:renderer-error" }, location.origin),
  );
  viewer.scene.canvas.addEventListener("webglcontextlost", () =>
    parent.postMessage({ type: "uita:renderer-error" }, location.origin),
  );
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

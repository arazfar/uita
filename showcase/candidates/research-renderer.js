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
  const projections = new Map();
  let trailClock = -Infinity,
    trailSource = null;
  connectRenderer(
    (frame, selected, frames, clock) => {
      paintedFrame = frame;
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
        if (
          clock - trailClock >= 2 ||
          clock < trailClock ||
          trailSource !== frame.source_id
        ) {
          // Route trail: the last 8 minutes, coloured by what the aircraft is doing
          // (descending cyan, climbing amber, level grey, ground faint), plus a dashed
          // 2-minute projection ahead for airborne traffic.
          const pts = frames
            .filter((f) => f.clock <= clock && f.clock >= clock - 480)
            .map((f) => [f.clock, f.aircraft.find((x) => x.id === a.id)])
            .filter(([, x]) => x && plottable(x));
          const positions = pts.map(([, x]) =>
            C.Cartesian3.fromDegrees(
              x.longitude,
              x.latitude,
              x.altitude_ft * 0.3048 + altitudeOffset(),
            ),
          );
          const recent = pts.filter(([t]) => t >= clock - 60);
          const dAlt = recent.length > 1 ? recent.at(-1)[1].altitude_ft - recent[0][1].altitude_ft : 0;
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
          if (positions.length > 1)
            entity.polyline = {
              positions,
              width: selected === a.id ? 3 : 2,
              material: C.Color.fromCssColorString(tone).withAlpha(onGround ? 0.35 : 0.85),
            };
          else entity.polyline = undefined;
          let proj = projections.get(a.id);
          if (!proj) {
            proj = viewer.entities.add({ polyline: { positions: [], width: 1.5,
              material: new C.PolylineDashMaterialProperty({ color: C.Color.WHITE.withAlpha(0.6), dashLength: 12 }) } });
            projections.set(a.id, proj);
          }
          const last = pts.at(-1), prev = recent.length > 1 ? recent[0] : null;
          if (!onGround && last && prev && last[0] > prev[0]) {
            const k = 120 / (last[0] - prev[0]);
            const [, l] = last, [, q] = prev;
            proj.polyline.positions = [
              C.Cartesian3.fromDegrees(l.longitude, l.latitude, l.altitude_ft * 0.3048 + altitudeOffset()),
              C.Cartesian3.fromDegrees(
                l.longitude + (l.longitude - q.longitude) * k,
                l.latitude + (l.latitude - q.latitude) * k,
                Math.max(0, l.altitude_ft + (l.altitude_ft - q.altitude_ft) * k) * 0.3048 + altitudeOffset(),
              ),
            ];
            proj.polyline.material = new C.PolylineDashMaterialProperty({ color: C.Color.fromCssColorString(tone).withAlpha(0.7), dashLength: 12 });
            proj.show = true;
          } else proj.show = false;
        }
      }
      for (const [id, e] of entities) if (!ids.has(id)) e.show = false;
      for (const [id, e] of projections) if (!ids.has(id)) e.show = false;
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

/** Cab-relative metres and radians. The eye stays inside the existing console bay. */
export const TOWER_DESK_POSE = Object.freeze({
  eye: Object.freeze({ x: 0.02, y: 1.68, z: 0.32 }),
  yaw: -0.08,
  pitch: -0.12,
  fov: 58,
});

/** Keep shortcuts out of forms and native controls, including their child elements. */
export function isTowerShortcutTarget(target) {
  return !target?.closest?.(
    'input, textarea, select, button, a, [contenteditable]:not([contenteditable="false"]), [role="textbox"], [role="slider"]',
  );
}

const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
const LOOK_KEYS = new Set(["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"]);
const LEAN_KEYS = new Set(["q", "e"]);

/**
 * Adds first-person input without owning the renderer, traffic, presets, or buttons.
 * `pose` is the existing mutable { eye, yaw, pitch, fov } camera state.
 * Call update(deltaSeconds) once per rendered frame, and add its returned local offset
 * to pose.eye before cab.localToWorld(). Do not accumulate that offset into pose.eye.
 */
export function createTowerCameraControls({
  canvas,
  pose,
  onTakeControl,
  onPick,
}) {
  const doc = canvas.ownerDocument;
  const win = doc.defaultView;
  const motion = win.matchMedia("(prefers-reduced-motion: reduce)");
  const keys = new Set();
  const offset = { x: 0, y: 0, z: 0 };
  const removers = [];
  let anchorYaw = pose.yaw;
  let pointer = null;
  let disposed = false;
  let lean = 0;
  const priorTouchAction = canvas.style.touchAction;
  const priorTabIndex = canvas.getAttribute("tabindex");
  canvas.style.touchAction = "none";
  if (priorTabIndex === null) canvas.tabIndex = 0;

  function listen(target, event, handler, options) {
    target.addEventListener(event, handler, options);
    removers.push(() => target.removeEventListener(event, handler, options));
  }
  function look(yawDelta, pitchDelta) {
    // A seated controller can turn their head, but cannot rotate through the rear wall.
    const delta = pose.yaw - anchorYaw;
    const relativeYaw = Math.atan2(Math.sin(delta), Math.cos(delta)) + yawDelta;
    pose.yaw = anchorYaw + clamp(relativeYaw, -Math.PI * 0.75, Math.PI * 0.75);
    pose.pitch = clamp(pose.pitch + pitchDelta, -1.15, 0.65);
  }
  function releasePointer() {
    const id = pointer?.id;
    pointer = null;
    if (id !== undefined && canvas.hasPointerCapture?.(id))
      canvas.releasePointerCapture(id);
  }
  function clearInput() {
    releasePointer();
    keys.clear();
    // Returning from another tab must never resume a held lean or turn.
    lean = 0;
    offset.x = offset.y = offset.z = 0;
  }
  listen(canvas, "pointerdown", (event) => {
    if (event.button !== 0 || event.isPrimary === false || pointer) return;
    canvas.focus({ preventScroll: true });
    pointer = {
      id: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      startX: event.clientX,
      startY: event.clientY,
      moved: false,
    };
    canvas.setPointerCapture(event.pointerId);
    onTakeControl?.();
  });
  listen(canvas, "pointermove", (event) => {
    if (!pointer || event.pointerId !== pointer.id) return;
    const scale = (pose.fov / 60) * 0.0042;
    look(
      (event.clientX - pointer.x) * scale,
      (event.clientY - pointer.y) * scale,
    );
    pointer.x = event.clientX;
    pointer.y = event.clientY;
    pointer.moved ||=
      Math.hypot(
        event.clientX - pointer.startX,
        event.clientY - pointer.startY,
      ) >= 5;
  });
  listen(canvas, "pointerup", (event) => {
    if (!pointer || event.pointerId !== pointer.id) return;
    const clicked =
      !pointer.moved &&
      Math.hypot(
        event.clientX - pointer.startX,
        event.clientY - pointer.startY,
      ) < 5;
    releasePointer();
    if (clicked) onPick?.(event.clientX, event.clientY);
  });
  listen(canvas, "pointercancel", releasePointer);
  listen(canvas, "lostpointercapture", () => {
    pointer = null;
  });
  listen(canvas, "blur", clearInput);
  listen(win, "blur", clearInput);
  listen(doc, "visibilitychange", () => {
    if (doc.hidden) clearInput();
  });
  listen(win, "keydown", (event) => {
    if (
      event.altKey ||
      event.ctrlKey ||
      event.metaKey ||
      !isTowerShortcutTarget(event.target)
    )
      return;
    const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
    if (!LOOK_KEYS.has(key) && !LEAN_KEYS.has(key)) return;
    event.preventDefault();
    keys.add(key);
    onTakeControl?.();
  });
  listen(win, "keyup", (event) =>
    keys.delete(event.key.length === 1 ? event.key.toLowerCase() : event.key),
  );

  return {
    get reducedMotion() {
      return motion.matches;
    },
    /** Reset around each preset's viewing direction; preset positions remain authoritative. */
    resetLook(yaw = pose.yaw) {
      clearInput();
      anchorYaw = yaw;
    },
    /** Explicit presets still work with reduced motion, but do not animate between seats. */
    transitionDuration(seconds) {
      return motion.matches ? 0 : seconds;
    },
    cinematicFovMultiplier(seconds, enabled) {
      return enabled && !motion.matches
        ? 1 + Math.sin(seconds * 0.45) * 0.012
        : 1;
    },
    update(deltaSeconds) {
      if (disposed) return offset;
      // Clamp long frames after tab suspension; input must never teleport the viewpoint.
      const dt = clamp(
        Number.isFinite(deltaSeconds) ? deltaSeconds : 0,
        0,
        0.05,
      );
      const yaw =
        Number(keys.has("ArrowLeft")) - Number(keys.has("ArrowRight"));
      const pitch = Number(keys.has("ArrowUp")) - Number(keys.has("ArrowDown"));
      if (yaw || pitch)
        look(
          (yaw * dt * 0.8 * pose.fov) / 58,
          (pitch * dt * 0.65 * pose.fov) / 58,
        );
      const target = (Number(keys.has("e")) - Number(keys.has("q"))) * 0.22;
      lean = motion.matches
        ? target
        : lean + (target - lean) * (1 - Math.exp(-dt * 14));
      if (Math.abs(lean) < 0.00001) lean = 0;
      offset.x = lean;
      return offset;
    },
    dispose() {
      clearInput();
      disposed = true;
      removers.forEach((remove) => remove());
      canvas.style.touchAction = priorTouchAction;
      if (priorTabIndex === null) canvas.removeAttribute("tabindex");
      else canvas.setAttribute("tabindex", priorTabIndex);
    },
  };
}

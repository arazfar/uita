import { AIRFRAMES } from "./tower-flight-dynamics.js";

const RAD = Math.PI / 180;
const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
const finite = (x, fallback = 0) => (Number.isFinite(x) ? x : fallback);
const angle = (a, b) => (((b - a + 540) % 360) - 180) * RAD;

const WIDEBODY = Object.freeze({
  ...AIRFRAMES.heavy,
  name: "Twin-engine widebody representative",
  length: 64,
  span: 61,
  upperDeck: false,
});

// These are representative silhouettes. Never infer a type from an airline callsign.
export function airframeForAircraft(a) {
  const type = a.aircraft_type || "";
  if (/^B74/.test(type)) return AIRFRAMES.heavy;
  return /^(B77|B78|A33|A35)/.test(type) ? WIDEBODY : AIRFRAMES.medium;
}

/** Keep source positions and lifecycle authoritative. Only attitude and mechanical
 * configuration are visual estimates; they never enter telemetry or KPI evidence.
 * An independent client flight model would move aircraft away from their evidence.
 */
export function connectedAircraftState({
  aircraft: a,
  frame,
  frames = [],
  clock,
  project,
  groundY = 0,
}) {
  const [x, z] = project(a.longitude, a.latitude);
  const observed = frame.mode === "historical" || a.status === "observed";
  const ground =
    a.arrival_cue?.phase === "on_ground" ||
    (!observed &&
      [
        "taxi",
        "landing-roll",
        "runway-exit",
        "holding-short",
        "takeoff-roll",
        "line-up",
      ].includes(a.status));
  const sample = frames.find(
    (f) =>
      f.source_id === frame.source_id &&
      f.clock > clock &&
      f.clock - clock <= 15,
  );
  const next = sample?.aircraft.find(
    (b) =>
      b.id === a.id &&
      b.status === a.status &&
      b.provenance?.segment_id === a.provenance?.segment_id,
  );
  const dt = sample ? sample.clock - clock : 0;
  let speed = finite(a.groundspeed_kt) * 0.514444,
    vertical = 0,
    turn = 0;
  if (next && dt > 0.05 && Number.isFinite(next.altitude_ft)) {
    const [nx, nz] = project(next.longitude, next.latitude);
    const derivedSpeed = Math.hypot(nx - x, nz - z) / dt;
    // Segment jumps must never become violent attitude or wheel movement.
    if (derivedSpeed < 350) {
      speed = derivedSpeed;
      vertical = clamp(
        ((next.altitude_ft - a.altitude_ft) * 0.3048) / dt,
        -25,
        25,
      );
      if (
        Number.isFinite(a.track_deg_true) &&
        Number.isFinite(next.track_deg_true)
      )
        turn = clamp(
          angle(a.track_deg_true, next.track_deg_true) / dt,
          -0.07,
          0.07,
        );
    }
  }
  const altitude = finite(a.altitude_ft) * 0.3048;
  const approach =
    ["approach", "flare"].includes(a.status) || Boolean(a.arrival_cue);
  const y = observed
    ? altitude - groundY
    : ground
      ? 0
      : Math.max(0, altitude - 13 * 0.3048);
  const pitch = ground
    ? 0
    : clamp(
        Math.atan2(vertical, Math.max(speed, 30)) + (approach ? 0.07 : 0.04),
        -0.035,
        0.22,
      );
  const heading = finite(a.track_deg_true) * RAD;
  const gear =
    ground || (approach && y < 750) ? 1 : clamp(1 - (y - 15) / 45, 0, 1);
  const flap = ground
    ? speed > 18
      ? 1
      : 0
    : approach && y < 900
      ? clamp(1 - y / 1800, 0.4, 1)
      : y < 180
        ? 0.5
        : 0;
  return {
    x,
    y,
    z,
    dx: Math.sin(heading),
    dy: Math.tan(pitch),
    dz: -Math.cos(heading),
    pitch,
    // Model nose is +Z: positive local roll lowers the right wing in a right turn.
    bank: ground ? 0 : clamp(Math.atan((speed * turn) / 9.80665), -0.44, 0.44),
    speed,
    onGround: ground,
    vis: true,
    gear,
    flap,
    spoilers: ground && approach && speed > 25 ? 1 : 0,
    // Absolute playhead produces stable configuration when seeking or pausing.
    wheelAngle: ground ? (((clock % 1000) * speed) / 0.45) % (2 * Math.PI) : 0,
    phase: a.status,
    configurationBasis: "visual estimate",
  };
}

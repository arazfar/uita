/** Tower flight model. SI units; local y is wheel height above the runway.
 * Reduced-order longitudinal forces, not a certified aircraft/engine model.
 * Profiles are explicit scenario assumptions, never inferred from a callsign.
 */
const G = 9.80665,
  RAD = Math.PI / 180,
  STEP = 1 / 60;
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const approach = (a, b, rate, dt) => a + clamp(b - a, -rate * dt, rate * dt);
export const AIRFRAMES = Object.freeze({
  heavy: Object.freeze({
    name: "747-400 representative",
    mass: 300000,
    area: 541,
    span: 64.4,
    thrust: 1000000,
    vr: 78,
    climbSpeed: 94,
    approachSpeed: 77,
    climbRate: 9,
    cl0: 0.48,
    clAlpha: 4.8,
    clMax: 2.2,
    cd0: 0.032,
    induced: 0.045,
    length: 70.7,
  }),
  medium: Object.freeze({
    name: "A320-class representative",
    mass: 62000,
    area: 122.6,
    span: 34.1,
    thrust: 240000,
    vr: 70,
    climbSpeed: 84,
    approachSpeed: 70,
    climbRate: 8,
    cl0: 0.5,
    clAlpha: 4.8,
    clMax: 2.4,
    cd0: 0.034,
    induced: 0.045,
    length: 37.6,
  }),
});

export function runwayFrame(runway) {
  const dx = runway.W[0] - runway.E[0],
    dz = runway.W[1] - runway.E[1];
  const length = Math.hypot(dx, dz);
  if (!Number.isFinite(length) || length < 1000)
    throw new Error("Invalid tower runway geometry");
  return {
    x: runway.E[0],
    z: runway.E[1],
    ux: dx / length,
    uz: dz / length,
    length,
  };
}

export function weatherForRunway(runway, metar = {}) {
  // METAR direction is degrees TRUE, wind FROM; x=east, z=south.
  const direction = Number(metar.wdir),
    knots = Number(metar.wspd);
  const valid =
    metar.wdir != null &&
    metar.wspd != null &&
    Number.isFinite(direction) &&
    Number.isFinite(knots) &&
    knots >= 0;
  const a = (valid ? direction : 0) * RAD,
    speed = valid ? knots * 0.514444 : 0;
  const wx = -Math.sin(a) * speed,
    wz = Math.cos(a) * speed;
  const temperature = Number(metar.temp);
  const kelvin = (Number.isFinite(temperature) ? temperature : 15) + 273.15;
  const pressure = Number(metar.altim);
  const density =
    ((pressure > 900 && pressure < 1100 ? pressure : 1013.25) * 100) /
    (287.05 * kelvin);
  return {
    along: wx * runway.ux + wz * runway.uz,
    cross: wx * -runway.uz + wz * runway.ux,
    density,
    source: valid ? "bundled METAR snapshot" : "calm ISA fallback",
    raw: metar.rawOb || null,
  };
}

/** Pre-integrate at 60 Hz so replay/seek and rendering FPS cannot change physics.
 * Guidance requests vertical speed and airspeed; forces determine acceleration.
 * Crosswind crab cancels drift on the centerline. Lateral turbulence is not modeled.
 */
export function createFlight({
  operation,
  runway,
  profile = AIRFRAMES.medium,
  weather = weatherForRunway(runway),
  taxiRoute = null,
  duration = taxiRoute && operation === "arrival" ? 360 : 240,
}) {
  if (!["arrival", "departure"].includes(operation))
    throw new Error("Unknown tower flight operation");
  const p = profile,
    arrival = operation === "arrival",
    glide = Math.tan(3 * RAD);
  const initialGroundSpeed =
    p.approachSpeed / Math.sqrt(weather.density / 1.225) + weather.along;
  const state = {
    time: 0,
    s: arrival ? -3800 : 90,
    h: arrival ? 15.24 + 3800 * glide : 0,
    u: arrival ? initialGroundSpeed : 0,
    w: arrival ? -initialGroundSpeed * glide : 0,
    pitch: arrival ? 3 * RAD : 0,
    thrust: arrival ? p.thrust * 0.14 : 0,
    phase: arrival ? "approach" : "line-up",
    ground: !arrival,
    gear: 1,
    flap: arrival ? 1 : 0.5,
    spoilers: 0,
    lift: 0,
    drag: 0,
    normal: p.mass * G,
    ax: 0,
    az: 0,
    touchTime: null,
    wheelAngle: 0,
    wheelOmega: 0,
    taxiDistance: null,
    runwayClear: false,
    lateralAcceleration: 0,
  };
  const frames = [],
    events = [];
  let previousPhase = "",
    liftTime = null;
  function snapshot() {
    const gamma = Math.atan2(state.w, Math.max(1, state.u - weather.along));
    const va = Math.hypot(state.u - weather.along, state.w, weather.cross);
    const crab = state.ground
      ? 0
      : Math.asin(clamp(-weather.cross / Math.max(va, 1), -0.3, 0.3)) *
        clamp(state.h / 8, 0, 1);
    const taxi =
      state.taxiDistance == null ? null : taxiRoute.sample(state.taxiDistance);
    return {
      ...state,
      airspeed: va,
      gamma,
      crab,
      distance: state.s,
      x: taxi?.x ?? runway.x + runway.ux * state.s,
      y: state.h,
      z: taxi?.z ?? runway.z + runway.uz * state.s,
      dx: taxi?.dx ?? runway.ux * Math.cos(crab) - runway.uz * Math.sin(crab),
      dy: Math.tan(state.pitch),
      dz: taxi?.dz ?? runway.uz * Math.cos(crab) + runway.ux * Math.sin(crab),
      speed: state.u,
      onGround: state.ground,
      vis: state.s < 14000,
      runwayRemaining: runway.length - state.s,
    };
  }
  for (let i = 0; i <= duration / STEP; i++) {
    state.time = i * STEP;
    if (state.phase !== previousPhase) {
      events.push({
        phase: state.phase,
        time: state.time,
        distance: state.s,
        height: state.h,
        speed: state.u,
        verticalSpeed: state.w,
      });
      previousPhase = state.phase;
    }
    frames.push(snapshot());
    const va = Math.max(
      1,
      Math.hypot(state.u - weather.along, state.w, weather.cross),
    );
    const gamma = Math.atan2(state.w, Math.max(1, state.u - weather.along));
    const rho = weather.density * Math.exp(-state.h / 8500),
      q = 0.5 * rho * va * va;
    const equivalentAirspeed = va * Math.sqrt(rho / 1.225);
    let targetPitch = 0,
      throttle = 0,
      brake = 0,
      reverse = 0;
    if (!arrival && state.ground) {
      state.phase =
        state.time < 4
          ? "line-up"
          : equivalentAirspeed < p.vr
            ? "takeoff-roll"
            : "rotation";
      throttle = state.time < 4 ? 0.15 : 1;
      brake = state.time < 4 ? 0.5 : 0.018;
      targetPitch = equivalentAirspeed >= p.vr ? 11 * RAD : 0;
    } else if (!state.ground) {
      let targetW;
      if (arrival) {
        const targetHeight = 15.24 - state.s * glide;
        state.phase = state.h < 12 ? "flare" : "approach";
        targetW =
          state.phase === "flare"
            ? -Math.max(0.6, state.h * 0.22)
            : clamp(-state.u * glide + (targetHeight - state.h) * 0.3, -6, -1);
      } else {
        state.phase = "climb";
        targetW = p.climbRate;
        state.gear = approach(state.gear, state.h > 15 ? 0 : 1, 0.17, STEP);
        state.flap = approach(
          state.flap,
          state.h > 150 && va > p.climbSpeed - 5 ? 0 : 0.5,
          0.04,
          STEP,
        );
      }
      const desiredLift =
        (p.mass * (G + clamp((targetW - state.w) * 0.8, -2.5, 2.5))) /
        Math.max(0.95, Math.cos(gamma));
      const clBase = p.cl0 + state.flap * 0.3;
      const alpha =
        (desiredLift / Math.max(q * p.area, 1) - clBase) / p.clAlpha;
      targetPitch = clamp(gamma + alpha, -2 * RAD, 13 * RAD);
      const targetSpeed =
        (arrival ? p.approachSpeed : p.climbSpeed) / Math.sqrt(rho / 1.225);
      const demandedThrust =
        state.drag +
        p.mass * G * Math.sin(gamma) +
        p.mass * (targetSpeed - va) * 0.2;
      throttle = clamp(demandedThrust / p.thrust, 0.035, 1);
      if (state.phase === "flare") throttle = 0.025;
    } else {
      state.phase = state.u > 0.2 || taxiRoute ? "landing-roll" : "stopped";
      state.spoilers = approach(
        state.spoilers,
        state.taxiDistance == null ? 1 : 0,
        2,
        STEP,
      );
      brake = state.time - state.touchTime > 1.2 ? 0.22 : 0.018;
      reverse =
        state.u > 30 && state.time - state.touchTime > 1 ? 0.22 * p.thrust : 0;
      targetPitch = 0;
      if (taxiRoute) {
        const remaining =
          state.taxiDistance == null
            ? taxiRoute.startDistance - state.s + taxiRoute.length
            : taxiRoute.length - state.taxiDistance;
        const routePosition =
          state.taxiDistance ?? state.s - taxiRoute.startDistance;
        // Bound lateral acceleration to 0.65 m/s² and yaw rate to 6°/s.
        // Look ahead with braking distance so speed drops before the turn.
        // A five-metre stop margin absorbs residual idle thrust during spool-down.
        const stoppingRoom = Math.max(0, remaining - 5);
        let targetSpeed = Math.min(
          7,
          stoppingRoom * 0.35,
          Math.sqrt(2 * 0.65 * stoppingRoom),
        );
        const ahead = taxiRoute.sample(Math.max(0, routePosition + 14));
        if (routePosition >= 0)
          targetSpeed = Math.min(
            targetSpeed,
            taxiRoute.sample(routePosition).speedLimit,
          );
        targetSpeed = Math.min(
          targetSpeed,
          Math.sqrt(
            ahead.speedLimit ** 2 + 2 * 0.35 * Math.max(0, -routePosition - 14),
          ),
        );
        const demand = clamp((targetSpeed - state.u) * 0.8, -1.8, 0.6);
        // Use the same rolling resistance, thrust spool and brake forces as rollout.
        const rolling = 0.018 * p.mass * G;
        throttle = clamp(
          (state.drag + rolling + p.mass * demand) / p.thrust,
          0,
          0.16,
        );
        brake = Math.max(0.018, -demand / G);
        if (state.taxiDistance != null) {
          state.flap = approach(state.flap, 0, 0.12, STEP);
          state.phase = state.runwayClear ? "taxi" : "runway-exit";
        }
        if (remaining < 5 && state.u < 0.1) {
          state.phase = "holding";
          throttle = 0;
          brake = 0.5;
        }
      }
    }
    state.pitch = approach(
      state.pitch,
      targetPitch,
      (state.ground ? 2.5 : 2) * RAD,
      STEP,
    );
    state.thrust +=
      (throttle * p.thrust - state.thrust) * (1 - Math.exp(-STEP / 2.5));
    const alpha = state.pitch - gamma;
    const cl =
      clamp(p.cl0 + state.flap * 0.3 + p.clAlpha * alpha, -0.3, p.clMax) *
      (1 - 0.8 * state.spoilers);
    // Ground effect reduces induced drag near the runway; no arbitrary vertical boost.
    const gh = (16 * (state.h + 3)) / p.span,
      groundEffect = (gh * gh) / (1 + gh * gh);
    const cd =
      p.cd0 +
      0.018 * state.gear +
      0.025 * state.flap +
      0.09 * state.spoilers +
      p.induced * cl * cl * groundEffect;
    state.lift = q * p.area * cl;
    state.drag = q * p.area * cd;
    const fx =
      state.thrust * Math.cos(state.pitch) -
      state.drag * Math.cos(gamma) -
      state.lift * Math.sin(gamma);
    const fy =
      state.lift * Math.cos(gamma) +
      state.thrust * Math.sin(state.pitch) -
      state.drag * Math.sin(gamma) -
      p.mass * G;
    state.normal = state.ground ? Math.max(0, -fy) : 0;
    state.ax = (fx - brake * state.normal - reverse) / p.mass;
    state.az = state.ground ? Math.max(0, fy / p.mass) : fy / p.mass;
    if (!arrival && state.ground && fy > 0 && state.pitch > 3 * RAD) {
      state.ground = false;
      liftTime = state.time;
    }
    if (state.phase === "stopped" || state.phase === "holding") {
      state.u = 0;
      state.ax = 0;
    } else state.u = Math.max(0, state.u + state.ax * STEP);
    state.w += state.az * STEP;
    if (
      arrival &&
      state.ground &&
      taxiRoute &&
      state.taxiDistance == null &&
      state.s + state.u * STEP >= taxiRoute.startDistance
    ) {
      // A fast/late landing must stop on the runway, never snap into a missed exit.
      if (state.u <= 8) state.taxiDistance = state.s - taxiRoute.startDistance;
      else taxiRoute = null;
    }
    if (state.taxiDistance != null) {
      state.taxiDistance = Math.min(
        taxiRoute.length,
        state.taxiDistance + state.u * STEP,
      );
      const at = taxiRoute.sample(state.taxiDistance);
      state.s = (at.x - runway.x) * runway.ux + (at.z - runway.z) * runway.uz;
      const crossTrack = Math.abs(
        (at.x - runway.x) * -runway.uz + (at.z - runway.z) * runway.ux,
      );
      state.runwayClear = crossTrack >= taxiRoute.clearance;
      state.lateralAcceleration = state.u * state.u * at.curvature;
    } else state.s += state.u * STEP;
    state.h += state.w * STEP;
    state.wheelOmega = state.ground
      ? state.u / 0.45
      : state.wheelOmega * Math.exp(-STEP / 2);
    state.wheelAngle += state.wheelOmega * STEP;
    if (state.h <= 0) {
      if (arrival && !state.ground) {
        events.push({
          phase: "touchdown",
          time: state.time,
          distance: state.s,
          speed: state.u,
          verticalSpeed: state.w,
          height: 0,
        });
        state.touchTime = state.time;
      }
      state.h = 0;
      state.w = 0;
      state.ground = true;
    }
  }
  return Object.freeze({
    operation,
    profile: p,
    weather,
    runway,
    taxiRoute,
    events,
    liftTime,
    duration,
    sample(time) {
      const f = clamp(time, 0, duration) / STEP,
        a = frames[Math.floor(f)],
        b = frames[Math.min(frames.length - 1, Math.floor(f) + 1)];
      const k = f - Math.floor(f),
        result = { ...a };
      for (const key of [
        "x",
        "y",
        "z",
        "dx",
        "dy",
        "dz",
        "pitch",
        "u",
        "w",
        "airspeed",
        "speed",
        "gear",
        "flap",
        "spoilers",
        "distance",
        "time",
        "wheelAngle",
      ])
        result[key] = a[key] + (b[key] - a[key]) * k;
      return result;
    },
  });
}

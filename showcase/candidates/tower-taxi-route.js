/** Offline ground routing in metres, x=east/z=south. Routes are scenario assumptions,
 * not ATC clearances. Only shared survey/OSM vertices count as taxiway connections.
 */
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const distance = (a, b) => Math.hypot(b[0] - a[0], b[1] - a[1]);
const cross = (a, b) => a[0] * b[1] - a[1] * b[0];
const sub = (a, b) => [a[0] - b[0], a[1] - b[1]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1];
const along = (r, p) => dot(sub(p, [r.x, r.z]), [r.ux, r.uz]);
const lateral = (r, p) => cross([r.ux, r.uz], sub(p, [r.x, r.z]));
const onRunway = (r, p, margin) =>
  along(r, p) > -margin &&
  along(r, p) < r.length + margin &&
  Math.abs(lateral(r, p)) < margin;

/** Build a centreline route with circular corner fillets. Arc radius and curvature
 * drive the speed limit, rather than rotating an aircraft instantly at vertices.
 */
function simplify(points, tolerance = 0.75) {
  if (points.length < 3) return points;
  const a = points[0],
    b = points.at(-1),
    ab = sub(b, a),
    length2 = dot(ab, ab);
  let greatest = 0,
    index = 0;
  for (let i = 1; i < points.length - 1; i++) {
    const t = length2 ? clamp(dot(sub(points[i], a), ab) / length2, 0, 1) : 0;
    const error = distance(points[i], [a[0] + ab[0] * t, a[1] + ab[1] * t]);
    if (error > greatest) {
      greatest = error;
      index = i;
    }
  }
  return greatest > tolerance
    ? [
        ...simplify(points.slice(0, index + 1), tolerance).slice(0, -1),
        ...simplify(points.slice(index), tolerance),
      ]
    : [a, b];
}
function curveRoute(rawPoints) {
  const points = simplify(rawPoints);
  const samples = [{ p: points[0], curvature: 0 }];
  const line = (p) => {
    const a = samples.at(-1).p,
      n = Math.max(1, Math.ceil(distance(a, p)));
    for (let j = 1; j <= n; j++)
      samples.push({
        p: [a[0] + ((p[0] - a[0]) * j) / n, a[1] + ((p[1] - a[1]) * j) / n],
        curvature: 0,
      });
  };
  for (let i = 1; i < points.length - 1; i++) {
    const a = points[i - 1],
      b = points[i],
      c = points[i + 1];
    const la = distance(a, b),
      lb = distance(b, c),
      u = sub(b, a).map((v) => v / la),
      v = sub(c, b).map((v) => v / lb);
    const turn = Math.atan2(cross(u, v), dot(u, v));
    if (Math.abs(turn) < 0.002) {
      line(b);
      continue;
    }
    if (Math.abs(turn) > 2.5) return null;
    const tangent = Math.min(
      22 * Math.tan(Math.abs(turn) / 2),
      la * 0.45,
      lb * 0.45,
    );
    const radius = tangent / Math.tan(Math.abs(turn) / 2),
      sign = Math.sign(turn);
    const start = [b[0] - u[0] * tangent, b[1] - u[1] * tangent];
    const centre = [
      start[0] - u[1] * radius * sign,
      start[1] + u[0] * radius * sign,
    ];
    line(start);
    const angle = Math.atan2(start[1] - centre[1], start[0] - centre[0]);
    const n = Math.max(3, Math.ceil(Math.abs(turn) * radius));
    for (let j = 1; j <= n; j++)
      samples.push({
        p: [
          centre[0] + radius * Math.cos(angle + (turn * j) / n),
          centre[1] + radius * Math.sin(angle + (turn * j) / n),
        ],
        curvature: 1 / radius,
      });
  }
  line(points.at(-1));
  let length = 0;
  for (let i = 0; i < samples.length; i++) {
    if (i) length += distance(samples[i - 1].p, samples[i].p);
    samples[i].s = length;
  }
  for (let i = 0; i < samples.length; i++) {
    const a = samples[Math.max(0, i - 1)].p,
      b = samples[Math.min(samples.length - 1, i + 1)].p,
      d = distance(a, b);
    samples[i].dx = (b[0] - a[0]) / d;
    samples[i].dz = (b[1] - a[1]) / d;
  }
  // A braking envelope visits every arc sample, including short corner fillets.
  // Margins allow for engine spool-down and the longitudinal controller response.
  for (const point of samples)
    point.speedLimit =
      point.curvature > 0.0001
        ? Math.min(
            7,
            Math.sqrt(0.35 / point.curvature),
            (4 * Math.PI) / 180 / point.curvature,
          )
        : 7;
  for (let i = samples.length - 2; i >= 0; i--)
    samples[i].speedLimit = Math.min(
      samples[i].speedLimit,
      Math.sqrt(
        samples[i + 1].speedLimit ** 2 +
          2 * 0.35 * (samples[i + 1].s - samples[i].s),
      ),
    );
  function sample(s) {
    s = clamp(s, 0, length);
    let lo = 0,
      hi = samples.length - 1;
    while (lo + 1 < hi) {
      const m = (lo + hi) >> 1;
      if (samples[m].s < s) lo = m;
      else hi = m;
    }
    const a = samples[lo],
      b = samples[hi],
      span = b.s - a.s,
      t = span ? (s - a.s) / span : 0;
    const dx = a.dx + (b.dx - a.dx) * t,
      dz = a.dz + (b.dz - a.dz) * t,
      norm = Math.hypot(dx, dz);
    return {
      x: a.p[0] + (b.p[0] - a.p[0]) * t,
      z: a.p[1] + (b.p[1] - a.p[1]) * t,
      dx: dx / norm,
      dz: dz / norm,
      speedLimit: Math.min(a.speedLimit, b.speedLimit),
      curvature: Math.max(a.curvature, b.curvature),
    };
  }
  return { length, sample, points, samples };
}

export function buildArrivalTaxiRoute({
  runway,
  taxiways,
  runways = [runway],
  profile,
  minExitDistance = 1700,
  parallelRef = "B",
}) {
  const clearance = (profile?.length || 38) / 2 + 61 / 2 + 20;
  const parallel = taxiways.filter((t) => t.ref === parallelRef);
  const candidates = [];
  for (const exit of taxiways) {
    if (!exit.pts?.length || exit.ref === parallelRef) continue;
    for (let i = 0; i < exit.pts.length; i++) {
      const p = exit.pts[i],
        entry = along(runway, p);
      if (
        Math.abs(lateral(runway, p)) > 1 ||
        entry < minExitDistance ||
        entry > runway.length - 100
      )
        continue;
      for (const direction of [-1, 1]) {
        const next = exit.pts[i + direction];
        if (!next) continue;
        // Reject exits that require an initial turn greater than 95 degrees.
        if (
          dot(sub(next, p), [runway.ux, runway.uz]) / distance(p, next) <
          -0.087
        )
          continue;
        const branch = [];
        for (
          let j = i + direction;
          j >= 0 && j < exit.pts.length;
          j += direction
        ) {
          const q = exit.pts[j];
          branch.push(q);
          if (runways.some((r) => r !== runway && onRunway(r, q, clearance)))
            break;
          if (Math.abs(lateral(runway, q)) < clearance) continue;
          for (const lane of parallel) {
            const k = lane.pts.findIndex((v) => distance(v, q) < 0.6);
            if (k < 0) continue;
            for (const taxiDirection of [-1, 1]) {
              const tail = [];
              let travelled = 0,
                previous = q;
              for (
                let n = k + taxiDirection;
                n >= 0 && n < lane.pts.length;
                n += taxiDirection
              ) {
                const end = lane.pts[n];
                if (runways.some((r) => onRunway(r, end, clearance))) break;
                const d = distance(previous, end);
                if (travelled + d >= 180) {
                  const f = (180 - travelled) / d;
                  tail.push([
                    previous[0] + (end[0] - previous[0]) * f,
                    previous[1] + (end[1] - previous[1]) * f,
                  ]);
                  travelled = 180;
                  break;
                }
                travelled += d;
                tail.push(end);
                previous = end;
              }
              if (travelled < 100) continue;
              const startDistance = entry - 45;
              const points = [
                [
                  runway.x + runway.ux * startDistance,
                  runway.z + runway.uz * startDistance,
                ],
                [runway.x + runway.ux * entry, runway.z + runway.uz * entry],
                ...branch,
                ...tail,
              ].filter((p, i, ps) => !i || distance(ps[i - 1], p) > 0.1);
              const route = curveRoute(points);
              if (
                !route ||
                route.samples.some((s) =>
                  runways.some(
                    (r) => r !== runway && onRunway(r, s.p, clearance),
                  ),
                )
              )
                continue;
              candidates.push({
                ...route,
                startDistance,
                exitDistance: entry,
                exitRef: exit.ref || "unnamed exit",
                taxiRef: parallelRef,
                clearance,
                source: "bundled OSM connected taxiway centreline",
                holdReason:
                  "Hold on taxiway; no onward clearance or stand assignment",
              });
            }
          }
          if (parallel.some((l) => l.pts.some((v) => distance(v, q) < 0.6)))
            break;
        }
      }
    }
  }
  candidates.sort(
    (a, b) => a.exitDistance - b.exitDistance || a.length - b.length,
  );
  return candidates[0] || null;
}

export const nodes = [
  { id: "SF", name: "San Francisco", ll: [-122.41, 37.785], pad: true },
  { id: "MAR", name: "Marin", ll: [-122.485, 37.862], pad: true },
  { id: "SFO", name: "SFO district", ll: [-122.375, 37.622], pad: true },
  { id: "OAK", name: "Oakland", ll: [-122.235, 37.722], pad: true },
  { id: "BER", name: "Berkeley", ll: [-122.275, 37.865], pad: true },
  { id: "W", name: "West approach", ll: [-122.39, 37.73] },
  { id: "C", name: "Central crossing", ll: [-122.34, 37.79] },
  { id: "E", name: "East approach", ll: [-122.29, 37.77] },
];
export const edgePairs = [
  ["SF", "MAR"],
  ["SF", "W"],
  ["SF", "C"],
  ["C", "BER"],
  ["C", "E"],
  ["W", "E"],
  ["W", "SFO"],
  ["E", "OAK"],
  ["OAK", "BER"],
];
export const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
export const edgeKey = (a, b) => [a, b].sort().join("-");
export function km(a, b) {
  const r = Math.PI / 180,
    p = byId[a].ll,
    q = byId[b].ll;
  const u = (q[1] - p[1]) * r,
    v = (q[0] - p[0]) * r;
  return (
    12742 *
    Math.asin(
      Math.sqrt(
        Math.sin(u / 2) ** 2 +
          Math.cos(p[1] * r) * Math.cos(q[1] * r) * Math.sin(v / 2) ** 2,
      ),
    )
  );
}
const adjacency = Object.fromEntries(nodes.map((n) => [n.id, []]));
for (const [a, b] of edgePairs) {
  adjacency[a].push(b);
  adjacency[b].push(a);
}
export function routes(a, b) {
  const out = [];
  function walk(path) {
    const p = path.at(-1);
    if (p === b) {
      out.push(path);
      return;
    }
    for (const q of adjacency[p]) if (!path.includes(q)) walk([...path, q]);
  }
  walk([a]);
  return out.sort(
    (p, q) => distance(p) - distance(q) || p.join().localeCompare(q.join()),
  );
}
export const distance = (p) =>
  p.slice(1).reduce((s, n, i) => s + km(p[i], n), 0);
export const SPEED = 2.8;
export const demand = Array.from({ length: 28 }, (_, i) => {
  const pairs = [
    ["SF", "OAK"],
    ["SFO", "BER"],
    ["MAR", "OAK"],
    ["OAK", "SF"],
    ["BER", "SFO"],
    ["SF", "BER"],
    ["OAK", "MAR"],
  ];
  const [from, to] = pairs[i % pairs.length];
  const release = +(i * 2.5).toFixed(2),
    free = distance(routes(from, to)[0]) / SPEED;
  return {
    id: "SF-" + String(101 + i),
    from,
    to,
    release,
    deadline: release + free + 15,
    free,
  };
});
function offsets(path) {
  let t = 0;
  const r = [{ resource: "node:" + path[0], start: 0, end: 0.35 }];
  for (let i = 0; i < path.length - 1; i++) {
    const d = km(path[i], path[i + 1]) / SPEED;
    r.push({
      resource: "edge:" + edgeKey(path[i], path[i + 1]),
      start: t,
      end: t + d + 0.12,
    });
    t += d;
    r.push({
      resource: "node:" + path[i + 1],
      start: Math.max(0, t - 0.12),
      end: t + (i === path.length - 2 ? 0.5 : 0.12),
    });
  }
  return { r, duration: t };
}
function earliest(path, start, book, storm) {
  const { r, duration } = offsets(path);
  let departure = start;
  for (let tries = 0; tries < 10000; tries++) {
    let bump = departure;
    for (const slot of r) {
      const intervals = book[slot.resource] || [];
      for (const other of intervals)
        if (
          departure + slot.start < other.end - 1e-8 &&
          departure + slot.end > other.start + 1e-8
        )
          bump = Math.max(bump, other.end - slot.start);
      if (
        storm &&
        slot.resource === "edge:C-E" &&
        departure + slot.start < 24 &&
        departure + slot.end > 8
      )
        bump = Math.max(bump, 24 - slot.start);
    }
    if (bump <= departure + 1e-8)
      return {
        path,
        departure,
        arrival: departure + duration,
        distance: distance(path),
        slots: r.map((s) => ({
          ...s,
          start: s.start + departure,
          end: s.end + departure,
        })),
      };
    departure = bump;
  }
  throw new Error("Scheduler did not converge");
}
// keep: flights already committed (airborne or departed) whose reservations stay fixed.
// priority: ids scheduled first. avoid: {id: [edgeKey]} corridors a flight refuses.
// notBefore: {id: minute} earliest departure a flight accepts.
export function schedule(
  mode,
  storm = true,
  { now = 0, keep = [], priority = [], avoid = {}, notBefore = {} } = {},
) {
  const book = {},
    flights = [...keep],
    kept = new Set(keep.map((f) => f.id));
  for (const f of keep)
    for (const s of f.slots) (book[s.resource] ??= []).push({ ...s, id: f.id });
  const order = demand
    .filter((r) => !kept.has(r.id))
    .sort((a, b) => priority.includes(b.id) - priority.includes(a.id));
  for (const req of order) {
    const options = routes(req.from, req.to),
      allowed = options.filter(
        (p) =>
          !p
            .slice(1)
            .some((n, i) => (avoid[req.id] || []).includes(edgeKey(p[i], n))),
      ),
      pool = mode === "fixed" ? allowed.slice(0, 1) : allowed,
      start = Math.max(req.release, now, notBefore[req.id] ?? 0);
    const candidates = (pool.length ? pool : options.slice(0, 1)).map((p) =>
      earliest(p, start, book, storm),
    );
    candidates.sort(
      (a, b) =>
        a.arrival - b.arrival ||
        a.distance - b.distance ||
        a.path.join().localeCompare(b.path.join()),
    );
    const f = { ...req, ...candidates[0] };
    f.rerouted = f.path.join() !== options[0].join();
    if (priority.includes(f.id)) f.priority = true;
    flights.push(f);
    for (const s of f.slots) (book[s.resource] ??= []).push({ ...s, id: f.id });
  }
  flights.sort((a, b) => a.id.localeCompare(b.id));
  return { flights, book, mode, storm };
}
export function validate(plan) {
  const errors = [],
    reconstructed = {};
  for (const f of plan.flights) {
    if (
      f.path.length < 2 ||
      f.path.some((id) => !byId[id]) ||
      f.path.slice(1).some((id, i) => !adjacency[f.path[i]]?.includes(id))
    ) {
      errors.push(f.id + ": invalid route");
      continue;
    }
    const expected = offsets(f.path).r.map((s) => ({
      ...s,
      start: s.start + f.departure,
      end: s.end + f.departure,
      id: f.id,
    }));
    for (const s of expected) (reconstructed[s.resource] ??= []).push(s);
    if (!Number.isFinite(f.departure) || f.departure < f.release - 1e-7)
      errors.push(f.id + ": early or invalid departure");
    if (
      Math.abs(f.arrival - f.departure - distance(f.path) / SPEED) > 1e-7 ||
      Math.abs(f.distance - distance(f.path)) > 1e-7
    )
      errors.push(f.id + ": inconsistent route metrics");
    if (f.path[0] !== f.from || f.path.at(-1) !== f.to)
      errors.push(f.id + ": endpoints");
    const signature = (s) =>
      [s.resource, s.start.toFixed(7), s.end.toFixed(7)].join("|");
    if (
      JSON.stringify(expected.map(signature).sort()) !==
      JSON.stringify((f.slots || []).map(signature).sort())
    )
      errors.push(f.id + ": missing or inconsistent flight reservations");
  }
  const keys = new Set([
    ...Object.keys(plan.book),
    ...Object.keys(reconstructed),
  ]);
  for (const resource of keys) {
    const list = reconstructed[resource] || [],
      book = plan.book[resource] || [],
      sig = (s) => [s.id, s.start.toFixed(7), s.end.toFixed(7)].join("|");
    if (
      JSON.stringify(list.map(sig).sort()) !==
      JSON.stringify(book.map(sig).sort())
    )
      errors.push(resource + ": booking mismatch");
    const s = [...list].sort((a, b) => a.start - b.start);
    for (let i = 0; i < s.length; i++)
      for (let j = i + 1; j < s.length; j++)
        if (s[j].start < s[i].end - 1e-7 && s[j].end > s[i].start + 1e-7)
          errors.push(resource + ": overlap");
    if (plan.storm && resource === "edge:C-E")
      for (const r of list)
        if (r.start < 24 - 1e-7 && r.end > 8 + 1e-7)
          errors.push(resource + ": closure");
  }
  return errors;
}
export function metrics(plan) {
  const f = plan.flights;
  return {
    onTime: f.filter((x) => x.arrival <= x.deadline + 1e-7).length,
    delay: f.reduce((s, x) => s + x.arrival - x.release - x.free, 0) / f.length,
    distance: f.reduce((s, x) => s + x.distance, 0),
    end: Math.max(...f.map((x) => x.arrival)),
    violations: validate(plan).length,
  };
}
export function position(f, t) {
  if (t < f.departure)
    return { node: f.from, state: t < f.release ? "scheduled" : "queued" };
  if (t >= f.arrival) return { node: f.to, state: "arrived" };
  let clock = f.departure;
  for (let i = 0; i < f.path.length - 1; i++) {
    const duration = km(f.path[i], f.path[i + 1]) / SPEED;
    if (t < clock + duration)
      return {
        a: f.path[i],
        b: f.path[i + 1],
        progress: (t - clock) / duration,
        state: "airborne",
      };
    clock += duration;
  }
  return { node: f.to, state: "arrived" };
}

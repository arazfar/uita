import test from "node:test";
import assert from "node:assert/strict";
import { PlaybackWindows } from "../candidates/research-windows.js";
import {
  landingCandidates,
  arrivalLabel,
} from "../candidates/research-arrivals.js";
const source = { id: "a", start: 0, end: 1000 };
test("window requests coalesce and cache hits do not fetch", async () => {
  let calls = 0;
  const cache = new PlaybackWindows(async () => {
    calls++;
    return { frames: [{ clock: 0 }] };
  });
  const [a, b] = await Promise.all([
    cache.load("history", source, 20),
    cache.load("history", source, 30),
  ]);
  assert.equal(a, b);
  assert.equal(calls, 1);
  await cache.load("history", source, 60);
  assert.equal(calls, 1);
});
test("LRU retains three windows in four sources", async () => {
  const cache = new PlaybackWindows(async () => ({ frames: [] }));
  for (let i = 0; i < 5; i++)
    await cache.load("history", { ...source, id: String(i) }, 0);
  assert.equal(cache.sources.size, 4);
  assert.equal(cache.sources.has("history:0"), false);
  for (const clock of [120, 240, 360])
    await cache.load("history", { ...source, id: "4" }, clock);
  assert.equal(cache.sources.get("history:4").size, 3);
  assert.equal(cache.sources.get("history:4").has(0), false);
});
test("one cancelled consumer does not cancel shared preload; last consumer cancels transport", async () => {
  let resolve, signal;
  const cache = new PlaybackWindows((k, id, c, s) => {
    signal = s;
    return new Promise((r) => (resolve = r));
  });
  const a = new AbortController(),
    b = new AbortController();
  const p = cache.load("history", source, 0, a.signal);
  const q = cache.load("history", source, 0, b.signal);
  await Promise.resolve();
  a.abort();
  await assert.rejects(p, { name: "AbortError" });
  assert.equal(signal.aborted, false);
  resolve({ frames: [] });
  await q;
  const other = new AbortController();
  const pending = cache.load("history", source, 120, other.signal);
  await Promise.resolve();
  other.abort();
  await assert.rejects(pending, { name: "AbortError" });
  assert.equal(signal.aborted, true);
});
test("landing suggestions prioritize authority then distance and keep inferred labels honest", () => {
  const a = (id, phase, distance) => ({
    id,
    status: "approach",
    arrival_cue: { phase, basis: "simulated", distance_nm: distance },
  });
  assert.deepEqual(
    landingCandidates({
      aircraft: [
        a("near", "approaching", 1),
        a("far", "landing_authorized", 4),
        a("ground", "on_ground", 0),
      ],
    }).map((x) => x.id),
    ["far", "near"],
  );
  assert.equal(
    arrivalLabel({ arrival_cue: { phase: "approaching", basis: "inferred" } }),
    "Approaching SFO · inferred",
  );
});

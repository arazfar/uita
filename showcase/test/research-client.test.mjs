import { test } from "node:test";
import assert from "node:assert/strict";
import {
  atClock,
  displayFrame,
  uniqueEvents,
  plottable,
  mutation,
} from "../candidates/research-client.js";
test("replay selects prior state without exposing future motion", () => {
  const frames = [{ clock: 1 }, { clock: 5 }];
  assert.equal(atClock(frames, 4).clock, 1);
  assert.equal(atClock(frames, 0), null);
});
test("reconnected journals are ordered and deduplicated", () => {
  assert.deepEqual(
    uniqueEvents([{ sequence: 2 }, { sequence: 1 }, { sequence: 2 }]).map(
      (e) => e.sequence,
    ),
    [1, 2],
  );
});
test("unknown altitudes and completed traffic are never fabricated onto the map", () => {
  const a = {
    longitude: -122,
    latitude: 37,
    altitude_ft: 100,
    status: "approach",
  };
  assert.ok(plottable(a));
  assert.equal(plottable({ ...a, altitude_ft: null }), false);
  assert.equal(plottable({ ...a, status: "complete" }), false);
});
test("commands bind revisions and get distinct idempotency keys", () => {
  const a = mutation({ revision: 7 }, { action: "pause" }),
    b = mutation({ revision: 7 }, { action: "pause" });
  assert.equal(a.expected_revision, 7);
  assert.notEqual(a.idempotency_key, b.idempotency_key);
});

test("visual interpolation preserves entry, status and unknown altitude", () => {
  const a = {
    id: "a",
    longitude: 0,
    latitude: 0,
    altitude_ft: 100,
    status: "approach",
    provenance: {},
  };
  const frames = [
    { clock: 0, aircraft: [a] },
    {
      clock: 10,
      aircraft: [
        { ...a, longitude: 0.1 },
        { ...a, id: "future" },
      ],
    },
  ];
  const shown = displayFrame(frames, 5);
  assert.equal(shown.aircraft.length, 1);
  assert.equal(shown.aircraft[0].longitude, 0.05);
  assert.equal(shown.clock, 0);
  frames[0].aircraft[0] = { ...a, altitude_ft: null };
  assert.equal(displayFrame(frames, 5).aircraft[0].altitude_ft, null);
});

test("heading wraps and discontinuities never interpolate", () => {
 const a={id:"a",longitude:0,latitude:0,altitude_ft:100,status:"approach",track_deg_true:350,provenance:{segment_id:1}};
 const frames=[{clock:0,aircraft:[a]},{clock:10,aircraft:[{...a,longitude:.1,track_deg_true:10}]}];
 assert.equal(displayFrame(frames,5).aircraft[0].track_deg_true,0);
 frames[1].aircraft[0].provenance={segment_id:2};
 assert.equal(displayFrame(frames,5).aircraft[0].longitude,0);
 frames[1].clock=100;
 assert.equal(displayFrame(frames,50).aircraft[0].longitude,0);
});

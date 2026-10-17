import test from "node:test";
import assert from "node:assert/strict";
import {
  schedule,
  validate,
  metrics,
  demand,
  km,
  SPEED,
  edgeKey,
  position,
} from "../src/scheduler.mjs";
for (const storm of [false, true])
  for (const mode of ["fixed", "adaptive"]) {
    test(`${mode}, forecast closure ${storm}: reconstructed reservations are feasible`, () => {
      const plan = schedule(mode, storm),
        resources = {};
      const add = (key, start, end, id) =>
        (resources[key] ??= []).push({ start, end, id });
      for (const f of plan.flights) {
        assert.ok(f.departure >= f.release);
        let clock = f.departure,
          dist = 0;
        add("node:" + f.from, clock, clock + 0.35, f.id);
        for (let i = 0; i < f.path.length - 1; i++) {
          const a = f.path[i],
            b = f.path[i + 1],
            duration = km(a, b) / SPEED;
          add("edge:" + edgeKey(a, b), clock, clock + duration + 0.12, f.id);
          if (storm && edgeKey(a, b) === "C-E")
            assert.ok(
              clock + duration + 0.12 <= 8 + 1e-7 || clock >= 24 - 1e-7,
            );
          clock += duration;
          dist += km(a, b);
          add(
            "node:" + b,
            clock - 0.12,
            clock + (i === f.path.length - 2 ? 0.5 : 0.12),
            f.id,
          );
        }
        assert.ok(Math.abs(clock - f.arrival) < 1e-7);
        assert.ok(Math.abs(dist - f.distance) < 1e-7);
        assert.equal(
          position(f, f.departure - 0.001).state,
          f.departure === f.release ? "scheduled" : "queued",
        );
        assert.equal(position(f, f.departure + 0.001).state, "airborne");
        assert.equal(position(f, f.arrival).state, "arrived");
      }
      for (const slots of Object.values(resources))
        for (let i = 0; i < slots.length; i++)
          for (let j = i + 1; j < slots.length; j++)
            assert.ok(
              slots[i].end <= slots[j].start + 1e-7 ||
                slots[j].end <= slots[i].start + 1e-7,
              `overlap ${slots[i].id}/${slots[j].id}`,
            );
      assert.deepEqual(validate(plan), []);
      assert.equal(
        metrics(plan).onTime,
        plan.flights.filter((f) => f.arrival <= f.deadline).length,
      );
      assert.ok(
        metrics(plan).end < 120,
        "replay horizon must include every trip",
      );
    });
  }
test("policies use identical demand, release times and deadlines", () => {
  const fields = (f) => ({
    id: f.id,
    from: f.from,
    to: f.to,
    release: f.release,
    deadline: f.deadline,
  });
  for (const mode of ["fixed", "adaptive"])
    assert.deepEqual(schedule(mode).flights.map(fields), demand.map(fields));
  assert.equal(edgeKey("C", "E"), edgeKey("E", "C"));
  assert.deepEqual(schedule("adaptive"), schedule("adaptive"));
});
test("validator rejects malformed routes and missing bookings", () => {
  const noBook = schedule("adaptive");
  noBook.book = {};
  assert.ok(validate(noBook).some((e) => e.includes("booking mismatch")));
  const badRoute = schedule("adaptive");
  badRoute.flights[0].path = ["SF", "OAK"];
  assert.ok(validate(badRoute).some((e) => e.includes("invalid route")));
  const noSlot = schedule("adaptive");
  noSlot.flights[0].slots = [];
  assert.ok(validate(noSlot).some((e) => e.includes("flight reservations")));
  const badTime = schedule("adaptive");
  badTime.flights[0].arrival += 1;
  assert.ok(validate(badTime).some((e) => e.includes("route metrics")));
});

import test from "node:test";
import assert from "node:assert/strict";
import { schedule } from "../src/scheduler.mjs";
import {
  clearanceFor,
  phrase,
  readback,
  parse,
  check,
  correction,
  intentOf,
} from "../src/radio.mjs";

const flights = [
  ...schedule("adaptive", true).flights,
  ...schedule("fixed", true).flights,
];

test("every clearance survives a correct readback", () => {
  for (const f of flights)
    for (const kind of ["takeoff", "hold"]) {
      const c = clearanceFor(f, kind);
      const r = check(c, parse(readback(c)));
      assert.ok(r.ok, `${f.id} ${kind}: ${JSON.stringify(r.mismatches)}`);
    }
});

test("controller phraseology parses to the same fields", () => {
  for (const f of flights) {
    const c = clearanceFor(f);
    assert.ok(check(c, parse(phrase(c))).ok, phrase(c));
  }
});

test("a wrong destination, band or slot is caught", () => {
  const c = clearanceFor(flights[3]);
  const wrongDest = c.dest === "OAK" ? "BER" : "OAK";
  for (const [error, field] of [
    [{ dest: wrongDest }, "dest"],
    [{ band: (c.band % 3) + 1 }, "band"],
    [{ slot: "2359" }, "slot"],
  ]) {
    const r = check(c, parse(readback(c, error)));
    assert.equal(r.ok, false);
    assert.ok(r.mismatches.some((m) => m.field === field));
    assert.match(correction(c, r.mismatches), /negative/);
  }
});

test("written digits and spoken digits both parse", () => {
  assert.equal(parse("UITA 106 band 2").id, "SF-106");
  assert.equal(parse("uita one zero six band two").band, 2);
});

test("pilot requests classify without an LLM", () => {
  assert.equal(
    intentOf("UITA one one two, low battery, request priority landing")
      .intent,
    "priority",
  );
  assert.equal(intentOf("UITA 107 unable, storm ahead").intent, "reroute");
  assert.equal(intentOf("UITA 107 unable, storm ahead").id, "SF-107");
});

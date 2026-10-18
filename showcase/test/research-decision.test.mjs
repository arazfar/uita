import test from "node:test";
import assert from "node:assert/strict";
import { decisionAt } from "../candidates/research-decision.js";
const frame = {
  mode: "simulation",
  aircraft: [{ id: "a", callsign: "UAL1", runway: "28L", status: "approach" }],
};
const proposal = {
  sequence: ["a"],
  clearances: [],
  explanation: "Aircraft a precedes later demand",
};
const events = [
  { sequence: 1, clock: 10, kind: "model_response", payload: { proposal } },
  {
    sequence: 2,
    clock: 11,
    kind: "proposal_verified",
    payload: { proposal, verdict: { status: "fail" } },
  },
  {
    sequence: 3,
    clock: 20,
    kind: "clearance_issued",
    payload: {
      clearance: { aircraft_id: "a" },
      text: "UAL1, runway 28L, cleared to land",
    },
  },
];
test("proposal explanations remain causal and rejected proposals are not clearances", () => {
  assert.equal(decisionAt(events, frame, 9), null);
  const d = decisionAt(events, frame, 12);
  assert.equal(d.verdict, "fail");
  assert.equal(d.clearance, null);
  assert.equal(d.callsign, "UAL1");
  assert.equal(d.origin, "Model explanation");
});
test("historical and baseline views never inherit candidate decisions", () => {
  assert.equal(decisionAt(events, { ...frame, mode: "historical" }, 30), null);
  assert.equal(decisionAt(events, frame, 30, true), null);
});
test("issued clearance is displayed only once its event exists", () => {
  assert.match(decisionAt(events, frame, 21).clearance, /cleared to land/);
});
test("missing independent verdict stays unresolved", () => {
  assert.equal(decisionAt(events.slice(0, 1), frame, 11).verdict, "unresolved");
});

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

test("later unrelated issued commands do not inherit rejected proposal explanations", () => {
  const d = decisionAt(events, frame, 21);
  assert.equal(d.phase, "Issued");
  assert.equal(d.verdict, "unresolved");
  assert.doesNotMatch(d.explanation, /precedes/);
});
test("acknowledgment, cancellation, touchdown and completion retain causal lifecycle", () => {
  const c = { id: "c", aircraft_id: "a", kind: "landing", target: "28L" };
  const p = { ...proposal, clearances: [c] };
  const journal = [
    {
      sequence: 1,
      clock: 10,
      kind: "clearance_issued",
      payload: { clearance: c, text: "Cleared to land" },
    },
    {
      sequence: 2,
      clock: 10,
      kind: "proposal_verified",
      payload: { proposal: p, verdict: { status: "pass" } },
    },
    {
      sequence: 3,
      clock: 12,
      kind: "pilot_acknowledged",
      payload: { clearance_id: "c", aircraft_id: "a" },
    },
  ];
  assert.equal(decisionAt(journal, frame, 10).phase, "Issued");
  assert.equal(decisionAt(journal, frame, 12).phase, "Acknowledged");
  assert.equal(decisionAt(journal, frame, 12).verdict, "pass");
  for (const [kind, phase] of [
    ["clearance_cancelled", "Cancelled"],
    ["synthetic_go_around", "Go-around"],
    ["touchdown_simulated", "On ground"],
    ["arrival_completed", "Completed"],
  ]) {
    assert.equal(
      decisionAt(
        [
          ...journal,
          {
            sequence: 4,
            clock: 13,
            kind,
            payload: { aircraft_id: "a", clearance_id: "c" },
          },
        ],
        frame,
        13,
      ).phase,
      phase,
    );
  }
});
test("simultaneous issued actions share a single decision group", () => {
  const d = decisionAt(
    [1, 2].map((n) => ({
      sequence: n,
      clock: 10,
      kind: "clearance_issued",
      payload: {
        clearance: {
          id: String(n),
          aircraft_id: "a",
          kind: "speed",
          value: 180,
        },
        text: "Speed 180",
      },
    })),
    frame,
    10,
  );
  assert.equal(d.actions.length, 2);
});
test("same-tick cancellation or rejection supersedes issuance", () => {
  const issue = {
    sequence: 1,
    clock: 10,
    kind: "clearance_issued",
    payload: {
      clearance: { id: "c", aircraft_id: "a", kind: "landing", target: "28L" },
    },
  };
  assert.equal(
    decisionAt(
      [
        issue,
        {
          sequence: 2,
          clock: 10,
          kind: "clearance_cancelled",
          payload: { clearance_id: "c" },
        },
      ],
      frame,
      10,
    ).phase,
    "Cancelled",
  );
  assert.equal(
    decisionAt(
      [
        issue,
        {
          sequence: 2,
          clock: 10,
          kind: "proposal_verified",
          payload: { proposal, verdict: { status: "fail" } },
        },
      ],
      frame,
      10,
    ).phase,
    "Rejected",
  );
});

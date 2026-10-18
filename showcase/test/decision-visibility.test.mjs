import test from "node:test";
import assert from "node:assert/strict";
import { DecisionVisibility } from "../candidates/research-decision.js";
test("decision dismissal counts foreground time and preserves seek labeling", () => {
  const v = new DecisionVisibility();
  assert.equal(v.update("source:1", 0, false, true), true);
  assert.equal(v.seek, true);
  for (let t = 1000; t <= 7000; t += 1000)
    assert.equal(v.update("source:1", t), true);
  assert.equal(v.update("source:1", 8000, true), true);
  assert.equal(v.update("source:1", 9000), false);
  assert.equal(v.update("other-source:1", 10000), true);
  assert.equal(v.seek, false);
});
test("seeking back to the same event restores its at-time card", () => {
  const v = new DecisionVisibility();
  v.update("a", 0);
  for (let t = 1000; t <= 9000; t += 1000) v.update("a", t);
  assert.equal(v.update("a", 10000, false, true), true);
  assert.equal(v.seek, true);
});

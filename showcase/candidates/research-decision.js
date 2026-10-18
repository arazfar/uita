// Only causal journal evidence; model explanations are public output, never hidden reasoning.
const kinds = new Set([
  "model_response",
  "proposal_verified",
  "clearance_issued",
  "pilot_acknowledged",
  "clearance_cancelled",
  "clearance_expired",
  "touchdown_simulated",
  "arrival_completed",
  "synthetic_go_around",
  "disruption",
]);
const commandEqual = (a, b) =>
  ["aircraft_id", "kind", "target", "value"].every(
    (k) => (a?.[k] ?? null) === (b?.[k] ?? null),
  );
export function decisionAt(events, frame, clock, baseline = false) {
  if (!frame || frame.mode === "historical" || baseline) return null;
  const visible = events
    .filter((e) => e.clock <= clock)
    .sort((a, b) => a.sequence - b.sequence);
  const meaningful = visible.filter(
    (e) =>
      kinds.has(e.kind) &&
      (!["model_response", "proposal_verified"].includes(e.kind) ||
        e.payload?.proposal?.sequence?.length ||
        e.payload?.proposal?.clearances?.length),
  );
  if (!meaningful.length) return null;
  const last = meaningful.at(-1);
  const group = meaningful.filter((e) => e.clock === last.clock);
  // Issued actions take precedence over the same transaction's verification event.
  const issued = group.filter((e) => e.kind === "clearance_issued");
  const committed =
    last.kind === "proposal_verified" && last.payload.verdict?.status === "pass"
      ? issued.filter((e) =>
          last.payload.proposal?.clearances?.some((c) =>
            commandEqual(c, e.payload.clearance),
          ),
        )
      : [];
  const event = committed.at(-1) || last;
  const p = event.payload;
  const issue =
    event.kind === "clearance_issued"
      ? event
      : visible.findLast(
          (e) =>
            p.clearance_id != null &&
            e.kind === "clearance_issued" &&
            e.payload.clearance?.id === p.clearance_id,
        );
  const clearance = p.clearance || issue?.payload.clearance;
  const proposal = p.proposal;
  const id =
    clearance?.aircraft_id ||
    p.aircraft_id ||
    proposal?.clearances?.[0]?.aircraft_id ||
    proposal?.sequence?.[0];
  const aircraft = frame.aircraft.find((a) => a.id === id);
  // Legacy correlation is restricted to the exact issued command in the same tick.
  const verified = proposal
    ? event.kind === "proposal_verified"
      ? event
      : null
    : visible.findLast(
        (e) =>
          e.kind === "proposal_verified" &&
          e.clock === (issue?.clock ?? event.clock) &&
          e.payload.proposal?.clearances?.some((c) =>
            commandEqual(c, clearance),
          ),
      );
  const explanation =
    proposal?.explanation || verified?.payload.proposal?.explanation;
  const model =
    (proposal || verified?.payload.proposal) &&
    visible.findLast(
      (e) =>
        e.kind === "model_response" &&
        e.clock <= event.clock &&
        JSON.stringify(e.payload.proposal) ===
          JSON.stringify(proposal || verified?.payload.proposal),
    );
  const verdict = verified?.payload.verdict?.status || "unresolved";
  const phase =
    {
      clearance_issued: "Issued",
      pilot_acknowledged: "Acknowledged",
      clearance_cancelled: "Cancelled",
      clearance_expired: "Expired",
      touchdown_simulated: "On ground",
      arrival_completed: "Completed",
      synthetic_go_around: "Go-around",
      disruption: "Disruption",
    }[event.kind] ||
    (verdict === "fail"
      ? "Rejected"
      : event.kind === "proposal_verified" && verdict === "unresolved"
        ? "Unresolved"
        : "Proposed");
  const action = clearance
    ? `${clearance.kind || "Clearance"}${clearance.target ? " · " + clearance.target : ""}${clearance.value != null ? " · " + clearance.value : ""}`
    : event.kind === "disruption"
      ? `${p.kind || "Runway change"} · ${p.runway || ""}`
      : phase;
  return {
    key: `${event.sequence}:${event.kind}`,
    clock: event.clock,
    phase,
    action,
    aircraft_id: id || null,
    callsign: aircraft?.callsign || id || null,
    runway: clearance?.target || aircraft?.runway || null,
    explanation:
      explanation ||
      p.reason ||
      "Committed simulation event; no separate controller explanation supplied.",
    origin: model
      ? frame.controller?.includes("fixture")
        ? "Fixture explanation"
        : "Model explanation"
      : "Deterministic demo controller",
    verdict,
    has_verification: !!(verified || proposal || clearance),
    clearance: p.text || null,
    clearance_clock: p.text ? event.clock : null,
    actions: issued.map((e) => ({
      aircraft_id: e.payload.clearance.aircraft_id,
      text: e.payload.text || e.payload.clearance.kind,
    })),
  };
}
// Uses foreground elapsed time, independent of simulation playback speed.
export class DecisionVisibility {
  constructor() {
    this.key = null;
    this.elapsed = 0;
    this.last = null;
    this.seek = false;
  }
  update(key, now, paused = false, seek = false) {
    if (key !== this.key || seek) {
      this.key = key;
      this.elapsed = 0;
      this.seek = seek;
      this.last = now;
    }
    if (this.last !== null && !paused)
      this.elapsed += Math.min(1000, Math.max(0, now - this.last));
    this.last = now;
    return !!key && this.elapsed < 8000;
  }
}

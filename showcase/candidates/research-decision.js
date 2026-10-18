// Public proposal explanations, never hidden reasoning or inferred clearances.
export function decisionAt(events, frame, clock, baseline = false) {
  if (!frame || frame.mode === "historical" || baseline) return null;
  const visible = events
    .filter((e) => e.clock <= clock)
    .sort((a, b) => a.sequence - b.sequence);
  const verified = visible.filter((e) => e.kind === "proposal_verified").at(-1);
  const model = visible
    .filter((e) => e.kind === "model_response" && e.payload?.proposal)
    .at(-1);
  const proposal = model?.payload.proposal || verified?.payload.proposal;
  if (!proposal) return null;
  const order = proposal.sequence?.length
    ? proposal.sequence
    : (proposal.clearances || []).map((c) => c.aircraft_id);
  const next = order
    .map((id) => frame.aircraft.find((a) => a.id === id))
    .find((a) => a && !["complete", "diverted", "landed"].includes(a.status));
  const issued = visible
    .filter(
      (e) =>
        e.kind === "clearance_issued" &&
        e.payload.clearance?.aircraft_id === next?.id,
    )
    .at(-1);
  const matching = visible
    .filter(
      (e) =>
        e.kind === "proposal_verified" &&
        e.clock >= (model?.clock ?? 0) &&
        JSON.stringify(e.payload.proposal) === JSON.stringify(proposal),
    )
    .at(-1);
  return {
    clock: model?.clock ?? verified?.clock,
    explanation: proposal.explanation || "No explanation supplied",
    origin: model
      ? frame.controller?.includes("fixture")
        ? "Fixture explanation"
        : "Model explanation"
      : "Deterministic / authored explanation",
    verdict:
      (model ? matching : verified)?.payload.verdict?.status || "unresolved",
    aircraft_id: next?.id || null,
    callsign: next?.callsign || null,
    runway: next?.runway || null,
    clearance: issued?.payload.text || null,
    clearance_clock: issued?.clock || null,
  };
}

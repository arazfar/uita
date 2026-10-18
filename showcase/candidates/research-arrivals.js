export function arrivalLabel(a) {
  const cue = a?.arrival_cue;
  if (!cue) return a?.status || "Unknown";
  if (cue.basis === "inferred") return "Approaching SFO · inferred";
  return (
    {
      approaching: "Approaching",
      clearance_issued: "Landing clearance issued",
      landing_authorized: "Landing authorized",
      on_ground: "On ground",
      arrival_completed: "Arrival completed",
    }[cue.phase] || "Unknown"
  );
}
export function landingCandidates(frame) {
  return (frame?.aircraft || [])
    .filter(
      (a) =>
        a.arrival_cue &&
        ["approaching", "clearance_issued", "landing_authorized"].includes(
          a.arrival_cue.phase,
        ),
    )
    .sort(
      (a, b) =>
        (a.arrival_cue.phase === "landing_authorized" ? 0 : 1) -
          (b.arrival_cue.phase === "landing_authorized" ? 0 : 1) ||
        (a.arrival_cue.distance_nm ?? Infinity) -
          (b.arrival_cue.distance_nm ?? Infinity) ||
        a.id.localeCompare(b.id),
    );
}

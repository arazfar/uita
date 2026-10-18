/** @typedef {import("./research.generated").components["schemas"]["PresentationFrame"]} PresentationFrame */
// One authenticated client. A failed connection never substitutes scripted traffic.
export async function api(path, body, signal) {
  const response = await fetch("/api/v2" + path, {
    credentials: "same-origin",
    signal: signal ?? AbortSignal.timeout(15000),
    ...(body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(
      response.status === 401
        ? "Session expired. Sign in to reconnect."
        : typeof data.detail === "string"
          ? data.detail
          : `Request failed (${response.status})`,
    );
    error.status = response.status;
    throw error;
  }
  return data;
}
export function mutation(frame, values) {
  return {
    expected_revision: frame.revision,
    idempotency_key: crypto.randomUUID(),
    ...values,
  };
}
export function atClock(frames, clock) {
  return frames.filter((f) => f.clock <= clock).at(-1) ?? null;
}
export function uniqueEvents(events) {
  return [...new Map(events.map((e) => [e.sequence, e])).values()].sort(
    (a, b) => a.sequence - b.sequence,
  );
}
export function validMessage(event, source, type) {
  return (
    event.origin === location.origin &&
    event.source === source &&
    event.data?.type === type
  );
}
export function plottable(a) {
  return (
    Number.isFinite(a.longitude) &&
    Number.isFinite(a.latitude) &&
    Number.isFinite(a.altitude_ft) &&
    !["complete", "diverted", "pending"].includes(a.status) &&
    (a.status !== "observed" || a.age_seconds <= 15)
  );
}
export const timeLabel = (t) =>
  new Date(t * 1000).toLocaleString("en-US", {
    timeZone: "America/Los_Angeles",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  });

// Recorded frames may be interpolated for display only. Aircraft never appear
// before their recorded entry, and missing altitude/status transitions are held.
/** @param {PresentationFrame[]} frames @param {number} clock */
export function displayFrame(frames, clock) {
  const before = atClock(frames, clock);
  const after = frames.find((f) => f.clock > clock);
  if (!before || !after || after.clock === before.clock) return before;
  if (after.clock - before.clock > 60) return before;
  const fraction = (clock - before.clock) / (after.clock - before.clock);
  const next = new Map(after.aircraft.map((a) => [a.id, a]));
  return {
    ...before,
    aircraft: before.aircraft.map((a) => {
      const b = next.get(a.id);
      if (
        !b ||
        b.status !== a.status ||
        !plottable(a) ||
        !plottable(b) ||
        a.provenance?.segment_id !== b.provenance?.segment_id ||
        Math.hypot(b.latitude - a.latitude, b.longitude - a.longitude) > 0.3
      )
        return a;
      return {
        ...a,
        longitude: a.longitude + (b.longitude - a.longitude) * fraction,
        latitude: a.latitude + (b.latitude - a.latitude) * fraction,
        altitude_ft: a.altitude_ft + (b.altitude_ft - a.altitude_ft) * fraction,
        track_deg_true:
          Number.isFinite(a.track_deg_true) && Number.isFinite(b.track_deg_true)
            ? (a.track_deg_true +
                (((b.track_deg_true - a.track_deg_true + 540) % 360) - 180) *
                  fraction +
                360) %
              360
            : a.track_deg_true,
        provenance: { ...a.provenance, presentation_interpolation: true },
      };
    }),
  };
}

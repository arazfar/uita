/** Original PostgreSQL observations returned by the existing history API. */
export type HistoryPoint = [
  t: number,
  latitude: number,
  longitude: number,
  altitudeFt: number | null,
  speedKt: number | null,
  heading: number | null,
  onGround: boolean | null,
  newLeg: boolean,
  callsign: string,
  registration: string | null,
  aircraftType: string | null,
];
export type HistoryFlight = {
  id: string;
  callsign: string;
  registration: string | null;
  type: string | null;
  points: HistoryPoint[];
};
export type HistoryWindow = {
  start: number;
  end: number;
  flights: HistoryFlight[];
  weather: [
    number,
    number | null,
    number | null,
    number | null,
    number | null,
  ][];
  sample_seconds: number;
  stale_after_seconds: number;
};
export type HistoryCatalog = {
  start: number;
  end: number;
  timezone: string;
  chunk_seconds: number;
  source: string;
  source_url: string;
  license: string;
  loaded_at: string | null;
  days: Array<{ date: string; rows: number; first: number; last: number }>;
  runways: Array<{
    id: string;
    start: [number, number];
    end: [number, number];
  }>;
  daily_operations: Array<{ date: string; total: number }>;
  limits: string[];
};
export type DisplayTarget = {
  id: string;
  callsign: string;
  aircraftType?: string;
  registration?: string;
  source: string;
  state: {
    t: number;
    x: number;
    y: number | null;
    z: number;
    latitude: number;
    longitude: number;
    altitudeFt: number | null;
    speedKt: number | null;
    heading: number | null;
    onGround: boolean | null;
  };
  trail: Array<{ t: number; x: number; y: number; z: number }>;
};
export type HistoryWeather = {
  t: number;
  visibilityMi: number | null;
  ceilingFt: number | null;
  windKt: number | null;
  windDirection: number | null;
};
export const HISTORY_TIMEZONE = "America/Los_Angeles";
export const HISTORY_STALE_SECONDS = 15;
export const HISTORY_TRAIL_SECONDS = 120;
const numeric = (value: number | null): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;
const east = (longitude: number) => (longitude + 122.3826) * 88288.08474587766;
const south = (latitude: number) => -(latitude - 37.6164) * 110989.20390546018;
const height = (point: HistoryPoint): number | null =>
  point[6] === true
    ? 3
    : numeric(point[3]) === null
      ? null
      : point[3]! * 0.3048;

/** Last observation at or before time. Never borrow a future observation. */
export function latestObservationIndex(
  points: HistoryPoint[],
  time: number,
): number {
  let low = 0,
    high = points.length;
  while (low < high) {
    const mid = (low + high) >>> 1;
    if (points[mid][0] <= time) low = mid + 1;
    else high = mid;
  }
  return low - 1;
}

export function targetsAtTime(
  frame: HistoryWindow | null,
  time: number,
  source: string,
): DisplayTarget[] {
  if (
    !frame ||
    !Number.isFinite(time) ||
    time < frame.start ||
    time >= frame.end
  )
    return [];
  const targets: DisplayTarget[] = [];
  for (const flight of frame.flights) {
    const index = latestObservationIndex(flight.points, time),
      p = flight.points[index];
    if (
      !p ||
      time - p[0] > HISTORY_STALE_SECONDS ||
      !Number.isFinite(p[1]) ||
      !Number.isFinite(p[2])
    )
      continue;
    const trail: DisplayTarget["trail"] = [];
    for (let j = index; j >= 0; j--) {
      const q = flight.points[j],
        y = height(q);
      if (
        time - q[0] > HISTORY_TRAIL_SECONDS ||
        y === null ||
        !Number.isFinite(q[1]) ||
        !Number.isFinite(q[2])
      )
        break;
      const next = flight.points[j + 1];
      if (j < index && (next[0] - q[0] > HISTORY_STALE_SECONDS || next[7]))
        break;
      trail.push({ t: q[0], x: east(q[2]), y, z: south(q[1]) });
    }
    trail.reverse();
    targets.push({
      id: flight.id,
      // Identity belongs to this observation; an aircraft may change flights within one window.
      callsign: p[8] || p[9] || flight.id,
      aircraftType: p[10] || undefined,
      registration: p[9] || undefined,
      source,
      state: {
        t: p[0],
        x: east(p[2]),
        y: height(p),
        z: south(p[1]),
        latitude: p[1],
        longitude: p[2],
        altitudeFt: numeric(p[3]),
        speedKt: numeric(p[4]),
        heading: numeric(p[5]),
        onGround: p[6] ?? null,
      },
      trail,
    });
  }
  return targets.sort(
    (a, b) => a.callsign.localeCompare(b.callsign) || a.id.localeCompare(b.id),
  );
}

export function weatherAtTime(
  frame: HistoryWindow | null,
  time: number,
): HistoryWeather | null {
  const p = frame?.weather.filter((point) => point[0] <= time).at(-1);
  return p
    ? {
        t: p[0],
        visibilityMi: numeric(p[1]),
        ceilingFt: numeric(p[2]),
        windKt: numeric(p[3]),
        windDirection: numeric(p[4]),
      }
    : null;
}
const clockFormat = new Intl.DateTimeFormat("en-US", {
  timeZone: HISTORY_TIMEZONE,
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
  timeZoneName: "short",
});
const timeFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: HISTORY_TIMEZONE,
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});
const dateFormat = new Intl.DateTimeFormat("en-CA", {
  timeZone: HISTORY_TIMEZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});
export const formatReplayTime = (epoch: number): string =>
  Number.isFinite(epoch) && epoch > 0
    ? clockFormat.format(new Date(epoch * 1000))
    : "Connecting…";
export const formatLocalTime = (epoch: number): string =>
  Number.isFinite(epoch) && epoch > 0
    ? timeFormat.format(new Date(epoch * 1000))
    : "";
export const dayKey = (epoch: number): string =>
  dateFormat.format(new Date(epoch * 1000));

// Indexed in-memory dataset + time queries. Pure functions, no DOM.
import { compileTrack, lowerBound, upperBound } from './interpolate'
import { toUnix } from './time'
import type { CompiledTrack, Flight, FlightsFile, TracksFile, Week } from './types'

export interface Dataset {
  week: Week
  /** sorted by t */
  flights: Flight[]
  /** flights[i].t, for binary search */
  times: Float64Array
  byId: Map<string, Flight>
  tracks: Map<string, CompiledTrack>
  /** tracks sorted by t0 */
  trackList: CompiledTrack[]
  trackT0: Float64Array
  maxTrackDur: number
  /** arrPrefix[i] = number of arrivals among flights[0..i) */
  arrPrefix: Int32Array
}

export function buildDataset(ff: FlightsFile, tf: TracksFile): Dataset {
  const flights = ff.flights.slice().sort((a, b) => a.t - b.t)
  const times = Float64Array.from(flights, (f) => f.t)
  const byId = new Map(flights.map((f) => [f.id, f]))
  const arrPrefix = new Int32Array(flights.length + 1)
  flights.forEach((f, i) => (arrPrefix[i + 1] = arrPrefix[i] + (f.kind === 'arr' ? 1 : 0)))

  const tracks = new Map<string, CompiledTrack>()
  for (const [id, pts] of Object.entries(tf)) {
    if (byId.has(id) && pts.length) tracks.set(id, compileTrack(id, pts))
  }
  const trackList = [...tracks.values()].sort((a, b) => a.t0 - b.t0)
  const trackT0 = Float64Array.from(trackList, (t) => t.t0)
  const maxTrackDur = trackList.reduce((m, t) => Math.max(m, t.t1 - t.t0), 0)

  return {
    week: { start: toUnix(ff.week.start_utc), end: toUnix(ff.week.end_utc), tz: ff.week.tz },
    flights,
    times,
    byId,
    tracks,
    trackList,
    trackT0,
    maxTrackDur,
    arrPrefix,
  }
}

/** Number of flights with op time <= t. */
export const eventCount = (ds: Dataset, t: number) => upperBound(ds.times, t)

/** Last `limit` events with op time <= t, newest first. */
export function recentEvents(ds: Dataset, t: number, limit: number): Flight[] {
  const end = eventCount(ds, t)
  const out: Flight[] = []
  for (let i = end - 1; i >= 0 && out.length < limit; i--) out.push(ds.flights[i])
  return out
}

/** Arrivals/departures with op time in (from, to]. */
export function countKinds(ds: Dataset, from: number, to: number) {
  const a = upperBound(ds.times, from)
  const b = upperBound(ds.times, to)
  const arr = ds.arrPrefix[b] - ds.arrPrefix[a]
  return { arr, dep: b - a - arr }
}

/** Flights without a track whose op time is in (t - windowSec, t]. */
export function recentNoTrack(ds: Dataset, t: number, windowSec: number): Flight[] {
  const out: Flight[] = []
  for (let i = upperBound(ds.times, t) - 1; i >= lowerBound(ds.times, t - windowSec); i--) {
    if (!ds.flights[i].has_track || !ds.tracks.has(ds.flights[i].id)) out.push(ds.flights[i])
  }
  return out
}

/** Tracks whose time span contains t. */
export function activeTracks(ds: Dataset, t: number): CompiledTrack[] {
  const out: CompiledTrack[] = []
  const lo = lowerBound(ds.trackT0, t - ds.maxTrackDur)
  const hi = upperBound(ds.trackT0, t)
  for (let i = lo; i < hi; i++) if (ds.trackList[i].t1 >= t) out.push(ds.trackList[i])
  return out
}

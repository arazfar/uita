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
}

export function buildDataset(ff: FlightsFile, tf: TracksFile): Dataset {
  const start = toUnix(ff.week.start_utc)
  const end = toUnix(ff.week.end_utc)
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) throw new Error('Invalid replay time range')
  if (ff.flights.some((flight) => flight.t < start || flight.t >= end)) throw new Error('Operation outside replay time range')
  // Coverage and the feed must agree with the actual paths loaded into the map.
  if (ff.flights.some((flight) => flight.has_track !== Boolean(tf[flight.id]?.length >= 2))) {
    throw new Error('Roster and path coverage disagree; regenerate replay data')
  }
  const flights = ff.flights.slice().sort((a, b) => a.t - b.t)
  const times = Float64Array.from(flights, (f) => f.t)
  const byId = new Map(flights.map((f) => [f.id, f]))

  const tracks = new Map<string, CompiledTrack>()
  for (const [id, pts] of Object.entries(tf)) {
    if (byId.has(id) && pts.length) tracks.set(id, compileTrack(id, pts))
  }
  const trackList = [...tracks.values()].sort((a, b) => a.t0 - b.t0)
  const trackT0 = Float64Array.from(trackList, (t) => t.t0)
  const maxTrackDur = trackList.reduce((m, t) => Math.max(m, t.t1 - t.t0), 0)

  return {
    week: { start, end, tz: ff.week.tz },
    flights,
    times,
    byId,
    tracks,
    trackList,
    trackT0,
    maxTrackDur,
  }
}

/** Number of flights with op time <= t. */
export const eventCount = (ds: Dataset, t: number) => upperBound(ds.times, t)

/** Last `limit` flights with a map path and op time <= t, newest first. */
export function recentTracked(ds: Dataset, t: number, limit: number): Flight[] {
  const out: Flight[] = []
  for (let i = eventCount(ds, t) - 1; i >= 0 && out.length < limit; i--) {
    if (ds.tracks.has(ds.flights[i].id)) out.push(ds.flights[i])
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

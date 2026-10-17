// Data contract for web/public/data/*. Pure types, no runtime deps.

export type Kind = 'arr' | 'dep'

export interface Flight {
  id: string
  kind: Kind
  /** unix seconds UTC: arrival/departure operation time at the runway */
  t: number
  callsign: string
  reg: string
  type: string
  airline: string
  /** origin for arrivals, destination for departures */
  port: string
  runway: string
  has_track: boolean
}

export interface WeekInfo {
  start_utc: number | string
  end_utc: number | string
  tz: string
}

export interface FlightsFile {
  week: WeekInfo
  flights: Flight[]
}

/** [t unix s, lon, lat, alt_ft | null, spd_kt | null] */
export type TrackPoint = [number, number, number, number | null, number | null]
export type TracksFile = Record<string, TrackPoint[]>

/** Track precomputed into typed arrays for fast binary search. */
export interface CompiledTrack {
  id: string
  n: number
  t0: number
  t1: number
  ts: Float64Array
  lon: Float64Array
  lat: Float64Array
  /** NaN where unknown */
  alt: Float32Array
  /** NaN where unknown */
  spd: Float32Array
}

export interface Sample {
  lon: number
  lat: number
  /** feet, NaN if unknown */
  alt: number
  /** knots, NaN if unknown */
  spd: number
  /** degrees clockwise from north */
  heading: number
}

export interface Week {
  start: number
  end: number
  tz: string
}

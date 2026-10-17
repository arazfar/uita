// Pure track compilation + time interpolation. Reusable by the sim.
import type { CompiledTrack, Sample, TrackPoint } from './types'

export const MAX_TRACK_GAP_SEC = 120

export function compileTrack(id: string, points: TrackPoint[]): CompiledTrack {
  const pts = points.slice().sort((a, b) => a[0] - b[0])
  const n = pts.length
  const ts = new Float64Array(n)
  const lon = new Float64Array(n)
  const lat = new Float64Array(n)
  const alt = new Float32Array(n)
  const spd = new Float32Array(n)
  for (let i = 0; i < n; i++) {
    const p = pts[i]
    ts[i] = p[0]
    lon[i] = p[1]
    lat[i] = p[2]
    alt[i] = p[3] ?? NaN
    spd[i] = p[4] ?? NaN
  }
  return { id, n, t0: n ? ts[0] : 0, t1: n ? ts[n - 1] : 0, ts, lon, lat, alt, spd }
}

/** Index of first element >= x in sorted array (length if none). */
export function lowerBound(a: ArrayLike<number>, x: number): number {
  let lo = 0
  let hi = a.length
  while (lo < hi) {
    const mid = (lo + hi) >>> 1
    if (a[mid] < x) lo = mid + 1
    else hi = mid
  }
  return lo
}

/** Index of first element > x in sorted array (length if none). */
export function upperBound(a: ArrayLike<number>, x: number): number {
  let lo = 0
  let hi = a.length
  while (lo < hi) {
    const mid = (lo + hi) >>> 1
    if (a[mid] <= x) lo = mid + 1
    else hi = mid
  }
  return lo
}

export function bearingDeg(lon1: number, lat1: number, lon2: number, lat2: number): number {
  const r = Math.PI / 180
  const dl = (lon2 - lon1) * r
  const p1 = lat1 * r
  const p2 = lat2 * r
  const y = Math.sin(dl) * Math.cos(p2)
  const x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl)
  return ((Math.atan2(y, x) / r) + 360) % 360
}

function lerpNaN(a: number, b: number, f: number): number {
  // A reported height cannot establish the height at an unmeasured neighbour.
  if (f === 0) return a
  if (f === 1) return b
  if (Number.isNaN(a) || Number.isNaN(b)) return NaN
  return a + (b - a) * f
}

/**
 * Position at time t, or null if t is outside the track's span or inside a
 * sample gap longer than maxGapSec (observed paths only, gaps are not filled).
 */
export function sampleTrack(tr: CompiledTrack, t: number, maxGapSec = MAX_TRACK_GAP_SEC): Sample | null {
  if (tr.n < 2 || t < tr.t0 || t > tr.t1) return null
  let i = upperBound(tr.ts, t) - 1 // last point with ts <= t
  if (i >= tr.n - 1) i = tr.n - 2
  const ta = tr.ts[i]
  const tb = tr.ts[i + 1]
  if (tb - ta > maxGapSec) return null
  const f = tb > ta ? (t - ta) / (tb - ta) : 0
  const lon = tr.lon[i] + (tr.lon[i + 1] - tr.lon[i]) * f
  const lat = tr.lat[i] + (tr.lat[i + 1] - tr.lat[i]) * f
  let heading = bearingDeg(tr.lon[i], tr.lat[i], tr.lon[i + 1], tr.lat[i + 1])
  if (tr.lon[i] === tr.lon[i + 1] && tr.lat[i] === tr.lat[i + 1]) {
    // stationary segment: borrow the neighbouring segment's heading
    const j = i > 0 ? i - 1 : i + 2 < tr.n ? i + 1 : i
    heading = bearingDeg(tr.lon[j], tr.lat[j], tr.lon[j + 1] ?? tr.lon[j], tr.lat[j + 1] ?? tr.lat[j])
  }
  return {
    lon,
    lat,
    alt: lerpNaN(tr.alt[i], tr.alt[i + 1], f),
    spd: lerpNaN(tr.spd[i], tr.spd[i + 1], f),
    heading,
  }
}

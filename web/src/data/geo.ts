// Geometry helpers: NM rings, runway thresholds.
import type { RunwayCollection } from './loaders'

export const SFO: [number, number] = [-122.379, 37.6213] // lon, lat
const NM_M = 1852
const R_EARTH = 6371008.8

/** Closed ring of points at a given distance (NM) from a center. */
export function ring(center: [number, number], nm: number, steps = 180): [number, number][] {
  const [lon0, lat0] = center
  const d = (nm * NM_M) / R_EARTH
  const r = Math.PI / 180
  const out: [number, number][] = []
  for (let i = 0; i <= steps; i++) {
    const b = (i / steps) * 2 * Math.PI
    const p1 = lat0 * r
    const lat = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(b))
    const lon = lon0 * r + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(p1), Math.cos(d) - Math.sin(p1) * Math.sin(lat))
    out.push([lon / r, lat / r])
  }
  return out
}

/** Point at bearing/distance from a center (used for ring labels). */
export function destination(center: [number, number], nm: number, bearing: number): [number, number] {
  const r = Math.PI / 180
  const d = (nm * NM_M) / R_EARTH
  const p1 = center[1] * r
  const b = bearing * r
  const lat = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(b))
  const lon = center[0] * r + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(p1), Math.cos(d) - Math.sin(p1) * Math.sin(lat))
  return [lon / r, lat / r]
}

function bearing(a: number[], b: number[]): number {
  const r = Math.PI / 180
  const dl = (b[0] - a[0]) * r
  const y = Math.sin(dl) * Math.cos(b[1] * r)
  const x = Math.cos(a[1] * r) * Math.sin(b[1] * r) - Math.sin(a[1] * r) * Math.cos(b[1] * r) * Math.cos(dl)
  return ((Math.atan2(y, x) / r) + 360) % 360
}

const angDiff = (a: number, b: number) => Math.abs(((a - b + 540) % 360) - 180)

/** "28R" / "28r" / "1L" -> "28R" / "01L" */
function normRunway(name: string): { num: number; side: string; key: string } | null {
  const m = /^0*(\d{1,2})\s*([LRC]?)/i.exec(name.trim())
  if (!m) return null
  const num = Number(m[1])
  const side = m[2].toUpperCase()
  return { num, side, key: `${String(num).padStart(2, '0')}${side}` }
}

/**
 * Threshold point per runway designator (e.g. "28R"), derived from the runway
 * polygons: of the two short-edge midpoints, the threshold is the end whose
 * direction toward the other end best matches the runway heading.
 */
export function runwayThresholds(fc: RunwayCollection): Map<string, [number, number]> {
  const out = new Map<string, [number, number]>()
  for (const f of fc.features) {
    const pair = f.properties.runway_pair
    const c = f.geometry.coordinates[0]
    if (!pair || c.length < 5) continue
    // longest edges are the sides; short edges are the ends
    const edges = [0, 1, 2, 3].map((i) => ({ i, len: Math.hypot(c[i + 1][0] - c[i][0], (c[i + 1][1] - c[i][1]) * 1.26) }))
    const shortEdges = edges.sort((a, b) => a.len - b.len).slice(0, 2)
    const mids = shortEdges.map(({ i }) => [(c[i][0] + c[i + 1][0]) / 2, (c[i][1] + c[i + 1][1]) / 2])
    for (const name of pair.split('/')) {
      const rw = normRunway(name)
      if (!rw) continue
      const heading = rw.num * 10
      const [a, b] = mids
      const useA = angDiff(bearing(a, b), heading) <= angDiff(bearing(b, a), heading)
      out.set(rw.key, (useA ? a : b) as [number, number])
    }
  }
  return out
}

export function thresholdFor(map: Map<string, [number, number]>, runway: string): [number, number] {
  const rw = normRunway(runway)
  return (rw && map.get(rw.key)) || SFO
}

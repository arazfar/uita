// Geometry helpers for range rings and labels.

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

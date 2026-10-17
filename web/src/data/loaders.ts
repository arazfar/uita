// Fetch + validate static data. URLs are parameters so other apps can reuse.
import type { FlightsFile, KpisFile, TracksFile } from './types'

export interface Polygon { type: 'Polygon'; coordinates: number[][][] }
export interface RunwayFeature { type: 'Feature'; properties: { runway_pair?: string }; geometry: Polygon }
export interface RunwayCollection { type: 'FeatureCollection'; features: RunwayFeature[] }

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`)
  try {
    return (await res.json()) as T
  } catch {
    // Vite dev server answers unknown paths with index.html (HTTP 200)
    throw new Error(`${url}: not valid JSON (file missing?)`)
  }
}

export async function loadFlights(url: string): Promise<FlightsFile> {
  const data = await getJson<FlightsFile>(url)
  if (!data?.week || !Array.isArray(data.flights) || !data.flights.length) throw new Error(`${url}: invalid flight roster`)
  const ids = new Set<string>()
  for (const flight of data.flights) {
    if (typeof flight.id !== 'string' || ids.has(flight.id) || !Number.isFinite(flight.t) ||
      !['arr', 'dep'].includes(flight.kind) || typeof flight.has_track !== 'boolean') {
      throw new Error(`${url}: invalid or duplicate operation`)
    }
    ids.add(flight.id)
  }
  return data
}

export async function loadTracks(url: string): Promise<TracksFile> {
  const data = await getJson<TracksFile>(url)
  if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error(`${url}: invalid tracks`)
  for (const [id, points] of Object.entries(data)) {
    if (!Array.isArray(points) || points.length < 2 || points.some((point, i) =>
      !Array.isArray(point) || point.length !== 5 || !point.slice(0, 3).every(Number.isFinite) ||
      Math.abs(point[1]) > 180 || Math.abs(point[2]) > 90 ||
      point.slice(3).some((value) => value !== null && !Number.isFinite(value)) ||
      (i > 0 && point[0] <= points[i - 1][0]))) throw new Error(`${url}: invalid track ${id}`)
  }
  return data
}
export const loadRunways = (url: string) => getJson<RunwayCollection>(url)
export async function loadKpis(url: string): Promise<KpisFile> {
  const data = await getJson<KpisFile>(url)
  if (!data || !Array.isArray(data.sep_events) || !Array.isArray(data.go_arounds) || !data.coverage ||
    Object.values(data.coverage).some((value) => !Number.isInteger(value) || value < 0)) {
    throw new Error(`${url}: invalid KPI data; regenerate the replay`)
  }
  return data
}

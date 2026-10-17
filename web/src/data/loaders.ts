// Fetch + validate static data. URLs are parameters so other apps can reuse.
import type { FlightsFile, TracksFile } from './types'

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

export const loadFlights = (url: string) => getJson<FlightsFile>(url)
export const loadTracks = (url: string) => getJson<TracksFile>(url)
export const loadRunways = (url: string) => getJson<RunwayCollection>(url)

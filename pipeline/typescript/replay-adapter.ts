/** Causal observed replay. Shows last received point; never interpolates toward a future sample. */
export interface ObservedPoint {
  t: number; lon: number; lat: number; altitude_ft: number | null;
  groundspeed_kt: number | null; track_deg_true: number | null; segment_id: number;
  altitude_reference: string;
}
export interface ObservedTrack { flight_id:string; points:ObservedPoint[] }
export function observedAt(track: ObservedTrack, clock: number, maxAgeSeconds=120) {
  let low=0, high=track.points.length;
  while (low<high) { const mid=(low+high)>>>1; if (track.points[mid].t<=clock) low=mid+1; else high=mid; }
  if (!low) return null;
  const p=track.points[low-1];
  const age=clock-p.t;
  if(age>maxAgeSeconds)return null;
  return { ...p, age_seconds:age, stale:age>30, provenance:'observed' as const };
}

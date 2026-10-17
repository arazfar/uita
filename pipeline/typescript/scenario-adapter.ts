/** Shared by browser and headless harness. Keep the pack in the simulator, outside agent prompts. */
export interface Entry {
  flight_id: string; callsign: string; aircraft_type: string; origin: string;
  spawn_time: number;
  position: { lon: number; lat: number; altitude_ft: number };
  groundspeed_kt: number; track_deg_true: number;
  position_provenance: string; altitude_provenance: string; motion_provenance: string;
}
export interface Weather {
  id: string; observed_at: number; available_at: number;
  wind_direction_deg_true: number | null; wind_speed_kt: number | null;
  wind_gust_kt: number | null; visibility_sm: number | null; altimeter_inhg: number | null;
  metar: string | null;
}
export interface Scenario {
  schema_version: 1; dataset_id: string; id: string; split: 'train' | 'validation' | 'test';
  clock_start: number; clock_end: number; entries: Entry[]; weather: Weather[];
}

export class ScenarioAdapter {
  readonly #entries: Entry[];
  readonly #weather: Weather[];
  #cursor = 0;
  #clock = -Infinity;
  constructor(pack: Scenario) {
    if (pack.schema_version !== 1) throw new Error('Unsupported scenario schema');
    this.#entries = structuredClone(pack.entries).sort((a,b) => a.spawn_time-b.spawn_time || a.flight_id.localeCompare(b.flight_id));
    this.#weather = structuredClone(pack.weather).sort((a,b) => a.available_at-b.available_at);
  }
  advance(clock: number) {
    if (!Number.isFinite(clock) || clock < this.#clock) throw new Error('Clock must advance monotonically');
    this.#clock = clock;
    const spawned: Entry[] = [];
    while (this.#cursor < this.#entries.length && this.#entries[this.#cursor].spawn_time <= clock) {
      const e = this.#entries[this.#cursor++];
      spawned.push({ flight_id:e.flight_id, callsign:e.callsign, aircraft_type:e.aircraft_type, origin:e.origin,
        spawn_time:e.spawn_time, position:structuredClone(e.position), groundspeed_kt:e.groundspeed_kt,
        track_deg_true:e.track_deg_true, position_provenance:e.position_provenance,
        altitude_provenance:e.altitude_provenance, motion_provenance:e.motion_provenance });
    }
    let low=0, high=this.#weather.length;
    while (low<high) { const mid=(low+high)>>>1; if (this.#weather[mid].available_at<=clock) low=mid+1; else high=mid; }
    const wx = low ? this.#weather[low-1] : undefined;
    return { clock, spawned, weather:wx ? { ...structuredClone(wx), age_seconds:clock-wx.observed_at,
      stale:clock-wx.observed_at>7200 } : null };
  }
}

export async function loadScenario(baseUrl: string, day: string, fetcher: typeof fetch = fetch): Promise<Scenario> {
  if (!/^2026-08-0[3-9]$/.test(day)) throw new Error('Day outside frozen demo week');
  const response=await fetcher(`${baseUrl.replace(/\/$/,'')}/scenarios/${day}.json`);
  if (!response.ok) throw new Error(`Scenario load failed: ${response.status}`);
  const pack=await response.json() as Scenario;
  if(pack.schema_version!==1 || pack.id!==day || !Array.isArray(pack.entries) || !Array.isArray(pack.weather))
    throw new Error('Invalid scenario pack');
  return pack;
}

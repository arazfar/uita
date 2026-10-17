/** Normalize FAA CSV fields. Runway identifiers use magnetic designation; headings here are TRUE. */
interface AirportCycle {
  effective_date: string;
  end_exclusive_date: string;
  tables: { 'APT_RWY.csv': Record<string,string>[]; 'APT_RWY_END.csv': Record<string,string>[] };
}
export interface AirportReference { airport: string; cycles: AirportCycle[] }
export function airportAt(reference: AirportReference, clock: number) {
  const parts=new Intl.DateTimeFormat('en-US',{ timeZone:'America/Los_Angeles',year:'numeric',month:'2-digit',day:'2-digit' }).formatToParts(new Date(clock*1000));
  const get=(key:string) => parts.find(p=>p.type===key)!.value;
  const day=`${get('year')}-${get('month')}-${get('day')}`;
  const cycle=reference.cycles.find(c=>c.effective_date<=day && day<c.end_exclusive_date);
  if (!cycle) throw new Error('No FAA reference cycle for simulation date');
  const number=(s:string|undefined) => s?.trim() ? Number(s) : null;
  return { airport:reference.airport, effective_date:cycle.effective_date,
    runway_ends:cycle.tables['APT_RWY_END.csv'].map(end=>{
      const runway=cycle.tables['APT_RWY.csv'].find(r=>r.RWY_ID===end.RWY_ID);
      if(!runway)throw new Error('Runway end has no matching physical runway');
      const displaced=number(end.DISPLACED_THR_LEN);
      const threshold=displaced && displaced>0
        ? { lon:number(end.LONG_DISPLACED_THR_DECIMAL), lat:number(end.LAT_DISPLACED_THR_DECIMAL), elevation_ft:number(end.DISPLACED_THR_ELEV) }
        : { lon:number(end.LONG_DECIMAL), lat:number(end.LAT_DECIMAL), elevation_ft:number(end.RWY_END_ELEV) };
      return { id:end.RWY_END_ID, physical_runway:end.RWY_ID, heading_deg_true:number(end.TRUE_ALIGNMENT),
        end:{ lon:number(end.LONG_DECIMAL),lat:number(end.LAT_DECIMAL),elevation_ft:number(end.RWY_END_ELEV) },
        landing_threshold:threshold,length_ft:number(runway.RWY_LEN),width_ft:number(runway.RWY_WIDTH) };
    }), historical_closures_known:false as const };
}

import { readFileSync } from 'node:fs';
import { ScenarioAdapter } from './typescript/scenario-adapter';
import { airportAt } from './typescript/airport-adapter';
import { observedAt } from './typescript/replay-adapter';
const root=new URL('./build/',import.meta.url);
const read=(path:string)=>JSON.parse(readFileSync(new URL(path,root),'utf8'));
const assert=(condition:unknown,message:string)=>{if(!condition)throw new Error(message)};
let total=0;
for(let day=3;day<=9;day++) {
 const pack=read(`scenarios/2026-08-0${day}.json`);
 const adapter=new ScenarioAdapter(pack);
 const sorted=pack.entries.toSorted((a:any,b:any)=>a.spawn_time-b.spawn_time);
 let seen=new Set<string>();
 for(const entry of sorted) {
  const frame=adapter.advance(entry.spawn_time);
  for(const aircraft of frame.spawned) {
   assert(!seen.has(aircraft.flight_id),'duplicate spawn');seen.add(aircraft.flight_id);
   assert(aircraft.spawn_time<=frame.clock,'future spawn');
   assert(!('template_flight_id' in aircraft) && !('runway' in aircraft),'outcome leak');
  }
  assert(!frame.weather || frame.weather.available_at<=frame.clock,'future weather');
 }
 assert(seen.size===pack.entries.length,'missing spawns'); total+=seen.size;
 assert(adapter.advance(sorted.at(-1).spawn_time).spawned.length===0,'duplicate same-clock spawn');
 const airport=airportAt(pack.airport,pack.clock_end-1);
 assert(airport.runway_ends.length===8,'airport runway ends');
 assert(airport.effective_date===(day<6?'2026-07-09':'2026-08-06'),'wrong FAA cycle');
 assert(airport.runway_ends.every((r:any)=>r.landing_threshold.lon && r.landing_threshold.lat),'missing threshold');
}
const track=read('observations.json')[0];
assert(observedAt(track,track.points[0].t-1)===null,'future replay point');
assert(observedAt(track,track.points[0].t)?.t===track.points[0].t,'missing observed point');
assert(observedAt(track,track.points.at(-1).t+121)===null,'stale replay point');
console.log({passed:true,typescript_spawns_verified:total,date_matched_airport_cycles:true,causal_replay:true});

import type { components } from './api.generated';
export type ControlCommand = components['schemas']['Control'];
export type ProposeCommand = components['schemas']['Propose'];
export type TrainCommand = components['schemas']['Train'];
export type CommitCommand = components['schemas']['Commit'];
export type Aircraft = {id:string;callsign:string;type:string;wake:string;operation:string;status:string;x:number;y:number;altitude:number;heading:number;speed:number;runway:string;scheduled:number;requested:number;delay:number;emergency:boolean;diverted?:boolean;exit_occupancy?:number;trajectory:{t:number;x:number;y:number;altitude:number}[]};
export type Check = {id:string;status:string;summary:string;evidence:unknown};
export type Proposal = {id:string;revision:number;status:string;slots:{aircraft_id:string;runway:string;time:number}[];rationale:string;source?:string;verification?:{status:string;checks:Check[];[key:string]:unknown}};
export type Policy = {id:string;name?:string;status?:string;generation?:number;parameters?:Record<string,number>;evaluation?:Record<string,unknown>;[key:string]:unknown};
export type State = {session_id:string;revision:number;time:number;running:boolean;speed:number;seed:number;scenario:string;mode:string;aircraft:Aircraft[];runway_reservations?:{aircraft_id:string;start:number;end:number}[];runways:{id:string;start:[number,number];end:[number,number];closed:boolean}[];weather:{visibility:number;wind:unknown;ceiling:number};disruptions:Record<string,unknown>[];metrics:{completed:number;total:number;mean_delay:number;conflicts:number;throughput:number};events:{time:number;type:string;message:string}[];proposals:Proposal[];policies:Policy[];learning_jobs:Record<string,unknown>[];sources:unknown[];limitations:string[];[key:string]:unknown};
export async function api<T, B=unknown>(path:string,body?:B):Promise<T>{const r=await fetch('/api'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok){const e=await r.json().catch(()=>({detail:r.statusText}));throw Error(typeof e.detail==='string'?e.detail:JSON.stringify(e.detail))}return r.json()}
export const clock=(t:number)=>new Date((16*3600+t)*1000).toISOString().slice(11,19);

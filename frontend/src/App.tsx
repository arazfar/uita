import { useCallback, useEffect, useRef, useState } from 'react';
import { Activity, ArrowDownLeft, ArrowUpRight, Check, ChevronRight, CircleHelp, Download, Eye, FlaskConical, Focus, Layers3, LoaderCircle, Map, Maximize, Pause, Play, Radio, RefreshCcw, RotateCcw, ShieldCheck, SkipForward, SlidersHorizontal, TriangleAlert, X } from 'lucide-react';
import World from './World';
import Comparison from './Comparison';
import type { ComparisonResult } from './Comparison';
import { api, clock } from './types';
import type { State, Proposal, Aircraft, Policy, ControlCommand, ProposeCommand, TrainCommand, CommitCommand, LearningJob, LearningEvent } from './types';
const fmt=(v:unknown)=>typeof v==='number'?Math.round(v*100)/100:typeof v==='string'?v:JSON.stringify(v);
function App(){
 const [state,setState]=useState<State|null>(null),[error,setError]=useState(''),[connectionError,setConnectionError]=useState(''),[busy,setBusy]=useState(''),[tab,setTab]=useState('traffic'),[selected,setSelected]=useState<string|null>(null),[camera,setCamera]=useState('overview'),[routes,setRoutes]=useState(true),[table,setTable]=useState(false),[proposal,setProposal]=useState<Proposal|null>(null),[replay,setReplay]=useState<State|null>(null),[replayTime,setReplayTime]=useState(0),[compare,setCompare]=useState<ComparisonResult|null>(null),[help,setHelp]=useState(false),[disruption,setDisruption]=useState(false),[resource,setResource]=useState<string|null>(null),[toast,setToast]=useState(''),[lastUpdate,setLastUpdate]=useState(Date.now());
 const [newSeed,setNewSeed]=useState('42'),[newScenario,setNewScenario]=useState('baseline');
 const [source,setSource]=useState<'fixture'|'crusoe'>('fixture'),[policyId,setPolicyId]=useState('static'),[revisionLimit,setRevisionLimit]=useState(1),[jobDetails,setJobDetails]=useState<Record<string,LearningJob>>({}),[policyDetails,setPolicyDetails]=useState<Record<string,Policy>>({});
 const compassRef=useRef<HTMLDivElement>(null);
 const updateCompass=useCallback((angle:number)=>{const el=compassRef.current;if(el){el.style.setProperty('--north-angle',`${angle}deg`);el.dataset.northAngle=angle.toFixed(2)}},[]);
 const inFlight=useRef(false),latest=useRef<State|null>(null);latest.current=state;
 const refresh=useCallback(async()=>{if(inFlight.current)return;inFlight.current=true;try{const s=await api<State>('/state');if(!latest.current&&s.active_policy&&s.active_policy!=='baseline')setPolicyId(String(s.active_policy));setState(s);setLastUpdate(Date.now());setConnectionError('')}catch(e){setConnectionError((e as Error).message)}finally{inFlight.current=false}},[]);
 useEffect(()=>{refresh();const t=setInterval(refresh,1000);return()=>clearInterval(t)},[refresh]);
 useEffect(()=>{let cancelled=false;if(state?.learning_jobs.length)Promise.all(state.learning_jobs.map(j=>api<LearningJob>('/learning/jobs/'+j.id).catch(()=>j))).then(js=>{if(!cancelled)setJobDetails(Object.fromEntries(js.map(j=>[String(j.id),j])))});return()=>{cancelled=true}},[state?.learning_jobs.map(j=>[j.id,j.status,j.stage,j.events?.length,j.events?.at(-1)?.sequence].join(':')).join('|')]);
 useEffect(()=>{let cancelled=false;if(state?.policies.length)Promise.all(state.policies.map(p=>api<Policy>('/learning/policies/'+p.id).catch(()=>p))).then(ps=>{if(!cancelled)setPolicyDetails(Object.fromEntries(ps.map(p=>[p.id,p])))});return()=>{cancelled=true}},[state?.policies.map(p=>p.id+p.status).join('|')]);
 useEffect(()=>{if(toast){const t=setTimeout(()=>setToast(''),5000);return()=>clearTimeout(t)}},[toast]);
 const run=async(name:string,fn:()=>Promise<unknown>)=>{setBusy(name);setError('');try{await fn()}catch(e){setError((e as Error).message)}finally{setBusy('')}};
 const control=(action:ControlCommand['action'],extra:Partial<ControlCommand>={})=>run(action,async()=>{setReplay(null);setState(await api<State,ControlCommand>('/control',{seconds:10,speed:latest.current?.speed||1,seed:latest.current?.seed||42,scenario:latest.current?.scenario||'baseline',idempotency_key:crypto.randomUUID(),action,revision:latest.current?.revision,...extra}))});
 const inject=(kind:string,extra={})=>run('disruption',async()=>{setState(await api<State>('/disruptions',{kind,idempotency_key:crypto.randomUUID(),revision:latest.current?.revision,...extra}));setDisruption(false);setToast('Disruption applied. Replan to check the updated constraints.');setTab('decisions')});
 const propose=()=>run('propose',async()=>{if(state?.running)setState(await api<State>('/control',{action:'pause',revision:latest.current?.revision,idempotency_key:crypto.randomUUID()}));setProposal(await api<Proposal,ProposeCommand>('/proposals',{source,policy_id:policyId,idempotency_key:crypto.randomUUID()}));setTab('decisions');await refresh()});
 const verify=()=>proposal&&run('verify',async()=>{setProposal(await api<Proposal>(`/proposals/${proposal.id}/verify`,{}));await refresh()});
 const commit=()=>{const p=proposal||state?.proposals?.[0];return p&&run('commit',async()=>{setState(await api<State,CommitCommand>(`/proposals/${p.id}/commit`,{idempotency_key:crypto.randomUUID(),revision:latest.current?.revision}));setProposal({...p,status:'committed'});setToast('Verified plan committed to the simulation.')})};
 const policies=state?.policies.map(p=>policyDetails[p.id]||p)||[],learningJobs=state?.learning_jobs.map(j=>jobDetails[String(j.id)]||j)||[];
 const providerConfigured=!!(state?.provider as {configured?:boolean}|undefined)?.configured;
 const sourceControl=<label className="source-select">Proposal source<select aria-label="Proposal source" value={source} onChange={e=>setSource(e.target.value as 'fixture'|'crusoe')}><option value="fixture">Offline fixture</option><option value="crusoe" disabled={!providerConfigured}>Crusoe · NVIDIA Nemotron{providerConfigured?'':' (not configured)'}</option></select></label>;
 const active=replay||state, aircraft=active?.aircraft.find(a=>a.id===selected),activeProposal=proposal||state?.proposals?.[0],stale=Date.now()-lastUpdate>7000;
 if(!state||!active)return <main className="startup"><div className="wordmark">uita<span>.</span></div><LoaderCircle className="spin"/><h1>Preparing San Francisco</h1><p>{connectionError?'The simulation service is unavailable. Start the backend on port 8001, then retry.':'Loading the airport, traffic, and authoritative simulation state.'}</p>{connectionError&&<><code>{connectionError}</code><button className="primary" onClick={refresh}>Retry connection</button></>}<small>RESEARCH SIMULATION · NOT FOR OPERATIONAL USE</small></main>;
 const reservationStart=Math.max(400,active.time-60),reservationEnd=reservationStart+600;
 const reservations=active.aircraft.map(a=>{const r=active.runway_reservations?.find(r=>r.aircraft_id===a.id);return {aircraft:a,start:r?.start??a.scheduled,end:r?.end??a.scheduled,verified:!!r}});
 const current=active.aircraft.filter(a=>!['complete','pending','diverted'].includes(a.status));
 return <main className="app-shell">
 <header className="header"><a className="wordmark" href="/" aria-label="Uita home">uita<span>.</span></a><div className="header-divider"/><div className="airport-title"><strong>San Francisco</strong><span>SFO <span className="dot-separator">/</span> West Plan</span></div><div className="header-center"><span className="live-dot"/>{replay?'CHECKPOINT REPLAY':'LIVING SIMULATION'}</div><div className="header-right"><span className="mode-badge">{source==='crusoe'?'CRUSOE SELECTED':'OFFLINE FIXTURE'}</span><button className="icon-button" aria-label="About this simulation" onClick={()=>setHelp(!help)}><CircleHelp size={18}/></button><a className="icon-button" href="/api/export" download="uita-evidence.json" aria-label="Export evidence bundle"><Download size={18}/></a></div></header>
 <section className="workspace">
 <div className="scene-wrap"><World onNorthAngle={updateCompass} state={active} selected={selected} onSelect={id=>{setSelected(id);setResource(null);setTab('traffic')}} mode={camera} routes={routes} onRunway={id=>{setResource(id);setSelected(null);setTab('traffic')}}/>
 <div className="scene-heading"><div className="scene-location">SFO terminal area <span>37°37′ N · 122°23′ W</span></div><h1>San Francisco<br/><span>Terminal operations</span></h1><p>{current.length} aircraft in the model <span>·</span> {active.weather.visibility} SM visibility <span>·</span> {Math.round(active.weather.ceiling).toLocaleString()} ft ceiling</p></div>
 <div className="view-controls" aria-label="Camera controls">{[{id:'overview',icon:Map,label:'Orbit'},{id:'top',icon:Maximize,label:'Top'},{id:'follow',icon:Focus,label:'Follow'},{id:'ground',icon:Eye,label:'Tower'}].map(v=><button key={v.id} className={camera===v.id?'active':''} disabled={v.id==='follow'&&!selected} onClick={()=>setCamera(v.id)} aria-pressed={camera===v.id}><v.icon size={15}/><span>{v.label}</span></button>)}<i/><button className={routes?'active':''} onClick={()=>setRoutes(!routes)} aria-pressed={routes} title="Show modeled trajectories"><Layers3 size={16}/></button><button className={table?'active':''} onClick={()=>setTable(!table)} aria-pressed={table} title="Open accessible traffic table"><SlidersHorizontal size={16}/></button></div>
 <div className="scene-legend"><span><i className="cyan"/>Selected aircraft / trajectory</span><span><i className="amber"/>Constraint or disruption</span><small>SCHEMATIC GEOMETRY · SYNTHETIC TRAFFIC</small></div>
 <div className="compass" ref={compassRef} aria-label="Projected north direction"><span>N</span><svg width="36" height="36" viewBox="0 0 36 36"><path d="M18 2 25 30 18 25 11 30Z" fill="#a3c1c9"/><path d="M18 2V25L11 30Z" fill="#45636c"/></svg></div>
 {replay&&<div className="replay-banner"><RotateCcw size={15}/> Replay at {clock(replay.time)}<button onClick={()=>setReplay(null)}>Return to current</button></div>}
 {table&&<div className="table-overlay"><div className="section-title"><h2>Traffic table</h2><button className="icon-button" onClick={()=>setTable(false)} aria-label="Close traffic table"><X size={17}/></button></div><div className="table-scroll"><table><thead><tr><th>Flight</th><th>State</th><th>Altitude · ft</th><th>Speed · kt</th><th>Runway</th></tr></thead><tbody>{active.aircraft.map(a=><tr key={a.id}><td><button onClick={()=>{setSelected(a.id);setTable(false)}}>{a.callsign}</button></td><td>{a.status}</td><td>{Math.round(a.altitude)}</td><td>{Math.round(a.speed)}</td><td>{a.runway}</td></tr>)}</tbody></table></div></div>}
 </div>
 <aside className="inspector"><div className="tabs" role="tablist" aria-label="Operations inspector">{['traffic','decisions','learning'].map(t=><button key={t} role="tab" aria-selected={tab===t} className={tab===t?'active':''} onClick={()=>setTab(t)}>{t==='traffic'?'Traffic':t==='decisions'?'Decisions':'Learning'}{t==='decisions'&&state.disruptions.length>0&&<i/>}</button>)}</div><div className="panel-scroll">
 {tab==='traffic'&&<><div className="section-title"><h2>{resource?'Runway '+resource:aircraft?'Flight details':'Movement board'}</h2><span className="subtle">{aircraft?'SELECTED':current.length+' ACTIVE'}</span></div>{resource?<><p className="body-copy">Runway {resource} is {state.runways.find(r=>r.id===resource)?.closed?'closed':'available'} in this modeled airport pack. Intersecting resources and wake spacing are evaluated by the independent verifier.</p><button className="secondary full" disabled={!!busy||replay!==null} onClick={()=>inject('runway_closure',{runway:resource})}><TriangleAlert size={15}/> Close runway in simulation</button><button className="text-button" onClick={()=>setResource(null)}>Back to movements</button></>:aircraft?<><FlightDetails aircraft={aircraft}/><div className="button-row"><button className="secondary" onClick={()=>setCamera('follow')}><Focus size={14}/> Follow flight</button><button className="text-button" onClick={()=>setSelected(null)}>All traffic</button></div><h3>Modeled trajectory</h3><p className="body-copy">Position is local east / north in nautical miles. Altitude and speed are supplied by the simulator. Routes show the current modeled path.</p><dl className="detail-list"><div><dt>East / north</dt><dd>{aircraft.x.toFixed(2)} / {aircraft.y.toFixed(2)} NM</dd></div><div><dt>Scheduled</dt><dd>{clock(aircraft.scheduled||0)}</dd></div><div><dt>Emergency</dt><dd>{aircraft.emergency?'Priority declared':'None declared'}</dd></div></dl></>:<><div className="movement-subhead"><span>FLIGHT / TYPE</span><span>STATE / RUNWAY</span></div><div className="flight-list">{active.aircraft.map(a=><button key={a.id} className={`flight-row ${selected===a.id?'selected':''}`} onClick={()=>setSelected(a.id)}><span className={`flight-direction ${a.emergency?'warning':''}`}>{a.operation==='arrival'?<ArrowDownLeft size={18}/>:<ArrowUpRight size={18}/>}</span><span className="flight-identity"><strong>{a.callsign}</strong><small>{a.type} <span>· {a.wake}</span></small></span><span className="flight-state"><strong>{a.status.replaceAll('_',' ')}</strong><small>{a.runway||'UNASSIGNED'} <ChevronRight size={11}/></small></span></button>)}</div></>}
 <div className="panel-bottom-note"><Radio size={15}/><span>Deterministic seed {state.seed}. {state.mode==='crusoe-live'?'Provider connected.':'No live inference or live traffic.'}</span></div></>}
 {tab==='decisions'&&<><div className="section-title"><h2>Plan, verify, commit</h2><ShieldCheck size={18}/></div><p className="body-copy">A proposal has no effect until the independent verifier passes and you commit it.</p>{sourceControl}<label className="source-select">Planning policy<select aria-label="Planning policy" value={policyId} onChange={e=>setPolicyId(e.target.value)}>{policies.filter(p=>p.status!=='rejected').map(p=><option value={p.id} key={p.id}>{p.name||p.id}</option>)}</select></label><button className="primary full" onClick={propose} disabled={!!busy||!!replay}>{busy==='propose'?<LoaderCircle size={16} className="spin"/>:<Activity size={16}/>} Propose movement plan</button>{activeProposal?<div className="proposal"><div className="proposal-head"><strong>Movement proposal</strong><span className={`status ${activeProposal.verification?.status||'pending'}`}>{activeProposal.status==='committed'?'COMMITTED':activeProposal.verification?.status?.toUpperCase()||'UNVERIFIED'}</span></div><p>{activeProposal.rationale}</p><div className="small-data"><span>Snapshot revision</span><code>{activeProposal.revision}</code></div><div className="slot-list">{activeProposal.slots.map((slot,i)=><div key={i}><strong>{state.aircraft.find(a=>a.id===slot.aircraft_id)?.callsign||slot.aircraft_id}</strong><span>{slot.runway}</span><code>{clock(slot.time)}</code></div>)}</div>{activeProposal.verification?.checks?.map(c=><details className="check" key={c.id}><summary><span className={`check-dot ${c.status}`}/><span>{c.summary||c.id}</span><ChevronRight size={13}/></summary><pre>{JSON.stringify(c.evidence,null,2)}</pre></details>)}<div className="button-row"><button className="secondary" disabled={!!busy||!!replay||activeProposal.status==='committed'} onClick={()=>{if(!proposal)setProposal(activeProposal);run('verify',async()=>{setProposal(await api<Proposal>(`/proposals/${activeProposal.id}/verify`,{}));await refresh()})}}><ShieldCheck size={14}/> Verify</button><button className="primary" onClick={commit} disabled={!!busy||!!replay||activeProposal.verification?.status!=='pass'||activeProposal.status==='committed'}><Check size={14}/> Commit plan</button></div></div>:<div className="empty-state"><ShieldCheck size={30}/><h3>No proposal yet</h3><p>Generate a plan to inspect resource reservations and constraint evidence.</p></div>}<h3>Operational record</h3><div className="event-list">{[...active.events].reverse().slice(0,12).map((e,i)=><div key={i}><code>{clock(e.time)}</code><p>{e.message}</p></div>)}{!active.events.length&&<p className="subtle">No events recorded yet.</p>}</div></>}
 {tab==='learning'&&<><div className="section-title"><h2>Policy laboratory</h2><FlaskConical size={18}/></div><p className="body-copy">Evolve bounded observation policies. Rules, verifier, and acceptance thresholds stay fixed.</p><div className="research-note"><strong>{source==='crusoe'?'Crusoe / NVIDIA Nemotron':'Offline fixture mode'}</strong><span>{source==='crusoe'?'Bounded live investigation and revisions precede frozen, independent validation.':'Candidate proposals are deterministic fixtures. No fresh model inference is claimed.'}</span></div>{sourceControl}<label className="source-select">Development revision limit<select aria-label="Development revision limit" value={revisionLimit} onChange={e=>setRevisionLimit(Number(e.target.value))}>{[0,1,2].map(value=><option value={value} key={value}>{value} {value===1?'revision':'revisions'}</option>)}</select></label><button className="primary full" disabled={!!busy||!!replay} onClick={()=>run('train',async()=>{await api<unknown,TrainCommand & {revisions:number}>('/learning/train',{generations:3,source,revisions:revisionLimit,idempotency_key:crypto.randomUUID()});setToast('Bounded experiment started. Results appear as the worker evaluates policies.');await refresh()})}>{busy==='train'?<LoaderCircle size={16} className="spin"/>:<FlaskConical size={16}/>} Run bounded experiment</button><h3>Experiment record</h3>{state.learning_jobs.length?learningJobs.map((j,i)=><details className="job" key={j.id} open={i===0}><summary><strong>{humanize(j.status)}</strong><code>{j.id.slice(0,10)}</code></summary><div className="job-stage"><span role="status">{humanize(j.stage||j.status)}</span>{['queued','running'].includes(j.status)&&<button className="secondary" disabled={!!busy||!!j.cancel_requested} onClick={()=>run('cancel-'+j.id,async()=>{const updated=await api<LearningJob>('/learning/jobs/'+j.id+'/cancel',{});setJobDetails(current=>({...current,[j.id]:updated}));setToast('Cancellation requested. Completed evidence is retained.');await refresh()})}>{busy==='cancel-'+j.id?'Requesting…':j.cancel_requested?'Cancellation requested':'Cancel experiment'}</button>}</div><ExperimentSummary job={j}/><LearningTimeline events={j.events||[]}/><details><summary>Full experiment evidence</summary><DataView value={j}/></details></details>):<p className="body-copy">No experiments have run in this session.</p>}<h3>Policy registry</h3>{policies.map(p=><div className="policy" key={p.id} id={policyAnchor(p.id)}><div className="proposal-head"><strong>{p.name||p.id}</strong><span className="status">{p.status||'REGISTERED'}</span></div><PolicySummary policy={p}/><details><summary>Program & evaluation evidence</summary><DataView value={p}/></details><div className="button-row"><button className="secondary" disabled={!!busy} onClick={()=>run('compare',async()=>setCompare(await api<ComparisonResult>('/compare',{policy_ids:p.id==='baseline'?['baseline','static']:['baseline',p.id]})))}>Compare</button><button className="secondary" disabled={!!busy||p.id==='baseline'||p.status==='promoted'||(p.id!=='static'&&p.status!=='accepted')} onClick={()=>run('promote',async()=>{setState(await api<State>(`/learning/policies/${p.id}/promote`,{}));setPolicyId(p.id);setToast('Policy promotion processed by the backend gate.')} )}>Promote</button></div></div>)}<p className="panel-bottom-note">Rejected candidates remain visible. Promotion is conditional on the backend acceptance gate.</p></>}
 </div><div className="inspector-footer"><button className="secondary full" onClick={()=>setDisruption(!disruption)} disabled={!!replay}><SlidersHorizontal size={15}/> Inject a disruption <ChevronRight size={14}/></button></div></aside>
 </section>
 <footer className="timeline"><div className="transport"><button className="play-button" aria-label={state.running?'Pause simulation':'Play simulation'} disabled={!!busy||!!replay} onClick={()=>control(state.running?'pause':'play')}>{state.running?<Pause size={19} fill="currentColor"/>:<Play size={19} fill="currentColor"/>}</button><div className="time-readout"><strong>{clock(active.time)}</strong><span>{replay?'REPLAY':state.running?'RUNNING':'PAUSED'} · SIM UTC</span></div><button className="icon-button" aria-label="Advance simulation 10 seconds" disabled={!!busy||!!replay} onClick={()=>control('step',{seconds:10})}><SkipForward size={18}/></button><select aria-label="Simulation speed" value={state.speed} onChange={e=>control('speed',{speed:Number(e.target.value)})} disabled={!!replay}><option value={1}>1×</option><option value={5}>5×</option><option value={10}>10×</option><option value={30}>30×</option></select><button className="icon-button reset" aria-label="Reset current scenario" onClick={()=>{setProposal(null);setCompare(null);control('reset',{seed:state.seed,scenario:state.scenario})}} disabled={!!busy}><RefreshCcw size={16}/></button></div><div className="timeline-track"><div className="timeline-caption"><strong>{active.runway_reservations?'Resource reservations':'Scheduled movements'}</strong><span>{active.metrics.completed} completed <i/> {Math.round(active.metrics.mean_delay)}s mean delay <i/> {active.metrics.conflicts??'—'} modeled conflicts</span></div><div className="reservation-track">{[0,1,2,3,4].map(n=><span className="time-tick" key={n} style={{left:`${n*25}%`}}>{clock(reservationStart+n*150)}</span>)}{['28L','28R','01L','01R'].map((r,lane)=><div className="reservation-lane" key={r} style={{top:15+lane*14}}><span>{r}</span>{reservations.filter(item=>item.aircraft.runway===r&&item.end>=reservationStart&&item.start<reservationEnd).map(item=>{const a=item.aircraft,left=Math.max(item.start,reservationStart);return <button title={`${a.callsign} · ${a.runway} · ${item.verified?`protected ${clock(item.start)}–${clock(item.end)} UTC`:`scheduled ${clock(a.scheduled)} UTC; interval unavailable`}`} key={a.id} className={`reservation ${a.operation==='arrival'?'arrival':'departure'} ${a.id===selected?'selected':''}`} onClick={()=>{setSelected(a.id);setTab('traffic')}} style={{left:`${(left-reservationStart)/600*100}%`,width:item.verified?`${Math.max(0,(Math.min(item.end,reservationEnd)-left)/600*100)}%`:'3px',minWidth:'3px'}}>{item.verified?a.callsign:''}</button>})}</div>)}</div></div><div className="replay-control"><label htmlFor="replay">Checkpoint replay <span>{clock(replay?replay.time:state.time)}</span></label><input id="replay" type="range" min={400} max={Math.max(400,Math.floor(state.time))} value={replay?replayTime:state.time} onChange={e=>{const n=Number(e.target.value);setReplayTime(n);run('replay',async()=>setReplay(await api<State>('/replay?time='+n)))}}/><span className="replay-hint">{replay?<button onClick={()=>setReplay(null)}>Return to current state</button>:'Drag to inspect a recorded checkpoint'}</span></div></footer>
 <div className="statusbar"><span><span className={`connection-dot ${connectionError||stale?'bad':''}`}/>{connectionError||stale?'CONNECTION DEGRADED':'BACKEND CONNECTED'}<i/>REV {state.revision}<i/>SEED {state.seed}</span><span>Research simulation · Not for operational use</span></div>
 {compare?.comparisons?.length&&<Comparison result={compare} onClose={()=>setCompare(null)}/>}
 {(error||connectionError)&&<div className="error-toast" role="alert"><TriangleAlert size={18}/><span>{error||connectionError}</span><button onClick={()=>setError('')} aria-label="Dismiss error"><X size={15}/></button></div>}{toast&&<div className="toast" role="status"><Check size={16}/>{toast}</div>}
 {disruption&&<div className="drawer disruption-drawer"><div className="section-title"><h2>Change the conditions</h2><button className="icon-button" onClick={()=>setDisruption(false)} aria-label="Close disruption controls"><X size={18}/></button></div><p className="body-copy">Inject a modeled event at {clock(state.time)}. Existing plans may need new verification.</p>{[{kind:'runway_closure',title:'Close runway 28R',desc:'Remove an arrival resource.',extra:{runway:'28R'}},{kind:'weather',title:'Reduce visibility',desc:'Apply more restrictive spacing.',extra:{severity:0.8}},{kind:'arrival_surge',title:'Add an arrival surge',desc:'Introduce additional airline demand.',extra:{}},{kind:'emergency',title:'Declare an emergency',desc:'Prioritize a flight in this simulation.',extra:{aircraft_id:selected||current[0]?.id}},{kind:'gate_delay',title:'Delay gate readiness',desc:'Hold a departure at its gate.',extra:{aircraft_id:state.aircraft.find(a=>a.operation==='departure'&&a.status!=='complete')?.id,severity:1}},{kind:'communications',title:'Delay observations',desc:'Test unresolved evidence handling.',extra:{severity:0.7}}].map(d=><button className="disruption-option" key={d.kind} disabled={!!busy} onClick={()=>inject(d.kind,d.extra)}><span><strong>{d.title}</strong><small>{d.desc}</small></span><ChevronRight size={16}/></button>)}<h3>Load a seeded scenario</h3><label className="source-select">Scenario<select value={newScenario} onChange={e=>setNewScenario(e.target.value)}>{['baseline','arrival-surge','low-visibility','runway-closure','emergency','communications','exit-congestion','departure-bank','transfer'].map(s=><option value={s} key={s}>{s.replaceAll('-',' ')}</option>)}</select></label><label className="source-select">Deterministic seed<input type="number" min="0" max="100000" value={newSeed} onChange={e=>setNewSeed(e.target.value)}/></label><button className="secondary full" disabled={!!busy||!Number.isInteger(Number(newSeed))||Number(newSeed)<0||Number(newSeed)>100000} onClick={()=>{setProposal(null);setSelected(null);setDisruption(false);control('reset',{scenario:newScenario,seed:Number(newSeed)})}}>Load scenario</button></div>}
 {help&&<div className="drawer help-drawer"><div className="section-title"><h2>A shared sky, under study</h2><button className="icon-button" onClick={()=>setHelp(false)} aria-label="Close about panel"><X size={18}/></button></div><p>Uita is a reproducible research sandbox for airport orchestration. All aircraft, clearances, and disruptions belong to the simulation.</p><h3>Explore the world</h3><p>Drag to orbit, scroll to zoom, and select a flight or runway. Use the traffic table for a keyboard-accessible view. Pause and step to inspect a decision.</p><h3>Understand the evidence</h3><p>Propose a plan, inspect independent verification, then commit. Run a bounded experiment to compare observation policies under matched scenarios.</p><h3>Model boundaries</h3><ul>{state.limitations.map((x,i)=><li key={i}>{x}</li>)}</ul><details><summary>Source provenance</summary><DataView value={state.sources}/></details><p className="subtle">Scene geometry is schematic. Aircraft assets are original Blender exports. Rapier geometry supports camera clearance only; safety verification is performed by the backend.</p></div>}
 </main>
}
function FlightDetails({aircraft:a}:{aircraft:Aircraft}){return <div className="flight-detail"><div className="flight-detail-title"><span className="flight-direction large">{a.operation==='arrival'?<ArrowDownLeft size={25}/>:<ArrowUpRight size={25}/>}</span><div><h3>{a.callsign}</h3><p>{a.type} · {a.wake} wake</p></div><span className="status">{a.operation.toUpperCase()}</span></div><dl className="detail-list"><div><dt>Status</dt><dd>{a.status.replaceAll('_',' ')}</dd></div><div><dt>Runway</dt><dd>{a.runway}</dd></div><div><dt>Altitude</dt><dd>{Math.round(a.altitude).toLocaleString()} ft</dd></div><div><dt>Ground speed</dt><dd>{Math.round(a.speed)} kt</dd></div><div><dt>Heading</dt><dd>{Math.round(a.heading)}°</dd></div><div><dt>Delay</dt><dd>{Math.round(a.delay)} s</dd></div></dl></div>}

function EvaluationRows({evaluation}:{evaluation:Record<string,unknown>}){return <dl className="evaluation-rows">{[['mean_delay','Mean delay','s'],['p95_delay','Tail delay','s'],['mean_backlog','Mean backlog',''],['pass_count','Feasible cases',''],['mean_observations','Mean observations',''],['solver_seconds','Solver time','s']].map(([key,label,unit])=><div key={key}><dt>{label}</dt><dd>{evaluation[key]===undefined?'—':String(fmt(evaluation[key]))}{evaluation[key]===undefined?'':unit}{key==='pass_count'&&evaluation.cases!==undefined?` / ${evaluation.cases}`:''}</dd></div>)}</dl>}
const humanize = (value: string) =>
  value.replaceAll("_", " ").replaceAll("-", " ");
const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
const display = (value: unknown) =>
  value === undefined || value === null ? "—" : String(fmt(value));
const money = (value: unknown) =>
  typeof value === "number"
    ? value.toFixed(8).replace(/0+$/, "").replace(/\.$/, "")
    : value;
const policyAnchor = (id: string) => "policy-" + encodeURIComponent(id);
function Lineage({
  parent,
  ancestry,
}: {
  parent: unknown;
  ancestry?: unknown;
}) {
  const ancestors = Array.isArray(ancestry) ? ancestry.slice(-12) : [];
  return (
    <div className="lineage">
      {typeof parent === "string" && (
        <p>
          Parent{" "}
          <a href={"#" + policyAnchor(parent)}>
            <code>{parent}</code>
          </a>
        </p>
      )}
      {ancestors.length > 0 && (
        <details>
          <summary>
            Accepted ancestry · {ancestors.length}
            {Array.isArray(ancestry) && ancestry.length > 12
              ? " most recent"
              : ""}
          </summary>
          <ol>
            {ancestors.map((entry, i) => {
              const id =
                typeof entry === "string"
                  ? entry
                  : String(
                      record(entry).id ||
                        record(entry).policy_id ||
                        "Unspecified",
                    );
              return (
                <li key={i}>
                  <a href={"#" + policyAnchor(id)}>
                    <code>{id}</code>
                  </a>
                </li>
              );
            })}
          </ol>
        </details>
      )}
    </div>
  );
}
function PolicySummary({ policy }: { policy: Record<string, unknown> }) {
  const program = record(policy.program),
    validation = record(policy.validation),
    development = record(policy.development || policy.train);
  const selectors = Array.isArray(program.selectors) ? program.selectors : [];
  return (
    <div className="policy-summary">
      <Lineage parent={policy.parent_id} ancestry={policy.ancestry} />
      {Object.keys(program).length > 0 && (
        <p className="program-summary">
          <span>Grammar</span>{" "}
          {display(
            policy.grammar_version ||
              program.grammar_version ||
              program.version ||
              "legacy",
          )}{" "}
          · <span>Generation</span> {display(policy.generation)}
          <br />
          <span>Observes</span>{" "}
          {Array.isArray(program.observations) && program.observations.length
            ? program.observations.join(" · ")
            : selectors.length
              ? `${selectors.length} bounded selectors`
              : "No optional observations"}
          <br />
          <span>Decision budget</span> {display(program.max_observations)} reads
          · <span>Order</span> {display(program.order)}
          {program.observation_scope !== undefined && (
            <>
              <br />
              <span>Scope</span> {humanize(String(program.observation_scope))} ·{" "}
              <span>Allocation</span>{" "}
              {humanize(String(program.allocation || "—"))}
            </>
          )}
        </p>
      )}
      {Object.keys(development).length > 0 && (
        <details>
          <summary>Development evaluation</summary>
          <EvaluationRows evaluation={development} />
        </details>
      )}
      {policy.frozen_before_validation === true && (
        <p className="body-copy">
          Program frozen before independent validation.
        </p>
      )}
      {Object.keys(validation).length > 0 && (
        <>
          <h4 className="learning-heading">Independent validation</h4>
          <EvaluationRows evaluation={validation} />
        </>
      )}
      <p className="acceptance-reason">
        {String(policy.reason || "Registered reference policy.")}
      </p>
    </div>
  );
}
function ObservationSummary({ data }: { data: Record<string, unknown> }) {
  const evidence = record(data.evidence || data.feedback);
  return (
    <>
      {typeof data.tool === "string" && (
        <p className="program-summary">Tool: {humanize(data.tool)}</p>
      )}
      {typeof data.explanation === "string" && (
        <p className="body-copy">{data.explanation}</p>
      )}
      {Object.keys(evidence).length > 0 && (
        <dl className="evaluation-rows evidence-fields">
          {(
            ["source", "case_id", "freshness", "units", "uncertainty"] as const
          ).map(
            (key) =>
              evidence[key] !== undefined && (
                <div key={key}>
                  <dt>{humanize(key)}</dt>
                  <dd>{display(evidence[key])}</dd>
                </div>
              ),
          )}
          {evidence.available === false && (
            <div>
              <dt>Availability</dt>
              <dd>Unavailable</dd>
            </div>
          )}
        </dl>
      )}
    </>
  );
}
function LearningTimeline({ events }: { events: LearningEvent[] }) {
  const [expanded, setExpanded] = useState(false),
    visible = events.slice(-(expanded ? 60 : 12));
  if (!events.length)
    return (
      <p className="body-copy">
        No staged events recorded for this experiment.
      </p>
    );
  return (
    <section
      className="learning-timeline"
      aria-label="Investigation and evaluation events"
    >
      <h4 className="learning-heading">
        Investigation & evaluation <span>{events.length} events</span>
      </h4>
      <ol>
        {[...visible].reverse().map((event) => (
          <li key={event.sequence}>
            <div className="learning-event-head">
              <strong>{humanize(event.stage)}</strong>
              <code>#{event.sequence}</code>
            </div>
            <p>{event.message}</p>
            <span className="learning-event-kind">{humanize(event.kind)}</span>
            {Object.keys(record(event.data)).length > 0 && (
              <details>
                <summary>Observations & evidence</summary>
                <ObservationSummary data={event.data} />
                <DataView value={event.data} />
              </details>
            )}
          </li>
        ))}
      </ol>
      {events.length > 12 && (
        <button
          className="text-button"
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded
            ? "Show latest 12 events"
            : `Show latest ${Math.min(60, events.length)} events`}
        </button>
      )}
      {expanded && events.length > 60 && (
        <p className="body-copy">
          Older events are available in the complete experiment JSON.
        </p>
      )}
    </section>
  );
}
function RevisionHistory({
  revisions,
  frozenHash,
}: {
  revisions: unknown[];
  frozenHash?: unknown;
}) {
  return (
    <section className="revision-history" aria-label="Development revisions">
      <h4 className="learning-heading">
        Development history · {revisions.length} proposals
      </h4>
      {revisions.slice(0, 8).map((value, index) => {
        const revision = record(value),
          program = record(revision.program),
          previous = record(record(revisions[index - 1]).program);
        const feedback = record(revision.feedback),
          metrics = record(feedback.data);
        const changes = [
          "observations",
          "observation_scope",
          "allocation",
        ].filter(
          (key) =>
            JSON.stringify(previous[key]) !== JSON.stringify(program[key]),
        );
        return (
          <details
            className="candidate-record"
            key={String(revision.artifact_hash || index)}
          >
            <summary>
              {index === 0
                ? "Initial proposal"
                : `Revision ${display(revision.revision ?? index)}`}
              {revision.artifact_hash === frozenHash
                ? " · frozen selection"
                : ""}
            </summary>
            <p className="program-summary">
              {index === 0 ? "Proposed" : "Changed"}:{" "}
              {changes
                .map(
                  (key) =>
                    `${humanize(key)}: ${Array.isArray(program[key]) ? (program[key] as string[]).join(", ") : display(program[key])}`,
                )
                .join(" · ") || "No program change"}
            </p>
            <dl className="evaluation-rows">
              {[
                ["Development score", metrics.mean_score],
                ["Feasible cases", metrics.pass_count],
                ["Case count", metrics.cases],
              ].map(([label, value]) => (
                <div key={String(label)}>
                  <dt>{String(label)}</dt>
                  <dd>{display(value)}</dd>
                </div>
              ))}
            </dl>
            {Array.isArray(revision.evidence_refs) && (
              <p className="lineage">
                Evidence: {revision.evidence_refs.join(" · ")}
              </p>
            )}
            <DataView value={revision} />
          </details>
        );
      })}
    </section>
  );
}
function ExperimentSummary({ job }: { job: LearningJob }) {
  const result = record(job.result || job.results),
    frozen = record(job.frozen),
    usage = { ...record(result.provider_usage), ...record(job.provider_usage) },
    limits = record(job.limits);
  const candidates = Array.isArray(result.candidates)
    ? result.candidates.map(record)
    : [];
  const revisions = Array.isArray(result.revisions)
    ? result.revisions
    : Array.isArray(frozen.revisions)
      ? frozen.revisions
      : Array.isArray(job.revisions)
        ? job.revisions
        : [];
  const events = job.events || [],
    resources = {
      ...record([...events].reverse().find(event => event.data.resources)?.data.resources),
      ...record(frozen.resources),
      ...record(result.resources),
    },
    latestTools = [...events]
      .reverse()
      .find((event) => typeof event.data.tools_used === "number"),
    latestEvaluations = [...events]
      .reverse()
      .find((event) => typeof event.data.evaluations_used === "number" || typeof event.data.evaluation === "number"),
    latestValidation = [...events]
      .reverse()
      .find((event) => typeof event.data.validation_evaluations === "number");
  const source = String(job.source || result.source || "unknown"),
    replayed = !!(job.replayed || result.replayed) || source.includes("replay");
  const live = source.includes("crusoe") || source.includes("live");
  const timestamp = (value: unknown) =>
    typeof value === "number"
      ? value * 1000
      : typeof value === "string"
        ? Date.parse(value)
        : NaN;
  const start = timestamp(job.created_at || job.started_at),
    end = timestamp(job.finished_at || job.completed_at || job.updated_at);
  const elapsed =
    (Number.isFinite(start) && Number.isFinite(end)
      ? Math.max(0, (end - start) / 1000)
      : undefined);
  return (
    <div className="experiment-summary">
      <p className="evidence-provenance">
        {replayed
          ? "Replayed evidence · no fresh inference"
          : live
            ? "Live provider experiment"
            : source.includes("fixture")
              ? "Offline fixture · no fresh inference"
              : "Source not recorded"}
        {live && !replayed && (
          <span>
            {Number(usage.calls) > 0
              ? "Live provider requests recorded for this experiment."
              : "No provider requests recorded yet."}
          </span>
        )}
      </p>
      <Lineage
        parent={job.parent_id || result.parent_id}
        ancestry={job.ancestry || result.ancestry}
      />
      {result.selected_policy_id !== undefined && (
        <p className="acceptance-reason">
          {result.selected_policy_id
            ? `Selected: ${result.selected_policy_id}`
            : "No candidate cleared the promotion gate."}
        </p>
      )}
      <dl className="evaluation-rows learning-usage">
        {[
          ["Provider calls", usage.calls],
          ["Model requests", resources.model_requests],
          [
            "Provider tokens (in / out)",
            `${display(usage.input_tokens)} / ${display(usage.output_tokens)}`,
          ],
          [
            "Tool calls",
            resources.tools ?? usage.tool_calls ?? latestTools?.data.tools_used,
          ],
          [
            "Development evaluations",
            resources.evaluations ??
              usage.evaluations ??
              latestEvaluations?.data.evaluations_used ??
              latestEvaluations?.data.evaluation,
          ],
          [
            "Validation evaluations",
            resources.validation_evaluations ?? latestValidation?.data.validation_evaluations,
          ],
          ["Job elapsed (s)", elapsed],
          ["Verified cost (USD)", money(usage.cost_usd)],
          ["Request reserves (USD)", money(usage.reserved_usd)],
        ].map(([label, value]) => (
          <div key={String(label)}>
            <dt>{String(label)}</dt>
            <dd>{display(value)}</dd>
          </div>
        ))}
      </dl>
      {usage.cost_estimate_known === false && (
        <p className="acceptance-reason" role="status">
          Final cost is unresolved for {display(usage.ambiguous_requests)} request(s).
          Reserved spend remains charged against the cap; verified cost is incomplete.
        </p>
      )}
      {usage.unresolved_reserved_usd !== undefined && (
        <p className="acceptance-reason">Unresolved reserve: ${display(money(usage.unresolved_reserved_usd))} USD</p>
      )}
      {Object.keys(limits).length > 0 && (
        <details className="learning-limits">
          <summary>Experiment resource limits</summary>
          <dl className="evaluation-rows">
            {Object.entries(limits)
              .slice(0, 24)
              .map(([key, value]) => (
                <div key={key}>
                  <dt>{humanize(key)}</dt>
                  <dd>{display(value)}</dd>
                </div>
              ))}
          </dl>
        </details>
      )}
      {revisions.length > 0 && (
        <RevisionHistory
          revisions={revisions}
          frozenHash={frozen.artifact_hash}
        />
      )}
      {!!frozen.artifact_hash && (
        <p className="lineage">
          Frozen before validation <code>{String(frozen.artifact_hash)}</code>
        </p>
      )}
      {candidates.length > 0 && (
        <section aria-label="Candidate development and validation">
          <h4 className="learning-heading">Candidate history</h4>
          {candidates.slice(0, 8).map((candidate, i) => (
            <details
              className="candidate-record"
              key={String(candidate.id || i)}
            >
              <summary>
                {String(candidate.name || `Candidate ${i + 1}`)} ·{" "}
                {humanize(String(candidate.status || "evaluated"))}
              </summary>
              <PolicySummary policy={candidate} />
              {!!candidate.artifact_hash && (
                <p className="lineage">
                  Program artifact{" "}
                  <code>{String(candidate.artifact_hash)}</code>
                </p>
              )}
              <DataView value={candidate} />
            </details>
          ))}
        </section>
      )}
      {!!result.heldout_status && (
        <p className="body-copy">
          Held-out: {humanize(String(result.heldout_status))}
        </p>
      )}
      {result.heldout_policy_frozen_before_evaluation === true && (
        <p className="body-copy">
          {frozen.artifact_hash || candidates.some(candidate => candidate.frozen_before_validation === true)
            ? "Candidate frozen before independent validation."
            : "Selection frozen; held-out consumption is recorded above."}
        </p>
      )}
      {!!result.baseline && !!result.static && (
        <table className="learning-comparison">
          <thead>
            <tr>
              <th>Validation</th>
              <th>FCFS</th>
              <th>Static</th>
            </tr>
          </thead>
          <tbody>
            {[
              ["mean_delay", "Mean delay (s)"],
              ["p95_delay", "Tail delay (s)"],
              ["mean_backlog", "Backlog"],
              ["pass_count", "Feasible cases"],
            ].map(([key, label]) => (
              <tr key={key}>
                <td>{label}</td>
                <td>{display(record(result.baseline)[key])}</td>
                <td>{display(record(result.static)[key])}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {!!job.error && (
        <p className="acceptance-reason" role="alert">
          {String(job.error)}
        </p>
      )}
    </div>
  );
}

function DataView({value}:{value:unknown}){const [loaded,setLoaded]=useState(false);const json=loaded?JSON.stringify(value,null,2):'';const download=()=>{const blob=new Blob([JSON.stringify(value,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='uita-evidence.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};return <div className="raw-evidence"><div className="button-row"><button className="secondary" onClick={()=>setLoaded(!loaded)}>{loaded?'Hide JSON':'Load raw JSON'}</button><button className="text-button" onClick={download}><Download size={12}/> Complete JSON</button></div>{loaded&&<><pre>{json.slice(0,20000)}</pre>{json.length>20000&&<p className="body-copy">Preview limited to 20,000 characters. Download complete JSON for all cases and evidence.</p>}</>}</div>}
export default App;

"""Rolling-horizon CP-SAT scheduler. Feasibility is independently rechecked downstream."""
import time, uuid
from ortools.sat.python import cp_model
from .models import Policy
from .simulator import snapshot_hash
from .airport import RULE_VERSION

BASELINE=Policy(name='FCFS baseline',observations=[],order='fcfs',reserve_seconds=30,max_observations=8)
STATIC=Policy(name='Static observation policy',observations=['exit_occupancy','gate_ready'],order='priority',reserve_seconds=30,max_observations=8)

def plan(state,policy=BASELINE):
    started=time.perf_counter();m=cp_model.CpModel();now=state['time'];aa=state['aircraft']
    fixed=[a for a in aa if a['trajectory'][0]['t']<=now]
    pending=[a for a in aa if a not in fixed]
    if policy.order=='wake_group':pending.sort(key=lambda a:(not a['emergency'],int(a['requested']//300),a['wake'],a['requested']))
    else:pending.sort(key=lambda a:(not a['emergency'],a['requested']))
    ordered=sorted(fixed,key=lambda a:a['scheduled'])+pending
    observations=[];budget=policy.max_observations;observed={}
    # Program order controls observation allocation; the planner sees cached tool
    # outputs only. Every optional operation consumes one budget unit per aircraft.
    targets=ordered
    if policy.grammar_version=='observations-2':
        if policy.observation_scope=='pending':targets=[a for a in ordered if a in pending]
        elif policy.observation_scope=='pending-first':targets=[a for a in ordered if a in pending]+[a for a in ordered if a in fixed]
    pairs=((tool,a) for tool in policy.observations for a in targets)
    if policy.grammar_version=='observations-2' and policy.allocation=='aircraft-major':
        pairs=((tool,a) for a in targets for tool in policy.observations)
    for tool,a in pairs:
        if budget<=0:break
        if tool=='exit_occupancy' and a['operation']!='arrival':continue
        if tool=='gate_ready' and a['operation']!='departure':continue
        value=state['weather']['visibility'] if tool=='weather' else a[tool]
        observed[(a['id'],tool)]=value;budget-=1
        observations.append({'aircraft_id':a['id'],'tool':tool,'value':value,'cost':1})
    def observe(a,key,fallback):
        return observed.get((a['id'],key),fallback)
    times={};runways={};tails={};leads={}
    for a in ordered:
        active=a in fixed
        gate=observe(a,'gate_ready',a['requested']+300) if a['operation']=='departure' else a['requested']
        earliest=int(max(a['requested'],gate,max(now,state.get('admission_blocked_until',now))+(360 if a['operation']=='arrival' else 120)))
        t=m.NewIntVar(0,20000,a['id']);times[a['id']]=t
        if active:m.Add(t==int(a['scheduled']))
        else:m.Add(t>=earliest)
        allowed=['28L','28R'] if a['operation']=='arrival' else ['01L','01R']
        available=[r for r in allowed if r not in state['closed_runways']]
        runways[a['id']]=a['runway'] if active else (a['runway'] if a['runway'] in available else available[0] if available else allowed[0])
        tails[a['id']]=observe(a,'exit_occupancy',140)+90 if a['operation']=='arrival' else 160
        if state['weather']['visibility']<3:tails[a['id']]+=40
        leads[a['id']]=80 if a['operation']=='arrival' else 120
    for prev,a in zip(ordered,ordered[1:]):
        if prev in fixed and a in fixed:continue
        spacing=max(120 if prev['wake']=='heavy' else 90,tails[prev['id']]+leads[a['id']]+policy.reserve_seconds)
        m.Add(times[a['id']]>=times[prev['id']]+int(spacing))
    m.Minimize(sum(times.values()))
    solver=cp_model.CpSolver();solver.parameters.max_time_in_seconds=2;solver.parameters.num_search_workers=1;solver.parameters.random_seed=state['seed']
    status=solver.Solve(m)
    feasible=status in (cp_model.OPTIMAL,cp_model.FEASIBLE)
    slots=[{'aircraft_id':a['id'],'runway':runways[a['id']],'time':solver.Value(times[a['id']]) if feasible else a['scheduled']} for a in aa]
    return {'id':str(uuid.uuid4()),'revision':state['revision'],'rule_version':RULE_VERSION,'snapshot_hash':snapshot_hash(state),'snapshot_time':now,'valid_until':now+30,'status':'proposed' if feasible else 'infeasible','slots':slots,'policy':policy.model_dump(),'rationale':f'{policy.name}: {policy.order} ordering, {len(observations)} bounded observations, {policy.reserve_seconds}s reservation margin. All runways share a conflict resource.','solver':{'status':solver.StatusName(status),'optimal':status==cp_model.OPTIMAL,'optimal_scope':'fixed ordering only','wall_seconds':round(time.perf_counter()-started,5),'objective':solver.ObjectiveValue() if feasible else None},'observations':observations,'observation_budget':policy.max_observations,'verification':None}

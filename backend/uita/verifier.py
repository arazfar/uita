"""Independent analytical verifier. Does not import the planner or use its feasibility flag.

For each overlapping linear trajectory segment, clip the time interval by altitude
applicability, then minimize squared lateral distance analytically on that interval.
This checks critical instants between ticks, not just sampled frames.
"""
import math
from .airport import RULE_VERSION, RUNWAYS
from .simulator import trajectory, snapshot_hash

def _clip(lo,hi,v0,slope,minimum=None,maximum=None):
    if abs(slope)<1e-12:
        return (lo,hi) if (minimum is None or v0>=minimum) and (maximum is None or v0<=maximum) else None
    for bound,lower in ((minimum,True),(maximum,False)):
        if bound is None:continue
        cross=(bound-v0)/slope
        if (slope>0)==lower:lo=max(lo,cross)
        else:hi=min(hi,cross)
    return (lo,hi) if lo<=hi else None

def segment_conflict(a,b,c,d):
    start=max(a['t'],c['t']);end=min(b['t'],d['t'])
    if end<=start:return None
    va={k:(b[k]-a[k])/(b['t']-a['t']) for k in ('x','y','altitude')}
    vb={k:(d[k]-c[k])/(d['t']-c['t']) for k in ('x','y','altitude')}
    pa={k:a[k]+va[k]*(start-a['t']) for k in va};pb={k:c[k]+vb[k]*(start-c['t']) for k in vb}
    bounds=(0,end-start)
    for p,v in ((pa['altitude'],va['altitude']),(pb['altitude'],vb['altitude'])):
        bounds=_clip(*bounds,p,v,minimum=1000)
        if bounds is None:return None
    dz=pa['altitude']-pb['altitude'];vz=va['altitude']-vb['altitude']
    bounds=_clip(*bounds,dz,vz,minimum=-999.999,maximum=999.999)
    if bounds is None:return None
    dx=pa['x']-pb['x'];dy=pa['y']-pb['y'];vx=va['x']-vb['x'];vy=va['y']-vb['y']
    denom=vx*vx+vy*vy
    tau=max(bounds[0],min(bounds[1],-(dx*vx+dy*vy)/denom)) if denom>1e-12 else bounds[0]
    dist=math.hypot(dx+vx*tau,dy+vy*tau)
    if dist<3-1e-7:return {'time':round(start+tau,3),'lateral_nm':round(dist,4),'vertical_ft':round(abs(dz+vz*tau),2),'interval':[round(start+bounds[0],3),round(start+bounds[1],3)]}
    return None

def verify(state,plan):
    checks=[]
    def add(id,status,summary,evidence):checks.append({'id':id,'status':status,'summary':summary,'evidence':evidence})
    bound_state={**state,'time':plan.get('snapshot_time',state['time'])}
    stale=plan['revision']!=state['revision'] or plan['rule_version']!=RULE_VERSION or state['rule_version']!=RULE_VERSION or state['time']>plan['valid_until'] or plan['snapshot_hash']!=snapshot_hash(bound_state)
    add('binding','fail' if stale else 'pass','Revision, rule pack and validity interval binding',{'plan_revision':plan['revision'],'current_revision':state['revision'],'rule_version':RULE_VERSION,'valid_until':plan['valid_until'],'time':state['time']})
    age=state.get('communications_delay')
    if age is None or not isinstance(state.get('weather'),dict) or state['weather'].get('visibility') is None:
        add('mandatory-observations','unresolved','Required freshness or weather observations unavailable',{})
        return _result(checks)
    add('freshness','unresolved' if age>15 else 'pass','Observations must be no older than 15 seconds',{'observation_age_seconds':age,'maximum':15})
    aircraft={a['id']:a for a in state['aircraft']};slots=plan['slots']
    ids=[s['aircraft_id'] for s in slots]
    valid_ids=set(ids)==set(aircraft) and len(ids)==len(set(ids))
    add('coverage','pass' if valid_ids else 'fail','Every aircraft has exactly one reservation',{'expected':len(aircraft),'actual':len(ids)})
    if not valid_ids:return _result(checks)
    invalid=[];commitment=[];readiness=[];intervals=[];paths={};wake=[];taxi=[]
    known={r['id'] for r in RUNWAYS}
    for s in slots:
        a=aircraft[s['aircraft_id']];t=s['time'];r=s['runway']
        if not math.isfinite(t) or r not in known:
            invalid.append(s);continue
        allowed=['28L','28R'] if a['operation']=='arrival' else ['01L','01R']
        if not a.get('diverted') and (r not in allowed or (r in state['closed_runways'] and t+180>=state['time'])):invalid.append({'aircraft_id':a['id'],'runway':r,'reason':'closure or route incompatibility'})
        active=a['trajectory'][0]['t']<=state['time']
        if active and (abs(t-a['scheduled'])>.001 or r!=a['runway']):commitment.append(a['id'])
        if not active and t<max(a['requested'],a['gate_ready'] if a['operation']=='departure' else state['time']+360,state.get('admission_blocked_until',0)+(120 if a['operation']=='departure' else 360)):readiness.append(a['id'])
        lead=80 if a['operation']=='arrival' else 25
        tail=a['exit_occupancy'] if a['operation']=='arrival' else 160
        if state['weather']['visibility']<3:tail+=40
        if not a.get('diverted'):intervals.append((t-lead,t+tail,a['id'],a['wake'],t))
        paths[a['id']]=a['trajectory'] if active else trajectory(a,t,r)
        if not a.get('diverted'):taxi.append((t+a['exit_occupancy'],t+a['exit_occupancy']+90,a['id']) if a['operation']=='arrival' else (t-120,t-25,a['id']))
    add('route-closure','fail' if invalid else 'pass','West Plan routing and runway availability',invalid)
    add('commitments','fail' if commitment else 'pass','Preserve admitted aircraft trajectories',commitment)
    add('readiness','fail' if readiness else 'pass','Admission, demand time and departure gate readiness',readiness)
    overlaps=[];ordered=sorted(intervals)
    for i,a in enumerate(ordered):
        for b in ordered[i+1:]:
            if max(a[0],b[0],state['time'])<min(a[1],b[1])-1e-6:overlaps.append({'aircraft':[a[2],b[2]],'interval':[max(a[0],b[0]),min(a[1],b[1])]})
        if i+1<len(ordered):
            b=ordered[i+1];required=120 if a[3]=='heavy' else 90
            if b[4]>=state['time'] and b[4]-a[4]<required:wake.append({'aircraft':[a[2],b[2]],'actual_seconds':b[4]-a[4],'required_seconds':required})
    add('runway-resource','fail' if overlaps else 'pass','All intersecting and closely spaced runways share one conflict resource',{'overlaps':overlaps,'intervals':[{'aircraft_id':x[2],'start':x[0],'end':x[1]} for x in ordered]})
    add('wake','fail' if wake else 'pass','Research wake floor: 120s following heavy, otherwise 90s',wake)
    taxi_conflicts=[]
    for i,a in enumerate(taxi):
        for b in taxi[i+1:]:
            if max(a[0],b[0],state['time'])<min(a[1],b[1])-1e-6:taxi_conflicts.append({'aircraft':[a[2],b[2]],'interval':[max(a[0],b[0]),min(a[1],b[1])]})
    add('surface-resource','fail' if taxi_conflicts else 'pass','One exclusive synthetic taxi trunk connects runway exits and departure entries',{'conflicts':taxi_conflicts,'reservations':[{'start':x[0],'end':x[1],'aircraft_id':x[2]} for x in taxi]})
    performance=[]
    for aid,path in paths.items():
        for a,b in zip(path,path[1:]):
            dt=b['t']-a['t']
            if dt<=0:performance.append({'aircraft_id':aid,'reason':'non-increasing trajectory time'});continue
            speed=math.hypot(b['x']-a['x'],b['y']-a['y'])/dt*3600;vertical=abs(b['altitude']-a['altitude'])/dt*60
            # Broad research category envelope includes runway acceleration.
            if speed>350 or vertical>4000 or min(a['altitude'],b['altitude'])<0:performance.append({'aircraft_id':aid,'knots':round(speed,1),'vertical_fpm':round(vertical,1)})
    add('performance','fail' if performance else 'pass','Piecewise motion stays inside broad 350kt / 4000ft/min research envelope',performance)
    conflicts=[];pairs=0
    for i,aid in enumerate(paths):
        for bid in list(paths)[i+1:]:
            for a,b in zip(paths[aid],paths[aid][1:]):
                for c,d in zip(paths[bid],paths[bid][1:]):
                    if min(b['t'],d['t'])<state['time']:continue
                    def clip_start(p,q):
                        if p['t']>=state['time']:return p
                        f=(state['time']-p['t'])/(q['t']-p['t'])
                        return {'t':state['time'],**{k:p[k]+f*(q[k]-p[k]) for k in ('x','y','altitude')}}
                    pairs+=1;conflict=segment_conflict(clip_start(a,b),b,clip_start(c,d),d)
                    if conflict:conflicts.append({'aircraft':[aid,bid],**conflict})
    add('continuous-separation','fail' if conflicts else 'pass','Analytical closest approach across every overlapping linear segment',{'checked_segment_pairs':pairs,'conflicts':conflicts,'lateral_minimum_nm':3,'vertical_minimum_ft':1000,'domain':'both aircraft at or above 1000ft MSL'})
    emergency=[a['id'] for a in aircraft.values() if a['emergency'] and a['trajectory'][0]['t']>state['time']]
    pending=sorted([s for s in slots if aircraft[s['aircraft_id']]['trajectory'][0]['t']>state['time']],key=lambda s:s['time'])
    wrong=bool(emergency and pending and pending[0]['aircraft_id'] not in emergency)
    add('priority','fail' if wrong else 'pass','Declared emergency receives first uncommitted reservation',{'emergency_aircraft':emergency})
    return _result(checks)

def _result(checks):
    status='fail' if any(c['status']=='fail' for c in checks) else 'unresolved' if any(c['status']=='unresolved' for c in checks) else 'pass'
    return {'status':status,'checks':checks,'checked_at':'logical snapshot','scope':RULE_VERSION,'failures':sum(c['status']=='fail' for c in checks),'unresolved':sum(c['status']=='unresolved' for c in checks)}

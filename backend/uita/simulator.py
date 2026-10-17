import copy, hashlib, json, math, random
from .airport import RUNWAYS, RULE_VERSION

SCENARIOS = {'baseline','arrival-surge','low-visibility','runway-closure','emergency','communications','exit-congestion','departure-bank','transfer'}
from .objectives import OBJECTIVE_CONFIG as OBJECTIVES, enrich_metrics

def new_state(seed=42,scenario='baseline'):
    if scenario not in SCENARIOS: raise ValueError('Unknown scenario')
    rng=random.Random(seed)
    aircraft=[]
    for i in range(16 if scenario=='arrival-surge' else 12):
        op='departure' if (i%3==2 if scenario!='departure-bank' else i%3!=0) else 'arrival'
        ready=600+i*rng.randint(65,95)
        aircraft.append({'id':f'A{i+1:02}','callsign':f'{["UAL","SWA","ASA","DAL","ANA","SKW"][i%6]}{rng.randint(100,999)}','type':'B77W' if i%5==0 else 'A320','wake':'heavy' if i%5==0 else 'medium','operation':op,'requested':ready,'scheduled':600+i*340,'runway':('01R' if i%2 else '01L') if op=='departure' else ('28R' if i%2 else '28L'),'gate_ready':ready+rng.randint(0,300 if scenario=='departure-bank' else 120),'exit_occupancy':rng.randint(90,140) if scenario=='exit-congestion' else rng.randint(45,105),'emergency':scenario=='emergency' and i==5,'group':i%3,'route_variant':1 if scenario=='transfer' else 0,'trajectory':[]})
    state={'session_id':f'sfo-{seed}','revision':1,'time':400.0,'running':False,'speed':1.0,'seed':seed,'scenario':scenario,'rule_version':RULE_VERSION,'aircraft':aircraft,'weather':{'visibility':10.0,'wind':280,'ceiling':5000},'closed_runways':[],'communications_delay':0,'disruptions':[],'events':[{'time':400,'type':'checkpoint','message':f'Seed {seed} loaded · West Plan · conservative shared runway resource'}],'active_policy':'baseline','checkpoints':[]}
    if scenario=='low-visibility':state['weather']['visibility']=1.0
    if scenario=='runway-closure':state['closed_runways']=['28R']
    if scenario=='communications':state['communications_delay']=45
    if scenario=='transfer':
        for a in aircraft:
            a['requested']+=rng.randint(-40,80)
            if a['operation']=='arrival':a['runway']='28R' if a['runway']=='28L' else '28L'
    for a in aircraft:a['trajectory']=trajectory(a,a['scheduled'],a['runway'])
    if scenario=='runway-closure':inject(state,{'kind':'runway_closure','runway':'28R','severity':1})
    return state

def trajectory(a,slot,rwy):
    r=next(r for r in RUNWAYS if r['id']==rwy); x,y=r['start']; ex,ey=r['end'];route_shift=a.get('route_variant',0)*1.0
    if a['operation']=='arrival':
        return [{'t':slot-360,'x':x+14,'y':y-7.13-route_shift,'altitude':5000},{'t':slot-90,'x':x+3.5,'y':y-1.7825,'altitude':1400},{'t':slot,'x':x,'y':y,'altitude':13},{'t':slot+a['exit_occupancy'],'x':ex+.35,'y':ey-.1,'altitude':13},{'t':slot+a['exit_occupancy']+90,'x':-1.7-(int(a['id'][1:])%4)*.16,'y':-.60,'altitude':13}]
    return [{'t':slot-120,'x':-1.7,'y':-.60,'altitude':13},{'t':slot-25,'x':x,'y':y,'altitude':13},{'t':slot+35,'x':ex,'y':ey,'altitude':200},{'t':slot+160,'x':ex+2,'y':ey+6,'altitude':3500},{'t':slot+300,'x':ex+4,'y':ey+12,'altitude':7000}]

def sample(a,t):
    path=a['trajectory'];out=copy.deepcopy(a)
    before=t<path[0]['t'];after=t>=path[-1]['t']
    p=path[0] if before else path[-1]
    heading=297;speed=0
    for p0,p1 in zip(path,path[1:]):
        if p0['t']<=t<p1['t']:
            f=(t-p0['t'])/(p1['t']-p0['t']);p={k:p0[k]+f*(p1[k]-p0[k]) for k in ('x','y','altitude')}
            heading=(math.degrees(math.atan2(p1['x']-p0['x'],p1['y']-p0['y']))+360)%360
            speed=math.hypot(p1['x']-p0['x'],p1['y']-p0['y'])/(p1['t']-p0['t'])*3600;break
    out.update(p);out['heading']=heading
    out['status']='pending' if before else 'complete' if after else ('approach' if t<a['scheduled'] else 'taxi') if a['operation']=='arrival' else ('taxi' if t<a['scheduled'] else 'departure')
    if a.get('diverted'):out['status']='diverted' if after else 'diverting'
    if a.get('admission_hold'):out['status']='pending';before=True
    out['speed']=round(speed,1);out['in_model']=not before and not after
    out['delay']=max(0,a['scheduled']-a['requested'])
    return out

def snapshot_hash(state):
    keys={k:state[k] for k in ('seed','revision','time','aircraft','weather','closed_runways','communications_delay','rule_version')}
    keys['admission_blocked_until']=state.get('admission_blocked_until',0)
    return hashlib.sha256(json.dumps(keys,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def advance(state,seconds):
    state['time']=round(state['time']+seconds,3)
    return state

def inject(state,d):
    kind=d['kind'];now=state['time'];severity=d.get('severity',1)
    if kind=='runway_closure':
        if d['runway'] not in [r['id'] for r in RUNWAYS]:raise ValueError('Unknown runway')
        if d['runway'] not in state['closed_runways']:state['closed_runways'].append(d['runway'])
        diversions=[]
        for a in state['aircraft']:
            if a['runway']!=d['runway']:continue
            current=sample(a,now)
            if current['status']=='pending':
                a['admission_hold']=True
                # Shift only the unadmitted future. A verified plan clears the hold.
                a['scheduled']=max(a['scheduled'],now+86400)
                a['trajectory']=trajectory(a,a['scheduled'],a['runway'])
            elif a['operation']=='arrival' and current['altitude']>100 and current['status'] not in ('complete','diverted','diverting'):
                past=[p for p in a['trajectory'] if p['t']<now]
                point={'t':now,'x':current['x'],'y':current['y'],'altitude':current['altitude']}
                a['trajectory']=past+[point,{'t':now+90,'x':point['x']+.5,'y':point['y']+2,'altitude':point['altitude']+1800},{'t':now+240,'x':point['x']+3,'y':point['y']+10,'altitude':point['altitude']+4800}]
                a['diverted']=True;a['contingency']='Synthetic climb-and-exit diversion; not a published procedure';diversions.append(a['callsign'])
        if diversions:state['admission_blocked_until']=max(state.get('admission_blocked_until',0),now+240)
        message=f"Runway {d['runway']} closed. "+('Synthetic diversion initiated for '+', '.join(diversions)+'. ' if diversions else '')+'Affected unadmitted demand held for independent replanning.'
    elif kind=='weather':state['weather']['visibility']=max(.3,3-severity);message='Visibility reduced; conservative occupancy buffer increased.'
    elif kind=='communications':state['communications_delay']=45*severity;message='Observation age increased; freshness gate blocks commitment.'
    elif kind in ('emergency','gate_delay'):
        candidates=[a for a in state['aircraft'] if kind!='gate_delay' or a['operation']=='departure']
        a=next((a for a in candidates if a['id']==d.get('aircraft_id')),None) or next((a for a in candidates if a['scheduled']>now+360),candidates[-1])
        if kind=='emergency':a['emergency']=True;message=f"{a['callsign']} declared priority emergency."
        else:a['gate_ready']+=300*severity;message=f"{a['callsign']} readiness delayed {300*severity:.0f}s."
    else:
        rng=random.Random(state['seed']+len(state['disruptions']))
        for _ in range(3):
            i=len(state['aircraft'])+1; a={'id':f'A{i:02}','callsign':f'UAL{rng.randint(1000,1999)}','type':'A320','wake':'medium','operation':'arrival','requested':now+400,'scheduled':max(a['scheduled'] for a in state['aircraft'])+210,'runway':'28L','gate_ready':now+400,'exit_occupancy':65,'emergency':False,'group':i%3}
            a['trajectory']=trajectory(a,a['scheduled'],a['runway']);state['aircraft'].append(a)
        message='Three new airline arrival requests entered the admission queue.'
    state['revision']+=1;state['disruptions'].append({**d,'time':now});state['events'].append({'time':now,'type':kind,'message':message})
    return state

def metrics(state,slots=None,horizon=None):
    time=state['time'] if horizon is None else horizon
    aa=state['aircraft'];schedule={s['aircraft_id']:s['time'] for s in slots} if slots is not None else {a['id']:a['scheduled'] for a in aa}
    delays=[max(0,schedule.get(a['id'],time+600)-a['requested']) for a in aa]
    complete=[a for a in aa if not a.get('diverted') and not a.get('admission_hold') and schedule.get(a['id'],time+600)+(a['exit_occupancy']+90 if a['operation']=='arrival' else 300)<=time]
    backlog=len(aa)-len(complete)
    groups=[]
    for group in sorted(set(a['group'] for a in aa)):
        members=[(a,d) for a,d in zip(aa,delays) if a['group']==group]
        groups.append({'group':group,'total':len(members),'completed':sum(a in complete for a,_ in members),'mean_delay':round(sum(d for _,d in members)/len(members),1)})
    hour=(16+time/3600)%24;night=5<=hour<13;noise=sum(1.4 if a['wake']=='heavy' else 1 for a in complete)
    base={'completed':len(complete),'total':len(aa),'arrivals_completed':sum(a['operation']=='arrival' for a in complete),'departures_completed':sum(a['operation']=='departure' for a in complete),'diverted':sum(bool(a.get('diverted')) for a in aa),'backlog':backlog,'mean_delay':round(sum(delays)/len(delays),1),'p95_delay':round(sorted(delays)[min(len(delays)-1,int(.95*len(delays)))],1),'max_delay':round(max(delays),1),'conflicts':None,'throughput':round(len(complete)/max((time-400)/3600,.01),1),'airborne_hold_seconds':round(sum(d for a,d in zip(aa,delays) if a['operation']=='arrival'),1),'taxi_hold_seconds':round(sum(d for a,d in zip(aa,delays) if a['operation']=='departure'),1),'fuel_proxy_kg':round(sum(delays)*.12,1),'emissions_proxy_kg':round(sum(delays)*.12*3.16,1),'relative_noise_exposure':round(noise,2),'relative_night_exposure':round(noise*2 if night else 0,2),'group_service':groups,'group_mean_delay_gap':round(max(g['mean_delay'] for g in groups)-min(g['mean_delay'] for g in groups),1),'starved_over_1800_seconds':sum(d>1800 for d in delays),'plan_changes':state.get('plan_changes',0),'recovery_seconds':state.get('last_recovery_seconds'),'unfinished_penalty':backlog*600,'score':round(sum(delays)+backlog*600,1)}
    return enrich_metrics(state,schedule,time,base)

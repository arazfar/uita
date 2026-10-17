from copy import deepcopy
from uita.simulator import new_state,inject,sample,advance,metrics,snapshot_hash
from uita.planner import plan,STATIC
from uita.verifier import verify

def test_closed_runway_airborne_arrival_continues_diversion_without_jump():
    state=new_state(42);state['time']=580
    before=sample(state['aircraft'][0],580);past=deepcopy([p for p in state['aircraft'][0]['trajectory'] if p['t']<580])
    inject(state,{'kind':'runway_closure','runway':'28L','severity':1})
    a=state['aircraft'][0];after=sample(a,580)
    assert a['diverted'] and a['trajectory'][:len(past)]==past
    for key in ('x','y','altitude'):assert abs(before[key]-after[key])<1e-9
    advance(state,60);moving=sample(a,state['time']);assert moving['altitude']>before['altitude']
    assert moving['status']=='diverting'
    advance(state,240);assert sample(a,state['time'])['status']=='diverted'
    m=metrics(state);assert m['diverted']==1 and m['arrivals_completed']==0

def test_closed_unadmitted_traffic_held_until_replanned():
    state=new_state(42);inject(state,{'kind':'runway_closure','runway':'28R'})
    affected=[a for a in state['aircraft'] if a['runway']=='28R']
    assert affected and all(a['admission_hold'] for a in affected)
    assert all(sample(a,5000)['status']=='pending' for a in affected)
    proposal=plan(state,STATIC);verdict=verify(state,proposal)
    assert verdict['status']=='pass'
    assert all(s['runway']!='28R' for s in proposal['slots'])

def test_diversion_horizon_binds_plan_admission():
    state=new_state(42);state['time']=580;inject(state,{'kind':'runway_closure','runway':'28L'})
    p=plan(state,STATIC)
    by_id={a['id']:a for a in state['aircraft']}
    for s in p['slots']:
        a=by_id[s['aircraft_id']]
        if a['trajectory'][0]['t']>state['time']:
            assert s['time']>=state['admission_blocked_until']+(360 if a['operation']=='arrival' else 120)

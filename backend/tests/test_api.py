import os
os.environ.setdefault('DATABASE_URL','sqlite:///:memory:')
from fastapi.testclient import TestClient
from uita.app import create_app
from uita.airport import RUNWAYS

def client(tmp_path):return TestClient(create_app('sqlite:///'+str(tmp_path/'api.sqlite')))
def proposal(c):
    response=c.post('/api/proposals',json={'policy_id':'static'});assert response.status_code==200
    return response.json()

def test_propose_verify_commit_idempotent_and_reload(tmp_path):
    with client(tmp_path) as c:
        p=proposal(c);v=c.post('/api/proposals/'+p['id']+'/verify').json();assert v['status']=='pass'
        payload={'idempotency_key':'same-command-once'}
        a=c.post('/api/proposals/'+p['id']+'/commit',json=payload);b=c.post('/api/proposals/'+p['id']+'/commit',json=payload)
        assert a.status_code==b.status_code==200
        assert a.json()['revision']==b.json()['revision']==2
        assert len([e for e in b.json()['events'] if e['type']=='commit'])==1
    with client(tmp_path) as c:
        assert c.get('/api/state').json()['revision']==2
        assert c.get('/api/export').json()['checkpoints']

def test_stale_disrupted_plan_cannot_commit(tmp_path):
    with client(tmp_path) as c:
        p=proposal(c)
        assert c.post('/api/disruptions',json={'kind':'runway_closure','runway':'28R','revision':1}).status_code==200
        r=c.post('/api/proposals/'+p['id']+'/commit',json={'idempotency_key':'stale-no-commit'})
        assert r.status_code==409
        assert c.get('/api/state').json()['revision']==2

def test_unresolved_cannot_commit(tmp_path):
    with client(tmp_path) as c:
        c.post('/api/disruptions',json={'kind':'communications'})
        p=proposal(c);v=c.post('/api/proposals/'+p['id']+'/verify').json()
        assert v['status']=='unresolved'
        assert c.post('/api/proposals/'+p['id']+'/commit',json={'idempotency_key':'unresolved-plan'}).status_code==409

def test_replay_uses_pre_disruption_checkpoint(tmp_path):
    with client(tmp_path) as c:
        c.post('/api/control',json={'action':'step','seconds':100})
        c.post('/api/disruptions',json={'kind':'runway_closure','runway':'28R'})
        replay=c.get('/api/replay?time=450').json()
        assert replay['time']==450 and replay['closed_runways']==[]
        assert c.get('/api/state').json()['closed_runways']==['28R']

def test_cross_origin_write_rejected_and_input_limits(tmp_path):
    with client(tmp_path) as c:
        assert c.post('/api/control',json={'action':'reset'},headers={'origin':'https://untrusted.example'}).status_code==403
        assert c.post('/api/control',json={'action':'step','seconds':10000}).status_code==422
        assert c.post('/api/learning/train',json={'generations':999}).status_code==422

def test_idempotency_key_cannot_bind_different_proposal(tmp_path):
    with client(tmp_path) as c:
        p=proposal(c);c.post('/api/proposals/'+p['id']+'/commit',json={'idempotency_key':'unique-identity'})
        q=proposal(c)
        assert c.post('/api/proposals/'+q['id']+'/commit',json={'idempotency_key':'unique-identity'}).status_code==409

def test_actual_intersecting_pairs_and_lengths():
    def cross(u,v):return u[0]*v[1]-u[1]*v[0]
    def sub(u,v):return (u[0]-v[0],u[1]-v[1])
    for a in RUNWAYS[:2]:
        for b in RUNWAYS[2:]:
            r=sub(a['end'],a['start']);s=sub(b['end'],b['start']);q=sub(b['start'],a['start']);den=cross(r,s)
            assert 0<cross(q,s)/den<1 and 0<cross(q,r)/den<1
    import math
    for a in RUNWAYS:
        feet=math.dist(a['start'],a['end'])*6076.11549
        assert abs(feet-a['length_ft'])<15

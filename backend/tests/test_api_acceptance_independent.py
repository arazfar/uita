"""Independent HTTP/persistence/real subprocess acceptance checks."""
import copy
import importlib
import time
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api(tmp_path,monkeypatch):
    monkeypatch.setenv('DATABASE_URL',f'sqlite:///{tmp_path}/module-default.db')
    module=importlib.import_module('uita.app')
    url=f'sqlite:///{tmp_path}/api.db'
    application=module.create_app(url)
    with TestClient(application) as client:
        yield client,application,url,module


def propose(client):
    response=client.post('/api/proposals',json={'policy_id':'static','source':'fixture'})
    assert response.status_code==200,response.text
    return response.json()


def test_commit_is_atomic_idempotent_and_preserves_executed_paths(api):
    client,application,_,_=api
    before=copy.deepcopy(application.state.store.get('state'))
    p=propose(client)
    command={'idempotency_key':'independent-duplicate-commit','revision':before['revision']}
    first=client.post(f"/api/proposals/{p['id']}/commit",json=command)
    assert first.status_code==200,first.text
    second=client.post(f"/api/proposals/{p['id']}/commit",json=command)
    assert second.status_code==200,second.text
    after=application.state.store.get('state')
    assert after['revision']==before['revision']+1
    assert first.json()['revision']==second.json()['revision']
    assert sum(event['type']=='commit' for event in after['events'])==1
    for aircraft in before['aircraft']:
        if aircraft['trajectory'][0]['t']<=before['time']:
            actual=next(a for a in after['aircraft'] if a['id']==aircraft['id'])
            assert actual['trajectory']==aircraft['trajectory']
    different=client.post(f"/api/proposals/{p['id']}/commit",json={'idempotency_key':'another-independent-key'})
    assert different.status_code==409


def test_expired_and_disrupted_proposals_cannot_commit(api):
    client,application,_,_=api
    p=propose(client)
    assert client.post('/api/control',json={'action':'step','seconds':31}).status_code==200
    expired=client.post(f"/api/proposals/{p['id']}/commit",json={'idempotency_key':'expired-commit-attempt'})
    assert expired.status_code==409
    p=propose(client)
    assert client.post('/api/disruptions',json={'kind':'weather','severity':1}).status_code==200
    stale=client.post(f"/api/proposals/{p['id']}/commit",json={'idempotency_key':'stale-commit-attempt'})
    assert stale.status_code==409


def test_checkpoint_replay_does_not_mutate_live_state(api):
    client,application,_,_=api
    assert client.post('/api/control',json={'action':'step','seconds':120}).status_code==200
    current=copy.deepcopy(application.state.store.get('state'))
    replay=client.get('/api/replay',params={'time':450})
    assert replay.status_code==200
    assert replay.json()['time']==450
    assert replay.json()['replay'] is True
    assert application.state.store.get('state')==current


def test_real_worker_completes_and_registry_survives_app_reopen(api):
    client,application,url,module=api
    response=client.post('/api/learning/train',json={'generations':1,'source':'fixture'})
    assert response.status_code==200,response.text
    job_id=response.json()['id']
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        job=client.get(f'/api/learning/jobs/{job_id}').json()
        if job['status'] not in ('running','queued'):break
        time.sleep(.05)
    assert job['status']=='complete',job
    assert job['result']['static']['execution_mode']=='verified-commit-advance-replan'
    assert job['result']['provider_usage']['calls']==0
    candidate=job['result']['candidates'][0]
    stored=client.get(f"/api/learning/policies/{candidate['id']}")
    assert stored.status_code==200
    reopened=module.create_app(url)
    with TestClient(reopened) as after:
        assert after.get(f'/api/learning/jobs/{job_id}').json()['status']=='complete'
        assert after.get(f"/api/learning/policies/{candidate['id']}").json()['artifact_hash']==candidate['artifact_hash']


def test_readonly_store_does_not_interrupt_live_worker(api):
    from uita.storage import Store
    client,application,url,_=api
    response=client.post('/api/learning/train',json={'generations':3,'source':'fixture'})
    assert response.status_code==200,response.text
    job_id=response.json()['id']
    reader=Store(url)
    assert reader.get('job-'+job_id)['status'] in ('queued','running','complete')
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        job=client.get(f'/api/learning/jobs/{job_id}').json()
        if job['status'] not in ('running','queued'):break
        time.sleep(.05)
    assert job['status']=='complete',job


def test_abrupt_api_and_worker_process_loss_recovers_explicitly(tmp_path,monkeypatch):
    import json
    import os
    from pathlib import Path
    import signal
    import subprocess
    import sys
    url=f'sqlite:///{tmp_path}/crashed-api.db'
    ready=tmp_path/'started.json'
    script=tmp_path/'crash_driver.py'
    script.write_text('''import json, sys, time
from pathlib import Path
from fastapi.testclient import TestClient
from uita.app import create_app
if __name__ == '__main__':
    app=create_app(sys.argv[1])
    with TestClient(app) as client:
        response=client.post('/api/learning/train',json={'generations':8,'source':'fixture'})
        Path(sys.argv[2]).write_text(json.dumps(response.json()))
        time.sleep(60)
''')
    env={**os.environ,'DATABASE_URL':f'sqlite:///{tmp_path}/module-crash.db'}
    process=subprocess.Popen([sys.executable,str(script),url,str(ready)],env=env,start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        deadline=time.monotonic()+15
        while not ready.exists() and process.poll() is None and time.monotonic()<deadline:time.sleep(.02)
        assert ready.exists(),process.stderr.read().decode() if process.poll() is not None else 'worker startup timed out'
        job=json.loads(ready.read_text())
        assert job['status'] in ('queued','running'),job
        os.killpg(process.pid,signal.SIGKILL)
        process.wait(timeout=10)
        from uita.storage import Store
        reader=Store(url)
        assert reader.get('job-'+job['id'])['status'] in ('queued','running')
        recovered=Store(url,recover=True)
        record=recovered.get('job-'+job['id'])
        assert record['status']=='interrupted'
        assert record['error']
        assert recovered.get('state')['time']==400
        assert recovered.list('checkpoint')
    finally:
        if process.poll() is None:
            os.killpg(process.pid,signal.SIGKILL)
            process.wait(timeout=10)
        process.stderr.close()

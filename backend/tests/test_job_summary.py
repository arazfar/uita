"""Frequent scene polls carry a journal cursor, while raw evidence stays on demand."""
from fastapi.testclient import TestClient

def test_scene_summary_retains_progress_cursor_without_raw_episode_payload(tmp_path,monkeypatch):
    monkeypatch.setenv('DATABASE_URL',f'sqlite:///{tmp_path}/default.db')
    from uita.app import create_app
    app=create_app(f'sqlite:///{tmp_path}/summary.db')
    event={'sequence':1,'stage':'frozen','kind':'frozen','message':'Frozen fixture','data':{'evidence':'cached'},'created_at':1.0}
    job={'id':'summary-test','status':'complete','stage':'rejected','source':'offline-fixture','events':[event],'frozen':{'development':{'raw':['x'*20000]}},'result':{'raw':['y'*20000]}}
    app.state.store.put('job-summary-test','job',job)
    policy={'id':'summary-policy','status':'rejected','development':{'raw':['z'*20000]},'revisions':[{'feedback':'r'*20000}]}
    app.state.store.put('policy-summary-policy','policy',policy)
    with TestClient(app) as client:
        summary=next(j for j in client.get('/api/state').json()['learning_jobs'] if j['id']=='summary-test')
        assert 'frozen' not in summary and 'result' not in summary
        assert summary['event_count']==1 and summary['events'][-1]['sequence']==1
        assert summary['events'][-1]['data']=={}
        full=client.get('/api/learning/jobs/summary-test').json()
        assert full['frozen']==job['frozen'] and full['result']==job['result']
        assert full['events']==[event]
        policy_summary=next(p for p in client.get('/api/state').json()['policies'] if p['id']=='summary-policy')
        assert 'development' not in policy_summary and 'revisions' not in policy_summary
        assert client.get('/api/learning/policies/summary-policy').json()==policy

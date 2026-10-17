"""HTTP cancellation races and durable command identity for investigator jobs."""
import copy
import importlib
import inspect

from fastapi.testclient import TestClient
import pytest


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{tmp_path}/default.db')
    module = importlib.import_module('uita.app')
    application = module.create_app(f'sqlite:///{tmp_path}/api.db')
    with TestClient(application) as client:
        yield client, application


def test_cancel_preserves_worker_completion_that_wins_during_join(api):
    client, application = api
    store = application.state.store
    job = {'id': 'race', 'status': 'running', 'stage': 'validating', 'events': []}
    store.put('job-race', 'job', job)
    route = next(route for route in application.routes if route.path == '/api/learning/jobs/{id}/cancel')
    workers = inspect.getclosurevars(route.endpoint).nonlocals['workers']
    complete = {**job, 'status': 'complete', 'stage': 'accepted', 'result': {'selected_policy_id': 'fixture-winner'}}

    class CompletionDuringJoin:
        def is_alive(self):
            return True

        def terminate(self):
            pass

        def join(self, timeout=None):
            # Deterministic scheduling of a real race: worker commits before
            # the cancelling API finishes joining it.
            store.put('job-race', 'job', complete)

    workers['race'] = CompletionDuringJoin()
    try:
        response = client.post('/api/learning/jobs/race/cancel')
        assert response.status_code == 200
        assert {key: response.json()[key] for key in complete} == complete
        assert store.get('job-race') == complete
    finally:
        workers.pop('race')


def test_cancel_is_idempotent_and_does_not_append_duplicate_terminal_events(api):
    client, application = api
    application.state.store.put('job-cancel', 'job', {'id': 'cancel', 'status': 'queued', 'stage': 'queued', 'events': []})
    first = client.post('/api/learning/jobs/cancel/cancel')
    second = client.post('/api/learning/jobs/cancel/cancel')
    assert first.status_code == second.status_code == 200
    assert first.json()['status'] == 'cancelled'
    assert first.json() == second.json()
    assert len(first.json()['events']) == 1


def test_training_command_identity_survives_immediate_cancellation(api):
    client, application = api
    command = {'source': 'fixture', 'revisions': 0, 'generations': 1, 'idempotency_key': 'independent-training-identity'}
    first = client.post('/api/learning/train', json=command)
    assert first.status_code == 200
    identifier = first.json()['id']
    cancelled = client.post(f'/api/learning/jobs/{identifier}/cancel')
    assert cancelled.status_code == 200
    replay = client.post('/api/learning/train', json=command)
    assert replay.status_code == 200
    assert replay.json()['id'] == identifier
    assert replay.json()['status'] in ('cancelled', 'complete')
    assert len(application.state.store.list('job')) == 1
    changed = client.post('/api/learning/train', json={**command, 'revisions': 1})
    assert changed.status_code == 409


def test_repeated_activation_of_current_policy_does_not_duplicate_revision_or_events(api):
    client, application = api
    first = client.post('/api/learning/policies/static/promote')
    second = client.post('/api/learning/policies/static/promote')
    assert first.status_code == second.status_code == 200
    assert first.json()['revision'] == second.json()['revision']
    assert first.json()['events'] == second.json()['events']


def test_test_only_promotion_fixture_persists_lineage_and_keeps_activation_separate(api, monkeypatch):
    """Manufactured favorable gate inputs test lifecycle, never learning quality."""
    import asyncio
    from uita import agent_jobs
    from uita.agent_contracts import AgentLimits
    from uita.investigator import STRONG_STATIC, fixture_model
    client, application = api
    store = application.state.store
    before = store.get('state')['active_policy']
    identifier = 'explicit-promotion-fixture'
    store.put('job-'+identifier, 'job', {'id': identifier, 'status': 'queued', 'stage': 'queued',
              'source': 'offline-fixture', 'memory_mode': 'persistent', 'parent_id': 'static-v2',
              'parent_program': STRONG_STATIC.model_dump(), 'ancestry': [], 'events': [],
              'limits': AgentLimits(revisions=0).model_dump(), 'provider_usage': {'calls': 0}})

    def artificial_validation(policy, seeds):
        score = 80 if policy.observation_scope == 'pending' else 100
        return {'cases': 1, 'pass_count': 1, 'fail_count': 0, 'unresolved_count': 0,
                'mean_score': score, 'p95_delay': 10, 'mean_backlog': 1,
                'raw': [{'observation_count': 8, 'max_solver_seconds': .01}]}

    monkeypatch.setattr(agent_jobs, 'evaluate', artificial_validation)
    asyncio.run(agent_jobs.execute_job(store, identifier, fixture_model()))
    job = store.get('job-'+identifier)
    assert job['status'] == 'complete'
    candidate = job['result']['candidates'][0]
    assert candidate['accepted'] and candidate['source'] == 'offline-fixture'
    memory = store.get('agent-accepted-parent')
    assert memory['policy_id'] == candidate['id']
    assert memory['ancestry'] == [candidate['id']]
    assert store.get('state')['active_policy'] == before

    next_job = client.post('/api/learning/train', json={'source': 'fixture', 'revisions': 0, 'idempotency_key': 'next-accepted-parent-fixture'})
    assert next_job.status_code == 200
    assert next_job.json()['parent_id'] == candidate['id']
    assert next_job.json()['ancestry'] == [candidate['id']]
    assert client.post('/api/learning/jobs/'+next_job.json()['id']+'/cancel').status_code == 200

    promoted = client.post('/api/learning/policies/'+candidate['id']+'/promote')
    assert promoted.status_code == 200
    assert store.get('state')['active_policy'] == candidate['id']
    assert client.post('/api/learning/rollback').status_code == 200
    assert store.get('state')['active_policy'] == before

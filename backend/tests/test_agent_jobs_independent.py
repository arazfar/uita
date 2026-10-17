"""Independent durable freeze, idempotency, cancellation and real process loss."""
import asyncio
import copy
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from uita import agent_jobs
from uita.agent_contracts import AgentLimits
from uita.investigator import STRONG_STATIC, fixture_model
from uita.storage import Store


def seed_job(store, identifier='independent-job', **changes):
    job = {'id': identifier, 'status': 'queued', 'stage': 'queued', 'source': 'offline-fixture',
           'limits': AgentLimits(revisions=0).model_dump(), 'parent_program': STRONG_STATIC.model_dump(),
           'parent_id': 'static-v2', 'memory_mode': 'persistent', 'ancestry': [], 'events': [],
           'provider_usage': {'calls': 0, 'input_tokens': 0, 'output_tokens': 0, 'cost_usd': 0}, **changes}
    store.put('job-'+identifier, 'job', job)
    return job


@pytest.mark.parametrize('status', ['complete', 'cancelled', 'interrupted', 'budget_exhausted', 'provider_failure', 'running'])
def test_repeated_worker_entry_cannot_reissue_model_or_mutate_nonqueued_job(tmp_path, status):
    store = Store(f'sqlite:///{tmp_path}/idempotency.db')
    original = seed_job(store, status=status)
    calls = []

    def forbidden_model(messages, info):
        calls.append(messages)
        raise AssertionError('Worker attempted model replay')

    asyncio.run(agent_jobs.execute_job(store, original['id'], FunctionModel(forbidden_model)))
    assert calls == []
    assert store.get('job-'+original['id']) == original


def test_frozen_artifact_is_durable_before_validation_and_validation_never_returns_to_model(tmp_path, monkeypatch):
    store = Store(f'sqlite:///{tmp_path}/freeze.db')
    job = seed_job(store)
    original_validation = agent_jobs.independent_validation
    validation_calls = []

    def verify_boundary(frozen, parent, emit, consumed=False):
        persisted = Store(f'sqlite:///{tmp_path}/freeze.db').get('job-'+job['id'])
        assert persisted['frozen']['artifact_hash'] == frozen['artifact_hash']
        assert persisted['frozen']['program'] == frozen['program']
        assert persisted['events'][-1]['kind'] == 'frozen'
        assert persisted['frozen']['exposures'] == ['development']
        validation_calls.append(frozen['artifact_hash'])
        return original_validation(frozen, parent, emit, consumed)

    monkeypatch.setattr(agent_jobs, 'independent_validation', verify_boundary)
    asyncio.run(agent_jobs.execute_job(store, job['id'], fixture_model()))
    result = store.get('job-'+job['id'])
    assert result['status'] == 'complete', result
    assert len(validation_calls) == 1
    kinds = [event['kind'] for event in result['events']]
    frozen_index = kinds.index('frozen')
    assert not any(kind in ('candidate', 'tool_result', 'development_started') for kind in kinds[frozen_index+1:])
    assert result['result']['candidates'][0]['frozen_before_validation'] is True
    assert result['result']['heldout_status'] == 'sealed-not-consumed-by-adaptive-job'
    assert store.list('heldout') == []


def test_cancellation_of_async_model_preserves_journal_without_candidate(tmp_path):
    store = Store(f'sqlite:///{tmp_path}/cancel.db')
    job = seed_job(store)

    async def run():
        entered = asyncio.Event()

        async def slow_model(messages, info):
            entered.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(agent_jobs.execute_job(store, job['id'], FunctionModel(slow_model)))
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        await task

    asyncio.run(run())
    result = store.get('job-'+job['id'])
    assert result['status'] == 'cancelled'
    assert result['events']
    assert 'frozen' not in result
    assert store.list('policy') == []


@pytest.mark.parametrize('boundary', ['before_response', 'after_response_before_persistence', 'after_persistence'])
def test_real_process_loss_after_paid_reservation_preserves_budget_and_explicit_recovery(tmp_path, boundary):
    database = tmp_path/'kill.db'
    ledger = tmp_path/'kill-ledger.db'
    barrier = tmp_path/'request-entered'
    script = tmp_path/'kill_driver.py'
    script.write_text('''import asyncio, json, sys, time
from pathlib import Path
import httpx
from uita.agent_contracts import AgentLimits
from uita.agent_provider import ReservedTransport
from uita.provider import SpendLedger, BASE, MODEL
from uita.storage import Store
async def main():
    store=Store('sqlite:///'+sys.argv[1])
    store.put('job-killed','job',{'id':'killed','status':'running','stage':'proposing','events':[]})
    boundary=sys.argv[4]
    def block():
        Path(sys.argv[3]).write_text(boundary)
        while True:time.sleep(1)
    def emit(kind,message,data):
        if kind=='inference_received' and boundary=='after_response_before_persistence':block()
        job=store.get('job-killed');job['events'].append({'kind':kind,'data':data});store.put('job-killed','job',job)
        if kind=='inference_received' and boundary=='after_persistence':block()
    async def response_lost(request):
        if boundary=='before_response':
            Path(sys.argv[3]).write_text(boundary)
            await asyncio.Event().wait()
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':'{}'}}],'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}})
    transport=ReservedTransport(httpx.MockTransport(response_lost),SpendLedger(sys.argv[2],cap=.05),'killed',AgentLimits(),(.05/1e6,.20/1e6),emit)
    async with httpx.AsyncClient(transport=transport) as client:
        await client.post(BASE+'/chat/completions',json={'model':MODEL,'max_tokens':1000})
asyncio.run(main())
''')
    env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])}
    process = subprocess.Popen([sys.executable, str(script), str(database), str(ledger), str(barrier), boundary], env=env, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic()+15
        while not barrier.exists() and process.poll() is None and time.monotonic()<deadline:
            time.sleep(.02)
        assert barrier.exists(), process.stderr.read().decode() if process.poll() is not None else 'Request never entered mocked wire'
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
        reader = Store(f'sqlite:///{database}')
        assert reader.get('job-killed')['status'] == 'running'
        recovered = Store(f'sqlite:///{database}', recover=True)
        job = recovered.get('job-killed')
        assert job['status'] == 'interrupted'
        assert job['events'][0]['kind'] == 'inference_reserved'
        assert any(event['kind'] == 'inference_received' for event in job['events']) == (boundary == 'after_persistence')
        with sqlite3.connect(ledger) as connection:
            rows = connection.execute('SELECT reserved_usd,actual_usd FROM inference_reservations').fetchall()
        assert len(rows) == 1 and rows[0][0] > 0
        if boundary == 'before_response':
            assert rows[0][1] is None
        else:
            assert rows[0][1] == pytest.approx(1.5e-6)
        from uita.provider import SpendLedger, ProviderError
        reopened = SpendLedger(str(ledger), cap=.05)
        with pytest.raises(ProviderError):
            reopened.reserve(.05)
        model_calls = []
        def forbidden_replay(messages, info):
            model_calls.append(messages)
            raise AssertionError('Recovered ambiguous inference was reissued')
        asyncio.run(agent_jobs.execute_job(recovered, 'killed', FunctionModel(forbidden_replay)))
        assert model_calls == []
        assert recovered.get('job-killed') == job
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        process.stderr.close()


def test_changed_frozen_program_is_rejected_before_any_validation_access(monkeypatch):
    from uita.learning import program_hash
    frozen = {'program': STRONG_STATIC.model_dump(), 'artifact_hash': program_hash(STRONG_STATIC)}
    frozen['program']['observations'] = ['weather']
    calls = []
    monkeypatch.setattr(agent_jobs, 'evaluate', lambda *args: calls.append(args))
    with pytest.raises(ValueError, match='hash mismatch'):
        agent_jobs.independent_validation(frozen, STRONG_STATIC, lambda *args: None)
    assert calls == []


def test_weaker_upgraded_static_cannot_lower_legacy_promotion_hurdle(monkeypatch):
    """Synthetic promotion-gate fixture, not evidence of learning quality."""
    from uita.learning import program_hash
    from uita.planner import STATIC
    candidate = STRONG_STATIC.model_copy(update={'observations': ['gate_ready']})
    parent = STRONG_STATIC
    calls = []

    def summary(score):
        return {'cases': 1, 'pass_count': 1, 'mean_score': score, 'p95_delay': 10,
                'raw': [{'observation_count': 8, 'max_solver_seconds': .01}]}

    def evaluator(policy, seeds):
        calls.append(policy)
        if (policy.observations == STATIC.observations and policy.observation_scope == 'all'
                and policy.allocation == 'tool-major'):
            return summary(100)
        if program_hash(policy) == program_hash(candidate):
            return summary(100)
        return summary(110)

    monkeypatch.setattr(agent_jobs, 'evaluate', evaluator)
    frozen = {'program': candidate.model_dump(), 'artifact_hash': program_hash(candidate), 'development': summary(100)}
    verdict = agent_jobs.independent_validation(frozen, parent, lambda *args: None)
    assert not verdict['accepted']
    assert any(policy.observations == STATIC.observations and policy.observation_scope == 'all'
               and policy.allocation == 'tool-major' for policy in calls)


def test_two_workers_racing_same_job_only_run_one_investigation(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Lock
    store = Store(f'sqlite:///{tmp_path}/claim.db')
    job = seed_job(store)
    barrier = Barrier(2)
    lock = Lock()
    calls = []

    def respond(messages, info):
        with lock:
            calls.append(messages)
        names = [getattr(part, 'tool_name', None) for part in messages[-1].parts]
        if 'inspect_dependencies' not in names:
            return ModelResponse(parts=[ToolCallPart('inspect_dependencies', {'request': {'case_id': 'dev-101-baseline'}})])
        return ModelResponse(parts=[ToolCallPart('submit_candidate', {'observations': ['gate_ready'], 'evidence_refs': ['dev-101-baseline'], 'explanation': 'Concurrency fixture only.'})])

    def worker(_):
        barrier.wait(timeout=5)
        asyncio.run(agent_jobs.execute_job(store, job['id'], FunctionModel(respond)))

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(worker, range(2)))
    assert len(calls) == 2  # one inspect request and one proposal request
    assert store.get('job-'+job['id'])['status'] == 'complete'
    assert len(store.list('policy')) == 1


def test_cancellation_during_development_evaluation_cannot_freeze_or_promote(tmp_path, monkeypatch):
    from threading import Event
    from uita import investigator
    store = Store(f'sqlite:///{tmp_path}/cancel-evaluation.db')
    job = seed_job(store)
    entered, release = Event(), Event()
    original = investigator.evaluate
    evaluations = []

    def blocked_evaluate(policy, seeds):
        evaluations.append(policy)
        if len(evaluations) == 2:
            entered.set()
            assert release.wait(timeout=5)
        return original(policy, seeds)

    monkeypatch.setattr(investigator, 'evaluate', blocked_evaluate)

    async def run():
        task = asyncio.create_task(agent_jobs.execute_job(store, job['id'], fixture_model()))
        deadline = time.monotonic()+5
        while not entered.is_set() and time.monotonic()<deadline:
            await asyncio.sleep(.01)
        assert entered.is_set()
        task.cancel()
        await task
        release.set()  # trusted bounded worker may finish, but cannot publish

    try:
        asyncio.run(run())
    finally:
        release.set()
    result = store.get('job-'+job['id'])
    assert result['status'] == 'cancelled'
    assert any(event['kind'] == 'development_started' and 'artifact_hash' in event['data'] for event in result['events'])
    assert not any(event['kind'] == 'frozen' for event in result['events'])
    assert store.list('policy') == []

"""Provider wire → durable event journal → browser API, with no paid inference."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from uita.agent_contracts import AgentLimits
from uita.agent_jobs import append_event
from uita.agent_provider import ReservedTransport
from uita.app import create_app
from uita.provider import BASE, MODEL, THINKING, SpendLedger, ProviderError


@pytest.mark.parametrize('reasoning', ['Inspect readiness before changing the candidate.', '✈🛬' * 10000, None])
def test_provider_reasoning_survives_journal_and_job_api_without_fabrication(tmp_path, reasoning):
    app = create_app(f'sqlite:///{tmp_path}/journal.db')
    store = app.state.store
    store.put('job-trace', 'job', {'id': 'trace', 'status': 'running', 'stage': 'inspecting', 'source': 'crusoe-live', 'events': []})
    original_content = '<think>This final-output text must never become a reasoning trace.</think>'
    message = {'role': 'assistant', 'content': original_content}
    if reasoning is not None:
        message['reasoning_content'] = reasoning
    def response(request):
        body = json.loads(request.content)
        assert body['chat_template_kwargs']['enable_thinking'] is True
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': message}], 'usage': {'prompt_tokens': 20, 'completion_tokens': 30, 'total_tokens': 50}})
    transport = ReservedTransport(httpx.MockTransport(response), SpendLedger(str(tmp_path/'spend.db'), cap=.02), 'trace', AgentLimits(), (.1/1e6, .4/1e6), lambda kind, text, data: append_event(store, 'trace', kind, text, data))
    async def run():
        async with httpx.AsyncClient(transport=transport) as client:
            await client.post(BASE+'/chat/completions', json={'model': MODEL, 'max_tokens': 1000, 'chat_template_kwargs': THINKING})
    asyncio.run(run())
    with TestClient(app) as client:
        result = client.get('/api/learning/jobs/trace')
    assert result.status_code == 200
    job = result.json()
    event = job['events'][-1]
    assert job['provider_usage']['calls'] == 1
    assert job['provider_usage']['thinking_enabled'] is True
    assert original_content not in json.dumps(job)
    if reasoning is None:
        assert event['kind'] == 'reasoning_unavailable'
        assert 'text' not in event['data']
    else:
        assert event['kind'] == 'reasoning'
        assert reasoning.startswith(event['data']['text'])
        assert event['data']['truncated'] == (len(reasoning) > len(event['data']['text']))
        assert len(json.dumps(event).encode()) < 18000


def test_thinking_disabled_request_never_reaches_paid_transport(tmp_path):
    calls = []
    transport = ReservedTransport(httpx.MockTransport(lambda request: calls.append(request)), SpendLedger(str(tmp_path/'spend.db'), cap=.02), 'trace', AgentLimits(), (.1/1e6, .4/1e6), lambda *args: None)
    async def run():
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(ProviderError, match='thinking enabled'):
                await client.post(BASE+'/chat/completions', json={'model': MODEL, 'max_tokens': 1000, 'chat_template_kwargs': {'enable_thinking': False}})
    asyncio.run(run())
    assert calls == []
    assert transport.usage['calls'] == 0

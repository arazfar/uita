"""Independent mock-wire checks of paid-request reservation and fail-closed use."""
import asyncio
import json
import sqlite3

import httpx
import pytest

from uita.agent_contracts import AgentLimits
from uita.agent_provider import ReservedTransport
from uita.provider import BASE, MODEL, ProviderError, SpendLedger, THINKING


def paid_rows(path):
    with sqlite3.connect(path) as connection:
        return connection.execute('SELECT reserved_usd,actual_usd FROM inference_reservations').fetchall()


def wire_response(usage=None, finish='stop'):
    return {'choices': [{'finish_reason': finish, 'message': {'role': 'assistant', 'content': '{}'}}],
            'usage': usage if usage is not None else {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}


def make_transport(tmp_path, handler, limits=None):
    path = str(tmp_path/'transport.sqlite')
    events = []
    limits = limits or AgentLimits()
    transport = ReservedTransport(httpx.MockTransport(handler), SpendLedger(path, cap=.05), 'independent-job', limits, (0.05/1e6, .20/1e6), lambda *args: events.append(args))
    return path, events, transport


async def post(transport, limits=None, url=None, body=None):
    limits = limits or AgentLimits()
    async with httpx.AsyncClient(transport=transport) as client:
        return await client.post(url or BASE+'/chat/completions', json=body or {'model': MODEL, 'max_tokens': limits.request_output_tokens, 'chat_template_kwargs': THINKING, 'messages': [{'role': 'user', 'content': 'development only'}]})


def test_request_is_reserved_durably_before_wire_dispatch_and_usage_is_settled(tmp_path):
    received = []

    def handler(request):
        received.append(request)
        rows = paid_rows(path)
        assert len(rows) == 1 and rows[0][0] > 0 and rows[0][1] is None
        assert events[-1][0] == 'inference_reserved'
        return httpx.Response(200, json=wire_response())

    path, events, transport = make_transport(tmp_path, handler)
    result = asyncio.run(post(transport))
    assert result.status_code == 200
    assert len(received) == 1
    assert paid_rows(path)[0][1] == pytest.approx(1.5e-6)
    assert transport.usage['calls'] == 1
    assert [event[0] for event in events] == ['inference_reserved', 'inference_metadata', 'inference_received', 'reasoning_unavailable']


@pytest.mark.parametrize('response', [
    {}, wire_response(usage={}),
    wire_response(usage={'prompt_tokens': True, 'completion_tokens': 5}),
    wire_response(usage={'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 16}),
    wire_response(usage={'prompt_tokens': 10, 'completion_tokens': 1001}),
    wire_response(usage={'prompt_tokens': -1, 'completion_tokens': 5}),
    wire_response(finish='length'),
])
def test_invalid_response_keeps_reservation_and_is_not_retried(tmp_path, response):
    calls = []
    path, events, transport = make_transport(tmp_path, lambda request: calls.append(request) or httpx.Response(200, json=response))
    with pytest.raises(ProviderError):
        asyncio.run(post(transport))
    assert len(calls) == 1
    assert len(paid_rows(path)) == 1
    if response.get('choices', [{}])[0].get('finish_reason') == 'length':
        # Rejected output may still have valid billable usage. Settle the actual
        # amount while retaining its original conservative reservation.
        assert paid_rows(path)[0][1] == pytest.approx(1.5e-6)
        assert any(event[0] == 'inference_received' for event in events)
        assert transport.usage['cost_estimate_known'] is True
    else:
        assert paid_rows(path)[0][1] is None
        assert not any(event[0] == 'inference_received' for event in events)
        assert transport.usage['cost_estimate_known'] is False


@pytest.mark.parametrize('status', [400, 429, 500, 503])
def test_http_failure_is_single_attempt_with_reservation_retained(tmp_path, status):
    calls = []
    path, _, transport = make_transport(tmp_path, lambda request: calls.append(request) or httpx.Response(status, json={'error': 'fixture'}))
    with pytest.raises(ProviderError):
        asyncio.run(post(transport))
    assert len(calls) == 1
    assert paid_rows(path)[0][1] is None


def test_timeout_retains_ambiguous_paid_reservation(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout('mock response lost', request=request)

    path, _, transport = make_transport(tmp_path, handler)
    with pytest.raises(httpx.ReadTimeout):
        asyncio.run(post(transport))
    assert len(calls) == 1
    reopened = SpendLedger(path, cap=.05)
    remaining = .05-paid_rows(path)[0][0]
    with pytest.raises(ProviderError):
        reopened.reserve(remaining+.000001)


@pytest.mark.parametrize('url,body', [
    ('https://unapproved.invalid/v1/chat/completions', None),
    ('http://api.inference.crusoecloud.com/v1/chat/completions', None),
    (BASE+'/other', None),
    (None, {'model': 'unapproved-model', 'max_tokens': 1000}),
    (None, {'model': MODEL, 'max_tokens': 1001}),
])
def test_invalid_endpoint_model_or_bound_is_rejected_before_spend(tmp_path, url, body):
    calls = []
    path, _, transport = make_transport(tmp_path, lambda request: calls.append(request) or httpx.Response(200, json=wire_response()))
    with pytest.raises(ProviderError):
        asyncio.run(post(transport, url=url, body=body))
    assert calls == []
    assert paid_rows(path) == []


def test_cancellation_during_wire_request_retains_reservation_without_retry(tmp_path):
    calls = []

    async def run():
        entered = asyncio.Event()

        async def handler(request):
            calls.append(request)
            entered.set()
            await asyncio.Event().wait()

        path, _, transport = make_transport(tmp_path, handler)
        task = asyncio.create_task(post(transport))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(paid_rows(path)) == 1 and paid_rows(path)[0][1] is None

    asyncio.run(run())
    assert len(calls) == 1


def test_request_budget_blocks_second_dispatch_before_new_reservation(tmp_path):
    calls = []
    limits = AgentLimits(model_requests=1)
    path, _, transport = make_transport(tmp_path, lambda request: calls.append(request) or httpx.Response(200, json=wire_response()), limits)

    async def run():
        async with httpx.AsyncClient(transport=transport) as client:
            body = {'model': MODEL, 'max_tokens': limits.request_output_tokens, 'chat_template_kwargs': THINKING}
            await client.post(BASE+'/chat/completions', json=body)
            with pytest.raises(ProviderError):
                await client.post(BASE+'/chat/completions', json=body)

    asyncio.run(run())
    assert len(calls) == len(paid_rows(path)) == 1


@pytest.mark.parametrize('changes', [
    {'input_tokens': 1000},
    {'output_tokens': 256},
    {'spend_usd': .000001},
])
def test_token_or_job_spend_budget_blocks_request_before_dispatch(tmp_path, changes):
    calls = []
    limits = AgentLimits(**changes)
    path, _, transport = make_transport(tmp_path, lambda request: calls.append(request) or httpx.Response(200, json=wire_response()), limits)
    with pytest.raises(ProviderError):
        asyncio.run(post(transport, limits))
    assert calls == paid_rows(path) == []


@pytest.mark.parametrize('failure', ['rate_limit', 'timeout'])
def test_configured_sdk_does_not_retry_ambiguous_or_rate_limited_paid_requests(tmp_path, monkeypatch, failure):
    from uita import agent_provider
    calls = []
    original_client = httpx.AsyncClient
    ledger_path = str(tmp_path/'sdk.sqlite')
    monkeypatch.setenv('CRUSOE_API_KEY', 'independent-mock-key')
    monkeypatch.setenv('CRUSOE_MAX_SPEND_USD', '.05')
    monkeypatch.setenv('CRUSOE_BUDGET_DB', ledger_path)

    def discovery(request):
        assert request.method == 'GET'
        return httpx.Response(200, json={'data': [{'id': MODEL, 'supported_parameters': ['temperature', 'top_p', 'max_tokens', 'tools', 'chat_template_kwargs'], 'context_length': 262144, 'is_billed_by_token': True, 'pricing': {'prompt': '.05', 'completion': '.20'}}]})

    def generation(request):
        calls.append(request)
        if failure == 'timeout':
            raise httpx.ReadTimeout('mock ambiguous wire request', request=request)
        return httpx.Response(429, json={'error': {'message': 'mock rate limit'}})

    class MockClient(original_client):
        def __init__(self, **kwargs):
            kwargs.setdefault('transport', httpx.MockTransport(discovery))
            super().__init__(**kwargs)

    def transport_factory(*, retries):
        assert retries == 0
        return httpx.MockTransport(generation)

    monkeypatch.setattr(agent_provider.httpx, 'AsyncClient', MockClient)
    monkeypatch.setattr(agent_provider.httpx, 'AsyncHTTPTransport', transport_factory)

    async def run():
        _, sdk, _ = await agent_provider.open_model('sdk-job', AgentLimits(), lambda *args: None)
        try:
            assert sdk.max_retries == 0
            with pytest.raises(Exception):
                await sdk.chat.completions.create(model=MODEL, max_tokens=1000, extra_body={'chat_template_kwargs': THINKING}, messages=[{'role': 'user', 'content': 'mock development evidence'}])
        finally:
            await sdk.close()

    asyncio.run(run())
    assert len(calls) == 1
    assert len(paid_rows(ledger_path)) == 1 and paid_rows(ledger_path)[0][1] is None

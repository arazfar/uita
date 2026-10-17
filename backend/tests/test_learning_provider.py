"""Implementation regression tests for learning/provider, no paid network calls."""
import copy
import json
import pytest
import httpx
from uita import provider
from uita.models import Policy
from uita.planner import STATIC
from uita import learning


def test_closed_loop_case_executes_and_matches_exogenous_tape():
    other=STATIC.model_copy(update={'name':'alternative','observations':['gate_ready','exit_occupancy']})
    left=learning.evaluate(STATIC,[101],['baseline'])['raw'][0]
    right=learning.evaluate(other,[101],['baseline'])['raw'][0]
    assert left['snapshot_hash']==right['snapshot_hash']
    assert left['event_tape']==right['event_tape']
    assert left['event_hash']==right['event_hash']
    for row in (left,right):
        assert row['final_time']==2700
        assert len(row['decisions'])==8
        assert row['metrics']['total']==15
        assert row['metrics']['completed']==len(row['completed_aircraft_ids'])
        assert row['metrics']['completed']+row['metrics']['backlog']==15
        assert all(d['observation_count']<=8 for d in row['decisions'])
        assert any(d['accepted'] for d in row['decisions'])


def test_candidate_cannot_change_solver_or_scoring_configuration():
    for field,value in [('reserve_seconds',0),('max_observations',96),('order','wake_group'),('lookahead',24)]:
        with pytest.raises(ValueError):
            learning.run_experiment(candidates=[STATIC.model_copy(update={field:value})])


def test_parent_mutations_are_bounded_even_for_empty_program():
    parent=STATIC.model_copy(update={'observations':[]})
    candidates=learning.fixture_candidates(8,parent=parent)
    assert len(candidates)==8
    assert all(len(candidate.observations)<=1 for candidate in candidates)
    assert all(candidate.max_observations==parent.max_observations for candidate in candidates)


def test_artifact_identity_ignores_cosmetic_name():
    assert learning.program_hash(STATIC)==learning.program_hash(STATIC.model_copy(update={'name':'rename'}))


def test_consumed_final_set_is_not_reused_for_another_artifact(monkeypatch):
    calls=[]
    def fake_evaluate(policy,seeds,variants=learning.VARIANTS):
        calls.append(seeds)
        score=80 if policy.observations==['gate_ready'] else 100
        return {'mean_score':score,'p95_delay':10,'pass_count':1,'fail_count':0,'cases':1,'raw':[{'observation_count':1,'max_solver_seconds':.001}]}
    monkeypatch.setattr(learning,'evaluate',fake_evaluate)
    candidate=STATIC.model_copy(update={'observations':['gate_ready']})
    result=learning.run_experiment(candidates=[candidate],consumed_artifacts=['previous-different-program'])
    assert result['selected_policy_id']
    assert result['heldout_status']=='sealed-prior-use'
    assert learning.HELDOUT_SEEDS not in calls


def test_aggregate_spend_reservation_survives_restart(tmp_path):
    path=str(tmp_path/'ledger.sqlite')
    first=provider.SpendLedger(path,cap=.05)
    first.reserve(.03)
    second=provider.SpendLedger(path,cap=.05)
    with pytest.raises(provider.ProviderError):second.reserve(.03)


@pytest.mark.parametrize('rate', ['nan','inf','-1'])
def test_invalid_provider_prices_are_rejected(rate):
    with pytest.raises(provider.ProviderError):
        provider._pricing({'id':provider.MODEL,'is_billed_by_token':True,'pricing':{'prompt':rate,'completion':'.20'}})


def test_authenticated_discovery_prices_use_documented_million_token_units():
    rates=provider._pricing({'id':provider.MODEL,'is_billed_by_token':True,'pricing':{'prompt':'.05','completion':'.20'}})
    assert rates==pytest.approx((.05/1e6,.20/1e6))


def fake_network(monkeypatch,tmp_path,*,supported=None,finish='stop',content=None):
    requests=[]
    supported=['temperature','top_p','max_tokens','response_format','chat_template_kwargs'] if supported is None else supported
    def handler(request):
        requests.append(request)
        if request.url.path.endswith('/models'):
            return httpx.Response(200,json={'data':[{'id':provider.MODEL,'is_billed_by_token':True,'context_length':262144,'supported_parameters':supported,'pricing':{'prompt':'.05','completion':'.20'}}]})
        return httpx.Response(200,json={'choices':[{'finish_reason':finish,'message':{'content':content or '{"observations":["gate_ready"]}'}}],'usage':{'prompt_tokens':120,'completion_tokens':20}})
    original=httpx.Client
    monkeypatch.setattr(provider.httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    monkeypatch.setenv('CRUSOE_API_KEY','unit-test-not-a-secret')
    monkeypatch.setenv('CRUSOE_MAX_SPEND_USD','.05')
    monkeypatch.setenv('CRUSOE_BUDGET_DB',str(tmp_path/'budget.sqlite'))
    return requests


def test_provider_uses_discovered_identity_and_fixed_grammar(monkeypatch,tmp_path):
    requests=fake_network(monkeypatch,tmp_path)
    policy,usage=provider.propose_policy({'summary':'development case only'})
    assert policy.max_observations==8
    assert usage['calls']==1
    assert usage['cost_usd']<usage['reserved_usd']<.05
    body=json.loads(requests[-1].content)
    assert body['model']==provider.MODEL
    assert body['max_tokens']==4096
    assert body['chat_template_kwargs']=={'enable_thinking':True,'medium_effort':True}
    assert body['temperature']==1.0 and body['top_p']==.95
    assert body['response_format']=={'type':'json_object'}


def test_missing_capability_blocks_paid_generation(monkeypatch,tmp_path):
    requests=fake_network(monkeypatch,tmp_path,supported=['temperature'])
    with pytest.raises(provider.ProviderError):provider.propose_policy({'summary':'test'})
    assert all(request.method=='GET' for request in requests)


def test_truncation_is_rejected_without_paid_retry(monkeypatch,tmp_path):
    requests=fake_network(monkeypatch,tmp_path,finish='length')
    with pytest.raises(provider.ProviderError):provider.propose_policy({'summary':'test'})
    assert sum(request.method=='POST' for request in requests)==1


def test_malformed_program_is_rejected(monkeypatch,tmp_path):
    fake_network(monkeypatch,tmp_path,content='{"observations":["read_secret"]}')
    with pytest.raises(provider.ProviderError):provider.propose_policy({'summary':'test'})

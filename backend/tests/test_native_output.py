"""Native-output protocol tests: typed JSON never bypasses required investigation."""
import asyncio
import json
import pytest
from pydantic_ai.messages import ModelResponse,ToolCallPart,TextPart
from pydantic_ai.models.function import FunctionModel
from uita.agent_contracts import AgentLimits
from uita.investigator import investigate,STRONG_STATIC

DRAFT={'observations':['gate_ready'],'observation_scope':'pending','allocation':'aircraft-major','evidence_refs':['dev-101-baseline'],'explanation':'Native-output boundary fixture; not evidence of live learning.'}

def test_native_json_after_registered_tool_uses_same_development_freeze_gate():
    calls=[];events=[]
    def respond(messages,info):
        calls.append(messages)
        assert info.output_tools==[]
        if len(calls)==1:
            return ModelResponse(parts=[ToolCallPart('inspect_dependencies',{'request':{'case_id':'dev-101-baseline'}})])
        return ModelResponse(parts=[TextPart(json.dumps(DRAFT))])
    model=FunctionModel(respond,profile={'supports_json_schema_output':True})
    result=asyncio.run(investigate(model,STRONG_STATIC,AgentLimits(revisions=0),lambda *args:events.append(args),native_output=True))
    assert result['resources']['tools']==1
    assert result['resources']['evaluations']==2
    assert events[-1][0]=='frozen'
    assert len(calls)==2


def test_native_json_cannot_skip_mandatory_inspection():
    model=FunctionModel(lambda messages,info:ModelResponse(parts=[TextPart(json.dumps(DRAFT))]),profile={'supports_json_schema_output':True})
    with pytest.raises(ValueError,match='investigation'):
        asyncio.run(investigate(model,STRONG_STATIC,AgentLimits(revisions=0),lambda *args:None,native_output=True))


def test_native_json_keeps_strict_local_schema_validation():
    model=FunctionModel(lambda messages,info:ModelResponse(parts=[TextPart(json.dumps({**DRAFT,'hidden_truth':'unavailable'}))]),profile={'supports_json_schema_output':True})
    with pytest.raises(Exception):
        asyncio.run(investigate(model,STRONG_STATIC,AgentLimits(revisions=0),lambda *args:None,native_output=True))

def test_native_crusoe_wire_uses_guided_output_and_auto_tools(monkeypatch):
    import httpx
    import pydantic_ai.models
    from openai import AsyncOpenAI
    from pydantic_ai.models.crusoe import CrusoeModel
    from pydantic_ai.providers.crusoe import CrusoeProvider
    from pydantic_ai.profiles.openai import OpenAIModelProfile
    from uita.investigator import build_agent
    monkeypatch.setattr(pydantic_ai.models,'ALLOW_MODEL_REQUESTS',True)
    requests=[]
    def handler(request):
        body=json.loads(request.content);requests.append(body)
        assert body['response_format']['type']=='json_schema'
        assert body['tool_choice']=='auto'
        assert body['max_tokens']==1000 and 'max_completion_tokens' not in body
        assert all('strict' not in tool['function'] for tool in body['tools'])
        return httpx.Response(200,json={'id':'native-fixture','created':0,'model':body['model'],'object':'chat.completion','choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':json.dumps(DRAFT)}}],'usage':{'prompt_tokens':100,'completion_tokens':50,'total_tokens':150}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            sdk=AsyncOpenAI(api_key='mock-only',base_url='https://api.inference.crusoecloud.com/v1',http_client=client,max_retries=0)
            provider=CrusoeProvider(openai_client=sdk)
            profile=OpenAIModelProfile(**{**provider.model_profile('nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B'),'openai_chat_supports_max_completion_tokens':False,'openai_supports_strict_tool_definition':False})
            model=CrusoeModel('nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B',provider=provider,profile=profile)
            result=await build_agent(model,AgentLimits()).run('Mock native response')
            assert result.output.observations==['gate_ready']
    asyncio.run(run())
    assert len(requests)==1

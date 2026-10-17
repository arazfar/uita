"""Async Crusoe integration with a reservation immediately before each paid POST.

SDK retries, transport retries, and Pydantic AI output/tool repair retries are zero.
The ledger keeps conservative reservations even when responses are lost or invalid.
"""
import json
import os
import httpx
from openai import AsyncOpenAI
from pydantic_ai.models.crusoe import CrusoeModel
from pydantic_ai.providers.crusoe import CrusoeProvider
from pydantic_ai.profiles.openai import OpenAIModelProfile
from .provider import BASE, MODEL, ProviderError, SpendLedger, _cap, _pricing, THINKING, MODEL_GUIDANCE

INTEGRATION_VERSION='super-vl-thinking-trace-3'

class ReservedTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner, ledger, job_id, limits, rates, emit):
        self.inner,self.ledger,self.job_id,self.limits,self.rates,self.emit=inner,ledger,job_id,limits,rates,emit
        self.usage={'calls':0,'input_tokens':0,'output_tokens':0,'reserved_usd':0.,'cost_usd':0.,'cost_estimate_known':True,'ambiguous_requests':0,'paid_retries':0,'provider':'Crusoe','model':MODEL,'integration_version':INTEGRATION_VERSION,'thinking_enabled':True,'reasoning_effort':'medium'}

    async def handle_async_request(self, request):
        if str(request.url.copy_with(path='',query=None))!='https://api.inference.crusoecloud.com':
            raise ProviderError('Unapproved generation origin')
        if request.method!='POST' or request.url.path!='/v1/chat/completions':
            raise ProviderError('Agent transport only permits the pinned generation endpoint')
        body=json.loads(request.content)
        if body.get('model')!=MODEL:raise ProviderError('Unpinned model rejected')
        if body.get('chat_template_kwargs')!=THINKING:raise ProviderError('Pinned model requires thinking enabled with bounded medium effort')
        if self.usage['calls']>=self.limits.model_requests:raise ProviderError('Model request budget exhausted')
        bound=len(request.content)*2+1024
        maximum=body.get('max_tokens',body.get('max_completion_tokens'))
        if maximum!=self.limits.request_output_tokens:raise ProviderError('Missing fixed generation output bound')
        if bound>30000 or self.usage['input_tokens']+bound>self.limits.input_tokens:raise ProviderError('Input token budget exhausted')
        if self.usage['output_tokens']+maximum>self.limits.output_tokens:raise ProviderError('Output token budget exhausted')
        amount=bound*self.rates[0]+maximum*self.rates[1]
        reservation=self.ledger.reserve(amount,self.job_id,self.limits.spend_usd)
        self.usage['calls']+=1;self.usage['reserved_usd']+=amount
        self.usage['ambiguous_requests']+=1;self.usage['cost_estimate_known']=False
        self.emit('inference_reserved','Paid request reserved before dispatch',{'reservation_id':reservation,'input_bound':bound,'output_bound':maximum,'usage':dict(self.usage)})
        response=await self.inner.handle_async_request(request)
        await response.aread()
        if response.status_code!=200:raise ProviderError('Crusoe generation failed; reservation retained, no retry')
        try:
            result=response.json();usage=result['usage'];choice=result['choices'][0]
            finish=choice.get('finish_reason')
            metadata={'finish_reason':finish if finish in ('stop','tool_calls','length','content_filter',None) else 'unrecognized','usage':{key:value for key,value in usage.items() if key in ('prompt_tokens','completion_tokens','total_tokens') and type(value) is int},'status_code':response.status_code}
            self.emit('inference_metadata','Response envelope inspected without storing model content',metadata)
            for key,limit in [('prompt_tokens',bound),('completion_tokens',maximum)]:
                if type(usage[key]) is not int or not 0<=usage[key]<=limit:raise ValueError('Invalid usage')
            if 'total_tokens' in usage and usage['total_tokens']!=usage['prompt_tokens']+usage['completion_tokens']:raise ValueError('Inconsistent usage')
        except (KeyError,ValueError,TypeError,IndexError):
            raise ProviderError('Missing or inconsistent provider usage; reservation retained') from None
        actual=usage['prompt_tokens']*self.rates[0]+usage['completion_tokens']*self.rates[1]
        self.ledger.record_actual(reservation,actual)
        self.usage['ambiguous_requests']-=1;self.usage['cost_estimate_known']=self.usage['ambiguous_requests']==0
        self.usage['input_tokens']+=usage['prompt_tokens'];self.usage['output_tokens']+=usage['completion_tokens'];self.usage['cost_usd']+=actual
        self.emit('inference_received','Complete response usage verified',{'reservation_id':reservation,'usage':dict(self.usage)})
        emit_reasoning(choice.get('message'),self.emit,self.usage['calls'])
        if finish not in ('stop','tool_calls'):
            raise ProviderError('Incomplete or truncated model output rejected; verified cost and reservation retained')
        return response

    async def aclose(self):await self.inner.aclose()


def emit_reasoning(message,emit,request_number):
    """Expose only a named provider reasoning field, never infer thoughts from output.

    The journal stores bounded plain text. React escapes it; it is never markup,
    an instruction, or evidence that a proposed plan passed the safety verifier.
    """
    message=message if isinstance(message,dict) else {}
    field=next((key for key in ('reasoning_content','reasoning') if isinstance(message.get(key),str) and message[key].strip()),None)
    if field is None:
        emit('reasoning_unavailable','Provider did not expose a reasoning field for this response',{'request':request_number,'thinking_enabled':True,'source':'provider-response'})
        return
    original=message[field];text=original
    # Bound the serialized representation, including escaped Unicode, below the
    # existing 18 KB AgentEvent limit without changing the provider's text.
    while len(json.dumps(text).encode())>10000:text=text[:max(1,len(text)*3//4)]
    emit('reasoning','Provider reasoning received',{'request':request_number,'source':'provider-response','field':field,'text':text,'truncated':len(text)<len(original),'original_characters':len(original),'thinking_enabled':True})

async def open_model(job_id,limits,emit):
    key=os.getenv('CRUSOE_API_KEY')
    if not key or _cap()<=0:raise ProviderError('Live Crusoe requires configured credentials and approved cap')
    async with httpx.AsyncClient(base_url=BASE,headers={'Authorization':'Bearer '+key},timeout=10,follow_redirects=False) as discovery:
        response=await discovery.get('/models');response.raise_for_status()
        catalog=response.json();model=next((m for m in catalog.get('data',catalog.get('models',[])) if m.get('id')==MODEL),None)
    if not model:raise ProviderError('Pinned Nemotron unavailable in authenticated discovery')
    supported=model.get('supported_parameters',[])
    if not all(k in supported for k in ('temperature','top_p','max_tokens','tools','chat_template_kwargs')):raise ProviderError('Discovery does not support bounded tool calling')
    if model.get('context_length',0)<32000:raise ProviderError('Discovery context bound inadequate')
    rates=_pricing(model)
    emit('discovery','Authenticated exact-model capabilities checked',{'model':MODEL,'supported_parameters':supported,'rates_usd_per_token':rates,'context_length':model.get('context_length'),'integration_version':INTEGRATION_VERSION,'settings':{'temperature':1.0,'top_p':.95,'model_guidance':MODEL_GUIDANCE,'output_token_parameter':'max_tokens','provider_strict_tool_definition':False,'local_pydantic_strict':True,'paid_retries':0,'thinking_enabled':True,'reasoning_effort':'medium'}})
    transport=ReservedTransport(httpx.AsyncHTTPTransport(retries=0),SpendLedger(),job_id,limits,rates,emit)
    http=httpx.AsyncClient(transport=transport,timeout=httpx.Timeout(60,connect=5),follow_redirects=False)
    sdk=AsyncOpenAI(api_key=key,base_url=BASE,http_client=http,max_retries=0)
    provider=CrusoeProvider(openai_client=sdk)
    settings={'temperature':1.0,'top_p':.95,'extra_body':{'chat_template_kwargs':dict(THINKING)}}
    profile=OpenAIModelProfile(**{**(provider.model_profile(MODEL) or {}),'openai_chat_supports_max_completion_tokens':False,'openai_supports_strict_tool_definition':False})
    return CrusoeModel(MODEL,provider=provider,profile=profile,settings=settings),sdk,transport

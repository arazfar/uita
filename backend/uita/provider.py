"""Fail-closed NVIDIA Nemotron adapter for Crusoe only; no live call at import.

A persistent, transactionally reserved spend ledger bounds aggregate generation
across retries, jobs and restarts. Ambiguous paid failures retain the reservation.
"""
import json
import math
import os
import sqlite3
import time
import uuid
from pathlib import Path
import httpx
from .models import Policy
from .planner import STATIC

MODEL='nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B'
PRICING_UNIT_SOURCE='https://www.crusoe.ai/cloud/pricing'
BASE='https://api.inference.crusoecloud.com/v1'
PROMPT_VERSION='observation-dsl-2'

class ProviderError(Exception):pass


def _cap():
    try:value=float(os.getenv('CRUSOE_MAX_SPEND_USD','0'))
    except ValueError:raise ProviderError('CRUSOE_MAX_SPEND_USD must be a finite nonnegative number') from None
    if not math.isfinite(value) or value<0:raise ProviderError('CRUSOE_MAX_SPEND_USD must be a finite nonnegative number')
    return value


class SpendLedger:
    def __init__(self,path=None,cap=None):
        self.path=path or os.getenv('CRUSOE_BUDGET_DB','uita-inference-budget.sqlite3')
        self.cap=_cap() if cap is None else cap
        if not math.isfinite(self.cap) or self.cap<=0:raise ProviderError('A finite positive approved spend cap is required')
        self.budget_id=os.getenv('CRUSOE_BUDGET_ID','default')
        with sqlite3.connect(self.path,timeout=5) as db:
            db.execute('CREATE TABLE IF NOT EXISTS inference_budgets (budget_id TEXT PRIMARY KEY, cap REAL NOT NULL)')
            db.execute('INSERT OR IGNORE INTO inference_budgets VALUES (?,?)',(self.budget_id,self.cap))
            stored=db.execute('SELECT cap FROM inference_budgets WHERE budget_id=?',(self.budget_id,)).fetchone()[0]
            self.cap=min(self.cap,stored)
            db.execute('CREATE TABLE IF NOT EXISTS inference_reservations (id TEXT PRIMARY KEY, budget_id TEXT NOT NULL, reserved_usd REAL NOT NULL, actual_usd REAL, created REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS inference_job_reservations (reservation_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, reserved_usd REAL NOT NULL)')
    def reserve(self,amount,job_id=None,job_cap=None):
        if not math.isfinite(amount) or amount<0:raise ProviderError('Invalid request reservation')
        with sqlite3.connect(self.path,timeout=5) as db:
            db.execute('BEGIN IMMEDIATE')
            used=db.execute('SELECT COALESCE(SUM(reserved_usd),0) FROM inference_reservations WHERE budget_id=?',(self.budget_id,)).fetchone()[0]
            if used+amount>self.cap:raise ProviderError('Aggregate approved Crusoe spend cap exhausted')
            if job_id is not None:
                job_used=db.execute('SELECT COALESCE(SUM(reserved_usd),0) FROM inference_job_reservations WHERE job_id=?',(job_id,)).fetchone()[0]
                if job_cap is None or job_used+amount>job_cap:raise ProviderError('Per-job Crusoe spend cap exhausted')
            identifier=str(uuid.uuid4())
            db.execute('INSERT INTO inference_reservations VALUES (?,?,?,?,?)',(identifier,self.budget_id,amount,None,time.time()))
            if job_id is not None:db.execute('INSERT INTO inference_job_reservations VALUES (?,?,?)',(identifier,job_id,amount))
            return identifier
    def record_actual(self,identifier,actual):
        if not math.isfinite(actual) or actual<0:raise ProviderError('Invalid actual cost')
        with sqlite3.connect(self.path,timeout=5) as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT reserved_usd,actual_usd FROM inference_reservations WHERE id=?',(identifier,)).fetchone()
            if row is None or actual>row[0]:raise ProviderError('Actual cost outside reservation')
            if row[1] is not None and row[1]!=actual:raise ProviderError('Conflicting actual cost update')
            db.execute('UPDATE inference_reservations SET actual_usd=? WHERE id=?',(actual,identifier))


def status():
    try:cap=_cap();configuration_error=None
    except ProviderError as exc:cap=0;configuration_error=str(exc)
    return {'provider':'Crusoe','model':MODEL,'configured':bool(os.getenv('CRUSOE_API_KEY')),'mode':'offline-fixture','live_verified':False,'prompt_version':PROMPT_VERSION,'spend_cap_usd':cap,'budget_scope':'persistent aggregate reservation; ambiguous failures remain reserved','configuration_error':configuration_error}


def _pricing(model):
    pricing=model.get('pricing') or {}
    if 'input_usd_per_million_tokens' in pricing and 'output_usd_per_million_tokens' in pricing:
        raw=(pricing['input_usd_per_million_tokens'],pricing['output_usd_per_million_tokens']);scale=1e6
    else:
        unit=pricing.get('unit',pricing.get('units'))
        # Crusoe's serverless pricing page explicitly denominates the discovery
        # prompt/completion numbers per million tokens (reviewed 2026-10-17).
        if unit is None and model.get('id')==MODEL and model.get('is_billed_by_token') is True:
            unit='usd_per_million_tokens'
        if unit not in ('usd_per_token','usd_per_million_tokens'):
            raise ProviderError('Discovery pricing lacks explicit supported USD/token units; spend gate closed')
        raw=(pricing.get('prompt',pricing.get('input')),pricing.get('completion',pricing.get('output')))
        scale=1e6 if unit=='usd_per_million_tokens' else 1
    try:rates=tuple(float(value)/scale for value in raw)
    except (TypeError,ValueError):raise ProviderError('Discovery pricing is malformed') from None
    if any(not math.isfinite(rate) or rate<0 for rate in rates):raise ProviderError('Discovery pricing must be finite and nonnegative')
    return rates


def propose_policy(weakness,ledger=None,cancel=None):
    key=os.getenv('CRUSOE_API_KEY');cap=_cap()
    if not key:raise ProviderError('CRUSOE_API_KEY missing. Offline fixture does not call a model.')
    if cap<=0:raise ProviderError('Live inference requires positive approved CRUSOE_MAX_SPEND_USD configuration.')
    if cancel is not None and cancel.is_set():raise ProviderError('Inference cancelled before request')
    # Only development evidence and the current parent may enter the prompt.
    def forbidden(value):
        if isinstance(value,dict):
            return any(any(word in str(k).lower().replace('_','') for word in ('heldout','secret','hiddentruth')) or forbidden(v) for k,v in value.items())
        if isinstance(value,list):return any(forbidden(v) for v in value)
        return False
    if forbidden(weakness):
        raise ProviderError('Held-out evidence or secret fields cannot enter a development prompt')
    messages=[{'role':'system','content':'Return only a JSON object with observations: an ordered list containing zero to four unique tool names from exit_occupancy, gate_ready, wake, weather. Only observations may change. Fixed budget is eight optional reads per decision. Safety observations and verifier run externally. No executable code. You cannot access hidden truth or held-out cases. Mutate the supplied accepted parent when provided.'},{'role':'user','content':json.dumps({'observed_weakness':weakness,'budget':STATIC.max_observations,'prompt_version':PROMPT_VERSION},allow_nan=False)}]
    # A deliberately conservative bound includes UTF-8 byte fallback plus chat
    # framing. Oversized prompts fail closed rather than truncating evidence.
    prompt_bytes=len(json.dumps(messages,ensure_ascii=False).encode('utf-8'))
    if prompt_bytes>3500:raise ProviderError('Development prompt exceeds bounded input size')
    input_bound=prompt_bytes*2+1024;output_bound=512
    usage={'calls':0,'input_tokens':0,'output_tokens':0,'cost_usd':None,'provider':'Crusoe','model':MODEL,'prompt_version':PROMPT_VERSION,'temperature':0,'max_tokens':output_bound,'paid_retries':0}
    with httpx.Client(timeout=httpx.Timeout(20,connect=5),base_url=BASE,headers={'Authorization':f'Bearer {key}'},follow_redirects=False) as client:
        try:
            discovered=client.get('/models');discovered.raise_for_status();catalog=discovered.json()
            models=catalog.get('data',catalog.get('models',[]))
            model=next((m for m in models if isinstance(m,dict) and m.get('id')==MODEL),None)
            if not model:raise ProviderError('Pinned NVIDIA model unavailable in authenticated Crusoe discovery')
            supported=model.get('supported_parameters')
            if not isinstance(supported,(list,dict)):raise ProviderError('Discovery did not establish supported generation parameters')
            if 'temperature' not in supported:raise ProviderError('Pinned model does not advertise temperature control')
            token_parameter='max_tokens' if 'max_tokens' in supported else 'max_completion_tokens' if 'max_completion_tokens' in supported else None
            if token_parameter is None:raise ProviderError('Pinned model does not advertise an output token bound')
            context=model.get('context_length',(model.get('limits') or {}).get('context_length'))
            if not isinstance(context,(int,float)) or context<input_bound+output_bound:raise ProviderError('Discovery did not establish sufficient context capacity')
            input_rate,output_rate=_pricing(model)
            usage['discovery']={'id':model.get('id'),'supported_parameters':supported,'pricing':model.get('pricing'),'context_length':context,'normalized_pricing_unit':'USD per token','pricing_unit_source':PRICING_UNIT_SOURCE}
            worst=input_rate*input_bound+output_rate*output_bound
            ledger=ledger or SpendLedger(cap=cap)
            if ledger.cap>cap:raise ProviderError('Supplied ledger exceeds currently approved aggregate cap')
            if cancel is not None and cancel.is_set():raise ProviderError('Inference cancelled before generation')
            reservation=ledger.reserve(worst);usage['reserved_usd']=worst;usage['reservation_id']=reservation
            body={'model':MODEL,'messages':messages,'temperature':0,token_parameter:output_bound}
            if 'response_format' in supported:body['response_format']={'type':'json_object'}
            if 'chat_template_kwargs' in supported:body['chat_template_kwargs']={'enable_thinking':False}
            # Never retry an ambiguous paid POST: a timeout can still be billed.
            usage['calls']=1;response=client.post('/chat/completions',json=body);response.raise_for_status()
            result=response.json();choice=result['choices'][0]
            if choice.get('finish_reason')!='stop':raise ProviderError('Incomplete or truncated model output rejected')
            output=json.loads(choice['message']['content'])
            if not isinstance(output,dict) or set(output)!={'observations'}:raise ProviderError('Output must contain only bounded observations')
            policy=Policy(**{**STATIC.model_dump(),'name':'Nemotron observation candidate','observations':output['observations']})
            if len(policy.observations)!=len(set(policy.observations)):raise ProviderError('Duplicate observation operations rejected')
            tokens=result.get('usage',{})
            for name,bound in [('prompt_tokens',input_bound),('completion_tokens',output_bound)]:
                value=tokens.get(name)
                if not isinstance(value,int) or value<0 or value>bound:raise ProviderError('Provider token usage absent or outside reserved bounds')
            usage.update(input_tokens=tokens['prompt_tokens'],output_tokens=tokens['completion_tokens'])
            usage['cost_usd']=usage['input_tokens']*input_rate+usage['output_tokens']*output_rate
            ledger.record_actual(reservation,usage['cost_usd'])
            return policy,usage
        except (httpx.HTTPError,ValueError,KeyError,TypeError,IndexError,sqlite3.Error):
            raise ProviderError('Crusoe request failed safely; paid requests are not retried and reservations are retained. Credentials and bodies are not logged.') from None

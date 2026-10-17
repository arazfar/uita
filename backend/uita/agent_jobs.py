"""Isolated worker and transactional evidence journal for investigator jobs."""
import asyncio
import hashlib
import json
import time
from .agent_contracts import AgentEvent,AgentLimits,GRAMMAR_VERSION,PROMPT_VERSION
from .investigator import investigate,fixture_model,STRONG_STATIC,BudgetExhausted,InvestigationStopped
from .learning import evaluate,TRAIN_SEEDS,VALIDATION_SEEDS,HELDOUT_SEEDS,CRITERIA,CONFIG_HASH,program_hash,validate_candidate
from .models import Policy
from .provider import ProviderError
from .planner import BASELINE
from .storage import Store,Record
from sqlalchemy import update

AGENT_EVALUATOR_VERSION='frozen-investigator-1'
AGENT_CONFIG_HASH=hashlib.sha256(json.dumps({'legacy_config':CONFIG_HASH,'grammar':GRAMMAR_VERSION,'strong_static':program_hash(STRONG_STATIC),'criteria':CRITERIA,'protocol':AGENT_EVALUATOR_VERSION,'prompt_version':PROMPT_VERSION,'live_output_mode':'native-json-schema','model_settings':{'temperature':0,'parallel_tool_calls':False,'paid_retries':0}},sort_keys=True).encode()).hexdigest()
TERMINAL={'complete','failed','cancelled','budget_exhausted','provider_failure','interrupted'}


def append_event(store,job_id,kind,message,data=None):
    with store.transaction() as db:
        job=store.get('job-'+job_id,db)
        if not job or job['status'] in TERMINAL:return False
        data=data or {};stage=data.get('stage',job.get('stage','queued'))
        if kind=='development_started':stage='evaluating_development'
        event=AgentEvent(sequence=len(job.get('events',[]))+1,stage=stage,kind=kind,message=message,data=data,created_at=time.time()).model_dump()
        events=job.get('events',[])+[event]
        if len(events)>200:raise BudgetExhausted('Event journal budget exhausted')
        update={**job,'events':events,'stage':stage,'updated_at':time.time()}
        if 'usage' in data:update['provider_usage']=data['usage']
        store.put('job-'+job_id,'job',update,db)
    return True


def independent_validation(frozen,parent,emit,consumed=False):
    """Called after frozen artifact is durable. Never fed back to the agent."""
    policy=validate_candidate(Policy(**frozen['program']))
    if program_hash(policy)!=frozen['artifact_hash']:raise ValueError('Frozen program hash mismatch')
    emit('stage','Independent validation of the frozen candidate',{'stage':'validating','artifact_hash':frozen['artifact_hash'],'exposures':['development','validation']})
    evaluation_count=0
    def fixed_evaluate(program,label):
        nonlocal evaluation_count
        if evaluation_count>=4:raise BudgetExhausted('Independent validation evaluation budget exhausted')
        evaluation_count+=1
        emit('validation_started','Evaluating fixed validation comparator',{'stage':'validating','label':label,'validation_evaluations':evaluation_count,'validation_evaluation_limit':4})
        return evaluate(program,VALIDATION_SEEDS)
    static=fixed_evaluate(STRONG_STATIC,'strong-static');baseline=fixed_evaluate(BASELINE,'FCFS')
    parent_result=static if program_hash(parent)==program_hash(STRONG_STATIC) else fixed_evaluate(parent,'accepted-parent')
    validation=fixed_evaluate(policy,'frozen-candidate');development=frozen['development']
    reasons=[]
    safe=all(r['pass_count']==r['cases'] for r in (development,validation))
    bounded=all(r['observation_count']<=8 and r['max_solver_seconds']<=2.1 for r in development['raw']+validation['raw'])
    if not safe:reasons.append('Independent feasibility regression')
    if not bounded:reasons.append('Fixed observation or solver budget exceeded')
    if validation['p95_delay']>static['p95_delay']*1.05:reasons.append('Tail delay regressed more than 5%')
    if validation['mean_score']>min(static['mean_score'],parent_result['mean_score'])*.99:reasons.append('Frozen validation score did not improve strong static and accepted parent by 1%')
    accepted=not reasons
    return {'validation_evaluations':evaluation_count,'validation':validation,'static':static,'baseline':baseline,'parent_validation':parent_result,'accepted':accepted,'reason':'; '.join(reasons) or 'Passed independent fixed promotion gates','heldout':None,'heldout_status':'sealed-prior-use' if consumed else 'sealed-not-consumed-by-adaptive-job'}


async def execute_job(store,job_id,model_override=None):
    with store.transaction() as db:
        record=db.get(Record,'job-'+job_id)
        if record is None or record.payload['status']!='queued':return
        job=record.payload
        claimed=db.execute(update(Record).where(Record.id==record.id,Record.version==record.version).values(payload={**job,'status':'running','started_at':time.time()},version=record.version+1))
        if claimed.rowcount!=1:return
    limits=AgentLimits(**job['limits']);parent=Policy(**job['parent_program']);sdk=None;transport=None
    def emit(kind,message,data=None):
        if not append_event(store,job_id,kind,message,data):raise asyncio.CancelledError()
    try:
        emit('stage','Preparing fixed development evidence',{'stage':'inspecting','exposures':['development'],'parent_id':job['parent_id'],'ancestry':job.get('ancestry',[])})
        if model_override is not None:model=model_override
        elif job['source']=='crusoe-live':
            from .agent_provider import open_model
            model,sdk,transport=await open_model(job_id,limits,emit)
            transport.usage['output_mode']='native-json-schema'
        else:model=fixture_model()
        async with asyncio.timeout(limits.wall_seconds):
            frozen=await investigate(model,parent,limits,emit,persistent=job.get('memory_mode','persistent')=='persistent')
            # Frozen program and complete development evidence are persisted before
            # the independent evaluator is called. Recovered jobs never resume POSTs.
            with store.transaction() as db:
                latest=store.get('job-'+job_id,db)
                if latest['status'] in TERMINAL:raise asyncio.CancelledError()
                store.put('job-'+job_id,'job',{**latest,'frozen':frozen},db)
            verdict=await asyncio.to_thread(independent_validation,frozen,parent,emit,bool(job.get('heldout_consumed')))
        identifier='agent-'+hashlib.sha256(f"{job_id}:{frozen['artifact_hash']}:{AGENT_CONFIG_HASH}".encode()).hexdigest()[:16]
        candidate={'id':identifier,'name':'Investigated observation policy','program':frozen['program'],'artifact_hash':frozen['artifact_hash'],'parent_id':job['parent_id'],'ancestry':job.get('ancestry',[]),'generation':len(frozen['revisions']),'status':'accepted' if verdict['accepted'] else 'rejected','accepted':verdict['accepted'],'reason':verdict['reason'],'train':frozen['development'],'development':frozen['development'],'validation':verdict['validation'],'heldout':None,'criteria':CRITERIA,'source':job['source'],'grammar_version':GRAMMAR_VERSION,'evaluator_version':AGENT_EVALUATOR_VERSION,'config_hash':AGENT_CONFIG_HASH,'frozen_before_validation':True,'exposures':['development','validation'],'revisions':frozen['revisions']}
        emit('decision',verdict['reason'],{'stage':candidate['status'],'artifact_hash':frozen['artifact_hash'],'accepted':verdict['accepted']})
        with store.transaction() as db:
            latest=store.get('job-'+job_id,db)
            if latest['status'] in TERMINAL:return
            usage=latest['provider_usage']
            result={'candidates':[candidate],'selected_policy_id':identifier if verdict['accepted'] else None,'baseline':verdict['baseline'],'static':verdict['static'],'parent_validation':verdict['parent_validation'],'source':job['source'],'provider_usage':usage,'revisions':frozen['revisions'],'resources':{**frozen['resources'],'validation_evaluations':verdict['validation_evaluations']},'elapsed_seconds':time.time()-latest.get('started_at',time.time()),'evaluator_version':AGENT_EVALUATOR_VERSION,'config_hash':AGENT_CONFIG_HASH,'grammar_version':GRAMMAR_VERSION,'prompt_version':PROMPT_VERSION,'heldout_status':verdict['heldout_status'],'heldout_policy_frozen_before_evaluation':True,'memory_mode':job.get('memory_mode','persistent'),'parent_id':job['parent_id']}
            store.put('policy-'+identifier,'policy',candidate,db)
            if verdict['accepted'] and job.get('memory_mode','persistent')=='persistent':
                store.put('agent-accepted-parent','agent_memory',{'policy_id':identifier,'artifact_hash':frozen['artifact_hash'],'config_hash':AGENT_CONFIG_HASH,'ancestry':job.get('ancestry',[])+[identifier]},db)
            store.put('job-'+job_id,'job',{**latest,'status':'complete','stage':candidate['status'],'result':result,'finished_at':time.time()},db)
    except BaseException as exc:
        latest=store.get('job-'+job_id)
        if latest and latest['status'] not in TERMINAL:
            name=type(exc).__name__
            status='cancelled' if isinstance(exc,asyncio.CancelledError) else 'budget_exhausted' if isinstance(exc,(BudgetExhausted,TimeoutError)) or 'UsageLimit' in name or 'budget' in str(exc).lower() or 'cap exhausted' in str(exc).lower() else 'provider_failure' if job['source']=='crusoe-live' else 'failed'
            # Framework exceptions can contain raw model text; never persist them.
            safe_message=str(exc) if isinstance(exc,(ProviderError,InvestigationStopped)) else 'bounded investigation stopped; no paid request will be retried'
            message=f'{name}: {safe_message}'
            append_event(store,job_id,'termination',message,{'stage':status})
            latest=store.get('job-'+job_id)
            store.put('job-'+job_id,'job',{**latest,'status':status,'stage':status,'error':message,'finished_at':time.time()})
    finally:
        if sdk is not None:await sdk.close()


def worker_entry(database_url,job_id):
    store=Store(database_url)
    asyncio.run(execute_job(store,job_id))

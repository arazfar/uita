"""HTTP adapter for the persistent single-process Uita research monolith."""
import copy, hashlib, json, logging, multiprocessing, os, threading, time, uuid
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .models import Control, Disruption, Propose, Commit, Train, Compare, Policy, Snapshot
from .storage import Store, Record
from .simulator import new_state, advance, inject, sample, metrics, trajectory, snapshot_hash, OBJECTIVES
from .planner import plan, BASELINE, STATIC
from .verifier import verify
from .airport import RUNWAYS, RULE_VERSION, SOURCES, LIMITATIONS
from .provider import status as provider_status, ProviderError
from .learning import run_experiment, evaluate, TRAIN_SEEDS, CONFIG_HASH
from .agent_contracts import AgentLimits,GRAMMAR_VERSION,PROMPT_VERSION,LearningJobView
from .agent_jobs import worker_entry,AGENT_CONFIG_HASH,AGENT_EVALUATOR_VERSION,TERMINAL,append_event
from .investigator import STRONG_STATIC

log=logging.getLogger('uita')

def create_app(database_url=None):
    store=Store(database_url,recover=True);lock=threading.RLock();last_wall=[time.monotonic()]
    workers={}
    database_address=str(store.engine.url)
    with store.transaction() as db:
        if store.get('state',db) is None:
            initial=new_state();initial['session_id']=str(uuid.uuid4())
            store.put('checkpoint-'+str(uuid.uuid4()),'checkpoint',{'session_id':initial['session_id'],'time':initial['time'],'state':initial},db)
            if database_url is None:
                initial=copy.deepcopy(initial);advance(initial,180);initial['running']=True
            store.put('state','state',initial,db)
        if not store.get('policy-baseline',db):store.put('policy-baseline','policy',{'id':'baseline','name':BASELINE.name,'program':BASELINE.model_dump(),'status':'builtin','accepted':True,'source':'hand-authored'},db)
        if not store.get('policy-static-v2',db):store.put('policy-static-v2','policy',{'id':'static-v2','name':STRONG_STATIC.name,'program':STRONG_STATIC.model_dump(),'status':'builtin','accepted':True,'source':'hand-authored'},db)
        if not store.get('policy-static',db):store.put('policy-static','policy',{'id':'static','name':STATIC.name,'program':STATIC.model_dump(),'status':'builtin','accepted':True,'source':'hand-authored'},db)

    @asynccontextmanager
    async def lifespan(app):
        yield
        for process in list(workers.values()):
            if process.is_alive():process.terminate();process.join(timeout=2)

    app=FastAPI(title='Uita research simulation',version='0.1.0',lifespan=lifespan)
    from .history import router as history_router
    app.include_router(history_router)
    app.state.store=store;app.state.lock=lock
    origins=os.getenv('UITA_ALLOWED_ORIGINS','http://localhost:5173,http://127.0.0.1:5173').split(',')
    app.add_middleware(CORSMiddleware,allow_origins=origins,allow_methods=['GET','POST'],allow_headers=['Content-Type','Authorization'])

    @app.middleware('http')
    async def boundary(request:Request,call_next):
        run_id=str(uuid.uuid4());start=time.perf_counter()
        if request.method!='GET' and request.url.path.startswith('/api/'):
            host=request.client.host if request.client else ''
            token=os.getenv('UITA_API_TOKEN')
            if token:
                import hmac
                if not hmac.compare_digest(request.headers.get('authorization',''),'Bearer '+token):return JSONResponse({'detail':'Mutation authorization required'},status_code=401)
            elif host not in ('127.0.0.1','::1','localhost','testclient'):
                return JSONResponse({'detail':'Remote mutation disabled. Configure UITA_API_TOKEN for hosted use.'},status_code=403)
            origin=request.headers.get('origin')
            if origin and origin not in origins and origin!=str(request.base_url).rstrip('/'):
                return JSONResponse({'detail':'Origin not allowed'},status_code=403)
        response=await call_next(request);response.headers['X-Run-ID']=run_id
        log.info(json.dumps({'run_id':run_id,'method':request.method,'path':request.url.path,'status':response.status_code,'elapsed_ms':round((time.perf_counter()-start)*1000,2)}))
        return response

    @app.exception_handler(ValueError)
    async def invalid(request,exc):return JSONResponse({'detail':str(exc)},status_code=409)
    @app.exception_handler(ProviderError)
    async def provider_failure(request,exc):return JSONResponse({'detail':str(exc)},status_code=503)

    def load():
        with store.sessions() as db:
            record=db.get(Record,'state');s=copy.deepcopy(record.payload);s['_storage_version']=record.version;return s
    def save(s,checkpoint=False,db=None):
        if db is None:
            with store.transaction() as tx:return save(s,checkpoint,tx)
        record=db.get(Record,'state');version=s.get('_storage_version',record.version)
        payload=copy.deepcopy(s);payload.pop('_storage_version',None)
        store.cas_state(version,payload,db);s['_storage_version']=version+1
        if checkpoint:store.put('checkpoint-'+str(uuid.uuid4()),'checkpoint',{'session_id':s['session_id'],'time':s['time'],'revision':s['revision'],'state':payload},db)
    def tick():
        s=load();now=time.monotonic();elapsed=now-last_wall[0];last_wall[0]=now
        if s['running']:
            before=s['time'];advance(s,elapsed*s['speed']);save(s,checkpoint=int(before//30)!=int(s['time']//30))
        return s
    def previous_command(command,kind):
        key=command.idempotency_key
        if not key:return None
        fingerprint=hashlib.sha256(json.dumps(command.model_dump(),sort_keys=True).encode()).hexdigest()
        previous=store.get('command-'+key)
        if previous:
            if previous['kind']!=kind or previous['fingerprint']!=fingerprint:raise HTTPException(409,'Idempotency key reused with different command')
            if previous['response'] is None:raise HTTPException(409,'This command is in progress or previously interrupted; it will not be issued twice')
            return previous['response']
        return None
    def record_command(command,kind,response,db=None):
        if command.idempotency_key:
            fingerprint=hashlib.sha256(json.dumps(command.model_dump(),sort_keys=True).encode()).hexdigest()
            store.put('command-'+command.idempotency_key,'command',{'kind':kind,'fingerprint':fingerprint,'response':response},db)
    def policy(id,research=False):
        p=store.get('policy-'+id)
        if not p:raise HTTPException(404,'Policy not found')
        if not research and p.get('status') not in ('builtin','accepted','promoted'):raise HTTPException(409,'Rejected or unsupported policy cannot control the simulator')
        return Policy(**p['program'])
    def provider_info():
        info=provider_status()
        completed=[j for j in store.list('job',1000) if j.get('source')=='crusoe-live' and j.get('status')=='complete' and j.get('provider_usage',{}).get('calls',0)>0]
        agent_completed=[j for j in completed if j.get('evaluator_version')==AGENT_EVALUATOR_VERSION]
        info.update(agent_loop_verified=bool(agent_completed),agent_framework='pydantic-ai 2.57.0',agent_prompt_version=PROMPT_VERSION,agent_integration_version='native-crusoe-profile-2')
        if completed:
            info.update(live_verified=True,last_verified_job_id=completed[0]['id'],verified_model=completed[0]['provider_usage'].get('model',completed[0]['provider_usage'].get('candidate',{}).get('model')),last_usage=completed[0]['provider_usage'])
        return info
    def decorate(s,extras=True):
        result=copy.deepcopy(s);result.pop('_storage_version',None);result['aircraft']=[sample(a,s['time']) for a in s['aircraft']]
        result['runways']=[{**r,'closed':r['id'] in s['closed_runways']} for r in RUNWAYS]
        result['mode']='offline-fixture';result['provider']=provider_info();result['metrics']=metrics(s)
        # Safety findings are recomputed from the actual current commitments.
        actual={'revision':s['revision'],'rule_version':RULE_VERSION,'snapshot_hash':snapshot_hash(s),'snapshot_time':s['time'],'valid_until':s['time']+30,'slots':[{'aircraft_id':a['id'],'runway':a['runway'],'time':a['scheduled']} for a in s['aircraft']]}
        verdict=verify(s,actual);result['safety']=verdict
        result['metrics']['conflicts']=sum(len(c['evidence'].get('conflicts',c['evidence'].get('overlaps',[]))) for c in verdict['checks'] if isinstance(c['evidence'],dict))
        result['coordinate_frame']={'horizontal':'local approximate ENU nautical miles','altitude':'MSL feet','time':'seconds since 2026-10-17T16:00:00Z','magnetic_runway_heading':284,'approximate_true_heading':297}
        result['sources']=SOURCES;result['limitations']=LIMITATIONS
        result['objective_config']=OBJECTIVES
        result['runway_reservations']=next((c['evidence']['intervals'] for c in verdict['checks'] if c['id']=='runway-resource'),[])
        if extras:
            result['proposals']=[p for p in store.list('proposal',40) if p.get('session_id')==s['session_id']][:12]
            result['policies']=[{k:v for k,v in p.items() if k not in ('train','validation','heldout','development','revisions')} for p in store.list('policy')]
            result['learning_jobs']=[{**{k:v for k,v in j.items() if k not in ('result','frozen','events')},'event_count':len(j.get('events',[])),'events':[{**e,'data':{}} for e in j.get('events',[])[-1:]]} for j in store.list('job',12)]
            result['checkpoints']=[{'time':c['time'],'revision':c.get('revision',1)} for c in store.list('checkpoint',500) if c['session_id']==s['session_id']]
        return result

    @app.get('/api/health')
    def health():return {'status':'ok','rule_version':RULE_VERSION,'database':'connected','worker':'bounded subprocess','schema_version':2,'provider':provider_info()}
    @app.get('/api/state',response_model=Snapshot)
    def state():
        with lock:return decorate(tick())
    @app.post('/api/control',response_model=Snapshot)
    def control(command:Control):
        with lock:
            prior=previous_command(command,'control')
            if prior:return decorate(prior)
            s=tick()
            if command.revision is not None and command.revision!=s['revision']:raise HTTPException(409,'Stale state revision')
            if command.action=='reset':
                version=s['_storage_version'];s=new_state(command.seed,command.scenario);s['session_id']=str(uuid.uuid4());s['_storage_version']=version
                # Preserve an initial checkpoint before the immediately moving demo.
                store.put('checkpoint-'+str(uuid.uuid4()),'checkpoint',{'session_id':s['session_id'],'time':400,'revision':1,'state':copy.deepcopy(s)})
                advance(s,180);s['running']=True;s['speed']=1
            elif command.action=='play':s['running']=True
            elif command.action=='pause':s['running']=False
            elif command.action=='step':s['running']=False;advance(s,command.seconds)
            elif command.action=='speed':s['speed']=command.speed
            last_wall[0]=time.monotonic()
            with store.transaction() as db:save(s,checkpoint=True,db=db);record_command(command,'control',s,db)
            return decorate(s)
    @app.post('/api/disruptions',response_model=Snapshot)
    def disruption(command:Disruption):
        with lock:
            prior=previous_command(command,'disruption')
            if prior:return decorate(prior)
            s=tick()
            if command.revision is not None and command.revision!=s['revision']:raise HTTPException(409,'Stale disruption revision')
            inject(s,command.model_dump())
            with store.transaction() as db:save(s,checkpoint=True,db=db);record_command(command,'disruption',s,db)
            return decorate(s)
    @app.post('/api/proposals')
    def propose(command:Propose):
        with lock:
            prior=previous_command(command,'propose')
            if prior:return prior
            s=tick();chosen_id=command.policy_id or s['active_policy'];chosen=policy(chosen_id)
            if command.idempotency_key:record_command(command,'propose',None)
        usage={'calls':0,'cost_usd':0,'source':'offline-fixture'}
        if command.source=='crusoe':
            accepted=store.get('policy-'+chosen_id)
            if not accepted or accepted.get('source')!='crusoe-live' or not accepted.get('accepted') or accepted.get('config_hash')!=AGENT_CONFIG_HASH:
                raise HTTPException(409,'Run a Crusoe investigation in Learning, then select an independently accepted agent policy. Movement proposals do not bypass the investigation gate.')
            usage={'calls':0,'cost_usd':0,'source':'accepted-agent-policy','policy_id':chosen_id}
        p=plan(s,chosen);p.update(session_id=s['session_id'],policy_id=chosen_id,source='crusoe-live' if command.source=='crusoe' else 'offline-fixture',provider_usage=usage)
        with store.transaction() as db:store.put('proposal-'+p['id'],'proposal',p,db);record_command(command,'propose',p,db)
        return p
    @app.post('/api/proposals/{id}/verify')
    def verify_proposal(id:str):
        with lock:
            s=tick();p=store.get('proposal-'+id)
            if not p:raise HTTPException(404,'Proposal not found')
            p=copy.deepcopy(p)
            if p['session_id']!=s['session_id']:raise HTTPException(409,'Proposal belongs to another scenario')
            p['verification']=verify(s,p);p['status']=p['verification']['status'];store.put('proposal-'+id,'proposal',p);return p
    @app.post('/api/proposals/{id}/commit',response_model=Snapshot)
    def commit(id:str,command:Commit):
        with lock:
            s=tick();key='idempotency-'+command.idempotency_key
            with store.transaction() as db:
                prior=store.get(key,db)
                if prior:
                    if prior['proposal_id']!=id:raise HTTPException(409,'Idempotency key belongs to another proposal')
                    return decorate(prior['state'])
                p=store.get('proposal-'+id,db)
                if not p:raise HTTPException(404,'Proposal not found')
                if p['session_id']!=s['session_id']:raise HTTPException(409,'Proposal belongs to another scenario')
                if command.revision is not None and command.revision!=s['revision']:raise HTTPException(409,'Stale command revision')
                if p['status']=='committed':raise HTTPException(409,'Proposal already committed with another key')
                v=verify(s,p)
                if v['status']!='pass':raise HTTPException(409,{'message':'Only independently passing current plans may be committed','verification':v})
                slots={slot['aircraft_id']:slot for slot in p['slots']}
                changes=0;shift_seconds=0
                for a in s['aircraft']:
                    slot=slots[a['id']]
                    if a['trajectory'][0]['t']>s['time']:
                        changes+=int(a['scheduled']!=slot['time'] or a['runway']!=slot['runway'])
                        shift_seconds+=abs(a['scheduled']-slot['time'])
                        a['scheduled']=slot['time'];a['runway']=slot['runway'];a['trajectory']=trajectory(a,slot['time'],slot['runway'])
                        a.pop('admission_hold',None)
                s['plan_changes']=s.get('plan_changes',0)+changes
                s['planning_decisions']=s.get('planning_decisions',0)+1
                s['plan_change_count']=s.get('plan_change_count',0)+changes
                s['schedule_shift_seconds']=s.get('schedule_shift_seconds',0)+shift_seconds
                s.setdefault('verified_replan_times',[]).append(s['time'])
                if s['disruptions']:s['last_recovery_seconds']=s['time']-s['disruptions'][-1]['time']
                s['revision']+=1;s['active_policy']=p['policy_id'];s['events'].append({'time':s['time'],'type':'commit','message':f'Verified plan committed · {changes} pending reservations changed · active trajectories preserved'})
                save(s,checkpoint=True,db=db)
                store.put('proposal-'+id,'proposal',{**p,'status':'committed','verification':v,'committed_revision':s['revision']},db)
                store.put(key,'idempotency',{'proposal_id':id,'state':s},db)
            return decorate(s)
    @app.get('/api/replay',response_model=Snapshot)
    def replay(time:float):
        with lock:
            current=load()
            if time<400 or time>current['time']:raise HTTPException(422,'Replay time must be inside recorded scenario history')
            records=[c for c in store.list('checkpoint',5000) if c['session_id']==current['session_id'] and c['time']<=time]
            s=copy.deepcopy(max(records,key=lambda c:c['time'])['state']) if records else current
            s['time']=time;s['running']=False;out=decorate(s);out['replay']=True;return out
    @app.post('/api/compare')
    def compare(command:Compare):
        with lock:s=tick()
        results=[]
        for id in command.policy_ids:
            p=plan(s,policy(id,research=True));v=verify(s,p);candidate=copy.deepcopy(s)
            if v['status']=='pass':
                for a in candidate['aircraft']:
                    slot=next(x for x in p['slots'] if x['aircraft_id']==a['id'])
                    if a['trajectory'][0]['t']>s['time']:a['scheduled']=slot['time'];a['runway']=slot['runway'];a['trajectory']=trajectory(a,slot['time'],slot['runway']);a.pop('admission_hold',None)
            results.append({'policy_id':id,'metrics':metrics(candidate,horizon=2700),'state':decorate(candidate,False),'verification':v,'plan':p,'projection_horizon':2700})
        return {'checkpoint_time':s['time'],'checkpoint_hash':snapshot_hash(s),'matched':True,'objective':OBJECTIVES,'scope':'Matched current checkpoint scheduling projection. Experiment worker performs separate fixed-seed closed-loop evaluation.','comparisons':results}
    @app.post('/api/learning/train',response_model=LearningJobView,response_model_exclude_unset=True)
    def train(command:Train):
        with lock:
            prior=previous_command(command,'train')
            if prior:return store.get('job-'+prior['id']) or prior
            if any(j['status'] in ('queued','running') for j in store.list('job')):
                raise HTTPException(409,'A bounded experiment is already running')
            memory=store.get('agent-accepted-parent')
            parent_record=store.get('policy-'+memory['policy_id']) if memory and memory.get('config_hash')==AGENT_CONFIG_HASH else None
            if parent_record and parent_record.get('accepted'):
                parent=Policy(**parent_record['program']);parent_id=parent_record['id'];ancestry=memory.get('ancestry',[])
            else:
                parent=STRONG_STATIC;parent_id='static-v2';ancestry=[]
            id=str(uuid.uuid4());limits=AgentLimits(revisions=command.revisions,**({'request_output_tokens':4096,'output_tokens':12000,'wall_seconds':180} if command.source=='crusoe' else {}))
            job={'id':id,'status':'queued','stage':'queued','generations':command.generations,'source':'crusoe-live' if command.source=='crusoe' else 'offline-fixture','created_at':time.time(),'parent_id':parent_id,'parent_program':parent.model_dump(),'ancestry':ancestry,'memory_mode':'persistent','provider_usage':{'calls':0,'input_tokens':0,'output_tokens':0,'cost_usd':0,'reserved_usd':0,'paid_retries':0},'limits':limits.model_dump(),'events':[],'grammar_version':GRAMMAR_VERSION,'prompt_version':PROMPT_VERSION,'evaluator_version':AGENT_EVALUATOR_VERSION,'config_hash':AGENT_CONFIG_HASH,'heldout_consumed':bool(store.list('heldout',1))}
            with store.transaction() as db:
                store.put('job-'+id,'job',job,db);record_command(command,'train',job,db)
            process=multiprocessing.get_context('spawn').Process(target=worker_entry,args=(database_address,id),name='uita-investigator-'+id[:8],daemon=True)
            workers[id]=process;process.start()
        def monitor():
            process.join(limits.wall_seconds+30)
            if process.is_alive():process.terminate();process.join(timeout=2)
            with lock:
                latest=store.get('job-'+id)
                if latest and latest['status'] not in TERMINAL:
                    append_event(store,id,'termination','Worker stopped; ambiguous inference is never reissued',{'stage':'interrupted'})
                    latest=store.get('job-'+id)
                    store.put('job-'+id,'job',{**latest,'status':'interrupted','stage':'interrupted','error':'Worker stopped before completion; retained evidence and spend reservations are available. Start a new bounded job.','finished_at':time.time()})
                workers.pop(id,None)
        threading.Thread(target=monitor,name='uita-investigator-monitor',daemon=True).start()
        return job

    @app.post('/api/learning/jobs/{id}/cancel',response_model=LearningJobView,response_model_exclude_unset=True)
    def cancel_job(id:str):
        with lock:
            job=store.get('job-'+id)
            if not job:raise HTTPException(404,'Experiment not found')
            if job['status'] in TERMINAL:return job
            process=workers.get(id)
            if process and process.is_alive():process.terminate();process.join(timeout=2)
            job=store.get('job-'+id)
            if job['status'] in TERMINAL:return job
            append_event(store,id,'termination','Cancelled; completed evidence and reservations retained',{'stage':'cancelled'})
            job=store.get('job-'+id)
            job={**job,'status':'cancelled','stage':'cancelled','finished_at':time.time()}
            store.put('job-'+id,'job',job)
            return job

    @app.get('/api/learning/jobs/{id}',response_model=LearningJobView,response_model_exclude_unset=True)
    def get_job(id:str):
        result=store.get('job-'+id)
        if not result:raise HTTPException(404,'Experiment not found')
        return result
    @app.get('/api/learning/policies/{id}')
    def get_policy(id:str):
        result=store.get('policy-'+id)
        if not result:raise HTTPException(404,'Policy not found')
        return result
    @app.post('/api/learning/policies/{id}/promote')
    def promote(id:str):
        with lock,store.transaction() as db:
            p=store.get('policy-'+id,db)
            if not p or not p.get('accepted'):raise HTTPException(409,'Only accepted, supported observation programs may be promoted')
            if p.get('status')!='builtin' and p.get('config_hash') not in (CONFIG_HASH,AGENT_CONFIG_HASH):raise HTTPException(409,'Policy evaluation is from another configuration; re-evaluate before promotion')
            Policy(**p['program'])
            s=load()
            if s['active_policy']==id:return decorate(s)
            s['previous_policy']=s['active_policy'];s['active_policy']=id;s['revision']+=1
            s['events'].append({'time':s['time'],'type':'policy','message':f'Observation policy {p["name"]} activated for future proposals'})
            save(s,True,db);return decorate(s)
    @app.post('/api/learning/rollback')
    def rollback():
        with lock:
            s=load();s['active_policy']=s.get('previous_policy','static');s['revision']+=1
            s['events'].append({'time':s['time'],'type':'policy','message':'Observation policy rolled back'});save(s,True);return decorate(s)
    @app.get('/api/export')
    def export():
        with lock:s=load()
        return {'schema_version':2,'research_only':True,'state':s,'rule_version':RULE_VERSION,'sources':SOURCES,'limitations':LIMITATIONS,'proposals':store.list('proposal',1000),'policies':store.list('policy',1000),'jobs':store.list('job',1000),'checkpoints':[c for c in store.list('checkpoint',5000) if c['session_id']==s['session_id']],'evaluation_config_hash':CONFIG_HASH,'provider':provider_status()}
    dist=Path(__file__).resolve().parents[2]/'frontend'/'dist'
    if dist.exists():app.mount('/',StaticFiles(directory=str(dist),html=True),name='frontend')
    return app

app=create_app()

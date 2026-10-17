"""Trusted closed-loop evaluator for a bounded observation-only policy grammar.

Candidates contain data, never executable code. Development/validation event tapes,
solver configuration, objective, observation budget and promotion criteria are fixed.
"""
import copy
import hashlib
import json
import random
import statistics
from .models import Policy
from .objectives import OBJECTIVE_CONFIG
from .planner import plan, BASELINE, STATIC
from .verifier import verify
from .simulator import new_state, metrics, advance, inject, trajectory, snapshot_hash

TRAIN_SEEDS=(101,103,107,109)
VALIDATION_SEEDS=(211,223,227,229)
HELDOUT_SEEDS=(307,311,313,317)
VARIANTS=('baseline','exit-congestion','departure-bank','transfer')
EVALUATOR_VERSION='closed-loop-matched-eval-3'
CRITERIA={'all_cases_pass':True,'validation_score_improvement_min':0.01,'maximum_tail_regression_fraction':0.05,'max_observations':8,'max_solver_seconds':2,'horizon':2700,'replan_interval_seconds':300,'all_flights_counted':True}
EVENT_TEMPLATE=[{'time':1000,'kind':'arrival_surge','severity':1}, {'time':1600,'kind':'gate_delay','severity':0.5,'aircraft_id':'last-initial-departure'}]
CONFIG_HASH=hashlib.sha256(json.dumps({'train':TRAIN_SEEDS,'validation':VALIDATION_SEEDS,'heldout':HELDOUT_SEEDS,'variants':VARIANTS,'criteria':CRITERIA,'events':EVENT_TEMPLATE,'objectives':OBJECTIVE_CONFIG},sort_keys=True).encode()).hexdigest()


def program_hash(policy):
    """Names are presentation metadata, not new executable artifacts."""
    body=policy.model_dump();body.pop('name',None)
    if body.get('grammar_version','observations-1')=='observations-1':
        for key in ('grammar_version','observation_scope','allocation'):body.pop(key,None)
    return hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()


def validate_candidate(policy):
    if policy.grammar_version=='observations-1' and (policy.observation_scope!='all' or policy.allocation!='tool-major'):
        raise ValueError('Legacy programs cannot use version 2 selectors')
    if len(policy.observations)!=len(set(policy.observations)):
        raise ValueError('Duplicate observation operations are forbidden')
    for field in ('order','reserve_seconds','lookahead','max_observations'):
        if getattr(policy,field)!=getattr(STATIC,field):
            raise ValueError(f'Candidate cannot change fixed evaluator field: {field}')
    return policy


def event_tape(state):
    tape=copy.deepcopy(EVENT_TEMPLATE)
    departures=[a for a in state['aircraft'] if a['operation']=='departure']
    tape[1]['aircraft_id']=departures[-1]['id']
    return tape


def evaluate(policy,seeds,variants=VARIANTS):
    raw=[]
    for seed in seeds:
        for scenario in variants:
            state=new_state(seed,scenario)
            initial_hash=snapshot_hash(state);tape=event_tape(state)
            event_hash=hashlib.sha256(json.dumps(tape,sort_keys=True).encode()).hexdigest()
            decisions=[];observations=[];failed=[];statuses=[];changes=0;shift_seconds=0;verified_times=[]
            for now in range(400,CRITERIA['horizon']+1,CRITERIA['replan_interval_seconds']):
                advance(state,now-state['time'])
                for event in tape:
                    if event['time']==now:inject(state,{k:v for k,v in event.items() if k!='time'})
                proposal=plan(state,policy);verification=verify(state,proposal)
                statuses.append(verification['status'])
                failed.extend(c['id'] for c in verification['checks'] if c['status']!='pass')
                observations.extend({'decision_time':now,**o} for o in proposal['observations'])
                if verification['status']=='pass':
                    verified_times.append(now)
                    by_id={s['aircraft_id']:s for s in proposal['slots']}
                    for aircraft in state['aircraft']:
                        slot=by_id[aircraft['id']]
                        if aircraft['trajectory'][0]['t']>now:
                            changes+=int(aircraft['scheduled']!=slot['time'] or aircraft['runway']!=slot['runway'])
                            shift_seconds+=abs(aircraft['scheduled']-slot['time'])
                            aircraft['scheduled']=slot['time'];aircraft['runway']=slot['runway']
                            aircraft['trajectory']=trajectory(aircraft,slot['time'],slot['runway'])
                    state['revision']+=1
                decisions.append({'time':now,'snapshot_hash':proposal['snapshot_hash'],'verification':verification['status'],'accepted':verification['status']=='pass','observation_count':len(proposal['observations']),'solver_seconds':proposal['solver']['wall_seconds'],'slots':proposal['slots']})
            advance(state,CRITERIA['horizon']-state['time'])
            # Only actually accepted schedules are present in state. Rejected
            # hypothetical plans never contribute their projected completions.
            state.update(plan_change_count=changes,planning_decisions=len(decisions),schedule_shift_seconds=shift_seconds,verified_replan_times=verified_times)
            m=metrics(state)
            case_status='fail' if 'fail' in statuses else 'unresolved' if 'unresolved' in statuses else 'pass'
            if case_status!='pass':m['score']+=100000
            completed_ids=[a['id'] for a in state['aircraft'] if not a.get('diverted') and not a.get('admission_hold') and a['trajectory'][-1]['t']<=state['time']]
            m['completed']=len(completed_ids);m['backlog']=len(state['aircraft'])-len(completed_ids)
            raw.append({'seed':seed,'scenario':scenario,'snapshot_hash':initial_hash,'event_tape':tape,'event_hash':event_hash,'verification':case_status,'failed_checks':sorted(set(failed)),'metrics':m,'observations':observations,'observation_count':max(d['observation_count'] for d in decisions),'total_observations':len(observations),'solver_seconds':sum(d['solver_seconds'] for d in decisions),'max_solver_seconds':max(d['solver_seconds'] for d in decisions),'decisions':decisions,'completed_aircraft_ids':completed_ids,'final_snapshot_hash':snapshot_hash(state),'final_time':state['time'],'rejected_plans':statuses.count('fail'),'unresolved_plans':statuses.count('unresolved')})
    scores=[r['metrics']['score'] for r in raw]
    return {'raw':raw,'cases':len(raw),'pass_count':sum(r['verification']=='pass' for r in raw),'fail_count':sum(r['verification']=='fail' for r in raw),'unresolved_count':sum(r['verification']=='unresolved' for r in raw),'mean_score':statistics.mean(scores),'score_stddev':statistics.pstdev(scores),'mean_delay':statistics.mean(r['metrics']['mean_delay'] for r in raw),'p95_delay':max(r['metrics']['p95_delay'] for r in raw),'mean_backlog':statistics.mean(r['metrics']['backlog'] for r in raw),'mean_observations':statistics.mean(r['total_observations'] for r in raw),'solver_seconds':sum(r['solver_seconds'] for r in raw),'rejected_plans':sum(r['rejected_plans'] for r in raw),'unresolved_plans':sum(r['unresolved_plans'] for r in raw),'execution_mode':'verified-commit-advance-replan'}


def fixture_candidates(generations,seed=73,parent=None):
    """Deterministic local parent mutations, with no hard-coded winning answer."""
    rng=random.Random(seed);tools=['exit_occupancy','gate_ready','wake','weather'];parent=parent or STATIC
    validate_candidate(parent);programs=[];seen=set()
    attempts=0
    while len(programs)<generations:
        attempts+=1
        ops=list(parent.observations);operation=rng.choice(['add','remove','reorder'])
        available=[t for t in tools if t not in ops]
        if operation=='add' and available:ops.insert(rng.randrange(len(ops)+1),rng.choice(available))
        elif operation=='remove' and ops:ops.pop(rng.randrange(len(ops)))
        else:rng.shuffle(ops)
        key=tuple(ops)
        if key in seen and attempts<64:continue
        seen.add(key);programs.append(ops)
    return [Policy(**{**parent.model_dump(),'name':f'Fixture observation mutation {i+1}','observations':ops}) for i,ops in enumerate(programs)]


def run_experiment(generations=3,candidates=None,parent_id='static',parent_program=None,iteration=0,consumed_artifacts=None,stateless_program=None,stateless_usage=None):
    if not 1<=generations<=8:raise ValueError('Experiment generation limit is 1–8')
    parent=validate_candidate(Policy(**parent_program)) if parent_program else STATIC
    candidates=candidates if candidates is not None else fixture_candidates(generations,seed=73+iteration,parent=parent)
    if not 1<=len(candidates)<=8:raise ValueError('Candidate count must be 1–8')
    candidates=[validate_candidate(p) for p in candidates]
    static_train=evaluate(STATIC,TRAIN_SEEDS);static_validation=evaluate(STATIC,VALIDATION_SEEDS)
    fcfs_validation=evaluate(BASELINE,VALIDATION_SEEDS)
    parent_validation=static_validation if program_hash(parent)==program_hash(STATIC) else evaluate(parent,VALIDATION_SEEDS)
    results=[]
    for index,policy in enumerate(candidates):
        train=evaluate(policy,TRAIN_SEEDS);validation=evaluate(policy,VALIDATION_SEEDS)
        improved=validation['mean_score']<=min(static_validation['mean_score'],parent_validation['mean_score'])*(1-CRITERIA['validation_score_improvement_min'])
        safe=all(result['pass_count']==result['cases'] for result in (validation,train))
        tail=validation['p95_delay']<=static_validation['p95_delay']*(1+CRITERIA['maximum_tail_regression_fraction'])
        bounded=all(r['observation_count']<=CRITERIA['max_observations'] and r['max_solver_seconds']<=CRITERIA['max_solver_seconds']+.1 for r in validation['raw']+train['raw'])
        accepted=improved and safe and tail and bounded;reasons=[]
        if not safe:reasons.append('Independent feasibility regression')
        if not improved:reasons.append('Validation score did not improve static and parent by 1%')
        if not tail:reasons.append('Tail delay regressed more than 5%')
        if not bounded:reasons.append('Observation or solver budget exceeded')
        artifact=program_hash(policy)
        # Execution hash is stable; registry ID additionally identifies lineage.
        version=hashlib.sha256(f'{parent_id}:{iteration}:{index}:{artifact}:{CONFIG_HASH}'.encode()).hexdigest()[:12]
        results.append({'id':f'policy-{version}','name':policy.name,'program':policy.model_dump(),'parent_id':parent_id,'generation':index+1,'artifact_hash':artifact,'evaluator_version':EVALUATOR_VERSION,'config_hash':CONFIG_HASH,'status':'accepted' if accepted else 'rejected','accepted':accepted,'reason':'; '.join(reasons) if reasons else 'Passed fixed validation promotion criteria','train':train,'validation':validation,'heldout':None,'criteria':CRITERIA,'source':'offline-fixture'})
    eligible=[r for r in results if r['accepted']]
    selected=min(eligible,key=lambda r:r['validation']['mean_score']) if eligible else None
    # The fixed final set is sealed after its first evaluation, for all artifacts.
    # Subsequent development may continue on dev/validation but cannot reuse it.
    heldout_available=not bool(consumed_artifacts)
    if selected and heldout_available:selected['heldout']=evaluate(Policy(**selected['program']),HELDOUT_SEEDS)
    stateless={'status':'not_run','reason':'No fresh independent live model proposal supplied. Fixture mutations are not a model baseline.'}
    if stateless_program is not None:
        one_shot=validate_candidate(Policy(**stateless_program))
        stateless={'status':'complete','source':'crusoe-live','memory':'fresh proposal without parent or registry policy; fixed for this evaluation only','program':one_shot.model_dump(),'validation':evaluate(one_shot,VALIDATION_SEEDS),'provider_usage':stateless_usage or {}}
    return {'candidates':results,'selected_policy_id':selected['id'] if selected else None,'baseline':fcfs_validation,'static':static_validation,'parent_validation':parent_validation,'static_train':static_train,'evaluator_version':EVALUATOR_VERSION,'config_hash':CONFIG_HASH,'criteria':CRITERIA,'heldout_consumed':bool(selected and selected['heldout']),'heldout_status':'evaluated-frozen-selection' if selected and selected['heldout'] else 'sealed-prior-use' if not heldout_available else 'not-consumed-no-promotion','heldout_policy_frozen_before_evaluation':True,'source':'offline-fixture','iteration':iteration,'parent_id':parent_id,'provider_usage':{'calls':0,'input_tokens':0,'output_tokens':0,'cost_usd':0},'stateless_model_baseline':stateless,'weakness':{'summary':'Observation allocation under exit congestion, departure demand and transfer traffic, with matched exogenous demand and gate-delay events. Only optional observation programs vary.','evidence':{'static_validation_mean_score':static_validation['mean_score'],'static_validation_failures':static_validation['fail_count']}}}


def run_live_experiment(generations=1,parent_id='static',parent_program=None,iteration=0,consumed_artifacts=None):
    """Trusted worker pipeline: observed development weakness -> two live proposals.

    One candidate proposal inherits the current parent. A separate, fresh baseline
    receives the same development evidence and tools/budget without parent memory.
    No validation/final results, hidden state, or secret values enter either prompt.
    """
    from .provider import propose_policy
    parent=validate_candidate(Policy(**parent_program)) if parent_program else STATIC
    development=evaluate(parent,TRAIN_SEEDS)
    worst=sorted(development['raw'],key=lambda row:row['metrics']['score'],reverse=True)[:3]
    evidence={'summary':'Allocate eight optional observation reads per decision across the fixed tools. Improve observed delay/backlog while all independent feasibility checks pass. Use only the supplied development evidence.',
              'development':{'mean_score':development['mean_score'],'pass_count':development['pass_count'],'cases':development['cases'],'repro_cases':[{'seed':row['seed'],'scenario':row['scenario'],'event_hash':row['event_hash'],'mean_delay':row['metrics']['mean_delay'],'backlog':row['metrics']['backlog'],'failed_checks':row['failed_checks'],'observations_used':row['total_observations']} for row in worst]}}
    candidate,usage=propose_policy({**evidence,'parent_program':parent.model_dump()})
    stateless,baseline_usage=propose_policy(evidence)
    result=run_experiment(1,[candidate],parent_id,parent.model_dump(),iteration,consumed_artifacts,stateless.model_dump(),baseline_usage)
    result['source']='crusoe-live';result['weakness']=evidence
    result['requested_generations']=generations;result['actual_fresh_candidates']=1
    result['inference_scope']='One parent-derived live candidate and one independent stateless baseline per bounded job; generations do not multiply paid calls.'
    result['provider_usage']={key:sum(item.get(key,0) for item in (usage,baseline_usage)) for key in ('calls','input_tokens','output_tokens','cost_usd','reserved_usd')}
    result['provider_usage'].update(provider=usage['provider'],model=usage['model'],prompt_version=usage['prompt_version'],requests=[usage,baseline_usage])
    for candidate_record in result['candidates']:candidate_record['source']='crusoe-live'
    return result

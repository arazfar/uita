"""Reproduce matched agent experiments; fixtures are never labeled live inference."""
import argparse
import asyncio
import hashlib
import json
import tempfile
import time
import uuid
from pathlib import Path
from uita.agent_contracts import AgentLimits,GRAMMAR_VERSION,PROMPT_VERSION
from uita.agent_jobs import execute_job,AGENT_CONFIG_HASH,AGENT_EVALUATOR_VERSION
from uita.investigator import STRONG_STATIC
from uita.learning import evaluate,VALIDATION_SEEDS
from uita.models import Policy
from uita.storage import Store

async def run(args):
    if args.replay:
        original_path=Path(args.replay);original=json.loads(original_path.read_text());rows=[]
        for job in original['jobs']:
            frozen=job.get('frozen')
            if not frozen:continue
            from uita.learning import program_hash
            policy=Policy(**frozen['program'])
            if program_hash(policy)!=frozen['artifact_hash']:raise ValueError('Replay frozen artifact hash mismatch')
            rows.append({'memory_mode':job['memory_mode'],'artifact_hash':frozen['artifact_hash'],'program':frozen['program'],'validation':evaluate(policy,VALIDATION_SEEDS),'original_status':job['status']})
        path=Path(args.output or 'docs/agent-upgrade/replay-evaluation.json');path.parent.mkdir(parents=True,exist_ok=True)
        report={'source':'offline-replay','fresh_inference_calls':0,'original_source':original['source'],'original_artifact_sha256':hashlib.sha256(original_path.read_bytes()).hexdigest(),'config_hash':AGENT_CONFIG_HASH,'evaluator_version':AGENT_EVALUATOR_VERSION,'candidates':rows}
        path.write_text(json.dumps(report,indent=2)+'\n')
        path.with_suffix('.md').write_text('# Frozen policy replay\n\nNo model calls. Re-evaluated frozen program hashes on the fixed validation suite; original job evidence is unchanged.\n\n'+str(len(rows))+' frozen programs replayed. Raw: ['+path.name+']('+path.name+').\n')
        print(path);return
    source='crusoe-live' if args.live else 'offline-fixture'
    with tempfile.TemporaryDirectory(prefix='uita-agent-eval-') as directory:
        store=Store('sqlite:///'+directory+'/evaluation.sqlite')
        jobs=[]
        for memory in ('stateless','persistent'):
            identifier=str(uuid.uuid4())
            limits=AgentLimits(revisions=args.revisions)
            job={'id':identifier,'status':'queued','stage':'queued','created_at':time.time(),'source':source,'memory_mode':memory,'parent_id':'static-v2','parent_program':STRONG_STATIC.model_dump(),'ancestry':[],'limits':limits.model_dump(),'events':[],'provider_usage':{'calls':0,'input_tokens':0,'output_tokens':0,'cost_usd':0,'reserved_usd':0},'heldout_consumed':True}
            store.put('job-'+identifier,'job',job)
            await execute_job(store,identifier)
            jobs.append(store.get('job-'+identifier))
        historical_path=Path('docs/research/live-experiment-2026-10-17.json')
        historical=json.loads(historical_path.read_text())
        previous=historical['result']['candidates'][0]
        previous_eval=evaluate(Policy(**previous['program']),VALIDATION_SEEDS)
        successful=next((j['result'] for j in jobs if j.get('result')),None)
        if successful:
            comparators={'fcfs':successful['baseline'],'strong_static':successful['static']}
        else:
            from uita.planner import BASELINE
            comparators={'fcfs':evaluate(BASELINE,VALIDATION_SEEDS),'strong_static':evaluate(STRONG_STATIC,VALIDATION_SEEDS)}
        report={'source':source,'fresh_live':bool(args.live),'created_at':time.time(),'evaluator_version':AGENT_EVALUATOR_VERSION,'config_hash':AGENT_CONFIG_HASH,'grammar_version':GRAMMAR_VERSION,'prompt_version':PROMPT_VERSION,'limits_per_arm':AgentLimits(revisions=args.revisions).model_dump(),'protocol':'Both arms use identical model settings/tools/development feedback budgets; persistent arm additionally receives accepted parent. This initial experiment has no learned accepted ancestor. Candidate selected on development, frozen, then independently validated. No held-out exposure.','comparators':{**comparators,'previous_single_proposal_migration_reference':{'source':'replayed-historical-live-program','original_artifact_sha256':hashlib.sha256(historical_path.read_bytes()).hexdigest(),'fresh_inference_calls':0,'program':previous['program'],'validation':previous_eval}},'jobs':jobs,'limitations':['Synthetic fixed suites only; no operational claims.','Fixtures exercise orchestration and are not evidence of model learning.','Single matched run does not establish statistical improvement.','Previous single proposal is a migration reference, not a matched current agent call.','Held-out benchmark remains sealed; original artifacts were not rewritten.']}
        path=Path(args.output or ('docs/agent-upgrade/live-evaluation.json' if args.live else 'docs/agent-upgrade/fixture-evaluation.json'));path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,indent=2)+'\n')
        lines=['# Matched investigator evaluation','',f'Source: **{source}**. Config `{AGENT_CONFIG_HASH}`.','',report['protocol'],'','| Arm | Validation score ↓ | Tail delay | Backlog | Passes | Outcome |','|---|---:|---:|---:|---:|---|']
        for name,r in [('FCFS',comparators['fcfs']),('Strong static v2',comparators['strong_static']),('Previous single-proposal migration reference (replayed)',previous_eval)]:
            lines.append(f"| {name} | {r['mean_score']:.6f} | {r['p95_delay']:.1f} | {r['mean_backlog']:.3f} | {r['pass_count']}/{r['cases']} | Comparator |")
        outcomes=[]
        for job in jobs:
            candidate=job.get('result',{}).get('candidates',[None])[0]
            if candidate:
                r=candidate['validation'];lines.append(f"| {job['memory_mode']} agent | {r['mean_score']:.6f} | {r['p95_delay']:.1f} | {r['mean_backlog']:.3f} | {r['pass_count']}/{r['cases']} | {candidate['status']} |")
                outcomes.append(f"{job['memory_mode']}: {candidate['reason']}")
            else:outcomes.append(f"{job['memory_mode']}: {job['status']}; {job.get('error','')}")
        lines+=['',*outcomes,'','| Agent | Calls | Tools / dev evals | Input / output tokens | Verified cost | Reserved cost | Elapsed |','|---|---:|---:|---:|---:|---:|---:|']
        for job in jobs:
            usage=job['provider_usage'];resources=job.get('result',{}).get('resources',{});elapsed=job.get('result',{}).get('elapsed_seconds',job.get('finished_at',job.get('created_at',0))-job.get('started_at',job.get('created_at',0)))
            if not resources:resources={'tools':max((e['data'].get('tools_used',0) for e in job['events']),default=0),'evaluations':max((e['data'].get('evaluation',e['data'].get('evaluations_used',0)) for e in job['events']),default=0)}
            cost=f"${usage.get('cost_usd',0):.8f}" if usage.get('cost_estimate_known',True) else f"Unknown; ${usage.get('cost_usd',0):.8f} verified"
            lines.append(f"| {job['memory_mode']} | {usage.get('calls',0)} | {resources.get('tools',0)} / {resources.get('evaluations',0)} | {usage.get('input_tokens',0)} / {usage.get('output_tokens',0)} | {cost} | ${usage.get('reserved_usd',0):.8f} | {elapsed:.2f}s |")
        if any(j['provider_usage'].get('ambiguous_requests',0) for j in jobs):lines+=['','Final billing is unknown for unresolved requests; all conservative reservations remain retained.']
        lines+=['',f'Raw per-case episodes, event tapes, rejected candidates, revisions, timings, tokens, costs and ordered tool provenance: [{path.name}]({path.name}).','',*report['limitations'],'','Reproduce: `PYTHONPATH=backend .venv-agent/bin/python scripts/evaluate_agent.py` (append `--live` only with the existing approved Crusoe budget configuration).']
        path.with_suffix('.md').write_text('\n'.join(lines)+'\n')
        print(path);print(path.with_suffix('.md'))
        print(json.dumps([{'memory':j['memory_mode'],'status':j['status'],'usage':j['provider_usage']} for j in jobs]))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--revisions',type=int,default=1);parser.add_argument('--output');parser.add_argument('--replay',help='Re-evaluate saved frozen programs without any model calls');args=parser.parse_args()
    asyncio.run(run(args))

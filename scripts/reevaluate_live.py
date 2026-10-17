"""Re-evaluate saved immutable live programs; never invokes an inference provider."""
import argparse
import hashlib
import json
from pathlib import Path
from uita.learning import run_experiment,program_hash
from uita.models import Policy
from uita.objectives import OBJECTIVE_CONFIG


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('artifact',help='Saved completed live experiment JSON')
    parser.add_argument('--output',default='docs/evaluation/live-program-reevaluation.json')
    args=parser.parse_args()
    source=Path(args.artifact);original=json.loads(source.read_text());old=original['result']
    if original['status']!='complete':raise ValueError('Original generation experiment must be complete')
    if original['parent_id']!='static':raise ValueError('This reproducible artifact requires a saved static-parent lineage')
    candidates=[Policy(**record['program']) for record in old['candidates']]
    baseline=old['stateless_model_baseline']['program']
    consumed=['original-final-set-consumed'] if old.get('heldout_consumed') else []
    result=run_experiment(len(candidates),candidates,original['parent_id'],None,original['iteration'],consumed,baseline,{'calls':0,'input_tokens':0,'output_tokens':0,'cost_usd':0})
    result['source']='saved-live-program-reevaluation'
    result['stateless_model_baseline']['source']='saved-live-program-reevaluation'
    for record in result['candidates']:record['source']='saved-live-program-reevaluation'
    output={'source':'saved-live-program-reevaluation','fresh_inference_calls':0,'fresh_inference_cost_usd':0,'original_generation':{'artifact_path':str(source),'artifact_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'job_id':original['id'],'created_at':original['created_at'],'finished_at':original['finished_at'],'source':original['source'],'provider_usage':original['provider_usage'],'evaluator_version':old['evaluator_version'],'config_hash':old['config_hash'],'candidate_program_hashes':[program_hash(policy) for policy in candidates],'stateless_program_hash':program_hash(Policy(**baseline))},'objective_config':OBJECTIVE_CONFIG,'result':result}
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(output,indent=2)+'\n')
    usage=original['provider_usage'];model=usage.get('candidate',usage).get('model','recorded in raw artifact')
    report=['# Saved live-program reevaluation','',f'Original generation job: `{original["id"]}`. Provider/model: Crusoe / `{model}`. Its **{usage["calls"]} original calls**, {usage["input_tokens"]} input tokens and {usage["output_tokens"]} output tokens cost **${usage["cost_usd"]:.8f}**. These charges are historical; this reevaluation made **zero inference calls and incurred $0 fresh inference cost**.','',f'The original artifact is preserved unchanged. Its SHA-256 is `{output["original_generation"]["artifact_sha256"]}`. Candidate and stateless program hashes and original request metadata are retained in the raw reevaluation artifact.','',f'Final evaluator: `{result["evaluator_version"]}`. Objective version: `{OBJECTIVE_CONFIG["version"]}`. Configuration hash: `{result["config_hash"]}`.','', 'All policies execute the same fixed development/validation seeds and event tapes, eight optional reads per decision, solver limits and normalized objectives. The fresh stateless model program was generated without an accepted parent and is reused only for this comparison; it is not a fresh LLM call at every decision.','', '| Policy | Validation score ↓ | Score stddev | Mean delay (s) | Mean backlog | Passing cases | Outcome |','|---|---:|---:|---:|---:|---:|---|']
    rows=[('FCFS',result['baseline'],'Comparator'),('Strong static',result['static'],'Comparator'),('Saved stateless model',result['stateless_model_baseline']['validation'],'Comparator')]
    rows += [(record['name'],record['validation'],record['status']) for record in result['candidates']]
    for name,row,outcome in rows:report.append(f'| {name} | {row["mean_score"]:.4f} | {row["score_stddev"]:.4f} | {row["mean_delay"]:.1f} | {row["mean_backlog"]:.2f} | {row["pass_count"]}/{row["cases"]} | {outcome} |')
    report += ['',f'Final held-out status: **{result["heldout_status"]}**. Candidate outcomes are recomputed against the final fixed criteria, and no registry activation occurs in this script.','', 'Score is the fixed normalized combination of delay, backlog, phase/wake-specific delay-equivalent fuel, relative day/night noise, synthetic-group service, starvation, instability and verified-replan recovery. Environmental values are proxies; admission/gate scheduling delay is not reported as actual airborne/taxi holding. Recovery refers to obtaining a passing replan, not restoring airport capacity.','',f'Every raw seed/variant, event tape, decision, metric component, solver cost, rejection and unfinished-flight count is in [{path.name}]({path.name}).','',f'Reproduce: `PYTHONPATH=backend .venv/bin/python scripts/reevaluate_live.py {source} --output {path}`']
    path.with_suffix('.md').write_text('\n'.join(report)+'\n')
    print(path);print(path.with_suffix('.md'))


if __name__=='__main__':main()

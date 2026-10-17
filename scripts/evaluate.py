"""Reproduce the credential-free experiment and write every raw evaluation case."""
import argparse, json
from pathlib import Path
from uita.learning import run_experiment

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--generations',type=int,default=3);parser.add_argument('--output',default='docs/evaluation/fixture-result.json');args=parser.parse_args()
    result=run_experiment(args.generations)
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(result,indent=2)+'\n')
    report=['# Reproducible fixture evaluation','',f'Evaluator: `{result["evaluator_version"]}`. Config hash: `{result["config_hash"]}`.','', 'Actual closed-loop results; no fresh model inference. Eight optional observations per decision. Candidates use the same fixed ordering, margin, objective, events and cases.','', '| Policy | Validation score ↓ | Mean delay (s) | Mean backlog | Passing cases | Outcome |','|---|---:|---:|---:|---:|---|']
    for name,key in [('FCFS','baseline'),('Strong static','static')]:
        r=result[key];report.append(f'| {name} | {r["mean_score"]:.4f} | {r["mean_delay"]:.1f} | {r["mean_backlog"]:.2f} | {r["pass_count"]}/{r["cases"]} | Comparator |')
    for c in result['candidates']:
        r=c['validation'];report.append(f'| {c["name"]} | {r["mean_score"]:.4f} | {r["mean_delay"]:.1f} | {r["mean_backlog"]:.2f} | {r["pass_count"]}/{r["cases"]} | {c["status"]} |')
    report+=['',f'Final held-out set: **{result["heldout_status"]}**. Selection is frozen before final evaluation. Rejected results remain in the raw artifact.','',f'Raw per-seed event tapes, observations, decisions, solver timing and accepted slots: [{path.name}]({path.name}).','', 'Score is a fixed normalized weighted sum of mean/tail delay, incomplete traffic, fuel and relative noise proxies, group service, starvation, plan stability and verified-replan recovery. Its versioned weights and normalizers are retained in every metrics record. A failed episode receives a 100,000-point feasibility penalty before quality comparison. Unfinished traffic stays in the denominator. Fuel/emissions/noise numbers are unvalidated proxies. These results describe the synthetic model, not real SFO operations.','', 'Reproduce: `PYTHONPATH=backend .venv/bin/python scripts/evaluate.py`']
    path.with_suffix('.md').write_text('\n'.join(report)+'\n');print(path);print(path.with_suffix('.md'))
if __name__=='__main__':main()

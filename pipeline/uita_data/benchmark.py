"""Summarize complete paired simulator runs. The simulator's fixed checker owns events."""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
from .common import ROOT, read_json, write_json

METRICS=['completed','backlog','separation_violations','runway_violations','checker_rejections',
         'delay_seconds_sum','holding_seconds_sum','decision_latency_p95_ms','cost_usd']


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('runs',type=Path,help='JSONL; one complete episode/seed/variant/controller result per line')
    parser.add_argument('--split',choices=['train','validation','test'],default='validation')
    parser.add_argument('--variants',nargs='+',choices=['nominal','synthetic_delayed_readback','synthetic_runway_unavailable'],default=['nominal','synthetic_delayed_readback','synthetic_runway_unavailable'])
    parser.add_argument('--controllers',nargs='+',default=['scripted','initial','improved'])
    parser.add_argument('--output',type=Path,default=ROOT/'pipeline/build/benchmark-results.json')
    args=parser.parse_args()
    episodes={e['id']:e for e in read_json(ROOT/'pipeline/build/episodes.json') if e['split']==args.split}
    expected={(e['id'],s,v) for e in episodes.values() for s in e['seeds'] for v in e['disturbance_variants'] if v in args.variants}
    runs={controller:{} for controller in args.controllers}
    checker_versions=set();simulator_versions=set()
    for line in args.runs.read_text().splitlines():
        if not line.strip():continue
        row=json.loads(line)
        if row['controller'] not in runs:continue
        key=(row['episode_id'],row['seed'],row['variant'])
        if key not in expected:raise ValueError('Run not in frozen split/seed/variant manifest')
        if key in runs[row['controller']]:raise ValueError('Duplicate paired run')
        if row.get('finished') is not True:raise ValueError('Run did not reach drain_end')
        if not row.get('checker_version') or not row.get('simulator_version'):raise ValueError('Version provenance required')
        checker_versions.add(row['checker_version']);simulator_versions.add(row['simulator_version'])
        for metric in METRICS:
            if not isinstance(row.get(metric),(float,int)) or not math.isfinite(row[metric]) or row[metric]<0:
                raise ValueError(f'Invalid metric: {metric}')
        for metric in ['completed','backlog','separation_violations','runway_violations','checker_rejections']:
            if int(row[metric])!=row[metric]:raise ValueError(f'Count must be integer: {metric}')
        if row['completed']+row['backlog']!=episodes[row['episode_id']]['spawn_count']:
            raise ValueError('Completion/backlog does not account for every scheduled spawn')
        runs[row['controller']][key]=row
    if len(checker_versions)!=1 or len(simulator_versions)!=1:raise ValueError('All candidates must use the same checker and simulator')
    for controller,rows in runs.items():
        if set(rows)!=expected:raise ValueError(f'Incomplete matrix for {controller}: {len(rows)}/{len(expected)}')
    results={}
    for controller,rows in runs.items():
        totals={m:sum(r[m] for r in rows.values()) for m in METRICS if m!='decision_latency_p95_ms'}
        totals['worst_run_decision_latency_p95_ms']=max(r['decision_latency_p95_ms'] for r in rows.values())
        totals['scheduled']=totals['completed']+totals['backlog']
        totals['safe_runs']=sum(r['separation_violations']==r['runway_violations']==0 for r in rows.values())
        totals['safety_pass_rate']=totals['safe_runs']/len(rows)
        totals['rank_tuple']=[totals['separation_violations']+totals['runway_violations'],totals['backlog'],
            (totals['delay_seconds_sum']+3600*totals['backlog'])/max(1,totals['scheduled'])]
        results[controller]=totals
    # Pair each episode first. Seeds and perturbations are correlated repeats, not new historical days.
    paired={}
    baseline=args.controllers[0]
    for controller in args.controllers[1:]:
        by_episode=defaultdict(list)
        for key,row in runs[controller].items():
            ref=runs[baseline][key]
            by_episode[key[0]].append({'completed_delta':row['completed']-ref['completed'],
                'violations_delta':row['separation_violations']+row['runway_violations']-ref['separation_violations']-ref['runway_violations'],
                'delay_seconds_delta':row['delay_seconds_sum']-ref['delay_seconds_sum']})
        paired[controller]={episode:{m:sum(r[m] for r in rows)/len(rows) for m in rows[0]} for episode,rows in by_episode.items()}
    report={'split':args.split,'runs_per_controller':len(expected),'independent_historical_windows':len(episodes),
            'controllers':results,'paired_vs':baseline,'episode_mean_deltas':paired,
            'ranking':'lexicographic: safety violations, unfinished aircraft, delay plus 3600 seconds per unfinished aircraft',
            'limits':'Simulator-only comparison. Historical traffic does not supply genuine human command labels. Twelve test windows cover only two days.'}
    write_json(args.output,report)
    print({k:v['rank_tuple'] for k,v in results.items()})

if __name__=='__main__':main()

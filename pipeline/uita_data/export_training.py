"""Export reviewed simulator decisions to Crusoe JSONL; never train on benchmark test days."""
import argparse
import hashlib
import json
from pathlib import Path
from .common import ROOT, read_json, write_json

FORBIDDEN={'arrival_operation_time_utc','operation_time','touchdown_time','future_positions','future_actions',
           'historical_runway','reference_action','template_flight_id','recorded_arrival_time','future_spawn_queue'}


def causal(value,clock):
    if isinstance(value,dict):
        if FORBIDDEN & value.keys():raise ValueError('Future outcome or reference fields in controller state')
        for key in ['observed_at','available_at','timestamp','spawn_time','t']:
            if isinstance(value.get(key),(int,float)) and value[key]>clock:
                raise ValueError(f'Future timestamp in state: {key}')
        for item in value.values():causal(item,clock)
    elif isinstance(value,list):
        for item in value:causal(item,clock)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('decisions',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'pipeline/build/training')
    parser.add_argument('--checker-version',required=True)
    args=parser.parse_args()
    episodes={e['id']:e for e in read_json(ROOT/'pipeline/build/episodes.json')}
    rows={'train':[],'validation':[]}; lineage=[];seen=set()
    for line in args.decisions.read_text().splitlines():
        if not line.strip():continue
        row=json.loads(line)
        episode=episodes.get(row.get('episode_id'))
        if not episode or episode['split']=='test':raise ValueError('Unknown or held-out episode; refusing training export')
        if row.get('checker_passed') is not True or row.get('reviewer_approved') is not True:
            raise ValueError('Every target must pass the fixed checker and a reviewer')
        if row.get('checker_version')!=args.checker_version:raise ValueError('Checker version mismatch')
        if row.get('target_provenance') not in ['reviewed_teacher','human_simulator_session']:
            raise ValueError('Target must identify teacher or human simulator provenance')
        clock=row['clock']
        if not episode['warmup_start']<=clock<episode['drain_end']:raise ValueError('Decision outside episode')
        causal(row['state'],clock)
        if not isinstance(row['action'],dict):raise ValueError('Action must be a structured JSON object')
        state=json.dumps(row['state'],sort_keys=True,separators=(',',':'),allow_nan=False)
        fingerprint=hashlib.sha256(state.encode()).hexdigest()
        if fingerprint in seen:raise ValueError('Duplicate state; group repeated/perturbed encounters before splitting')
        seen.add(fingerprint)
        rows[episode['split']].append({'messages':[
            {'role':'system','content':'Control the supplied simulated arrival traffic. Return one valid structured action under the simulator command contract.'},
            {'role':'user','content':state},
            {'role':'assistant','content':json.dumps(row['action'],sort_keys=True,separators=(',',':'),allow_nan=False)}]})
        lineage.append({'episode_id':row['episode_id'],'clock':clock,'split':episode['split'],'state_sha256':fingerprint,
                        'target_provenance':row['target_provenance'],'checker_version':args.checker_version})
    if not rows['train'] or not rows['validation']:raise ValueError('Provide both training-day and validation-day reviewed examples')
    args.output.mkdir(parents=True,exist_ok=True)
    for split,items in rows.items():
        (args.output/f'{split}.jsonl').write_text(''.join(json.dumps(r,separators=(',',':'))+'\n' for r in items))
    write_json(args.output/'lineage.json',{'source_sha256':hashlib.sha256(args.decisions.read_bytes()).hexdigest(),
               'counts':{k:len(v) for k,v in rows.items()},'decisions':lineage,
               'status':'prepared; no Crusoe upload or paid training submitted'})
    print({k:len(v) for k,v in rows.items()})

if __name__=='__main__':main()

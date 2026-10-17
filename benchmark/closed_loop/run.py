"""Run matched frozen historical-demand episodes without exposing final test days."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import statistics
from pathlib import Path
import shutil
import time

from .engine import CONFIG, percentile, simulate
from .traffic import DATA_DIR, load_episodes

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ['benchmark/closed_loop/traffic.py', 'benchmark/closed_loop/controllers.py',
           'benchmark/closed_loop/engine.py', 'benchmark/closed_loop/ai.py', 'benchmark/closed_loop/run.py',
           'backend/uita/airport.py', 'backend/uita/simulator.py', 'backend/uita/verifier.py', 'backend/uita/objectives.py',
           'benchmark/provider.py']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def aggregate(rows):
    flights = [f for row in rows for f in row['flights']]
    delays = [f['added_delay_seconds'] for f in flights]
    complete_delays = [f['added_delay_seconds'] for f in flights if f['completed']]
    total = len(flights)
    completed = sum(row['completed'] for row in rows)
    violations = sum(row['executed_violations'] for row in rows)
    unresolved = sum(row['unresolved_decisions'] for row in rows)
    return {'episodes': len(rows), 'spawned': total, 'landed': sum(row['landed'] for row in rows),
            'completed': completed, 'backlog': total - completed,
            'nominal_due_arrivals': sum(f['nominal_due_before_horizon'] for f in flights),
            'not_nominally_due_arrivals': sum(not f['nominal_due_before_horizon'] for f in flights),
            'executed_violations': violations, 'safe_episodes': sum(row['executed_violations'] == 0 for row in rows),
            'executed_safety_counts': {key: sum(row['safety'][key] for row in rows)
                                       for key in ['separation_violation_episodes', 'runway_violation_episodes', 'surface_violation_episodes', 'wake_violations', 'performance_violations']},
            'minimum_lateral_nm_when_vertical_under_1000_ft': min((row['safety']['minimum_lateral_nm_when_vertical_under_1000_ft'] for row in rows if row['safety']['minimum_lateral_nm_when_vertical_under_1000_ft'] is not None), default=None),
            'safety_eligible': violations == 0 and unresolved == 0,
            'added_delay_seconds_sum': round(sum(delays), 3),
            'mean_added_delay_seconds_all_demand': statistics.mean(delays) if delays else 0,
            'p95_added_delay_seconds_all_demand': percentile(delays, .95),
            'mean_added_delay_seconds_completed_only': statistics.mean(complete_delays) if complete_delays else None,
            'penalized_added_delay_seconds': round(sum(delays) + CONFIG['unfinished_penalty_seconds'] * (total - completed), 3),
            'controller_failures': sum(row['controller_failures'] for row in rows),
            'fallback_decisions': sum(row['fallback_decisions'] for row in rows),
            'rejected_proposals': sum(row['rejected_proposals'] for row in rows),
            'unresolved_decisions': unresolved, 'decisions': sum(row['decision_count'] for row in rows),
            'solver_status_counts': dict(__import__('collections').Counter(d['solver']['status'] for row in rows for d in row['decisions'] if d['solver'])),
            'source_strata': {stratum: {'spawned': sum(f['position_provenance'] == stratum for f in flights),
                                      'completed': sum(f['completed'] and f['position_provenance'] == stratum for f in flights),
                                      'mean_added_delay_seconds_all_demand': statistics.mean(f['added_delay_seconds'] for f in flights if f['position_provenance'] == stratum)}
                              for stratum in sorted({f['position_provenance'] for f in flights})}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--split', choices=['train', 'validation'], default='validation')
    parser.add_argument('--controllers', nargs='+', choices=['scripted', 'deterministic', 'ai'], default=['scripted', 'deterministic', 'ai'])
    parser.add_argument('--episode', help='Single development episode for runtime QA; partial validation is forbidden')
    parser.add_argument('--execute', action='store_true', help='Run simulation; includes paid inference if ai is selected')
    parser.add_argument('--cap-usd', type=float, default=1.)
    args = parser.parse_args()
    if args.episode and args.split != 'train':
        parser.error('Validation must use all six frozen episodes')
    if len(set(args.controllers)) != len(args.controllers) or not 0 < args.cap_usd <= 1:
        parser.error('Controllers must be unique; the inference cap must be positive and at most $1')
    episodes = load_episodes(args.split)
    if args.episode:
        episodes = [e for e in episodes if e['id'] == args.episode]
        if not episodes:
            parser.error('Unknown development episode')
    source_hashes = {name: sha(ROOT/name) for name in SOURCES}
    plan = {'version': CONFIG['version'], 'split': args.split, 'episodes': [e['id'] for e in episodes],
            'controllers': args.controllers, 'config': CONFIG, 'source_hashes': source_hashes,
            'traffic_sha256': sha(DATA_DIR/(args.split+'.json')), 'traffic_manifest_sha256': sha(DATA_DIR/'manifest.json'),
            'inference_cap_usd': args.cap_usd, 'model': 'nvidia/NVIDIA-Nemotron-3.5-Super-VL' if 'ai' in args.controllers else None,
            'final_test': 'August 8–9 excluded from traffic loader, runner and model calls',
            'runtime': {'python': platform.python_version(), 'ortools': importlib.metadata.version('ortools')}}
    args.out.mkdir(parents=True, exist_ok=True)
    if (args.out/'summary.json').exists():
        raise ValueError('Completed runs are immutable; choose a new output directory')
    if (args.out/'plan.json').exists() and json.loads((args.out/'plan.json').read_text()) != plan:
        raise ValueError('Existing run plan differs from current frozen configuration')
    write(args.out/'plan.json', plan)
    if not args.execute:
        print(json.dumps({'status': 'plan_only', 'episodes': len(episodes), 'controllers': args.controllers,
                          'source_spawns': sum(len(e['entries']) for e in episodes), 'paid_calls': 0}))
        return
    for name in SOURCES:
        target = args.out/'frozen_source'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and sha(target) != source_hashes[name]:
            raise ValueError('Frozen source differs from this run')
        shutil.copyfile(ROOT/name, target)
    ai = None
    if 'ai' in args.controllers:
        from .ai import AIController
        ai = AIController(args.out, cap_usd=args.cap_usd)
    started = time.time()
    rows = []
    def emit(item):
        print(json.dumps(item), flush=True)
    for controller in args.controllers:
        for episode in episodes:
            row = simulate(episode, controller, ai=ai, emit=emit)
            row['controller'] = controller
            rows.append(row)
            write(args.out/'episodes'/f"{episode['id']}-{controller}.json", row)
            emit({'finished_episode': episode['id'], 'controller': controller, 'completed': row['completed'],
                  'backlog': row['backlog'], 'violations': row['executed_violations']})
    for name, expected in source_hashes.items():
        if sha(ROOT/name) != expected:
            raise ValueError('Evaluator source changed during the run: '+name)
    reference = {row['episode_id']: row for row in rows if row['controller'] == args.controllers[0]}
    paired = {}
    for controller in args.controllers[1:]:
        paired[controller] = []
        for row in [r for r in rows if r['controller'] == controller]:
            base = reference[row['episode_id']]
            if {f['source_flight_id'] for f in row['flights']} != {f['source_flight_id'] for f in base['flights']}:
                raise ValueError('Controllers received different historical traffic')
            paired[controller].append({'episode_id': row['episode_id'], 'completed_delta': row['completed']-base['completed'],
                                       'backlog_delta': row['backlog']-base['backlog'],
                                       'added_delay_seconds_delta': round(row['added_delay_seconds_sum']-base['added_delay_seconds_sum'], 3),
                                       'executed_violations_delta': row['executed_violations']-base['executed_violations']})
    totals = {controller: aggregate([r for r in rows if r['controller'] == controller]) for controller in args.controllers}
    write(args.out/'runs.json', rows)
    summary = {'status': 'completed', 'plan_sha256': sha(args.out/'plan.json'), 'split': args.split,
               'controllers': totals, 'paired_reference': args.controllers[0], 'paired': paired,
               'elapsed_wall_seconds': time.time()-started, 'ai_usage': ai.summary() if ai is not None else {'calls': 0},
               'source_hashes': source_hashes,
               'artifacts': {name: sha(args.out/name) for name in ['plan.json', 'runs.json']},
               'limits': ['Historical-demand admission scheduling with reconstructed feeder and fixed final approaches.',
                          'Only modeled final approach, shared runway and taxi resources are safety-checked; feeder travel and upstream waiting are outside the controlled domain.',
                          'Added delay is modeled admission waiting, not measured historical airline delay or airborne holding.',
                          'Unfinished delay is right-censored at the fixed drain end; backlog and a fixed penalty are reported.',
                          'Synthetic occupancy is announced equally to all controllers; no measured runway-exit ground truth exists.',
                          'Simulation time pauses for controller computation; API latency and failures are reported separately rather than added to flight time.',
                          'One nominal variant and one seed per episode; six validation windows span only one historical day.',
                          'No human controller comparison or operational safety certification.',
                          'August 8–9 remain held out.']}
    write(args.out/'summary.json', summary)
    lines = ['# Historical-demand closed-loop comparison', '',
             f"{len(episodes)} {args.split} windows, seed 17, nominal conditions. August 8–9 stay held out.", '',
             '| Controller | Completed / demand | Backlog | Executed violations | Mean accrued added delay, all demand | P95 accrued delay | AI/controller failures | Checked fallback decisions |',
             '|---|---:|---:|---:|---:|---:|---:|---:|']
    for name, row in totals.items():
        lines.append(f"| {name} | {row['completed']}/{row['spawned']} | {row['backlog']} | {row['executed_violations']} | {row['mean_added_delay_seconds_all_demand']:.1f}s | {row['p95_added_delay_seconds_all_demand']:.1f}s | {row['controller_failures']} | {row['fallback_decisions']} |")
    lines += ['', 'Lower delay is interpreted alongside backlog. Unfinished values are censored at the common horizon. AI outcomes include explicitly counted checked fallbacks.', '',
              '## Scope and limits', '', *['- '+text for text in summary['limits']], '',
              'Raw per-episode decisions, verified commitments, executed safety findings and all-flight outcomes are in runs.json. Plan and source hashes freeze the protocol.']
    (args.out/'comparison.md').write_text('\n'.join(lines)+'\n')
    emit({'status': 'completed', 'controllers': totals, 'ai_usage': summary['ai_usage']})


if __name__ == '__main__':
    main()

"""Development-only exhaustive v2 capacity census; never runs model inference."""
import hashlib
import itertools
import json
import argparse
from pathlib import Path
import time

from uita import learning
from uita.planner import STATIC


def main(destination=None):
    root = Path(__file__).resolve().parents[2]
    destination = destination or root/'docs/agent-upgrade/v2-capacity-audit.json'
    if destination.exists():
        raise SystemExit('Preserve existing evidence; pass --output with a new filename')
    sources = {name: hashlib.sha256((root/'backend/uita'/name).read_bytes()).hexdigest() for name in ('models.py', 'planner.py', 'learning.py')}
    started = time.monotonic()
    programs = []
    for scope, allocation in itertools.product(('all', 'pending', 'pending-first'), ('tool-major', 'aircraft-major')):
        for size in range(5):
            for operations in itertools.permutations(('exit_occupancy', 'gate_ready', 'wake', 'weather'), size):
                policy = STATIC.model_copy(update={'name': 'Independent v2 audit', 'grammar_version': 'observations-2', 'observation_scope': scope, 'allocation': allocation, 'observations': list(operations)})
                learning.validate_candidate(policy)
                result = learning.evaluate(policy, learning.TRAIN_SEEDS)
                cases = [{key: row[key] for key in ('seed', 'scenario', 'snapshot_hash', 'event_hash', 'verification', 'failed_checks', 'metrics', 'observation_count', 'total_observations', 'max_solver_seconds', 'solver_seconds', 'rejected_plans', 'unresolved_plans', 'final_snapshot_hash')} for row in result['raw']]
                behavior_hash = hashlib.sha256(json.dumps([[{'slots': decision['slots'], 'verification': decision['verification']} for decision in row['decisions']] for row in result['raw']], sort_keys=True).encode()).hexdigest()
                programs.append({'program': policy.model_dump(), 'artifact_hash': learning.program_hash(policy), 'behavior_hash': behavior_hash, 'summary': {key: value for key, value in result.items() if key != 'raw'}, 'cases': cases})
        print(f'Finished {scope}/{allocation}: {len(programs)} programs', flush=True)
    static = next(row for row in programs if row['program']['observation_scope'] == 'pending-first' and row['program']['allocation'] == 'tool-major' and row['program']['observations'] == ['exit_occupancy', 'gate_ready'])
    feasible = [row for row in programs if row['summary']['pass_count'] == row['summary']['cases']]
    best = min(feasible, key=lambda row: row['summary']['mean_score'])
    report = {'schema': 'v2-capacity-audit-1', 'scope': 'development only; no validation or heldout access; no inference', 'source_sha256': sources, 'config_hash': learning.CONFIG_HASH, 'evaluator_version': learning.EVALUATOR_VERSION, 'development_seeds': list(learning.TRAIN_SEEDS), 'variants': list(learning.VARIANTS), 'program_count': len(programs), 'unique_behavior_count': len({row['behavior_hash'] for row in programs}), 'fully_feasible_program_count': len(feasible), 'predeclared_static': {key: value for key, value in static.items() if key != 'cases'}, 'best_feasible': {key: value for key, value in best.items() if key != 'cases'}, 'elapsed_seconds': time.monotonic()-started, 'programs': programs}
    # Equivalent behaviors share outcomes; retain per-program variable costs.
    shared = {}
    fields = ('seed', 'scenario', 'snapshot_hash', 'event_hash', 'verification', 'failed_checks', 'metrics', 'rejected_plans', 'unresolved_plans', 'final_snapshot_hash')
    for program in programs:
        common = [{key: case[key] for key in fields} for case in program['cases']]
        if program['behavior_hash'] in shared:
            assert shared[program['behavior_hash']] == common
        else:
            shared[program['behavior_hash']] = common
        program['cases'] = [{key: value for key, value in case.items() if key not in fields or key in ('seed', 'scenario')} for case in program['cases']]
    report['behavior_cases'] = shared
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, separators=(',', ':'))+'\n')
    print(json.dumps({key: value for key, value in report.items() if key not in ('programs', 'behavior_cases')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    main(parser.parse_args().output)

"""Exhaustive development-only audit of the legacy ordered-subset grammar.

Run from repository root: PYTHONPATH=backend .venv/bin/python docs/agent-upgrade/capacity_audit.py
Writes a new audit artifact; never loads validation or held-out cases.
"""
import hashlib
import itertools
import json
import argparse
from pathlib import Path
import time

from uita import learning
from uita.planner import STATIC


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def main(destination=None):
    started = time.monotonic()
    root = Path(__file__).resolve().parents[2]
    destination = destination or root/'docs'/'agent-upgrade'/'legacy-capacity-audit.json'
    if destination.exists():
        raise SystemExit('Audit artifact already exists; pass --output with a new filename to preserve historical evidence.')
    files = ['learning.py', 'planner.py', 'models.py', 'simulator.py', 'verifier.py', 'objectives.py', 'airport.py']
    sources = {name: hashlib.sha256((root/'backend'/'uita'/name).read_bytes()).hexdigest() for name in files}
    rows = []
    tools = ('exit_occupancy', 'gate_ready', 'wake', 'weather')
    for size in range(5):
        for operations in itertools.permutations(tools, size):
            policy = STATIC.model_copy(update={'name': 'Independent capacity audit', 'observations': list(operations)})
            learning.validate_candidate(policy)
            result = learning.evaluate(policy, learning.TRAIN_SEEDS)
            cases = []
            for case in result['raw']:
                cases.append({key: case[key] for key in ('seed', 'scenario', 'snapshot_hash', 'event_hash', 'verification', 'failed_checks', 'metrics', 'observation_count', 'total_observations', 'solver_seconds', 'max_solver_seconds', 'rejected_plans', 'unresolved_plans', 'completed_aircraft_ids', 'final_snapshot_hash')})
                cases[-1]['decisions'] = [{key: decision[key] for key in ('time', 'verification', 'accepted', 'observation_count', 'slots')} for decision in case['decisions']]
            behavior = [[{'slots': decision['slots'], 'verification': decision['verification']} for decision in case['decisions']] for case in cases]
            rows.append({'observations': list(operations), 'artifact_hash': learning.program_hash(policy), 'behavior_hash': digest(behavior), 'summary': {key: value for key, value in result.items() if key != 'raw'}, 'cases': cases})
    static = next(row for row in rows if row['observations'] == list(STATIC.observations))
    feasible = [row for row in rows if row['summary']['pass_count'] == row['summary']['cases']]
    best = min(feasible, key=lambda row: row['summary']['mean_score'])
    report = {'schema': 'legacy-capacity-audit-1', 'scope': 'development-only; no validation or heldout evaluation', 'execution': 'fresh local exhaustive deterministic evaluator; no inference', 'development_seeds': list(learning.TRAIN_SEEDS), 'variants': list(learning.VARIANTS), 'evaluator_version': learning.EVALUATOR_VERSION, 'config_hash': learning.CONFIG_HASH, 'source_sha256': sources, 'program_count': len(rows), 'unique_behavior_count': len({row['behavior_hash'] for row in rows}), 'unique_score_count': len({row['summary']['mean_score'] for row in rows}), 'fully_feasible_program_count': len(feasible), 'static': {'observations': static['observations'], 'summary': static['summary'], 'artifact_hash': static['artifact_hash'], 'behavior_hash': static['behavior_hash']}, 'best_feasible': {'observations': best['observations'], 'summary': best['summary'], 'behavior_hash': best['behavior_hash']}, 'elapsed_seconds': time.monotonic()-started, 'programs': rows}
    # Deduplicate identical schedules while retaining each program's raw metrics
    # and read counts. This preserves evidence without 65 repeated schedule sets.
    behaviors = {}
    for row in rows:
        behaviors.setdefault(row['behavior_hash'], [{'seed': case['seed'], 'scenario': case['scenario'], 'decisions': [{key: value for key, value in decision.items() if key != 'observation_count'} for decision in case['decisions']]} for case in row['cases']])
        for case in row['cases']:
            case['decision_observation_counts'] = [decision['observation_count'] for decision in case.pop('decisions')]
    report['behavior_cases'] = behaviors
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, separators=(',', ':'))+'\n')
    print(json.dumps({key: value for key, value in report.items() if key not in ('programs', 'behavior_cases')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    main(parser.parse_args().output)

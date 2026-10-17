"""Independent upgrade boundaries and pre-upgrade behavioral golden evidence.

These tests were authored separately from the agent implementation. Historical
results are development-only data and are never passed to the proposal agent.
"""
import hashlib
import json
from pathlib import Path

import pytest

from uita import learning
from uita.models import Policy


ROOT = Path(__file__).resolve().parents[2]
AUDIT = json.loads((ROOT/'docs/agent-upgrade/legacy-capacity-audit.json').read_text())


def legacy_policy(operations):
    return Policy(name='Independent legacy compatibility', observations=operations,
                  order='priority', reserve_seconds=30, lookahead=12, max_observations=8)


def test_historical_evidence_and_trusted_semantics_remain_unchanged():
    manifest = json.loads((ROOT/'docs/agent-upgrade/legacy-integrity.json').read_text())
    for name, expected in manifest['sha256'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == expected, name


def test_all_65_legacy_executable_hashes_survive_schema_upgrade():
    assert len(AUDIT['programs']) == 65
    for program in AUDIT['programs']:
        assert learning.program_hash(legacy_policy(program['observations'])) == program['artifact_hash']


@pytest.mark.parametrize('program', AUDIT['programs'], ids=lambda row: ','.join(row['observations']) or 'empty')
def test_every_legacy_program_preserves_original_development_case_schedule(program):
    # Every syntactically distinct old program is replayed after the interface
    # refactor. Golden evidence was collected before new grammar implementation.
    original = program['cases'][0]
    actual = learning.evaluate(legacy_policy(program['observations']), [original['seed']], [original['scenario']])['raw'][0]
    behavior = AUDIT['behavior_cases'][program['behavior_hash']][0]
    assert actual['snapshot_hash'] == original['snapshot_hash']
    assert actual['event_hash'] == original['event_hash']
    assert actual['final_snapshot_hash'] == original['final_snapshot_hash']
    assert actual['metrics'] == original['metrics']
    assert [decision['observation_count'] for decision in actual['decisions']] == original['decision_observation_counts']
    assert [{key: decision[key] for key in ('time', 'verification', 'accepted', 'slots')} for decision in actual['decisions']] == behavior['decisions']


@pytest.mark.parametrize('behavior_hash', list(AUDIT['behavior_cases']))
def test_legacy_behavior_representatives_preserve_all_development_cases(behavior_hash):
    program = next(row for row in AUDIT['programs'] if row['behavior_hash'] == behavior_hash)
    result = learning.evaluate(legacy_policy(program['observations']), AUDIT['development_seeds'], AUDIT['variants'])
    assert result['cases'] == 16
    for actual, original, behavior in zip(result['raw'], program['cases'], AUDIT['behavior_cases'][behavior_hash]):
        assert actual['metrics'] == original['metrics']
        assert actual['final_snapshot_hash'] == original['final_snapshot_hash']
        assert [{key: decision[key] for key in ('time', 'verification', 'accepted', 'slots')} for decision in actual['decisions']] == behavior['decisions']

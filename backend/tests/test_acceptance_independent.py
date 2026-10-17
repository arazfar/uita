"""Independent adversarial acceptance checks, authored separately from implementation."""
import copy
import math
import pytest

from uita.airport import RULE_VERSION
from uita.simulator import new_state, snapshot_hash, trajectory
from uita.verifier import segment_conflict, verify


def point(t, x, y=0, altitude=5000):
    return dict(t=t, x=x, y=y, altitude=altitude)


def fixture():
    state = new_state(42)
    for i, aircraft in enumerate(state['aircraft']):
        aircraft['scheduled'] = 600 + i * 400
        aircraft['trajectory'] = trajectory(aircraft, aircraft['scheduled'], aircraft['runway'])
    plan = dict(id='independent-plan', revision=state['revision'], rule_version=RULE_VERSION,
                snapshot_hash=snapshot_hash(state), valid_until=state['time'] + 30,
                slots=[dict(aircraft_id=a['id'], runway=a['runway'], time=a['scheduled'])
                       for a in state['aircraft']])
    return state, plan


def test_reference_fixture_is_feasible():
    state, plan = fixture()
    result = verify(state, plan)
    assert result['status'] == 'pass', result


def test_between_tick_crossing_is_detected():
    result = segment_conflict(point(0,-5), point(10,5), point(0,0,-5), point(10,0,5))
    assert result is not None
    assert result['time'] == pytest.approx(5)
    assert result['lateral_nm'] == pytest.approx(0)


@pytest.mark.parametrize('vertical_ft', [1000, 1001, 5000])
def test_vertical_separation_boundary_is_respected(vertical_ft):
    assert segment_conflict(point(0,-5), point(10,5),
                            point(0,0,-5,5000 + vertical_ft), point(10,0,5,5000 + vertical_ft)) is None


def test_vertical_crossing_inside_interval_is_detected():
    result = segment_conflict(point(0,0,altitude=5000), point(10,0,altitude=5000),
                              point(0,0,altitude=7000), point(10,0,altitude=3000))
    assert result is not None
    assert 2.5 <= result['time'] <= 7.5


def test_nonoverlapping_time_intervals_are_clear():
    assert segment_conflict(point(0,0), point(5,1), point(6,0), point(10,1)) is None


def test_exact_lateral_boundary_is_clear():
    assert segment_conflict(point(0,0), point(10,1), point(0,0,3), point(10,1,3)) is None


def test_hash_binding_rejects_forged_hash():
    state, plan = fixture()
    plan['snapshot_hash'] = '0' * 64
    assert verify(state, plan)['status'] == 'fail'


def test_snapshot_binding_rejects_changed_truth_without_revision():
    state, plan = fixture()
    state['weather']['wind'] += 1
    assert verify(state, plan)['status'] == 'fail'


def test_state_rule_pack_mismatch_is_rejected():
    state, plan = fixture()
    state['rule_version'] = 'unknown-rule-pack'
    assert verify(state, plan)['status'] == 'fail'


def test_expired_plan_is_rejected():
    state, plan = fixture()
    state['time'] = plan['valid_until'] + .001
    assert verify(state, plan)['status'] == 'fail'


def test_revision_mismatch_is_rejected():
    state, plan = fixture()
    state['revision'] += 1
    assert verify(state, plan)['status'] == 'fail'


def test_delayed_observations_are_unresolved_even_if_geometry_is_clear():
    state, plan = fixture()
    state['communications_delay'] = 16
    plan['snapshot_hash'] = snapshot_hash(state)
    assert verify(state, plan)['status'] == 'unresolved'


@pytest.mark.parametrize('change', ['omitted', 'duplicate', 'unknown'])
def test_coverage_cannot_manufacture_feasibility(change):
    state, plan = fixture()
    if change == 'omitted':
        plan['slots'].pop()
    elif change == 'duplicate':
        plan['slots'].append(copy.deepcopy(plan['slots'][-1]))
    else:
        plan['slots'][-1]['aircraft_id'] = 'DOES-NOT-EXIST'
    assert verify(state, plan)['status'] == 'fail'


@pytest.mark.parametrize('time', [float('nan'), float('inf'), -1])
def test_invalid_slot_times_are_rejected(time):
    state, plan = fixture()
    plan['slots'][-1]['time'] = time
    assert verify(state, plan)['status'] == 'fail'


def test_committed_aircraft_cannot_be_retimed():
    state, plan = fixture()
    plan['slots'][0]['time'] += 60
    assert verify(state, plan)['status'] == 'fail'


def test_cross_runway_reservation_overlap_is_rejected():
    state, plan = fixture()
    plan['slots'][1]['time'] = plan['slots'][0]['time'] + 50
    assert verify(state, plan)['status'] == 'fail'


def test_closed_runway_is_rejected():
    state, plan = fixture()
    state['closed_runways'] = ['28R']
    plan['snapshot_hash'] = snapshot_hash(state)
    assert verify(state, plan)['status'] == 'fail'


@pytest.mark.parametrize('field', ['communications_delay', 'weather'])
def test_missing_mandatory_observation_is_unresolved(field):
    state, plan = fixture()
    state[field] = None
    plan['snapshot_hash'] = snapshot_hash(state)
    assert verify(state, plan)['status'] == 'unresolved'


def test_relational_transaction_rolls_back_as_a_unit(tmp_path):
    from uita.storage import Store
    store = Store(f'sqlite:///{tmp_path}/atomic.db')
    with pytest.raises(RuntimeError):
        with store.transaction() as transaction:
            store.put('event-a', 'event', {'value': 1}, transaction)
            store.put('checkpoint-a', 'checkpoint', {'value': 2}, transaction)
            raise RuntimeError('simulated crash before commit')
    assert store.get('event-a') is None
    assert store.get('checkpoint-a') is None


def test_state_and_checkpoint_survive_store_reopen(tmp_path):
    from uita.storage import Store
    url = f'sqlite:///{tmp_path}/durability.db'
    first = Store(url)
    state, _ = fixture()
    with first.transaction() as transaction:
        first.put('state', 'state', state, transaction)
        first.put('checkpoint-a', 'checkpoint', {'state': state}, transaction)
    first.engine.dispose()
    second = Store(url)
    assert second.get('state') == state
    assert second.get('checkpoint-a')['state'] == state


def test_interrupted_jobs_are_explicit_after_store_restart(tmp_path):
    from uita.storage import Store
    url = f'sqlite:///{tmp_path}/recovery.db'
    first = Store(url)
    for status in ['queued', 'running', 'completed', 'failed']:
        first.put(f'job-{status}', 'job', {'id': f'job-{status}', 'status': status})
    first.engine.dispose()
    second = Store(url, recover=True)
    for status in ['queued', 'running']:
        assert second.get(f'job-{status}')['status'] == 'interrupted'
        assert second.get(f'job-{status}')['error']
    for status in ['completed', 'failed']:
        assert second.get(f'job-{status}')['status'] == status


def test_database_compare_and_swap_rejects_second_writer(tmp_path):
    from uita.storage import Store
    store = Store(f'sqlite:///{tmp_path}/cas.db')
    store.put('state', 'state', {'revision': 1})
    with store.transaction() as transaction:
        store.cas_state(1, {'revision': 2, 'writer': 'first'}, transaction)
    with pytest.raises(ValueError):
        with store.transaction() as transaction:
            store.cas_state(1, {'revision': 2, 'writer': 'stale'}, transaction)
    assert store.get('state')['writer'] == 'first'


def test_verifier_checks_actual_committed_trajectories_not_regenerated_defaults():
    state, plan = fixture()
    # A checkpoint may contain already executed/committed paths that no longer
    # equal a fresh trajectory template. Both are admitted and collide now.
    for aircraft in state['aircraft'][:2]:
        aircraft['trajectory'] = [point(0, 0), point(2000, 0)]
    plan['snapshot_hash'] = snapshot_hash(state)
    result = verify(state, plan)
    assert result['status'] == 'fail', result
    separation = next(check for check in result['checks'] if check['id'] == 'continuous-separation')
    assert separation['status'] == 'fail'


def test_empty_candidate_schedule_counts_every_flight_unfinished():
    from uita.simulator import metrics
    state, _ = fixture()
    result = metrics(state, slots=[], horizon=2700)
    assert result['completed'] == 0
    assert result['backlog'] == len(state['aircraft'])
    assert result['unfinished_penalty'] == len(state['aircraft']) * 600


def test_verifier_does_not_report_past_conflict_as_future_conflict():
    state, plan = fixture()
    state['aircraft'] = state['aircraft'][:2]
    plan['slots'] = plan['slots'][:2]
    # Cross at t=100 and are 12NM apart by t=400, diverging thereafter.
    state['aircraft'][0]['trajectory'] = [point(0,-10,50), point(1000,10,50)]
    state['aircraft'][1]['trajectory'] = [point(0,-6,50), point(1000,-26,50)]
    plan['snapshot_hash'] = snapshot_hash(state)
    result = verify(state, plan)
    separation = next(check for check in result['checks'] if check['id'] == 'continuous-separation')
    assert separation['status'] == 'pass'

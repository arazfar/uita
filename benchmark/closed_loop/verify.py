"""Replay the complete frozen matrix without inference or held-out data access.

Replay accepted slots rather than rerunning an anytime optimizer: a wall-time
limit can produce another valid schedule. Ordered decoders are reproduced exactly.
Raw AI requests and responses must match each reconstructed causal decision.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import math
import platform
from collections import Counter
from pathlib import Path

from backend.uita.airport import RULE_VERSION
from backend.uita.simulator import snapshot_hash, trajectory
from backend.uita.verifier import verify as verify_plan
from benchmark.provider import digest
from . import ai, controllers, engine
from .run import ROOT, aggregate, sha, write
from .traffic import DATA_DIR, available_weather, load_episodes


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text())


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def equal(actual, expected, context):
    require(actual == expected, context)


def bound_plan(state, slots):
    return {'id': 'independent-replay', 'revision': state['revision'], 'rule_version': RULE_VERSION,
            'snapshot_hash': snapshot_hash(state), 'snapshot_time': state['time'],
            'valid_until': state['time'] + 30, 'status': 'proposed', 'slots': slots}


def schedule_contract(state, slots):
    """Independently enforce the announced common resource, not just FAA proxies."""
    aircraft = {a['id']: a for a in state['aircraft']}
    equal(len(slots), len(aircraft), 'Reservation count differs from released demand')
    equal({s['aircraft_id'] for s in slots}, set(aircraft), 'Missing or repeated reservation')
    intervals = []
    for slot in slots:
        equal(set(slot), {'aircraft_id', 'runway', 'time'}, 'Unexpected reservation fields')
        a, t = aircraft[slot['aircraft_id']], slot['time']
        require(type(t) in (int, float) and math.isfinite(t) and 0 <= t <= 20000 and t == int(t),
                'Reservation is outside the frozen integer time domain')
        fixed = a['trajectory'][0]['t'] <= state['time']
        if fixed:
            require(t == a['scheduled'] and slot['runway'] == a['runway'], 'Active commitment changed')
        else:
            earliest = math.ceil(max(a['requested'], state['time'] + 360,
                                     state.get('admission_blocked_until', 0) + 360))
            require(t >= earliest, 'Reservation precedes causal readiness')
            require(slot['runway'] in ('28L', '28R') and slot['runway'] not in state['closed_runways'],
                    'Pending reservation uses an unavailable runway')
        intervals.append((t, t + math.ceil(a['exit_occupancy'] + 240)))
    ordered = sorted(intervals)
    require(all(b[0] >= a[1] for a, b in zip(ordered, ordered[1:])), 'Announced resource reservations overlap')


def solver_contract(state, slots, details, horizon):
    """Check the recorded optimizer objective without assuming repeatable search."""
    require(details['status'] in ('OPTIMAL', 'FEASIBLE'), 'Accepted optimizer has no feasible solution')
    equal(details['workers'], 1, 'Optimizer worker count changed')
    equal(details['time_limit_seconds'], .25, 'Optimizer time bound changed')
    equal(details['objective_order'], ['unfinished_aircraft_at_horizon', 'sum_landing_delay_seconds'],
          'Optimizer objective changed')
    by_id = {s['aircraft_id']: s for s in slots}
    unfinished = sum(by_id[a['id']]['time'] + a['exit_occupancy'] + 90 > horizon for a in state['aircraft'])
    delay = sum(by_id[a['id']]['time'] - a['requested'] for a in state['aircraft'])
    weight = len(state['aircraft']) * 20000 + 1
    objective = weight * unfinished + sum(s['time'] for s in slots)
    equal(details['unfinished_aircraft'], unfinished, 'Recorded optimizer completion objective differs')
    require(math.isclose(details['sum_landing_delay_seconds'], delay, abs_tol=1e-6), 'Optimizer delay objective differs')
    equal(details['unfinished_weight'], weight, 'Optimizer priority weight differs')
    require(math.isclose(details['objective'], objective, abs_tol=1e-6), 'Optimizer objective value differs')
    require(details['best_bound'] <= objective + 1e-6, 'Optimizer lower bound exceeds its solution')
    if details['optimal']:
        require(math.isclose(details['best_bound'], objective, abs_tol=1e-6), 'Optimal solution has an open bound')


def raw_audits(master):
    paths = [master / 'calls.jsonl', *sorted((master / 'workers').glob('*/calls.jsonl'))]
    indexed, duplicates, records = {}, 0, 0
    for path in paths:
        if not path.exists():
            continue
        for call in rows(path):
            records += 1
            identifier = call['request_id']
            if identifier in indexed:
                equal(indexed[identifier]['payload_sha256'], call['payload_sha256'],
                      'Repeated request identity has a different public input')
                duplicates += 1
            # This is the finalizer's documented source precedence. Its selected
            # record must still match the executed row and the exact replay below.
            indexed[identifier] = call
    return indexed, {'raw_audit_records': records, 'duplicate_same_payload_records': duplicates,
                     'unique_audit_request_ids': len(indexed)}


def check_call(call, public, decision):
    ai.validate_view(public)
    expected = {'model': ai.MODEL, 'messages': [
        {'role': 'system', 'content': ai.SYSTEM_PROMPT},
        {'role': 'user', 'content': ai.canonical(public)}], **ai.GENERATION}
    equal(call['request'], expected, 'Raw AI request differs from exact reconstructed public state/settings')
    equal(call['payload_sha256'], digest(expected), 'Raw AI payload checksum differs')
    equal(call['paid_retries'], 0, 'Paid retry found')
    if call['status'] != 'completed':
        require(decision['controller_failure'], 'Inference failure was not marked as a controller failure')
        return None
    choice = call['response']['choices'][0]
    equal(choice['finish_reason'], 'stop', 'Incomplete generation was marked successful')
    action = ai.parse_action(choice['message']['content'], public)
    equal(call['action'], action, 'Saved AI action differs from strict raw parsing')
    require(not decision['controller_failure'], 'Successful inference was marked failed')
    return action


def replay(episode, row, audits, selected):
    state = engine.initial_state(episode, 17)
    state['rule_version'] = RULE_VERSION
    epoch, horizon = episode['warmup_start'], episode['drain_end'] - episode['warmup_start']
    cursor, index = 0, 0
    ticks = set(float(t) for t in range(0, int(horizon) + 1, engine.CONFIG['decision_interval_seconds']))
    ticks.update(entry['spawn_time'] - epoch for entry in episode['entries'])
    ticks.add(horizon)
    for now in sorted(ticks):
        state['time'] = now
        while cursor < len(episode['entries']) and episode['entries'][cursor]['spawn_time'] - epoch <= now:
            engine.add_aircraft(state, episode['entries'][cursor], epoch, cursor + 1)
            cursor += 1
        weather = available_weather(episode, epoch + now)
        if weather is not None and weather['visibility_sm'] is not None:
            state['weather']['visibility'] = weather['visibility_sm']
        public = engine.view_for(state, horizon)
        if now == horizon or now % engine.CONFIG['decision_interval_seconds'] or not public['pending']:
            continue
        require(index < len(row['decisions']), 'Missing runtime decision')
        decision = row['decisions'][index]
        index += 1
        equal(decision['time_seconds'], now, 'Unexpected runtime decision time')
        equal(decision['public_view_sha256'], hashlib.sha256(engine.canonical(public).encode()).hexdigest(),
              'Reconstructed causal state differs from recorded public view')
        ai.validate_view(public)
        action = None
        if row['controller'] == 'ai':
            identifier = f"cl-{digest(ai.SYSTEM_PROMPT)[:12]}:{episode['id']}:17:{int(now)}"
            require(identifier in audits and identifier not in selected, 'Missing or repeated selected AI decision')
            selected[identifier] = audits[identifier]
            action = check_call(audits[identifier], public, decision)
        else:
            require(not decision['controller_failure'], 'Non-AI reference has an inference failure')
        proposed = decision['proposed_slots']
        method = 'deterministic' if decision['controller_failure'] else row['controller']
        if method in ('scripted', 'ai'):
            expected = controllers.propose(state, method, horizon, order=action['order'] if action else None)
            equal(proposed, expected['slots'], 'Ordered decoder did not apply the actual action')
            equal(decision['proposed_solver']['status'], expected['solver']['status'], 'Ordered decoder status differs')
        if proposed:
            schedule_contract(state, proposed)
            if method == 'deterministic':
                solver_contract(state, proposed, decision['proposed_solver'], horizon)
            verdict = verify_plan(state, bound_plan(state, proposed))
        else:
            verdict = {'status': 'infeasible', 'checks': []}
        equal(decision['proposal_status'], verdict['status'], 'Original proposal verification differs')
        equal(decision['proposal_failed_checks'], [c['id'] for c in verdict['checks'] if c['status'] != 'pass'],
              'Original proposal failed checks differ')
        expected_fallback = decision['controller_failure'] or verdict['status'] != 'pass'
        equal(decision['fallback_used'], expected_fallback, 'Fallback reporting differs')
        applied_method = 'deterministic_fallback' if decision['controller_failure'] else row['controller']
        applied_slots, applied = proposed, verdict
        if verdict['status'] != 'pass':
            fallback = controllers.propose(state, 'scripted', horizon)
            applied_slots = fallback['slots']
            applied_method = 'scripted_fallback'
            applied = (verify_plan(state, bound_plan(state, applied_slots)) if applied_slots else
                       {'status': 'infeasible', 'checks': []})
        equal(decision['applied_controller'], applied_method, 'Applied controller provenance differs')
        equal(decision['applied_status'], applied['status'], 'Applied verification status differs')
        if applied['status'] == 'pass':
            equal(decision['slots'], applied_slots, 'Executed reservations differ from checked reservations')
            schedule_contract(state, applied_slots)
            active_before = {a['id']: copy.deepcopy(a) for a in state['aircraft'] if a['trajectory'][0]['t'] <= now}
            equal(engine.commit(state, bound_plan(state, applied_slots))['status'], 'pass', 'Replay commit rejected')
            for a in state['aircraft']:
                if a['id'] in active_before:
                    equal(a, active_before[a['id']], 'Commit changed an admitted trajectory')
        else:
            equal(decision['slots'], [], 'Unverified reservations were recorded as executed')
    equal(cursor, len(episode['entries']), 'Some historical source requests were never released')
    equal(index, len(row['decisions']), 'Extra runtime decisions found')
    actual = engine.outcome(state, episode, row['decisions'], horizon)
    equal(actual, {key: value for key, value in row.items() if key != 'controller'}, 'Replayed episode outcomes differ')
    # An additional direct arithmetic check avoids trusting serialized summaries.
    for flight, a in zip(actual['flights'], state['aircraft']):
        delay = max(0, a['scheduled'] - a['requested']) if flight['landed'] else max(0, horizon - a['requested'])
        equal(flight['added_delay_seconds'], round(delay, 3), 'Censored all-demand delay arithmetic differs')
        equal(flight['completed'], bool(a['committed'] and a['trajectory'][-1]['t'] <= horizon),
              'Completion does not follow executed trajectory')
    return actual


def negative_qa(episode):
    """Exercise the real gate and executed checker without any paid controller."""
    state = engine.initial_state(episode, 17)
    state['rule_version'] = RULE_VERSION
    for i, entry in enumerate(episode['entries'][:2]):
        engine.add_aircraft(state, entry, episode['warmup_start'], i + 1)
    state['time'] = 0
    unsafe = bound_plan(state, [{'aircraft_id': a['id'], 'runway': '28L', 'time': 600 + i * 30}
                                for i, a in enumerate(state['aircraft'])])
    before = copy.deepcopy(state)
    equal(engine.commit(state, unsafe)['status'], 'fail', 'Unsafe plan was accepted')
    equal(state, before, 'Rejected plan mutated committed state')
    for i, a in enumerate(state['aircraft']):
        a.update(scheduled=600 + i * 30, committed=True, admission_hold=False)
        a['trajectory'] = trajectory(a, a['scheduled'], '28L')
    audit = engine.audit_executed(state, 1200)
    for key in ('separation_violation_episodes', 'runway_violation_episodes', 'surface_violation_episodes', 'wake_violations'):
        require(audit[key] > 0, 'Executed negative safety probe was missed: ' + key)
    state['aircraft'][0]['trajectory'] = [{'t': 0., 'x': 0., 'y': 0., 'altitude': 5000.},
                                         {'t': 800., 'x': 0., 'y': 0., 'altitude': 5000.}]
    state['aircraft'][1]['trajectory'] = [{'t': t, 'x': x, 'y': 0., 'altitude': 5000.}
                                         for t, x in [(0., -10.), (200., 0.), (400., 10.), (600., 0.), (800., -10.)]]
    intervals = [f['interval'] for f in engine.audit_executed(state, 800)['findings']['separation']]
    equal(intervals, [[140., 260.], [540., 660.]], 'Distinct executed conflicts were incorrectly merged')
    public = engine.view_for(before, 4500)
    public['pending'][0]['known_since_seconds'] = public['clock_seconds'] + 1
    try:
        ai.validate_view(public)
    except ValueError:
        pass
    else:
        raise ValueError('Future-known aircraft passed the public boundary')
    return ['unsafe commit rejected without mutation', 'executed separation/runway/surface/wake detection',
            'two exact conflict intervals remain separate', 'future-known public aircraft rejected']


def verify_run(master, output):
    master = Path(master)
    plan, summary = read(master / 'plan.json'), read(master / 'summary.json')
    equal(summary['status'], 'completed', 'Run is incomplete')
    equal(plan['controllers'], ['scripted', 'deterministic', 'ai'], 'Expected complete three-controller matrix')
    equal(plan['split'], 'validation', 'Final attestation is for the complete validation matrix')
    equal(plan['config'], engine.CONFIG, 'Frozen simulator configuration changed')
    equal(plan['runtime']['python'], platform.python_version(), 'Python runtime changed')
    equal(plan['runtime']['ortools'], importlib.metadata.version('ortools'), 'Optimizer runtime changed')
    equal(summary['plan_sha256'], sha(master / 'plan.json'), 'Plan checksum differs')
    equal(summary['source_hashes'], plan['source_hashes'], 'Summary source binding differs')
    for name, expected in plan['source_hashes'].items():
        equal(sha(ROOT / name), expected, 'Current frozen source differs: ' + name)
        equal(sha(master / 'frozen_source' / name), expected, 'Archived frozen source differs: ' + name)
    equal(sha(DATA_DIR / 'validation.json'), plan['traffic_sha256'], 'Traffic bytes changed')
    equal(sha(DATA_DIR / 'manifest.json'), plan['traffic_manifest_sha256'], 'Traffic manifest changed')
    for name in ('plan.json', 'runs.json'):
        equal(summary['artifacts'][name], sha(master / name), 'Result artifact checksum differs: ' + name)
    episodes = load_episodes('validation')
    equal(len(episodes), 6, 'Expected six fixed windows')
    equal([e['id'] for e in episodes], plan['episodes'], 'Episode membership differs')
    expected_flights = [e['flight_id'] for episode in episodes for e in episode['entries']]
    equal(len(expected_flights), 136, 'Expected 136 fixed source arrival operations')
    equal(len(set(expected_flights)), 136, 'A source arrival operation is reused')
    stored = read(master / 'runs.json')
    matrix = {(r['controller'], r['episode_id']): r for r in stored}
    equal(len(stored), 18, 'Expected 18 completed controller/episode results')
    equal(len(matrix), 18, 'Duplicate controller/episode result')
    equal(set(matrix), {(c, e['id']) for c in plan['controllers'] for e in episodes}, 'Incomplete result matrix')
    audits, audit_counts = raw_audits(master)
    selected, replayed = {}, []
    for controller in plan['controllers']:
        for episode in episodes:
            row = matrix[controller, episode['id']]
            equal(row['seed'], 17, 'Unexpected seed')
            equal(row['variant'], 'nominal', 'Unexpected disturbance variant')
            equal(row, read(master / 'episodes' / f"{episode['id']}-{controller}.json"), 'Per-episode file differs')
            replay(episode, row, audits, selected)
            replayed.append(row)
    totals = {c: aggregate([r for r in replayed if r['controller'] == c]) for c in plan['controllers']}
    equal(totals, summary['controllers'], 'Recomputed controller aggregates differ')
    equal(summary['ai_usage']['calls'], len(selected), 'Selected inference count differs')
    equal(summary['ai_usage']['statuses'], dict(Counter(c['status'] for c in selected.values())), 'Inference status counts differ')
    equal(summary['ai_usage']['successful_calls'], sum(c['status'] == 'completed' for c in selected.values()), 'Inference success count differs')
    require(math.isclose(summary['ai_usage']['reported_cost_usd'], sum(c.get('cost_usd') or 0 for c in selected.values()), abs_tol=1e-9), 'Selected known inference cost differs')
    equal(summary['ai_usage']['unknown_cost_requests'], sum(c.get('cost_usd') is None for c in selected.values()), 'Unknown inference cost count differs')
    for path in sorted((master / 'workers').glob('*/worker-verification.json')):
        equal(read(path)['worker_sha256'], sha(Path(__file__).with_name('worker.py')), 'Worker helper checksum differs')
    worker_hash = sha(Path(__file__).with_name('worker.py'))
    equal(summary['execution']['worker_sha256'], worker_hash, 'Finalizer helper checksum differs')
    result = {'passed': True, 'verification_kind': 'independent_complete_matrix_causal_replay',
              'verifier_sha256': sha(__file__), 'worker_sha256': worker_hash,
              'artifacts': {name: sha(master / name) for name in ('plan.json', 'runs.json', 'summary.json')},
              'counts': {'episodes': 6, 'controller_episode_results': 18, 'source_arrival_operations_per_controller': 136,
                         'replayed_decisions': sum(r['decision_count'] for r in replayed), 'selected_ai_decisions': len(selected), **audit_counts},
              'checks': ['frozen source/runtime/data checksums', 'complete matched matrix', 'causal traffic and weather replay',
                         'strict raw AI request/response binding', 'ordered action decoding', 'optimizer feasibility and recorded objective',
                         'independent verification before every commit', 'immutable admitted motion', 'executed safety and all-demand delay replay',
                         'controller aggregates and inference accounting'],
              'negative_qa': negative_qa(episodes[0]),
              'limits': ['No provider requests were made during verification.', 'August 8–9 were not opened or evaluated.',
                         'Anytime optimizer output is checked, not assumed globally optimal or re-solved identically.',
                         'AI results include recorded checked fallbacks; feeder and upstream queue safety remain outside scope.']}
    write(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = verify_run(args.run, args.output)
    print(json.dumps({'passed': result['passed'], 'counts': result['counts'], 'output': str(args.output)}, indent=2))


if __name__ == '__main__':
    main()

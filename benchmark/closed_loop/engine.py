"""Trusted historical-demand admission loop; controllers never see future queues."""
from __future__ import annotations

import hashlib
import math
import statistics
from backend.uita.airport import RULE_VERSION
from backend.uita.simulator import trajectory
from backend.uita.verifier import verify
from .controllers import propose
from .traffic import available_weather

VERSION = 'historical-admission-loop-v1'
CONFIG = {
    'version': VERSION, 'decision_interval_seconds': 300, 'approach_seconds': 360,
    'feeder_speed_min_kt': 140, 'feeder_speed_max_kt': 280,
    'source_center_lon_lat': [-122.379, 37.6213], 'synthetic_approach_entry_nm': [14.75, -7.41],
    'occupancy_min_seconds': 45, 'occupancy_max_seconds': 140,
    'reservation_extra_seconds': 240, 'unfinished_penalty_seconds': 3600,
    'computation_time': 'Logical clock pauses during controller computation; wall latency is reported separately',
    'scenario_variants': ['nominal'], 'seeds': [17],
    'safety_scope': 'Existing fixed synthetic approach, shared runway and taxi resource; upstream feeder/queue not safety-modeled',
    'objective': 'zero executed violations and unresolved decisions; then unfinished aircraft; then all-demand censored added delay plus unfinished penalty',
}
SENTINEL = 1_000_000_000


def canonical(value):
    import json
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def nominal_times(entry, epoch):
    """Synthetic feeder to the same checked approach, independent of actual outcomes."""
    lon0, lat0 = CONFIG['source_center_lon_lat']
    position = entry['position']
    x = (position['lon'] - lon0) * 60 * math.cos(math.radians(lat0))
    y = (position['lat'] - lat0) * 60
    px, py = CONFIG['synthetic_approach_entry_nm']
    feeder_nm = math.hypot(x - px, y - py)
    speed = max(CONFIG['feeder_speed_min_kt'], min(CONFIG['feeder_speed_max_kt'], entry['groundspeed_kt']))
    known = entry['spawn_time'] - epoch
    ready = known + feeder_nm / speed * 3600
    return known, ready, ready + CONFIG['approach_seconds']


def initial_state(episode, seed):
    return {'session_id': episode['id'], 'revision': 1, 'time': 0., 'seed': seed,
            'aircraft': [], 'weather': {'visibility': 10., 'wind': 280, 'ceiling': 5000},
            'closed_runways': [], 'communications_delay': 0, 'admission_blocked_until': 0}


def add_aircraft(state, entry, epoch, number):
    known, ready, earliest = nominal_times(entry, epoch)
    # Occupancy is synthetic exogenous input, announced equally to all controllers.
    token = hashlib.sha256(f"{state['seed']}:{entry['flight_id']}".encode()).digest()
    occupancy = CONFIG['occupancy_min_seconds'] + int.from_bytes(token[:4], 'big') % 96
    identifier = f'A{number:03}'
    aircraft_type = entry['aircraft_type'] or 'UNKNOWN'
    wake = 'heavy' if aircraft_type.startswith(('B74', 'B77', 'B78', 'A33', 'A34', 'A35', 'A38')) else 'medium'
    aircraft = {'id': identifier, 'callsign': identifier, 'type': aircraft_type, 'wake': wake,
                'operation': 'arrival', 'requested': earliest, 'known_since': known,
                'approach_ready': ready, 'scheduled': SENTINEL, 'runway': '28L',
                'gate_ready': earliest, 'exit_occupancy': occupancy, 'emergency': False,
                'group': 0, 'admission_hold': True, 'committed': False,
                'position_provenance': entry['position_provenance'],
                'source_flight_id': entry['flight_id'], 'source_altitude_provenance': entry['altitude_provenance']}
    aircraft['trajectory'] = trajectory(aircraft, SENTINEL, aircraft['runway'])
    state['aircraft'].append(aircraft)
    state['revision'] += 1


def view_for(state, horizon):
    pending, active = [], []
    for aircraft in state['aircraft']:
        if aircraft['trajectory'][0]['t'] <= state['time']:
            active.append({'id': aircraft['id'], 'landing_seconds': aircraft['scheduled'], 'runway': aircraft['runway'],
                           'exit_occupancy_seconds': aircraft['exit_occupancy']})
        else:
            pending.append({'id': aircraft['id'], 'known_since_seconds': aircraft['known_since'],
                            'earliest_landing_seconds': aircraft['requested'],
                            'current_slot_seconds': aircraft['scheduled'] if aircraft['committed'] else None,
                            'wake': aircraft['wake'], 'exit_occupancy_seconds': aircraft['exit_occupancy'],
                            'position_provenance': aircraft['position_provenance']})
    return {'episode_id': 'ep-'+hashlib.sha256(state['session_id'].encode()).hexdigest()[:12], 'clock_seconds': state['time'],
            'horizon_seconds': horizon, 'pending': pending, 'active_commitments': active,
            'runway_resource': 'shared', 'minimum_spacing': {'medium': 90, 'heavy': 120},
            'reservation_duration_formula': 'exit_occupancy_seconds+240',
            'objective': 'safety gate, then fewer unfinished, then lower total modeled added delay'}


def commit(state, proposal):
    # No mutation until the independent verifier passes at this exact revision.
    verdict = verify(state, proposal)
    if verdict['status'] != 'pass':
        return verdict
    by_id = {slot['aircraft_id']: slot for slot in proposal['slots']}
    for aircraft in state['aircraft']:
        if aircraft['trajectory'][0]['t'] <= state['time']:
            continue
        slot = by_id[aircraft['id']]
        aircraft['scheduled'] = slot['time']
        aircraft['runway'] = slot['runway']
        aircraft['trajectory'] = trajectory(aircraft, slot['time'], slot['runway'])
        aircraft['admission_hold'] = False
        aircraft['committed'] = True
    state['revision'] += 1
    return verdict


def _clipped_segments(path, horizon):
    for p, q in zip(path, path[1:]):
        lo, hi = max(0, p['t']), min(horizon, q['t'])
        if hi <= lo:
            continue
        def point(t):
            f = (t - p['t']) / (q['t'] - p['t'])
            return {'t': t, **{key: p[key] + f * (q[key] - p[key]) for key in ('x', 'y', 'altitude')}}
        yield point(lo), point(hi)


def _merge(intervals):
    out = []
    for lo, hi in sorted(intervals):
        if not out or lo > out[-1][1] + 1e-6:
            out.append([lo, hi])
        else:
            out[-1][1] = max(out[-1][1], hi)
    return out


def _separation(p, q, r, s):
    """Independent executed-path check, including exact lateral crossing times."""
    start, end = max(p['t'], r['t']), min(q['t'], s['t'])
    if start >= end:
        return None, None
    va = {key: (q[key]-p[key])/(q['t']-p['t']) for key in ('x', 'y', 'altitude')}
    vb = {key: (s[key]-r[key])/(s['t']-r['t']) for key in va}
    pa = {key: p[key]+va[key]*(start-p['t']) for key in va}
    pb = {key: r[key]+vb[key]*(start-r['t']) for key in vb}
    lo, hi = 0., end-start
    def band(value, rate, minimum, maximum):
        nonlocal lo, hi
        if abs(rate) < 1e-12:
            return minimum <= value <= maximum
        a, b = (minimum-value)/rate, (maximum-value)/rate
        lo, hi = max(lo, min(a, b)), min(hi, max(a, b))
        return lo < hi
    for position, velocity in [(pa, va), (pb, vb)]:
        if not band(position['altitude'], velocity['altitude'], 1000, float('inf')):
            return None, None
    if not band(pa['altitude']-pb['altitude'], va['altitude']-vb['altitude'], -999.999, 999.999):
        return None, None
    dx, dy = pa['x']-pb['x'], pa['y']-pb['y']
    vx, vy = va['x']-vb['x'], va['y']-vb['y']
    a, b, c = vx*vx+vy*vy, 2*(dx*vx+dy*vy), dx*dx+dy*dy-9
    closest = max(lo, min(hi, -b/(2*a))) if a > 1e-12 else lo
    minimum = math.hypot(dx+vx*closest, dy+vy*closest)
    if minimum >= 3-1e-7:
        return minimum, None
    if a <= 1e-12:
        return minimum, [start+lo, start+hi]
    discriminant = b*b-4*a*c
    if discriminant <= 0:
        return minimum, None
    root = math.sqrt(discriminant)
    left, right = max(lo, (-b-root)/(2*a)), min(hi, (-b+root)/(2*a))
    return minimum, [start+left, start+right] if left < right else None


def audit_executed(state, horizon):
    """Check actually flown path segments, not rejected hypothetical proposals."""
    flown = [a for a in state['aircraft'] if a['committed'] and a['trajectory'][0]['t'] < horizon]
    segments = {a['id']: list(_clipped_segments(a['trajectory'], horizon)) for a in flown}
    separation = []
    checks = 0
    minimum_separation = None
    for index, a in enumerate(flown):
        for b in flown[index + 1:]:
            conflicts = []
            for p, q in segments[a['id']]:
                for r, s in segments[b['id']]:
                    checks += 1
                    minimum, conflict = _separation(p, q, r, s)
                    if minimum is not None:
                        minimum_separation = min(minimum_separation, minimum) if minimum_separation is not None else minimum
                    if conflict is not None:
                        conflicts.append(conflict)
            for interval in _merge(conflicts):
                separation.append({'aircraft': [a['id'], b['id']], 'interval': interval})
    def overlaps(intervals):
        found = []
        for index, a in enumerate(intervals):
            for b in intervals[index + 1:]:
                lo, hi = max(a[0], b[0], 0), min(a[1], b[1], horizon)
                if lo < hi - 1e-6:
                    found.append({'aircraft': [a[2], b[2]], 'interval': [lo, hi]})
        return found
    runway = overlaps([(a['scheduled'] - 80, a['scheduled'] + a['exit_occupancy'] + 40, a['id']) for a in flown])
    surface = overlaps([(a['scheduled'] + a['exit_occupancy'], a['scheduled'] + a['exit_occupancy'] + 90, a['id']) for a in flown])
    landed = sorted((a for a in flown if a['scheduled'] <= horizon), key=lambda a: a['scheduled'])
    wake = [{'aircraft': [a['id'], b['id']], 'gap_seconds': b['scheduled'] - a['scheduled']}
            for a, b in zip(landed, landed[1:]) if b['scheduled'] - a['scheduled'] < (120 if a['wake'] == 'heavy' else 90)]
    performance = []
    for a in flown:
        for p, q in segments[a['id']]:
            dt = q['t'] - p['t']
            if (math.hypot(q['x'] - p['x'], q['y'] - p['y']) / dt * 3600 > 350 or
                    abs(q['altitude'] - p['altitude']) / dt * 60 > 4000 or min(p['altitude'], q['altitude']) < 0):
                performance.append(a['id'])
    return {'separation_violation_episodes': len(separation), 'runway_violation_episodes': len(runway),
            'surface_violation_episodes': len(surface), 'wake_violations': len(wake),
            'performance_violations': len(set(performance)), 'checked_segment_pairs': checks,
            'minimum_lateral_nm_when_vertical_under_1000_ft': minimum_separation,
            'findings': {'separation': separation, 'runway': runway, 'surface': surface, 'wake': wake, 'performance': sorted(set(performance))},
            'scope': CONFIG['safety_scope']}


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def outcome(state, episode, decisions, horizon):
    flights = []
    for a in state['aircraft']:
        landed = a['committed'] and a['scheduled'] <= horizon
        complete = a['committed'] and a['trajectory'][-1]['t'] <= horizon
        # Unfinished demand contributes accrued excess waiting, never its
        # hypothetical future reservation. The frozen backlog penalty is separate.
        delay = max(0, a['scheduled'] - a['requested']) if landed else max(0, horizon - a['requested'])
        flights.append({'id': a['id'], 'source_flight_id': a['source_flight_id'],
                        'position_provenance': a['position_provenance'],
                        'known_since_seconds': a['known_since'], 'nominal_landing_seconds': a['requested'],
                        'landing_seconds': a['scheduled'] if landed else None, 'landed': landed, 'completed': complete,
                        'nominal_due_before_horizon': a['requested']+a['exit_occupancy']+90 <= horizon,
                        'added_delay_seconds': round(delay, 3), 'uncontrolled_feeder_and_queue_scope': True})
    safety = audit_executed(state, horizon)
    values = [f['added_delay_seconds'] for f in flights]
    completed = sum(f['completed'] for f in flights)
    backlog = len(flights) - completed
    violations = sum(safety[k] for k in ['separation_violation_episodes', 'runway_violation_episodes', 'surface_violation_episodes', 'wake_violations', 'performance_violations'])
    unresolved = sum(d['applied_status'] != 'pass' for d in decisions)
    return {'episode_id': episode['id'], 'seed': state['seed'], 'variant': 'nominal', 'spawned': len(flights),
            'landed': sum(f['landed'] for f in flights), 'completed': completed, 'backlog': backlog,
            'added_delay_seconds_sum': round(sum(values), 3),
            'mean_added_delay_seconds_all_demand': statistics.mean(values) if values else 0,
            'p95_added_delay_seconds_all_demand': percentile(values, .95),
            'penalized_added_delay_seconds': round(sum(values) + CONFIG['unfinished_penalty_seconds'] * backlog, 3),
            'delay_metric': 'modeled additional feeder/admission waiting before a fixed final approach; unfinished values right-censored at drain_end',
            'airborne_holding_seconds': None, 'safety': safety, 'executed_violations': violations,
            'controller_failures': sum(d['controller_failure'] for d in decisions),
            'fallback_decisions': sum(d['fallback_used'] for d in decisions),
            'rejected_proposals': sum(d['proposal_status'] != 'pass' for d in decisions),
            'unresolved_decisions': unresolved, 'safety_eligible': violations == 0 and unresolved == 0,
            'decision_count': len(decisions), 'decisions': decisions, 'flights': flights,
            'rank': [violations, unresolved, backlog, round(sum(values) + CONFIG['unfinished_penalty_seconds'] * backlog, 3)]}


def simulate(episode, controller, seed=17, ai=None, emit=None):
    epoch = episode['warmup_start']
    horizon = episode['drain_end'] - epoch
    state = initial_state(episode, seed)
    state['rule_version'] = RULE_VERSION
    entries = episode['entries']
    cursor = 0
    decisions = []
    interval = CONFIG['decision_interval_seconds']
    ticks = set(float(t) for t in range(0, int(horizon) + 1, interval))
    ticks.update(entry['spawn_time'] - epoch for entry in entries)
    ticks.add(horizon)
    for now in sorted(ticks):
        state['time'] = now
        while cursor < len(entries) and entries[cursor]['spawn_time'] - epoch <= now:
            add_aircraft(state, entries[cursor], epoch, cursor + 1)
            cursor += 1
        report = available_weather(episode, epoch + now)
        if report is not None and report['visibility_sm'] is not None:
            state['weather']['visibility'] = report['visibility_sm']
        if now == horizon or now % interval or not view_for(state, horizon)['pending']:
            continue
        public = view_for(state, horizon)
        failure = False
        action = None
        if controller == 'ai':
            protocol = getattr(ai, 'plan', {}).get('prompt_sha256', 'fixture')[:12]
            action = ai.choose(public, f"cl-{protocol}:{episode['id']}:{seed}:{int(now)}")
            failure = action is None
        proposal = propose(state, controller if not failure else 'deterministic', horizon,
                           order=action['order'] if action is not None else None)
        if proposal.get('status') == 'infeasible':
            verdict = {'status': 'infeasible', 'checks': []}
        else:
            verdict = verify(state, proposal)
        proposed_solver = proposal.get('solver')
        proposed_slots = proposal.get('slots', [])
        fallback = failure or verdict['status'] != 'pass'
        applied = verdict
        applied_controller = 'deterministic_fallback' if failure else controller
        if verdict['status'] != 'pass':
            proposal = propose(state, 'scripted', horizon)
            applied_controller = 'scripted_fallback'
            applied = verify(state, proposal) if proposal.get('status') != 'infeasible' else {'status': 'infeasible', 'checks': []}
        if applied['status'] == 'pass':
            applied = commit(state, proposal)
        record = {'time_seconds': now, 'public_view_sha256': hashlib.sha256(canonical(public).encode()).hexdigest(),
                  'controller_failure': failure, 'fallback_used': fallback,
                  'proposal_status': verdict['status'], 'applied_status': applied['status'],
                  'applied_controller': applied_controller, 'proposed_solver': proposed_solver,
                  'proposed_slots': proposed_slots,
                  'proposal_failed_checks': [c['id'] for c in verdict['checks'] if c['status'] != 'pass'],
                  'solver': proposal.get('solver'), 'slots': proposal['slots'] if applied['status'] == 'pass' else []}
        decisions.append(record)
        if emit:
            emit({'episode': episode['id'], 'controller': controller, 'time': now,
                  'released': len(state['aircraft']), 'pending': len(public['pending']),
                  'applied_status': applied['status'], 'fallback': fallback})
    if cursor != len(entries):
        raise ValueError('Historical episode did not admit every scheduled source spawn')
    return outcome(state, episode, decisions, horizon)

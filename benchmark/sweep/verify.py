"""Independently replay the complete late-August model sweep without inference.

The original plan/resource/solver checks remain unchanged. Each model action is
bound to its frozen payload and raw response before replaying the shared decoder.
"""
from __future__ import annotations

import argparse
import ast
import copy
import csv
import datetime as dt
import io
import hashlib
import importlib.metadata
import json
import math
import platform
from collections import Counter
from pathlib import Path
import re
import sqlite3
from zoneinfo import ZoneInfo

from backend.uita.airport import RULE_VERSION
from backend.uita.verifier import verify as verify_plan
from benchmark.closed_loop import ai as original_ai, controllers, engine
from benchmark.closed_loop import verify as original
from benchmark.closed_loop.run import ROOT, aggregate, sha, write
from benchmark.closed_loop.traffic import available_weather
from benchmark.provider import canonical, digest

require, equal, read = original.require, original.equal, original.read
BOUND_DATES = [f'2026-08-{day:02}' for day in range(24, 31)]


def verify_traffic_source(episodes, directory):
    """Check frozen queues against permitted source files without remote reads.

    This version contains only synthetic initial states. Reconstruct their
    deterministic template selection independently from the target-day roster.
    The whole-month path archive is not opened by this verifier.
    """
    from benchmark.closed_loop.traffic import ENTRY_FIELDS
    directory = Path(directory)
    manifest, provenance = read(directory / 'manifest.json'), read(directory / 'provenance.json')
    sources = provenance['sources']
    for key in ('roster', 'weather', 'frozen_development_templates'):
        source = sources[key]
        path = ROOT / source['file']
        equal(sha(path), source['sha256'], 'Permitted raw source checksum differs: ' + key)
        equal(path.stat().st_size, source['bytes'], 'Permitted raw source size differs: ' + key)
    templates = read(ROOT / sources['frozen_development_templates']['file'])
    require(bool(templates), 'Development template bank is empty')
    for template in templates:
        require(template['entry']['local_date'] in ('2026-08-03', '2026-08-04', '2026-08-05', '2026-08-06')
                and template['entry']['split'] == 'train', 'Template donor is outside development days')
        require(120 <= template['lead_seconds'] <= 2400, 'Template lead is outside frozen bounds')
    zone = ZoneInfo('America/Los_Angeles')
    roster = read(ROOT / sources['roster']['file'])
    synthetic, operation_dates = {}, {}
    for operation in roster:
        local = dt.datetime.fromisoformat(operation['flight_date_time']).replace(tzinfo=zone)
        require(local.date().isoformat() in BOUND_DATES, 'Raw roster includes an unauthorized day')
        if not re.fullmatch(r'(?:0?1|10|19|28)[LR]', operation.get('runway_name', '')):
            continue
        identifier = 'a' + operation['operation_no']
        require(identifier not in synthetic, 'Raw roster repeats a source operation')
        candidates = [template for template in templates if template['origin'] == operation.get('other_port', '')] or templates
        selection = int(hashlib.sha256(identifier.encode()).hexdigest()[:8], 16) % len(candidates)
        template = candidates[selection]
        entry = {key: copy.deepcopy(template['entry'][key]) for key in ENTRY_FIELDS}
        entry.update(flight_id=identifier, callsign=operation.get('flight_no', ''),
                     aircraft_type=operation.get('aircraft_type', ''), origin=operation.get('other_port', ''),
                     spawn_time=local.timestamp() - template['lead_seconds'],
                     position_provenance='synthetic_training_template', altitude_provenance='synthetic_training_template',
                     motion_provenance='synthetic_training_template')
        synthetic[identifier], operation_dates[identifier] = entry, local.date().isoformat()
    equal(len(synthetic), provenance['source_arrival_operations_all_day'], 'Eligible source roster count differs')
    for episode in episodes:
        expected = sorted([entry for identifier, entry in synthetic.items()
                           if operation_dates[identifier] == episode['local_date']
                           and episode['warmup_start'] <= entry['spawn_time'] < episode['end']],
                          key=lambda entry: (entry['spawn_time'], entry['flight_id']))
        equal(episode['entries'], expected, 'Historical-demand source reconstruction differs: ' + episode['id'])
    # Every packed report must be a real source observation with the disclosed
    # five-minute receipt assumption. Selection of the causal report is replayed.
    source_weather = ROOT / sources['weather']['file']
    lines = '\n'.join(line for line in source_weather.read_text().splitlines() if not line.startswith('#'))
    raw_weather = {dt.datetime.fromisoformat(row['valid']).replace(tzinfo=dt.timezone.utc).timestamp(): row
                   for row in csv.DictReader(io.StringIO(lines))}
    for episode in episodes:
        expected_times = sorted(t for t in raw_weather if t + 300 <= episode['drain_end'])
        prior = [t for t in expected_times if t + 300 <= episode['warmup_start']]
        during = [t for t in expected_times if episode['warmup_start'] < t + 300 <= episode['drain_end']]
        equal([report['observed_at'] for report in episode['weather']], prior[-1:] + during,
              'Packed weather does not follow source availability')
        for report in episode['weather']:
            raw = raw_weather[report['observed_at']]
            equal(report['available_at'], report['observed_at'] + 300, 'Weather receipt assumption differs')
            equal(report['metar'], raw.get('metar'), 'Weather observation text differs')
            for target, source in (('visibility_sm', 'vsby'), ('wind_speed_kt', 'sknt'),
                                   ('wind_direction_deg_true', 'drct'), ('wind_gust_kt', 'gust'),
                                   ('altimeter_inhg', 'alti'), ('temperature_f', 'tmpf')):
                value = raw.get(source)
                expected = None if value in (None, '', 'M', 'T') else float(value)
                equal(report[target], expected, 'Weather numeric observation differs: ' + target)
    equal(manifest['artifacts']['evaluation.json']['position_strata'],
          {'synthetic_training_template': sum(len(e['entries']) for e in episodes)}, 'Source strata differ')
    return {'historical_roster_operations': len(synthetic), 'selected_source_operations': sum(len(e['entries']) for e in episodes),
            'all_initial_states_synthetic': True, 'template_donors_development_only': True,
            'source_weather_receipt_seconds': 300, 'whole_month_path_archive_opened': False}


def raw_audits(master):
    """Each scored model/window owns one audit path and unique request identities."""
    audits, records = {}, 0
    for path in sorted(Path(master).glob('configs/*/episodes/*/calls.jsonl')):
        configuration_id, episode_id = path.parts[-4], path.parts[-2]
        for call in original.rows(path):
            records += 1
            identifier = call['request_id']
            require(identifier not in audits, 'Duplicate scored inference identity: ' + identifier)
            equal(call['config_id'], configuration_id, 'Audit path/configuration mismatch')
            require(episode_id in call['engine_request_id'], 'Audit path/episode mismatch')
            audits[identifier] = call
    return audits, {'raw_audit_records': records, 'unique_audit_request_ids': len(audits)}


def check_call(call, public, decision, configuration):
    """The provider cannot change the task, settings, or valid action silently."""
    original_ai.validate_view(public)
    expected = {'model': configuration['model'], 'messages': [
        {'role': 'system', 'content': original_ai.SYSTEM_PROMPT},
        {'role': 'user', 'content': canonical(public)}], **configuration['generation']}
    equal(call['config_id'], configuration['id'], 'Inference configuration differs')
    equal(call['request'], expected, 'Raw inference differs from exact causal public state/settings')
    equal(call['payload_sha256'], digest(expected), 'Raw inference payload checksum differs')
    equal(call['paid_retries'], 0, 'Paid retry found')
    require(call['status'] in ('completed', 'invalid_response', 'http_failure', 'ambiguous_failure'),
            'Incomplete orchestration or unknown inference status was scored')
    require(call['dispatched'] is True, 'A scored model decision was not dispatched')
    require(type(call['latency_seconds']) in (int, float) and math.isfinite(call['latency_seconds'])
            and call['latency_seconds'] >= 0, 'Invalid inference latency')
    input_bound = 2 * len(canonical(expected).encode()) + 1024
    equal(call['input_token_bound'], input_bound, 'Conservative prompt token bound differs')
    discovery = configuration['discovery']
    input_rate = discovery['input_usd_per_million_tokens'] / 1_000_000
    output_rate = discovery['output_usd_per_million_tokens'] / 1_000_000
    reserved, cost = call['reserved_usd'], call.get('cost_usd')
    require(type(reserved) in (int, float) and math.isfinite(reserved) and reserved >= 0,
            'Invalid inference reservation')
    expected_reservation = input_bound * input_rate + configuration['generation']['max_tokens'] * output_rate
    require(math.isclose(reserved, expected_reservation, abs_tol=1e-12), 'Inference reservation arithmetic differs')
    require(cost is None or (type(cost) in (int, float) and math.isfinite(cost) and 0 <= cost <= reserved),
            'Inference cost is negative, non-finite, or exceeds its reservation')
    response = call.get('response')
    if isinstance(response, dict):
        equal(json.loads(call['response_text']), response, 'Parsed response differs from preserved raw text')
        equal(hashlib.sha256(call['response_text'].encode()).hexdigest(), call['response_sha256'],
              'Preserved raw response checksum differs')
        usage = response.get('usage') or {}
        prompt_tokens, output_tokens = usage.get('prompt_tokens'), usage.get('completion_tokens')
        usable_usage = (type(prompt_tokens) is int and 0 <= prompt_tokens <= input_bound
                        and type(output_tokens) is int and 0 <= output_tokens <= configuration['generation']['max_tokens'])
        if usable_usage:
            require(cost is not None and math.isclose(cost, prompt_tokens * input_rate + output_tokens * output_rate, abs_tol=1e-12),
                    'Provider token charge arithmetic differs')
        else:
            equal(cost, None, 'Unusable provider usage was reported as a known cost')
        if call['status'] == 'invalid_response' and call.get('failure') == 'incomplete_generation':
            require(response['choices'][0].get('finish_reason') != 'stop', 'Complete generation mislabeled incomplete')
        if call['status'] == 'invalid_response' and call.get('failure') == 'provider_or_action_contract':
            try:
                choice = response['choices'][0]
                require(choice.get('finish_reason') == 'stop', 'Incomplete generation has wrong failure category')
                original_ai.parse_action(choice['message'].get('content'), public)
            except (ValueError, KeyError, TypeError, IndexError, AttributeError):
                pass
            else:
                raise ValueError('A valid stopped action was mislabeled as a model/provider contract failure')

    if call['status'] != 'completed':
        require(decision['controller_failure'], 'Inference failure was not marked as a controller failure')
        return None
    require(call['dispatched'], 'Usable inference was never dispatched')
    choice = call['response']['choices'][0]
    equal(choice['finish_reason'], 'stop', 'Incomplete generation was marked successful')
    action = original_ai.parse_action(choice['message']['content'], public)
    equal(call['action'], action, 'Saved action differs from strict raw parsing')
    require(not decision['controller_failure'], 'Successful inference was marked failed')
    return action


def recovered_solver_contract(state, slots, details, horizon, audits, configuration):
    """Recover an applied commitment, never invent a lost optimizer result."""
    equal(details['status'], 'RECOVERED_FEASIBLE', 'Unknown recovered solver status')
    equal(details['optimal'], False, 'Recovered commitment cannot establish optimality')
    for key in ('original_solver_status', 'original_solver_best_bound', 'original_solver_wall_seconds'):
        equal(details[key], None, 'Lost optimizer metadata was fabricated')
    identifier = details['recovery_source_request_id']
    require(identifier in audits, 'Recovered commitment has no next-state request evidence')
    call = audits[identifier]
    equal(call['config_id'], configuration['id'], 'Recovered commitment uses another model configuration')
    equal(call['payload_sha256'], details['recovery_source_payload_sha256'], 'Recovered commitment payload binding differs')
    equal(call['payload_sha256'], digest(call['request']), 'Recovered next-state request checksum differs')
    public = json.loads(call['request']['messages'][1]['content'])
    original_ai.validate_view(public)
    require(public['clock_seconds'] > state['time'], 'Recovery evidence is not a later causal state')
    equal(public['episode_id'], engine.view_for(state, horizon)['episode_id'], 'Recovery evidence uses another episode')
    pending = {a['id']: a for a in public['pending']}
    active = {a['id']: a for a in public['active_commitments']}
    require(not state['closed_runways'] and all(a['runway'] == '28L' for a in state['aircraft']),
            'Prior pending runway cannot be uniquely reconstructed')
    expected = []
    for aircraft in state['aircraft']:
        identifier = aircraft['id']
        if identifier in active:
            landing, runway = active[identifier]['landing_seconds'], active[identifier]['runway']
        else:
            require(identifier in pending and pending[identifier]['current_slot_seconds'] is not None,
                    'Next causal view omits a prior applied commitment')
            landing, runway = pending[identifier]['current_slot_seconds'], '28L'
        expected.append({'aircraft_id': identifier, 'runway': runway, 'time': landing})
    equal(slots, expected, 'Recovered slots differ from the next actually recorded public state')
    by_id = {slot['aircraft_id']: slot for slot in slots}
    unfinished = sum(by_id[a['id']]['time'] + a['exit_occupancy'] + 90 > horizon for a in state['aircraft'])
    weight = len(state['aircraft']) * 20000 + 1
    equal(details['objective_order'], ['unfinished_aircraft_at_horizon', 'sum_landing_delay_seconds'], 'Recovered objective changed')
    equal(details['unfinished_weight'], weight, 'Recovered completion priority weight differs')
    equal(details['unfinished_aircraft'], unfinished, 'Recovered completion objective differs')
    require(math.isclose(details['sum_landing_delay_seconds'], sum(by_id[a['id']]['time'] - a['requested'] for a in state['aircraft']), abs_tol=1e-6),
            'Recovered delay objective differs')
    equal(details['objective'], weight * unfinished + sum(slot['time'] for slot in slots), 'Recovered objective arithmetic differs')


def verify_row(episode, row, audits, selected, configuration=None):
    """Verify one real runtime row; use this before publishing a worker result."""
    controller = row.get('engine_controller', row['controller'])
    require(controller in ('scripted', 'deterministic', 'ai'), 'Unknown engine controller')
    if controller == 'ai':
        require(configuration is not None, 'AI replay requires its frozen configuration')
        equal(row['controller'], configuration['id'], 'Row/configuration mismatch')
    else:
        equal(row['controller'], controller, 'Reference mislabeled as a model')
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
        original_ai.validate_view(public)
        action = None
        if controller == 'ai':
            engine_id = f"cl-{digest(original_ai.SYSTEM_PROMPT)[:12]}:{episode['id']}:17:{int(now)}"
            identifier = configuration['id'] + ':' + engine_id
            require(identifier in audits and identifier not in selected, 'Missing or repeated selected AI decision')
            call = audits[identifier]
            equal(call['engine_request_id'], engine_id, 'Wrapped inference identity differs')
            selected[identifier] = call
            action = check_call(call, public, decision, configuration)
        else:
            require(not decision['controller_failure'], 'Reference has an inference failure')
        proposed = decision['proposed_slots']
        method = 'deterministic' if decision['controller_failure'] else controller
        if method in ('scripted', 'ai'):
            expected = controllers.propose(state, method, horizon, order=action['order'] if action else None)
            equal(proposed, expected['slots'], 'Ordered decoder did not apply the actual action')
            equal(decision['proposed_solver']['status'], expected['solver']['status'], 'Ordered decoder status differs')
        if proposed:
            original.schedule_contract(state, proposed)
            if method == 'deterministic':
                if decision['proposed_solver']['status'] == 'RECOVERED_FEASIBLE':
                    require(configuration is not None and decision['controller_failure'], 'Only a recorded AI failure can use recovered fallback evidence')
                    recovered_solver_contract(state, proposed, decision['proposed_solver'], horizon, audits, configuration)
                else:
                    original.solver_contract(state, proposed, decision['proposed_solver'], horizon)
            verdict = verify_plan(state, original.bound_plan(state, proposed))
        else:
            verdict = {'status': 'infeasible', 'checks': []}
        equal(decision['proposal_status'], verdict['status'], 'Proposal verification differs')
        equal(decision['proposal_failed_checks'], [c['id'] for c in verdict['checks'] if c['status'] != 'pass'],
              'Proposal failed checks differ')
        expected_fallback = decision['controller_failure'] or verdict['status'] != 'pass'
        equal(decision['fallback_used'], expected_fallback, 'Fallback reporting differs')
        applied_method = 'deterministic_fallback' if decision['controller_failure'] else controller
        applied_slots, applied = proposed, verdict
        if verdict['status'] != 'pass':
            fallback = controllers.propose(state, 'scripted', horizon)
            applied_slots = fallback['slots']
            applied_method = 'scripted_fallback'
            applied = (verify_plan(state, original.bound_plan(state, applied_slots)) if applied_slots else
                       {'status': 'infeasible', 'checks': []})
        equal(decision['applied_controller'], applied_method, 'Applied controller provenance differs')
        equal(decision['applied_status'], applied['status'], 'Applied verification status differs')
        if applied['status'] == 'pass':
            equal(decision['slots'], applied_slots, 'Executed reservations differ from checked reservations')
            original.schedule_contract(state, applied_slots)
            active_before = {a['id']: copy.deepcopy(a) for a in state['aircraft'] if a['trajectory'][0]['t'] <= now}
            equal(engine.commit(state, original.bound_plan(state, applied_slots))['status'], 'pass', 'Replay commit rejected')
            for aircraft in state['aircraft']:
                if aircraft['id'] in active_before:
                    equal(aircraft, active_before[aircraft['id']], 'Commit changed admitted motion')
        else:
            equal(decision['slots'], [], 'Unchecked reservations were executed')
    equal(cursor, len(episode['entries']), 'Some source demand was never released')
    equal(index, len(row['decisions']), 'Extra runtime decisions found')
    actual = engine.outcome(state, episode, row['decisions'], horizon)
    equal(actual, {key: value for key, value in row.items() if key not in ('controller', 'engine_controller')},
          'Replayed episode outcomes differ')
    for flight, aircraft in zip(actual['flights'], state['aircraft']):
        delay = (max(0, aircraft['scheduled'] - aircraft['requested']) if flight['landed'] else
                 max(0, horizon - aircraft['requested']))
        equal(flight['added_delay_seconds'], round(delay, 3), 'Censored all-demand delay arithmetic differs')
        equal(flight['completed'], bool(aircraft['committed'] and aircraft['trajectory'][-1]['t'] <= horizon),
              'Completion differs from executed motion')
    return actual


def _usage(calls):
    return {'calls': len(calls), 'statuses': dict(Counter(call['status'] for call in calls)),
            'successful_calls': sum(call['status'] == 'completed' for call in calls),
            'reported_cost_usd': sum(call.get('cost_usd') or 0 for call in calls),
            'unknown_cost_requests': sum(call.get('cost_usd') is None for call in calls),
            'reserved_usd': sum(call['reserved_usd'] for call in calls)}


def verify_preflight(master, plan):
    """Bind ten unscored smoke calls to one shared, causal development state."""
    from benchmark.closed_loop.traffic import load_episodes as load_development
    episode = load_development('train')[0]
    state = engine.initial_state(episode, 17)
    for number, entry in enumerate(episode['entries'][:2], 1):
        engine.add_aircraft(state, entry, episode['warmup_start'], number)
    state['time'] = math.ceil(max(a['known_since'] for a in state['aircraft']) / 300) * 300
    public = engine.view_for(state, 4500)
    results = {}
    for configuration in plan['configurations']:
        path = Path(master) / 'preflight' / configuration['id'] / 'calls.jsonl'
        records = original.rows(path)
        equal(len(records), 1, 'Expected one unscored preflight call per configuration')
        call = records[0]
        equal(call['engine_request_id'], 'preflight-development-20260803-v1', 'Preflight development identity differs')
        equal(call['request_id'], configuration['id'] + ':' + call['engine_request_id'], 'Preflight wrapped identity differs')
        action = check_call(call, public, {'controller_failure': call['status'] != 'completed'}, configuration)
        require(action is not None, 'Frozen configuration did not pass development preflight')
        characters = call['reasoning_content_characters']
        if configuration['reasoning'] == 'off':
            equal(characters, 0, 'Reasoning OFF preflight emitted a nonempty reasoning channel')
        else:
            require(characters > 0, 'Reasoning ON preflight did not emit a reasoning channel')
        results[configuration['id']] = {'status': call['status'], 'reasoning_content_characters': characters,
                                       'cost_usd': call['cost_usd'], 'scored': False}
    return results


def verify_budget(master, plan, selected):
    """Reconcile dispatched evidence with the shared transactional spending cap."""
    path = Path(master) / 'budget.sqlite3'
    require(path.exists(), 'Missing shared inference ledger')
    budget = plan['budget']
    equal(budget['automatic_paid_retries'], 0, 'Plan permits automatic paid retries')
    with sqlite3.connect('file:' + str(path.resolve()) + '?mode=ro', uri=True) as db:
        stored = db.execute('SELECT cap_usd FROM benchmark_budgets WHERE id=?', (budget['id'],)).fetchone()
        require(stored is not None, 'Shared budget identity is absent')
        equal(stored[0], budget['cap_usd'], 'Shared budget cap differs from plan')
        reservations = db.execute(
            'SELECT request_id,payload_sha256,reserved_usd,actual_usd,status,record_json '
            'FROM benchmark_reservations WHERE budget_id=?', (budget['id'],)).fetchall()
    by_id = {row[0]: row for row in reservations}
    preflight = {}
    for audit_path in sorted(Path(master).glob('preflight/*/calls.jsonl')):
        for call in original.rows(audit_path):
            equal(call['config_id'], audit_path.parent.name, 'Preflight configuration path differs')
            equal(call['engine_request_id'], 'preflight-development-20260803-v1', 'Preflight identity differs')
            require(call['request_id'] not in preflight and call['request_id'] not in selected, 'Preflight/scored request identity reused')
            preflight[call['request_id']] = call
    require(len(preflight) == 10, 'Expected exactly ten unscored development preflight calls')
    all_calls = {**preflight, **selected}
    dispatched = {identifier: call for identifier, call in all_calls.items() if call['dispatched']}
    equal(set(by_id), set(dispatched), 'Shared budget contains orphaned or missing dispatched requests')
    for identifier, call in dispatched.items():
        _, payload_hash, reserved, cost, status, serialized = by_id[identifier]
        equal(payload_hash, call['payload_sha256'], 'Ledger payload binding differs')
        equal(reserved, call['reserved_usd'], 'Ledger reservation differs')
        equal(cost, call.get('cost_usd'), 'Ledger cost differs')
        equal(status, call['status'], 'Ledger status differs')
        require(serialized is not None, 'Inference reservation remains unresolved')
        equal(json.loads(serialized), {key: value for key, value in call.items() if key != 'reused_from_persistent_ledger'},
              'Ledger final record differs from raw audit')
    reserved = sum(row[2] for row in reservations)
    known = sum(row[3] or 0 for row in reservations)
    unresolved_exposure = sum(row[2] for row in reservations if row[3] is None)
    require(known + unresolved_exposure <= budget['cap_usd'] + 1e-9, 'Settled shared spending/exposure cap was exceeded')
    return {'budget_id': budget['id'], 'cap_usd': budget['cap_usd'],
            'dispatched_requests': len(dispatched), 'reserved_usd': reserved,
            'known_cost_usd': known, 'unknown_reserved_exposure_usd': unresolved_exposure,
            'settled_cost_plus_unknown_exposure_usd': known + unresolved_exposure,
            'unscored_development_preflight_calls': len(preflight),
            'unknown_cost_requests': sum(row[3] is None for row in reservations),
            'unresolved_reservations': 0, 'paid_retries': 0}


def execution_records(path):
    # Finalization may print a traceback after all futures finish because an
    # interrupted job requires explicit recovery. Preserve and hash that log;
    # consume only its JSON execution records and verify every result identity.
    records = []
    for line in Path(path).read_text().splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def verify_recoveries(master, plan, stored, audits):
    master = Path(master)
    paths = sorted((master / 'recoveries').glob('*/*.json'))
    if not paths:
        return {'recovered_jobs': 0, 'reconstructed_fallback_decisions': 0, 'jobs': []}
    amendment_path = master / 'recovery-execution-amendment.json'
    amendment = read(amendment_path)
    equal(amendment['version'], 'historical-admission-recovery-execution-amendment-v1', 'Unknown recovery amendment version')
    equal(amendment['maximum_main_workers_per_base_model'], 6, 'Recovery changed original concurrency')
    equal(amendment['maximum_helper_workers_per_base_model'], 18, 'Recovery changed helper concurrency')
    equal(amendment['maximum_recovery_workers_per_base_model'], 1, 'Recovery ownership is not bounded')
    equal(amendment['maximum_combined_workers_per_base_model'], 25, 'Recovery combined concurrency differs')
    equal(amendment['minimum_shared_per_model_dispatch_seconds'], 2.2, 'Recovery changed dispatch pacing')
    equal(amendment['cap_usd'], plan['budget']['cap_usd'], 'Recovery changed spending cap')
    equal(amendment['budget_id'], plan['budget']['id'], 'Recovery changed shared budget')
    equal(amendment['scoring_changes'], False, 'Recovery changed scoring')
    equal(amendment['payload_changes'], False, 'Recovery changed model payloads')
    equal(amendment['automatic_paid_retries'], 0, 'Recovery permits repeated paid requests')
    owned = {(job['configuration'], job['episode_id']) for job in amendment['owned_jobs']}
    equal(owned, {('nemotron-3.5-super-vl-off', '2026-08-25-1500'),
                  ('nemotron-3.5-lightning-on', '2026-08-24-1200')}, 'Unexpected recovery jobs')
    matrix = {(row['controller'], row['episode_id']): row for row in stored}
    jobs, recovered_count = [], 0
    for path in paths:
        manifest = read(path)
        key = manifest['configuration'], manifest['episode_id']
        require(key in owned, 'Recovery manifest claims an unapproved window')
        equal(manifest['status'], 'completed', 'Interrupted window recovery is incomplete')
        equal(manifest['execute'], True, 'A dry-run recovery was scored')
        equal(manifest['execution_amendment'], {'file': 'recovery-execution-amendment.json', 'sha256': sha(amendment_path)},
              'Recovery manifest execution amendment binding differs')
        equal(manifest['concurrency'], {key: amendment[key] for key in (
              'maximum_main_workers_per_base_model', 'maximum_helper_workers_per_base_model',
              'maximum_recovery_workers_per_base_model', 'maximum_combined_workers_per_base_model',
              'minimum_shared_per_model_dispatch_seconds')}, 'Recovery manifest concurrency differs')
        source = master / manifest['source_snapshot']
        equal(sha(source), manifest['source_sha256'], 'Recovery source snapshot differs')
        equal(manifest['source_sha256'], amendment['helper_source_sha256'], 'Recovery source differs from execution amendment')
        equal(sha(ROOT / 'benchmark/sweep/recover.py'), manifest['source_sha256'], 'Current recovery source differs')
        equal(sha(master / manifest['result']), manifest['result_sha256'], 'Recovered outcome checksum differs')
        equal(read(master / manifest['result']), matrix[key], 'Recovered outcome does not match the scored matrix')
        directory = master / 'configs' / key[0] / 'episodes' / key[1]
        original_audit = directory / 'recovery/original-calls.jsonl'
        original_progress = directory / 'recovery/original-progress.jsonl'
        equal(sha(original_audit), manifest['original_calls_sha256'], 'Original interrupted audit changed')
        equal(sha(original_progress), manifest['original_progress_sha256'], 'Original interrupted progress changed')
        final_audit = directory / 'calls.jsonl'
        equal(sha(final_audit), manifest['final_audit_sha256'], 'Recovered audit changed')
        require(final_audit.read_bytes().startswith(original_audit.read_bytes()), 'Recovery rewrote an original request record')
        prior = original.rows(original_audit)
        equal(len(prior), manifest['original_calls'], 'Original paid-call count differs')
        equal(prior[-1]['status'], 'ambiguous_failure', 'Interrupted prefix does not end with an ambiguous result')
        require(prior[-1]['cost_usd'] is None and prior[-1]['dispatched'], 'Interrupted unknown charge was lost')
        progressed = {record['time']: record for record in original.rows(original_progress)}
        expected_clocks = sorted(json.loads(call['request']['messages'][1]['content'])['clock_seconds']
                                 for call in prior[:-1] if call['status'] != 'completed')
        equal(manifest['reconstructed_fallback_clock_seconds'], expected_clocks, 'Recovered fallback clocks differ')
        recovered_decisions = [d for d in matrix[key]['decisions'] if d['proposed_solver']['status'] == 'RECOVERED_FEASIBLE']
        equal([d['time_seconds'] for d in recovered_decisions], expected_clocks, 'Recovered solver evidence count differs')
        for decision in recovered_decisions:
            progress = progressed[decision['time_seconds']]
            require(progress['applied_status'] == 'pass' and progress['fallback'] is True,
                    'A reconstructed commitment was not actually applied before interruption')
            evidence = audits[decision['proposed_solver']['recovery_source_request_id']]
            index = next(i for i, call in enumerate(prior) if json.loads(call['request']['messages'][1]['content'])['clock_seconds'] == decision['time_seconds'])
            equal(evidence, prior[index + 1], 'Recovery does not use the immediately next original causal request')
        equal(manifest['reused_cached_decisions'], len(prior), 'Recovery did not reuse every original decision')
        equal(manifest['new_decision_attempts'], len(original.rows(final_audit)) - len(prior), 'Recovery new-decision count differs')
        recovered_count += len(recovered_decisions)
        jobs.append({'configuration': key[0], 'episode_id': key[1], 'manifest_sha256': sha(path),
                     'result_sha256': manifest['result_sha256'], 'source_sha256': manifest['source_sha256'],
                     'original_calls': len(prior), 'reconstructed_fallback_decisions': len(recovered_decisions),
                     'original_calls_preserved': True, 'paid_retries': 0})
    equal({(job['configuration'], job['episode_id']) for job in jobs}, owned, 'Recovery manifest matrix is incomplete')
    return {'recovered_jobs': len(jobs), 'reconstructed_fallback_decisions': recovered_count,
            'jobs': jobs, 'execution_amendment_sha256': sha(amendment_path),
            'maximum_combined_workers_per_base_model': 25, 'maximum_recovery_workers_per_base_model': 1,
            'minimum_shared_per_model_dispatch_seconds': 2.2, 'spending_cap_usd': plan['budget']['cap_usd'],
            'payload_and_scoring_unchanged': True, 'original_paid_requests_preserved': True, 'paid_retries': 0,
            'unknown_original_fallback_producer_decisions': recovered_count,
            'original_solver_status_and_bound_recovered': False,
            'limits': ['Four original checked fallback schedules are reconstructed exactly; their original CP-SAT versus secondary-scripted producer and proposal verdict were not serialized.',
                       'RECOVERED_FEASIBLE attests current independent feasibility. Applied-controller labels describe replay policy, not a recovered original optimizer result.']}


def verify_orchestration(master, plan, stored, recovery):
    """A helper may change concurrency only with complete, disjoint ownership proof."""
    master = Path(master)
    amendment_path = master / 'orchestration-amendment.json'
    if not amendment_path.exists():
        return {'amended': False}
    amendment = read(amendment_path)
    completion_path = master / 'orchestration-worker-completion.json'
    require(completion_path.exists(), 'Concurrency helper is not complete')
    completion = read(completion_path)
    equal(amendment['kind'], 'execution_concurrency_only', 'Unknown execution amendment kind')
    equal(amendment['plan_sha256'], sha(master / 'plan.json'), 'Execution amendment plan binding differs')
    helper = ROOT / 'benchmark/sweep/parallel.py'
    equal(sha(helper), amendment['helper_sha256'], 'Execution helper source changed')
    equal(sha(master / 'frozen_source/benchmark/sweep/parallel.py'), amendment['helper_sha256'],
          'Frozen execution helper source differs')
    equal(amendment['original_workers'], plan['concurrency']['workers'], 'Original worker count differs')
    equal(amendment['original_workers_per_model'], plan['concurrency']['per_model_workers'],
          'Original per-model worker count differs')
    equal(amendment['additional_workers'], 90, 'Additional worker count differs')
    equal(amendment['additional_workers_per_model'], 18, 'Additional per-model worker count differs')
    equal(amendment['maximum_combined_workers_per_model'], 24, 'Combined per-model worker count differs')
    equal(amendment['minimum_per_model_dispatch_seconds'], 2.2, 'Shared dispatch pacing changed')
    equal(amendment['spending_cap_usd'], plan['budget']['cap_usd'], 'Shared spending cap changed')
    equal(amendment['unchanged'], ['model checkpoints', 'reasoning controls', 'task prompt',
          'output/token/deadline bounds', 'traffic', 'simulator', 'safety gate', 'decoder',
          'fallbacks', 'objective', 'request pacing', 'spending cap'], 'Execution amendment changed semantic scope')
    expected = {(configuration['id'], episode_id) for configuration in plan['configurations']
                for episode_id in plan['episodes'] if episode_id[:10] in ('2026-08-28', '2026-08-29', '2026-08-30')}
    def jobs(value):
        equal(len(value), 180, 'Expected exactly 180 helper-owned windows')
        actual = {(job['controller'], job['episode_id']) for job in value}
        equal(len(actual), 180, 'Execution helper repeats a window')
        equal(actual, expected, 'Execution helper ownership differs from the last three days')
        return actual
    jobs(amendment['jobs'])
    jobs(completion['jobs'])
    equal(completion['completed'], True, 'Execution helper did not complete')
    equal(completion['helper_sha256'], amendment['helper_sha256'], 'Completion helper source binding differs')
    equal(completion['amendment_sha256'], sha(amendment_path), 'Completion amendment binding differs')
    # The forward runner does not acquire new locks. Its later reuse of every
    # helper-owned row is the required evidence that it did not redispatch one.
    main_log = master / 'execution.log'
    execution = execution_records(main_log)
    finished = [record for record in execution if 'finished' in record]
    failures = [record for record in execution if 'failed' in record]
    recovered_keys = {(job['configuration'], job['episode_id']) for job in recovery['jobs']}
    equal(len(finished) + len(failures), 504, 'Original runner has not acknowledged all 504 windows')
    equal({record['finished'] for record in finished}, set(range(1, len(finished) + 1)), 'Original completion sequence differs')
    equal({(record['failed'], record['episode']) for record in failures}, recovered_keys, 'Original failures differ from explicit completed recoveries')
    equal(len(failures), len(recovered_keys), 'Original failure identity repeats')
    require(all(record['error_type'] == 'IncompleteRead' for record in failures), 'Unknown original execution failure')
    indexed = {(record['controller'], record['episode']): record for record in finished}
    equal(len(indexed), len(finished), 'Original runner repeats a controller/window')
    matrix = {(row['controller'], row['episode_id']): row for row in stored}
    equal(set(indexed) | recovered_keys, set(matrix), 'Original completion/recovery proof does not cover the exact scored matrix')
    require(not set(indexed) & recovered_keys, 'A recovered window also claims original completion')
    for key, record in indexed.items():
        equal(record['expected'], 504, 'Original runner expected a different result matrix')
        row = matrix[key]
        for recorded, field in (('completed', 'completed'), ('spawned', 'spawned'),
                                ('violations', 'executed_violations'), ('fallbacks', 'fallback_decisions')):
            equal(record[recorded], row[field], 'Original execution log/result differs: ' + field)
    require(all(indexed[key]['reused'] is True for key in expected),
            'Original runner redispatched a helper-owned window')
    helper_log = master / 'parallel.log'
    helper_records = [ast.literal_eval(line) for line in helper_log.read_text().splitlines() if line.strip()]
    helper_finished = [record for record in helper_records if 'helper_finished' in record]
    equal(len(helper_finished), 180, 'Helper log does not contain all 180 outcomes')
    equal({record['helper_finished'] for record in helper_finished}, set(range(1, 181)), 'Helper completion sequence differs')
    equal({(record['controller'], record['episode']) for record in helper_finished}, expected,
          'Helper completion log has overlapping or missing ownership')
    return {'amended': True, 'kind': 'execution_concurrency_only', 'plan_sha256': sha(master / 'plan.json'),
            'helper_sha256': amendment['helper_sha256'], 'amendment_sha256': sha(amendment_path),
            'completion_sha256': sha(completion_path), 'main_execution_log_sha256': sha(main_log),
            'helper_execution_log_sha256': sha(helper_log), 'helper_owned_windows': 180,
            'original_runner_reused_windows': 180, 'original_runner_finished_windows': len(finished),
            'original_runner_recovered_failed_windows': len(recovered_keys),
            'total_acknowledged_windows': 504,
            'minimum_per_model_dispatch_seconds': 2.2, 'maximum_combined_workers_per_model': 24,
            'spending_cap_usd': plan['budget']['cap_usd'], 'semantic_settings_unchanged': True,
            'all_helper_jobs_owned_once': True}


def verify_run(master, output):
    """Attest only a complete 42-window, ten-configuration, two-reference matrix."""
    from .traffic import DATA_DIR, load_episodes

    master = Path(master)
    plan, summary = read(master / 'plan.json'), read(master / 'summary.json')
    equal(summary['status'], 'completed', 'Sweep is incomplete')
    equal(plan['engine_config'], engine.CONFIG, 'Frozen simulator configuration changed')
    equal(plan['runtime']['python'], platform.python_version(), 'Python runtime changed')
    equal(plan['runtime']['ortools'], importlib.metadata.version('ortools'), 'Optimizer runtime changed')
    equal(summary['plan_sha256'], sha(master / 'plan.json'), 'Plan checksum differs')
    for name, expected in plan['source_hashes'].items():
        equal(sha(ROOT / name), expected, 'Current frozen source differs: ' + name)
        equal(sha(master / 'frozen_source' / name), expected, 'Archived frozen source differs: ' + name)
    for name in ('plan.json', 'runs.json'):
        equal(summary['artifacts'][name], sha(master / name), 'Result artifact checksum differs: ' + name)
    equal(sha(DATA_DIR / 'evaluation.json'), plan['traffic_sha256'], 'Traffic bytes changed')
    equal(sha(DATA_DIR / 'manifest.json'), plan['traffic_manifest_sha256'], 'Traffic manifest changed')
    equal(summary['source_hashes'], plan['source_hashes'], 'Summary source binding differs')
    equal(plan['references'], ['scripted', 'deterministic'], 'Matched reference controllers differ')
    equal(plan['date_range'], ['2026-08-24', '2026-08-30'], 'Evaluation date range differs')
    episodes = load_episodes()
    source_verification = verify_traffic_source(episodes, DATA_DIR)
    equal(len(episodes), 42, 'Expected 42 fixed windows')
    equal(sorted({e['local_date'] for e in episodes}), BOUND_DATES, 'Wrong evaluation days')
    equal([e['id'] for e in episodes], plan['episodes'], 'Episode membership differs')
    expected_flights = [entry['flight_id'] for episode in episodes for entry in episode['entries']]
    equal(len(set(expected_flights)), len(expected_flights), 'A source arrival operation is reused')
    configurations = plan['configurations']
    equal(len(configurations), 10, 'Expected ten model configurations')
    equal(len({config['id'] for config in configurations}), 10, 'Configuration identity repeats')
    equal(len({config['model'] for config in configurations}), 5, 'Expected five distinct base models')
    for model in {config['model'] for config in configurations}:
        equal({config['reasoning'] for config in configurations if config['model'] == model}, {'on', 'off'},
              'Each model requires reasoning ON and OFF configurations')
    from .models import validate_configuration
    for configuration in configurations:
        validate_configuration(configuration)
    generations = [config['generation'] for config in configurations]
    equal({generation['max_tokens'] for generation in generations}, {8192}, 'Output budget differs across configurations')
    require(all(generation['seed'] == 17 and generation['stream'] is False for generation in generations),
            'Seed or streaming contract differs')
    by_configuration = {config['id']: config for config in configurations}
    controller_ids = ['scripted', 'deterministic', *by_configuration]
    stored = read(master / 'runs.json')
    matrix = {(row['controller'], row['episode_id']): row for row in stored}
    equal(len(stored), 504, 'Expected 504 controller/window results')
    equal(len(matrix), 504, 'Duplicate controller/window result')
    equal(set(matrix), {(controller, episode['id']) for controller in controller_ids for episode in episodes},
          'Incomplete matched matrix')
    audits, audit_counts = raw_audits(master)
    selected, replayed = {}, []
    for controller in controller_ids:
        for episode in episodes:
            row = matrix[controller, episode['id']]
            equal(row['seed'], 17, 'Unexpected seed')
            equal(row['variant'], 'nominal', 'Unexpected scenario variant')
            equal(row, read(master / 'episodes' / controller / (episode['id'] + '.json')), 'Per-window file differs')
            verify_row(episode, row, audits, selected, by_configuration.get(controller))
            replayed.append(row)
    equal(set(selected), set(audits), 'Unselected or missing inference audit records')
    totals = {controller: aggregate([row for row in replayed if row['controller'] == controller])
              for controller in controller_ids}
    equal(totals, summary['controllers'], 'Recomputed controller aggregates differ')
    usage = {config: _usage([call for call in selected.values() if call['config_id'] == config])
             for config in by_configuration}
    equal(set(summary['ai_usage']), set(usage), 'Inference summary configuration membership differs')
    for config_id, counters in usage.items():
        for key, value in counters.items():
            recorded = summary['ai_usage'][config_id][key]
            if key in ('reserved_usd', 'reported_cost_usd'):
                require(math.isclose(value, recorded, abs_tol=1e-9), 'Inference accounting differs: ' + config_id + '/' + key)
            else:
                equal(value, recorded, 'Inference accounting differs: ' + config_id + '/' + key)
    preflight_verification = verify_preflight(master, plan)
    budget_verification = verify_budget(master, plan, selected)
    recovery_verification = verify_recoveries(master, plan, stored, audits)
    orchestration_verification = verify_orchestration(master, plan, stored, recovery_verification)
    result = {'passed': True, 'verification_kind': 'independent_complete_matrix_causal_replay',
              'verifier_sha256': sha(__file__),
              'artifacts': {name: sha(master / name) for name in ('plan.json', 'runs.json', 'summary.json')},
              'counts': {'episodes': 42, 'controller_episode_results': 504,
                         'source_arrival_operations_per_controller': len(expected_flights),
                         'base_models': 5, 'model_configurations': 10,
                         'replayed_decisions': sum(row['decision_count'] for row in replayed),
                         'selected_ai_decisions': len(selected), **audit_counts},
              'ai_usage_independently_recomputed': usage, 'source_verification': source_verification,
              'budget_verification': budget_verification,
              'unscored_development_preflight_verification': preflight_verification,
              'orchestration_verification': orchestration_verification,
              'recovery_verification': recovery_verification,
              'checks': ['frozen source/runtime/data checksums', 'complete matched matrix',
                         'causal traffic and weather replay', 'strict raw model request/response binding',
                         'ordered action decoding', 'optimizer feasibility and recorded objective',
                         'independent verification before every commit', 'immutable admitted motion',
                         'executed safety and all-demand delay replay', 'controller aggregates and inference accounting'],
              'negative_qa': original.negative_qa(episodes[0]),
              'limits': ['No provider requests were made during verification.',
                         'August 8–9 are excluded from generated datasets, model inputs and evaluation.',
                         'Anytime optimizer output is checked, not assumed optimal or reproduced identically.',
                         'Rows include counted checked fallbacks; upstream feeder/queue safety remains outside scope.']}
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

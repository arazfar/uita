"""Compare frozen model runs on the same historical-order proxy cases."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
from collections import Counter
from . import core


def read(path):
    return json.loads(Path(path).read_text())


def lines(path):
    return [json.loads(row) for row in Path(path).read_text().splitlines() if row.strip()]


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def audit_run(directory, plan, summary, cases):
    """Reconstruct decisions from raw paid responses before calculating results."""
    if summary['plan_sha256'] != sha_file(directory/'plan.json'):
        raise ValueError('Run plan checksum mismatch')
    for name in ['plan.json', 'prompts.jsonl', 'calls.jsonl', 'scores.jsonl']:
        if summary['artifacts'][name] != sha_file(directory/name):
            raise ValueError('Run artifact checksum mismatch: '+name)
    for name, key in [('core.py', 'core_sha256'), ('provider.py', 'provider_sha256'),
                      ('run_baseline.py', 'runner_sha256')]:
        if sha_file(directory/'frozen_source'/name) != plan[key]:
            raise ValueError('Frozen source checksum mismatch: '+name)
    if sha_file(Path(core.__file__)) != plan['core_sha256']:
        raise ValueError('Current scorer differs from the frozen run')
    expected_prompts = [{'case_id': c['case_id'], 'messages': core.model_messages(c)} for c in cases]
    if lines(directory/'prompts.jsonl') != expected_prompts:
        raise ValueError('Persisted prompts differ from frozen public inputs')
    if plan['case_ids'] != [c['case_id'] for c in cases] or plan['split'] != 'validation':
        raise ValueError('Run membership differs from frozen validation')
    calls = lines(directory/'calls.jsonl')
    indexed = {r['request_id']: r for r in calls}
    expected_ids = {directory.name+':'+c['case_id'] for c in cases}
    if len(indexed) != len(calls) or set(indexed) != expected_ids:
        raise ValueError('Paid-call audit has missing, duplicate or unexpected cases')
    decisions = {}
    for case in cases:
        call = indexed[directory.name+':'+case['case_id']]
        generation = {k: v for k, v in plan['generation'].items() if k != 'paid_retries'}
        expected = dict(generation, model=plan['model']['id'], stream=False,
                        messages=core.model_messages(case))
        if call['request'] != expected or call['payload_sha256'] != digest(expected):
            raise ValueError('Raw request differs from frozen prompt or generation settings')
        if call['paid_retries'] != 0:
            raise ValueError('Comparison forbids paid retries')
        action = None
        if call['status'] == 'completed':
            choice = call['response']['choices'][0]
            if choice['finish_reason'] != 'stop':
                raise ValueError('Incomplete response was marked completed')
            try:
                action = core.parse_action(choice['message']['content'], case['input'])
            except ValueError:
                pass
        decisions[case['case_id']] = (call, action)
    return calls, decisions


def wilson(correct, total):
    if not total:
        return [None, None]
    z = 1.959963984540054
    fraction = correct / total
    center = (fraction + z*z/(2*total))/(1+z*z/total)
    half = z*math.sqrt(fraction*(1-fraction)/total+z*z/(4*total*total))/(1+z*z/total)
    return [center-half, center+half]


def paired_test(wins, losses):
    """Exact two-sided sign/McNemar test on discordant paired binary outcomes."""
    n = wins + losses
    if not n:
        return 1.0
    return min(1.0, 2*sum(math.comb(n, i) for i in range(min(wins, losses)+1))/2**n)


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered)*fraction)-1)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('runs', nargs='+', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    cases = core.load_cases('validation')
    by_case = {c['case_id']: c for c in cases}
    expected_ids = set(by_case)
    manifest = read(core.DATA_DIR/'manifest.json')
    expected_sha = manifest['artifacts']['validation.jsonl']['sha256']
    references = {
        'free_flow_heuristic': {c['case_id']: core.scripted_action(c['input']) for c in cases},
        'older_observed_entry_first': {c['case_id']: {'order': [a['id'] for a in sorted(c['input']['aircraft'], key=lambda a: (-a['age_seconds'], a['id']))]} for c in cases},
        'always_A1': {c['case_id']: {'order': sorted(a['id'] for a in c['input']['aircraft'])} for c in cases},
        'candidate_list_order': {c['case_id']: {'order': [a['id'] for a in c['input']['aircraft']]} for c in cases},
    }
    reference_correct = {name: {case_id: core.evaluate_action(by_case[case_id], action)['next_arrival_correct']
                               for case_id, action in actions.items()} for name, actions in references.items()}
    models = []
    successful_sets = []
    per_case = {c['case_id']: {'case_id': c['case_id'],
                             'recorded_order': c['private']['historical_order'], 'models': {}} for c in cases}
    for directory in args.runs:
        summary = read(directory/'summary.json')
        plan = read(directory/'plan.json')
        if summary['status'] != 'completed' or plan['case_file_sha256'] != expected_sha:
            raise ValueError('Every run must finish the exact frozen validation split')
        if plan['prompt_sha256'] != hashlib.sha256(core.canonical(core.SYSTEM_PROMPT).encode()).hexdigest():
            raise ValueError('Model prompt differs from the frozen task')
        scores = [r for r in lines(directory/'scores.jsonl') if r['method'] == plan['controller_name']]
        scored = {r['case_id']: r for r in scores}
        if len(scores) != len(scored) or set(scored) != expected_ids:
            raise ValueError('Model run has missing, duplicate or unexpected cases')
        calls, decisions = audit_run(directory, plan, summary, cases)
        correct = {}
        valid_ids = set()
        for case_id, score in scored.items():
            call, action = decisions[case_id]
            if score['action'] != action or score['valid_action'] != (action is not None):
                raise ValueError('Saved decision differs from strict parsing of the raw response')
            metrics = core.evaluate_action(by_case[case_id], action) if action is not None else core.failed_metrics(by_case[case_id])
            if metrics != score['metrics']:
                raise ValueError('Saved score differs from independent recomputation')
            if action is not None:
                valid_ids.add(case_id)
                correct[case_id] = bool(metrics['next_arrival_correct'])
            else:
                correct[case_id] = False
            per_case[case_id]['models'][plan['model']['id']] = {
                'action': action, 'valid': action is not None, 'correct': correct[case_id],
                'status': call['status'], 'http_status': call.get('http_status'),
                'latency_seconds': call['latency_seconds'], 'reported_token_cost_usd': call.get('cost_usd')}
        latencies = [call['latency_seconds'] for case_id, (call, action) in decisions.items() if case_id in valid_ids]
        successes = sum(correct.values())
        actual = sum(r.get('cost_usd') or 0 for r in calls)
        unknown = sum(r.get('cost_usd') is None for r in calls)
        baseline = reference_correct['free_flow_heuristic']
        wins = sum(correct[k] and not baseline[k] for k in expected_ids)
        losses = sum(baseline[k] and not correct[k] for k in expected_ids)
        models.append({'model': plan['model']['id'], 'quantization': plan['model'].get('quantization'),
                       'run_directory': str(directory), 'cases': len(cases), 'valid_actions': len(valid_ids),
                       'correct': successes, 'accuracy': successes/len(cases), 'conditional_95pct_interval': wilson(successes, len(cases)),
                       'valid_response_accuracy': successes/len(valid_ids) if valid_ids else None,
                       'reported_token_cost_usd': actual, 'unknown_cost_requests': unknown,
                       'failure_counts': dict(Counter(('HTTP '+str(r.get('http_status'))) if r['status'] == 'http_failure' else r['status']
                                                      for r in calls if r['status'] != 'completed')),
                       'summary_sha256': sha_file(directory/'summary.json'),
                       'successful_response_median_seconds': statistics.median(latencies) if latencies else None,
                       'successful_response_p95_seconds': percentile(latencies, .95),
                       'wins_vs_free_flow': wins, 'losses_vs_free_flow': losses,
                       'paired_exact_p_value_unadjusted': paired_test(wins, losses),
                       'generation': plan['generation'], '_correct': correct, '_valid': valid_ids})
        successful_sets.append(valid_ids)
    common = set.intersection(*successful_sets) if successful_sets else set()
    for model in models:
        model['common_successful_cases'] = len(common)
        model['common_correct'] = sum(model['_correct'][k] for k in common)
        model['common_success_accuracy'] = model['common_correct']/len(common) if common else None
        del model['_correct'], model['_valid']
    refs = {name: {'correct': sum(rows.values()), 'cases': len(cases), 'accuracy': sum(rows.values())/len(cases),
                   'common_correct': sum(rows[k] for k in common),
                   'posthoc_diagnostic': name == 'older_observed_entry_first',
                   'common_success_accuracy': sum(rows[k] for k in common)/len(common) if common else None}
            for name, rows in reference_correct.items()}
    result = {'task': manifest['primary_task'], 'validation_cases': len(cases), 'validation_dates': ['2026-08-07'],
              'development_cases': manifest['artifacts']['train.jsonl']['cases'],
              'validation_sha256': expected_sha, 'models': models, 'references': refs,
              'common_success_case_ids': sorted(common), 'per_case_results': list(per_case.values()),
              'provenance_verified': True,
              'held_out': 'August 8–9 not queried, trained on, or evaluated',
              'limits': ['One binary recorded-operation-order prediction per two-arrival encounter.',
                         'Agreement with recorded order does not measure human ATC quality, safety or causal efficiency.',
                         'Position features are observed-entry snapshots, not full current radar histories.',
                         'All models receive the same inputs and task prompt; architecture-specific thinking controls are disclosed.',
                         'Intervals condition on this one validation day and do not establish generalization to other days.',
                         'The common-success intersection is a provider-success-selected diagnostic subset, not an unbiased test.',
                         'Older observed entry first was added after the initial run; it is a posthoc diagnostic reference.',
                         'Paired tests compare full-split operational outcomes including unavailable responses against free flow.',
                         'Unadjusted paired tests are exploratory; no multiple-comparison correction or model selection on final test.',
                         'Token costs are provider-usage estimates, not invoices; unknown charges are reported separately.',
                         'Fine-tuning was deferred by the user; no datasets uploaded or jobs submitted.']}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'comparison.json').write_text(json.dumps(result, indent=2)+'\n')
    out = ['# Model comparison on historical arrival order', '',
           'All runs use the same 141 validation pairs from August 7, 2026. August 8–9 remain untouched. No fine-tuning ran.', '',
           'The task predicts which of two arrivals appears first in the recorded operation roster. It does not grade authentic ATC commands or human control quality.', '',
           '| Model | Full 141 accuracy | Valid responses | Accuracy on own valid responses | Common '+str(len(common))+' accuracy | Median valid response | Known token cost / unknown requests |',
           '|---|---:|---:|---:|---:|---:|---:|']
    for m in sorted(models, key=lambda r: -r['accuracy']):
        latency = m['successful_response_median_seconds']
        latency_text = f'{latency:.2f}s' if latency is not None else '—'
        valid_text = f"{m['correct']}/{m['valid_actions']} = {m['valid_response_accuracy']:.1%}" if m['valid_actions'] else '—'
        common_text = f"{m['common_correct']}/{len(common)} = {m['common_success_accuracy']:.1%}" if common else '—'
        out.append(f"| {m['model']} | {m['correct']}/141 = {m['accuracy']:.1%} | {m['valid_actions']}/141 | {valid_text} | {common_text} | {latency_text} | ${m['reported_token_cost_usd']:.5f} / {m['unknown_cost_requests']} |")
    out += ['', '## Simple reference rules', '']
    for name, row in refs.items():
        label = ' (posthoc diagnostic)' if row['posthoc_diagnostic'] else ''
        out.append(f"- {name}{label}: {row['correct']}/141 = {row['accuracy']:.1%}; same common {len(common)}: {row['common_correct']}/{len(common)}.")
    out += ['', f'Common successful-case intersection: {len(common)}/141. Invalid or unavailable responses count as incorrect in the full-split accuracy above.', '',
            'With two aircraft, next-arrival accuracy, exact-order accuracy and pairwise agreement are the same binary metric. Synthetic scheduling checks are kept out of the primary leaderboard.', '',
            'The common subset depends on provider success and is a selected diagnostic, not an unbiased test. Own-valid columns use different cases for each model. Full-split accuracy counts unavailable decisions as incorrect.', '',
            '## Service failures', '',
            *[f"- {m['model']}: {json.dumps(m['failure_counts'], sort_keys=True)}." for m in models], '',
            '## Limits', '', *['- '+text for text in result['limits']], '',
            'Detailed scores, generation settings, confidence intervals, paired comparisons and run hashes are in comparison.json and each source run directory.']
    (args.output/'comparison.md').write_text('\n'.join(out)+'\n')
    print(json.dumps({'models': len(models), 'common_successful_cases': len(common),
                      'results': [{k: m[k] for k in ['model', 'correct', 'accuracy', 'valid_actions']} for m in models]}, indent=2))

if __name__ == '__main__':
    main()

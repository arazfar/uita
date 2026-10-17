"""Resume independent episode workers and finalize only a complete matched matrix."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import os

from .ai import AIController, GENERATION, SYSTEM_PROMPT, parse_action
from .engine import CONFIG, canonical, simulate
from .run import ROOT, aggregate, sha, write
from .traffic import DATA_DIR, load_episodes
from benchmark.provider import ReservationLedger


def frozen(master):
    plan = json.loads((master/'plan.json').read_text())
    if plan['controllers'] != ['scripted', 'deterministic', 'ai'] or plan['split'] != 'validation':
        raise ValueError('Workers require the complete three-controller validation plan')
    for name, expected in plan['source_hashes'].items():
        if sha(ROOT/name) != expected:
            raise ValueError('Frozen evaluator source differs: '+name)
    if sha(DATA_DIR/'validation.json') != plan['traffic_sha256']:
        raise ValueError('Frozen historical traffic differs')
    episodes = load_episodes('validation')
    if [e['id'] for e in episodes] != plan['episodes'] or len(episodes) != 6:
        raise ValueError('Expected all six validation windows')
    return plan, episodes


def work(master, episode_id, execute):
    plan, episodes = frozen(master)
    episode = next((e for e in episodes if e['id'] == episode_id), None)
    if episode is None:
        raise ValueError('Unknown frozen validation episode')
    if not execute:
        print(json.dumps({'status': 'plan_only', 'episode': episode_id, 'paid_calls': 0}))
        return
    target = master/'episodes'/f'{episode_id}-ai.json'
    if target.exists():
        raise ValueError('Episode already completed; workers cannot replace outcomes')
    directory = master/'workers'/episode_id
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory/'running.lock'
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.write(descriptor, str(os.getpid()).encode());os.close(descriptor)
    try:
        ai = AIController(directory, cap_usd=plan['inference_cap_usd'])
        row = simulate(episode, 'ai', ai=ai, emit=lambda item: print(json.dumps(item), flush=True))
        row['controller'] = 'ai'
        frozen(master)
        write(target, row)
        write(directory/'worker-verification.json', {'passed': True, 'source_hashes': plan['source_hashes'],
                                                    'worker_sha256': sha(__file__), 'episode': episode_id,
                                                    'ai_usage': ai.summary()})
        print(json.dumps({'status': 'completed', 'episode': episode_id, 'completed': row['completed'],
                          'backlog': row['backlog'], 'violations': row['executed_violations']}), flush=True)
    finally:
        lock.unlink(missing_ok=True)


def finish(master):
    plan, episodes = frozen(master)
    rows = []
    for controller in plan['controllers']:
        for episode in episodes:
            path = master/'episodes'/f"{episode['id']}-{controller}.json"
            row = json.loads(path.read_text())
            if (row['episode_id'] != episode['id'] or row['controller'] != controller or row['seed'] != 17 or
                    row['spawned'] != len(episode['entries']) or row['completed']+row['backlog'] != row['spawned']):
                raise ValueError('Incomplete or mismatched episode result')
            if {f['source_flight_id'] for f in row['flights']} != {e['flight_id'] for e in episode['entries']}:
                raise ValueError('Historical traffic differs across controllers')
            rows.append(row)
    ai_plans = [json.loads(p.read_text()) for p in [master/'ai-plan.json', *sorted((master/'workers').glob('*/ai-plan.json'))] if p.exists()]
    if not ai_plans or len({p['prompt_sha256'] for p in ai_plans}) != 1 or any(p['generation'] != GENERATION for p in ai_plans):
        raise ValueError('AI worker settings differ')
    indexed = {}
    for path in [master/'calls.jsonl', *sorted((master/'workers').glob('*/calls.jsonl'))]:
        if not path.exists():continue
        for line in path.read_text().splitlines():
            call = json.loads(line);identifier = call['request_id']
            if identifier in indexed and indexed[identifier]['payload_sha256'] != call['payload_sha256']:
                raise ValueError('Duplicate request ID with altered public input')
            indexed[identifier] = call
    selected = []
    for row in [r for r in rows if r['controller'] == 'ai']:
        for decision in row['decisions']:
            identifier = f"cl-{ai_plans[0]['prompt_sha256'][:12]}:{row['episode_id']}:17:{int(decision['time_seconds'])}"
            call = indexed[identifier]
            view = json.loads(call['request']['messages'][1]['content'])
            if __import__('hashlib').sha256(canonical(view).encode()).hexdigest() != decision['public_view_sha256']:
                raise ValueError('Raw model call differs from executed decision state')
            if call['request']['messages'][0]['content'] != SYSTEM_PROMPT or call['paid_retries'] != 0:
                raise ValueError('AI protocol changed')
            if call['status'] == 'completed':
                action = parse_action(call['response']['choices'][0]['message']['content'], view)
                if action != call['action'] or decision['controller_failure']:
                    raise ValueError('Raw response differs from executed AI action')
            elif not decision['controller_failure']:
                raise ValueError('Failed inference was not recorded as a controller failure')
            selected.append(call)
    totals = {c: aggregate([r for r in rows if r['controller'] == c]) for c in plan['controllers']}
    base = {r['episode_id']: r for r in rows if r['controller'] == 'scripted'}
    paired = {c: [{'episode_id': r['episode_id'], 'completed_delta': r['completed']-base[r['episode_id']]['completed'],
                   'backlog_delta': r['backlog']-base[r['episode_id']]['backlog'],
                   'added_delay_seconds_delta': round(r['added_delay_seconds_sum']-base[r['episode_id']]['added_delay_seconds_sum'], 3),
                   'executed_violations_delta': r['executed_violations']-base[r['episode_id']]['executed_violations']}
                  for r in rows if r['controller'] == c] for c in ['deterministic', 'ai']}
    from .ai import BUDGET_ID, LEDGER_PATH
    usage = {'calls': len(selected), 'successful_calls': sum(c['status'] == 'completed' for c in selected),
             'statuses': dict(Counter(c['status'] for c in selected)), 'paid_retries': 0,
             'reported_cost_usd': sum(c.get('cost_usd') or 0 for c in selected),
             'unknown_cost_requests': sum(c.get('cost_usd') is None for c in selected),
             'reserved_usd': sum(c['reserved_usd'] for c in selected),
             'budget': ReservationLedger(LEDGER_PATH, BUDGET_ID, plan['inference_cap_usd']).summary()}
    write(master/'runs.json', rows)
    summary = {'status': 'completed', 'plan_sha256': sha(master/'plan.json'), 'split': 'validation',
               'controllers': totals, 'paired_reference': 'scripted', 'paired': paired,
               'source_hashes': plan['source_hashes'], 'ai_usage': usage,
               'execution': {'independent_episode_workers': True, 'worker_sha256': sha(__file__),
                             'unused_partial_audit_records': len(indexed)-len(selected)},
               'artifacts': {name: sha(master/name) for name in ['plan.json', 'runs.json']},
               'limits': ['Historical demand with reconstructed feeder and fixed final approaches; upstream feeder and waiting are not safety-modeled.',
                          'Added delay is modeled admission waiting. Unfinished values are right-censored at the common drain end; backlog penalty is 3600 seconds.',
                          'All controllers have the same announced synthetic occupancy and safety envelope. Safety is enforced by common synthesis and verification.',
                          'AI outcomes include explicitly recorded deterministic/scripted fallbacks for API, contract, or verification failures.',
                          'Simulation time pauses for controller computation. API wall latency is not added to simulated flight time.',
                          'One nominal seed and six validation windows from one historical day do not establish operational safety or human-controller superiority.',
                          'Independent AI windows ran concurrently to bound wall time; per-model dispatch pacing and the aggregate $1 cap remained enforced.',
                          'August 8–9 remain held out.']}
    write(master/'summary.json', summary)
    lines = ['# Historical-demand closed-loop comparison', '',
             'Six August 7 validation windows; 136 arrival requests per controller; seed 17; nominal conditions. August 8–9 stay held out.', '',
             '| Controller | Completed | Backlog | Executed violations | Mean accrued added delay, all demand | P95 accrued delay | Controller failures | Checked fallback decisions |',
             '|---|---:|---:|---:|---:|---:|---:|---:|']
    for name, row in totals.items():
        lines.append(f"| {name} | {row['completed']}/136 | {row['backlog']} | {row['executed_violations']} | {row['mean_added_delay_seconds_all_demand']:.1f}s | {row['p95_added_delay_seconds_all_demand']:.1f}s | {row['controller_failures']} | {row['fallback_decisions']} |")
    lines += ['', 'Delay values include accrued waiting for unfinished demand, censored at the common end time. Interpret them together with backlog; completed-only means select different aircraft.', '',
              '## Limits', '', *['- '+text for text in summary['limits']]]
    (master/'comparison.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'status': 'completed', 'controllers': totals, 'ai_usage': usage}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--master', type=Path, required=True)
    parser.add_argument('--episode')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--finalize', action='store_true')
    args = parser.parse_args()
    if args.finalize:
        if args.episode:parser.error('Finalization requires the complete matrix')
        finish(args.master)
    elif args.episode:
        work(args.master, args.episode, args.execute)
    else:parser.error('Choose --episode or --finalize')


if __name__ == '__main__':main()

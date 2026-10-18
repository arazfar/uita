# Historical arrival admission model leaderboard

This benchmark measures how well a model orders arriving aircraft to complete more arrivals with less added waiting.
Each controller sees requests as they become known, chooses an arrival order, and replans after the simulator advances.
The common safety verifier checks each proposed plan before execution.

The experiment compares five base models with reasoning ON and OFF: ten configurations.
Two local reference controllers run on the same traffic: scripted first-come scheduling and the deterministic planner.
The complete experiment contains **504 controller/window runs**: 12 controllers across 42 windows.
All 504 runs are complete and independently verified. See [measured results](#measured-results).

## What the benchmark contains

The frozen pack covers **August 24–30, 2026**, in `America/Los_Angeles`.
It contains six windows per day and **1,029 unique arrival operations**.
Window starts are 06:00, 09:00, 12:00, 15:00, 18:00 and 21:00.
Requests release from 15 minutes before each start until 30 minutes after it.
The simulator then has another 30 minutes to drain the traffic.
These selected windows do not represent the full week's traffic.

Demand comes from real date-matched DataSF arrival-operation records.
**All 1,029 initial aircraft states are synthetic.** The cached monthly archive contains no matching late-week observed paths.
The builder uses unchanged templates fitted only on August 3–6.
It shifts each template using the target arrival's recorded operation time.
This reconstructs historical demand; it does not recover observed entry positions, entry times or human clearances.

Historical KSFO weather is revealed when each report becomes available.
Availability uses the existing assumption of observation time plus five minutes; actual receipt times are unknown.
The complete future request queue and future weather remain private to the runner.
Models receive only released requests, anonymous aircraft aliases, current commitments and current scheduling facts.

Read [data coverage and source evidence](data/README.md), [provenance](data/provenance.json) and [artifact hashes](data/manifest.json).
August 8–9 remain excluded from construction, model inputs and evaluation.

## Fixed task and common controller harness

The sweep imports the existing [closed-loop engine](../closed_loop/README.md) without changing its simulation or scoring rules.
Every configuration uses nominal conditions and seed **17**.
Models return an exact permutation of pending aircraft aliases.
The shared decoder assigns the earliest feasible slots for that ordering.

```text
historical demand → causal release → model ordering → shared plan decoder
                                             ↓
                         checked fallback ← safety verifier
                                             ↓
                                  execute accepted motion
                                             ↓
                                        next decision
```

The checked approach is a fixed, approximately 15-nautical-mile, 360-second synthetic trajectory.
Aircraft share a conservative runway and taxi resource.
Each receives a deterministic synthetic runway-exit occupancy between 45 and 140 seconds.
Completion requires landing, runway-exit occupancy and the modeled 90-second taxi segment.
The models do not choose headings, speeds, altitudes, routes or radio commands.

The upstream feeder and waiting queue are outside the safety model.
Added delay measures modeled admission waiting, not measured airline delay or airborne holding.
There are no authentic human ATC action labels or human-controller scores.
Zero checked violations does not establish full ATC capability or operational safety.
Simulation time pauses during model computation. API latency is reported separately.

## Model configurations and reasoning controls

[`models.py`](models.py) defines the provider adapters and ten configurations.
The immutable run `plan.json` records exact model IDs, reasoning controls, generation settings and source hashes.
It also records runtime versions, traffic checksums, concurrency and the spending cap.
Reasoning OFF must use a documented disabling control. Low reasoning is not OFF.
Do not change a configuration after scored calls start or substitute another model under the same row.

| Base model ID | Reasoning ON | Reasoning OFF |
|---|---|---|
| `nvidia/NVIDIA-Nemotron-3.5-Super-VL` | `enable_thinking=true`, `medium_effort=true` | `enable_thinking=false` |
| `nvidia/Nemotron-3.5-Lightning-30B-A3B` | `enable_thinking=true` | `enable_thinking=false` |
| `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | `enable_thinking=true` | `enable_thinking=false` |
| `Qwen/Qwen3.8-27B` | `enable_thinking=true`, `reasoning_effort="medium"` | `enable_thinking=false` |
| `google/gemma-4-31b-it` | `enable_thinking=true` | `enable_thinking=false` |

`enable_thinking` and Super's `medium_effort` belong inside `chat_template_kwargs`.
Qwen's `reasoning_effort` is a separate top-level generation parameter.
The model-specific effort names do not imply equal reasoning computation across families.
The three NVIDIA entries are distinct checkpoints, not three providers or unrelated model families.

The common task prompt and public information match the original AI controller.
Provider-specific reasoning parameters remain explicit in the plan.
All configurations use temperature 1.0, top-p 0.95, seed 17, JSON-object responses and an 8,192-token output limit.
The socket-operation timeout is 60 seconds. It is not a strict total request or controller deadline.
Connection and read operations can wait separately; observed request wall latency reached about 79 seconds.
Latency charts retain measured wall time. Simulation time still pauses during model computation.
The output limit also constrains reasoning where the provider counts reasoning tokens against that limit.
Truncation therefore measures service behavior under the recorded budget, not isolated scheduling ability.
No fine-tuning runs in this experiment.

## Objective and leaderboard ranking

The evaluator ranks complete, independently verified systems in this order:

1. Require zero executed violations and zero unresolved decisions.
2. Minimize unfinished arrivals at the common horizon.
3. Minimize penalized added delay across all demand.

```text
penalized added delay = sum(accrued added delay per aircraft)
                       + 3600 seconds × unfinished arrivals
```

For an aircraft that lands, added delay is its nonnegative simulated landing time minus its nominal landing time.
The nominal reference combines release time, modeled feeder travel time and the fixed 360-second approach.
For an aircraft that does not land, accrued delay is the nonnegative horizon minus its nominal landing time.
Waiting after the horizon is unknown. These unfinished-aircraft delays are therefore censored.
A landed aircraft still clearing the taxi segment remains unfinished.

The leaderboard shows completed arrivals, completion percentage, backlog, mean and P95 all-demand added delay, and executed violations.
It also shows valid-response rate, fallback rate, latency, cost, reasoning setting, harness version and audit links.
Completed-only delay can hide unserved demand, so it must not replace the all-demand metrics.
Report tail-delay regressions even when mean delay or completions improve.

All model rows describe **the model plus the common checked fallback system**.
Transport errors, HTTP errors, token-limit truncations and invalid actions remain in the denominator.
They trigger recorded deterministic fallbacks. Rejected plans can trigger separately checked scripted fallbacks.
A fallback is not a successful model response.
Executed safety events and rejected hypothetical proposals are separate measurements.

The matching references are the scripted and deterministic results rerun on these same 42 windows.
The old August 7 results provide historical context only.
Do not rank their absolute scores against late-week scores: the traffic and initial-state coverage differ.

## Run and resume

Use the prepared Python environment from the repository root.
It contains the pinned `ortools==9.11.4210` optimizer used by the existing engine.
`CRUSOE_API_KEY` stays server-side in the environment or root `.env.local`.
Never place credentials in configuration files, reports or browser code.

Create and inspect a plan without paid model calls:

```sh
benchmark/results/closed-loop-venv/bin/python -m benchmark.sweep.run
```

Run all ten configurations and both matching references:

```sh
benchmark/results/closed-loop-venv/bin/python -m benchmark.sweep.run --execute
```

Defaults use a **$30 total cap**, at most **30 worker threads**, and at most **six concurrent jobs per base model**.
Reasoning ON and OFF share their base model's concurrency and request pacing.
A shared ledger spaces dispatches by 2.2 seconds per model, respecting the provider's 30-requests-per-minute limit.
Expect about 45 minutes or longer. More worker threads cannot remove the provider's request limit.

The recorded October 17 run uses an explicit concurrency amendment to reduce time lost waiting for slow responses.
[`parallel.py`](parallel.py) adds 90 worker threads, limited to 18 additional jobs per base model.
It owns 180 previously unstarted model/window jobs for August 28–30 and processes those windows in reverse order.
The original forward runner continues with 30 threads and six jobs per base model.
The combined limit is therefore **24 concurrent jobs per base model**.
Both runners use the same SQLite ledger, 2.2-second per-model dispatch spacing and $30 spending cap.
Model settings, traffic, physical simulation, safety checks, fallback rules and scoring remain unchanged.

The raw run records ownership and the helper's source hash in `orchestration-amendment.json`.
It preserves the helper source and writes `orchestration-worker-completion.json` after all owned jobs finish.
The original runner must later reuse every one of those 180 completed outcomes.
Final verification must confirm all 180 original-runner reuse records, unique inference identities and complete causal replay.
The helper refuses a second amendment. Investigate existing ownership before attempting recovery; do not launch another helper blindly.

Two original windows stopped after interrupted provider responses.
They were Super VL OFF on August 25 at 15:00, and Lightning ON on August 24 at 12:00.
[`recover.py`](recover.py) completed those windows under explicit recovery manifests.
It reused seven cached calls and made 21 fresh calls for later decision IDs.
**No paid request was repeated.** Original logs and raw audit prefixes remain intact.
Independent replay passed both recovered rows.

Four earlier Lightning fallback commits were reconstructed exactly from the immediately following recorded public snapshots.
Their original fallback producer, proposal verdict, solver status, bound and timing remain unknown.
`RECOVERED_FEASIBLE` means the reconstructed slots passed the current independent feasibility checks.
It does not establish which original optimizer or secondary scripted fallback produced those slots.
The recovery amendment permits one additional worker per affected base model.
The temporary limit is therefore **25 concurrent jobs per affected base model**.
Ordinary main-plus-helper execution remains limited to 24.
Recovery preserves the shared dispatch spacing, spending cap, model payloads and scoring rules.

Known charges and conservative reservations for unknown or in-flight costs count against the shared spending cap.
An unknown cost is not zero. Automatic paid retries are disabled.
Every provider failure and fallback remains recorded; selective reruns for better scores are forbidden.

The default raw run directory is `benchmark/results/late-august-sweep-20261017`.
Run the same command to resume under the same immutable plan.
Resume after the previous runner stops and, for an amended run, after resolving helper ownership.
Completed controller/window outcomes are reused.
Keep the original output directory and budget ledger; a new folder must not become a budget workaround.
Changing sources, settings, runtime versions or the cap makes the existing plan fail clearly.

Standard execution finalizes and verifies automatically when the complete matrix exists.
In the recorded amended run, the original runner retains its two historical failures and exits with that failures list.
After the recovered rows are complete and the original runner stops, finalize without new model calls:

```sh
benchmark/results/closed-loop-venv/bin/python -m benchmark.sweep.run --finalize
```

## Verify and inspect

Independent replay makes no provider calls:

```sh
benchmark/results/closed-loop-venv/bin/python -m benchmark.sweep.verify \
  --run benchmark/results/late-august-sweep-20261017 \
  --output benchmark/results/late-august-sweep-20261017/reverification.json
```

The verifier reconstructs causal requests and weather from their sources.
It binds model decisions to exact requests, raw responses and frozen configurations.
It rechecks accepted plans, fixed commitments, executed motion, all-flight outcomes, delays and aggregates.
It also checks the original safety controls and recorded optimizer objectives.
Replay needs the original local raw audit files and recorded runtime; the compact public report alone is insufficient.

Published outputs go to [`reports/2026-08-24_30/`](reports/2026-08-24_30/):

- `index.html`: sortable leaderboard, filters and comparison charts.
- `leaderboard.json` and `leaderboard.csv`: measured records and exportable metrics.
- `completion.svg` and `delay.svg`: standalone charts with matching reference lines.
- `plan.json`, `summary.json` and `verification.json`: configuration and verification evidence.

Incomplete or unverified rows must remain labeled and unranked.
Raw requests, responses, per-window traces, budget ledger and frozen source copies stay in the ignored local run directory.
Inspect per-window differences and failure categories before attributing a result to reasoning or model capability.
Read the [independent review](review.md) with the final report.

## Measured results

The completed comparison covers five models, ten configurations, 42 windows and 1,029 arrivals per controller.
Independent verification replayed 6,799 decisions and bound all 5,667 scored model calls to their raw evidence.

| Controller | Completed arrivals | Mean all-demand added delay | Checked violations |
|---|---:|---:|---:|
| Scripted reference | 408 / 1,029 | 1,288.7 seconds | 0 |
| Deterministic planner | **427 / 1,029** | 1,277.0 seconds | 0 |
| Best model system: Nemotron 3 Nano, reasoning ON | 426 / 1,029 | 1,276.4 seconds | 0 |

**No AI configuration beats the deterministic planner on these windows under the completion-first objective.**
Nano ON has slightly lower mean delay but completes one fewer arrival.
It uses checked fallbacks on **493 of 566 decisions (87.1%)**.
Its result therefore measures the model-plus-fallback system, not isolated model scheduling performance.

All twelve controller configurations have zero executed violations in the checked model.
They share the safety gate and fallback machinery. The upstream feeder and waiting queue remain outside the safety model.
All 1,029 initial states are synthetic development templates, while the recorded late-week demand times are real.
These results do not establish operational safety or performance against human ATC.

There are 5,667 scored calls and ten unscored development preflight calls, with no repeated paid requests.
Known charges total **$10.15733646**.
The 980 requests with unknown cost retain **$5.11865738** in full reservations.
Known charges plus unknown exposure total **$15.27599384**, below the $30 cap. The final billed total remains unknown.

Open the [leaderboard and charts](reports/2026-08-24_30/index.html), [aggregate results](reports/2026-08-24_30/summary.json),
[independent verification](reports/2026-08-24_30/verification.json), and [model mistakes versus API failures](reports/2026-08-24_30/failure-analysis.md).

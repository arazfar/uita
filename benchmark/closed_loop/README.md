# Historical-demand closed-loop benchmark

This benchmark compares three controllers on the same historical arrival demand. Each controller repeatedly schedules announced traffic. The simulator executes accepted plans before the next decision. This differs from the separate arrival-pair prediction benchmark in `benchmark/`.

The task is **arrival admission and sequencing in a reconstructed terminal model**. It does not measure authentic human ATC decisions or unrestricted control of historical trajectories.

## Traffic and motion

The frozen source is `sfo-2026-08-03_09-v1`. The builder queries only allowed episode, entry and weather rows. It does not join recorded arrival outcomes.

| Split | Local dates | Windows | Arrival operations | Initial-position provenance |
|---|---|---:|---:|---|
| Development, filename `train.json` | August 3–6 | 24 | 572 | 282 observed; 290 synthetic |
| Validation | August 7 | 6 | 136 | 75 observed; 61 synthetic |
| Final test | August 8–9 | Sealed | Not loaded | Not inspected or evaluated |

Every window has 15 minutes of warmup, 30 minutes of incoming demand, and 30 minutes to drain. Evaluation uses one nominal variant and seed **17**. Windows share the same source arrival operations across controllers. A source operation identifies one arrival, not a unique physical airframe.

Historical entry time determines when an aircraft becomes known. Its initial position and bounded initial speed determine a nominal feeder time to the common approach entry. The feeder speed is clamped to 140–280 knots. The nominal landing reference is:

```text
entry time + nominal feeder travel time + 360 seconds
```

The checked final approach follows the backend's fixed, approximately 15-NM, 360-second path. Controllers choose admission order and landing reservations. They do not choose headings, speeds, altitudes, routes or radio commands.

**The feeder and upstream admission queue are outside the safety model.** Their waiting time is not measured airborne holding. Initial-position provenance remains labeled, but historical paths are not replayed after release. Synthetic entry timing can inherit historical operation timing from the upstream reconstruction; it is not an observed spawn timestamp.

Each arrival receives a deterministic synthetic runway-exit occupancy of 45–140 seconds. All controllers receive that value. Occupancy is not measured historical ground truth. Completion occurs after landing, runway-exit occupancy, and the modeled 90-second taxi segment.

## Controllers and information

`traffic.py` loads runner-private future queues and verifies frozen artifact checksums. `engine.py` releases entries causally, advances accepted motion, and builds the public controller view. `controllers.py` translates orderings into plans. `run.py` freezes sources and writes matched results.

The public view contains the simulation clock, horizon, announced pending aliases, modeled earliest landing times, current tentative slots, wake categories, occupancy durations and active commitments. It contains no future arrivals, source identities, authentic historical landing times, historical runway outcomes or future weather. The trusted driver applies weather only when reports become available.

The controllers use one conservative shared resource across 28L and 28R:

- **Scripted:** first come, first served by modeled requested landing time, then alias.
- **Deterministic:** CP-SAT can reorder pending arrivals. It preserves active commitments and minimizes unfinished arrivals first, then total landing delay. It uses one worker, seed 17 and a 0.25-second limit. `FEASIBLE` does not establish an optimum; `OPTIMAL` applies only to the current announced scheduling problem.
- **AI:** live `nvidia/NVIDIA-Nemotron-3.5-Super-VL` supplies an exact permutation of pending aliases. A shared decoder assigns earliest feasible slots for that order. Reasoning is enabled with medium effort, temperature 1.0, top-p 0.95, seed 17 and a 4,096-token output limit. These settings follow the model-specific policy in `ai.py`; this is not the earlier reasoning-disabled prediction experiment.

All three use the same announced synthetic occupancy and conservative reservation duration: `exit_occupancy + 240` seconds. The buffer covers approach/resource, taxi, reservation and worst-visibility allowances. The backend wake floors are 120 seconds after a heavy arrival and 90 otherwise; the shared resource duration is more restrictive here.

## Safety gate and objective

Every proposal must pass the independent backend verifier before state changes. The verifier checks snapshot binding, coverage, active commitments, readiness, runway/resource constraints, wake, surface reservations, performance and continuous approach separation. Once an approach starts, its accepted path is immutable.

The engine separately audits **executed trajectory segments** through the common horizon. It reports separation episodes, runway/surface overlap, wake and performance violations. Rejected hypothetical proposals are not counted as executed safety events.

The reported ranking is:

```text
1. Safety eligibility: zero executed violations and zero unresolved decisions.
2. Fewer unfinished arrival operations at drain_end.
3. Lower penalized added delay across all demand.

penalized added delay = sum(accrued added delay_i) + 3600 * unfinished_count
```

For an aircraft that lands, added delay is the nonnegative difference between its simulated and nominal landing times. For an aircraft that does not land, accrued delay is `max(0, drain_end - nominal_landing_time)`. Such values are **right-censored**: waiting after the common horizon is unknown. A landed aircraft that has not cleared the modeled taxi segment still counts as unfinished.

Always report completion, backlog, nominally due traffic, all-demand delay and penalties together. Completed-only delay can hide unserved demand. The deterministic planner optimizes its current announced scheduling problem; the final evaluator scores actual outcomes over the episode.

AI failures trigger a separately recorded deterministic fallback. A rejected plan can trigger a separately checked scripted fallback. Results therefore describe the **AI controller plus counted safety fallbacks**. Report AI failures, rejected proposals, fallbacks and unresolved decisions alongside efficiency. A fallback is not a successful AI response.

Simulation time pauses during computation. API wall latency is recorded separately and is not added to flight time. This experiment does not test a real-time controller deadline.

## Run locally

From the repository root, prepare the lightweight simulator runtime:

```sh
uv venv --python 3.12 benchmark/results/closed-loop-venv
uv pip install --python benchmark/results/closed-loop-venv/bin/python ortools==9.11.4210
benchmark/results/closed-loop-venv/bin/python -m benchmark.closed_loop.run --help
```

Reusing the existing prepared environment avoids recreating it. The backend modules used here do not require the backend web server. Rebuilding traffic uses the existing pipeline environment, which provides DuckDB:

```sh
pipeline/.venv/bin/python -m benchmark.closed_loop.traffic
```

Use the committed frozen traffic for comparisons. Rebuild only when intentionally creating a new data version; preserve existing hashes and run records.

Create a plan without simulation or paid calls:

```sh
benchmark/results/closed-loop-venv/bin/python -m benchmark.closed_loop.run \
  --out benchmark/results/closed-loop-plan-local --split validation \
  --controllers scripted deterministic ai --cap-usd 1
```

Run both local references without inference:

```sh
benchmark/results/closed-loop-venv/bin/python -m benchmark.closed_loop.run \
  --out benchmark/results/closed-loop-local-references --split validation \
  --controllers scripted deterministic --execute
```

Run the complete matched comparison only when paid inference is authorized:

```sh
benchmark/results/closed-loop-venv/bin/python -m benchmark.closed_loop.run \
  --out benchmark/results/closed-loop-validation-local --split validation \
  --controllers scripted deterministic ai --cap-usd 1 --execute
```

`CRUSOE_API_KEY` is read server-side from the environment or root `.env.local`. The AI model and endpoint are pinned. Persistent request reservations share the dedicated `uita-historical-closed-loop-20261017` budget and a maximum $1 cap. Unknown request costs retain their reservations. Requests are paced and never retried automatically. A new output folder does not reset that budget.

Use a unique output directory for a new experiment. Completed runs are immutable. Partial validation and final-test selection are forbidden. `--episode` is available only with `--split train` for development QA. No fine-tuning is performed or authorized by these filenames.

Independent AI windows can finish an interrupted complete validation plan with `benchmark.closed_loop.worker`. Stop the main runner before assigning its unfinished windows to workers; each window must have one owner. Worker audits live under `workers/<episode>/`. All workers share the same pacing and budget ledger. `--finalize` requires all eighteen controller/window outcomes; it cannot publish a selected subset.

```sh
benchmark/results/closed-loop-venv/bin/python -m benchmark.closed_loop.worker \
  --master benchmark/results/closed-loop-validation-local \
  --episode 2026-08-07-1200 --execute
benchmark/results/closed-loop-venv/bin/python -m benchmark.closed_loop.worker \
  --master benchmark/results/closed-loop-validation-local --finalize
```

## Inspect results

Each run writes `plan.json`, `runs.json`, `summary.json`, `comparison.md`, per-episode results and frozen source copies. AI runs also preserve exact requests, responses, failures, usage and their AI plan. Raw run folders stay local and are ignored by Git.

Read per-episode matched differences before interpreting aggregates. Inspect solver statuses, executed safety findings, source strata, all-flight outcomes and fallback counts. Six validation windows cover only one historical day; repeated decisions do not create independent days.

The [completed comparison](reports/2026-10-17/comparison.md) covers all eighteen controller/window runs. The planner and AI-plus-fallback system each completed 63/136 arrivals, versus 62/136 for the scripted baseline. All three had zero executed violations in the checked model. AI required 50 fallbacks in 83 decisions and did not beat the deterministic planner. Tail delay worsened for both planner and AI, despite small reductions in mean accrued delay. No controller was promoted.

No human-performance, operational-safety or airborne-holding claim follows from this benchmark. Read [verification](reports/2026-10-17/verification.json) and [independent review](review.md) with the results.

## Verify and archive

The independent verifier reconstructs causal state, checks every accepted action, and recomputes safety, delay and aggregates. It also binds each AI decision to its exact local request and response. Verification makes no provider calls:

```sh
benchmark/results/closed-loop-venv/bin/python -m benchmark.closed_loop.verify \
  --run benchmark/results/closed-loop-validation-final-20261017 \
  --output benchmark/results/closed-loop-validation-final-20261017/reverification.json
```

Use the original raw run directory, including worker audits and frozen sources. The compact published report alone cannot reproduce raw-response verification. Keep the recorded Python and optimizer versions; changed source hashes fail clearly.

Railway holds only six compact artifacts under `sfo-historical-closed-loop-validation-2026-08-07-v1`. They contain validation traffic, protocol, aggregate results, per-flight outcomes, verification and a manifest. The upload excludes raw API logs, internal decision lists, development data and final test data. [Database verification](reports/2026-10-17/railway-verification.json) confirms all 228,796 bytes matched after download.

Validate archive bytes locally before an authorized upload:

```sh
pipeline/.venv/bin/python -m benchmark.closed_loop.archive \
  --results benchmark/closed_loop/reports/2026-10-17
```

Adding `--execute` writes the immutable dataset through the server-side `DATABASE_URL` and verifies downloaded bytes. A conflicting existing version fails instead of overwriting it.

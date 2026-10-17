# Test models against the frozen arrival-order benchmark

This benchmark screens models for a small prediction task: given two observed SFO arrivals, predict their recorded operation order. It measures agreement with historical records. It cannot measure human ATC decision quality, safety, or the effects of new clearances.

The completed experiment contains five untuned model runs, with 141 attempts per model. See [results](reports/2026-10-17/comparison.md), [machine-readable predictions](reports/2026-10-17/comparison.json), and [independent review](independent_review.md). Fine-tuning is deferred. No training files were uploaded or jobs started.

## Contents and boundaries

| Split | SFO local dates in 2026 | Distinct pairs | Purpose |
|---|---|---:|---|
| Development, stored as `train.jsonl` | August 3–6 | 488 | Develop adapters and inspect failures |
| Validation | August 7 | 141 | Compare models and select a configuration |
| Final test | August 8–9 | Not extracted for this task | Reserved for a later frozen evaluation |

Each pair contains two distinct source arrival operations. No source operation repeats across pairs. The same physical aircraft can operate multiple flights. One validation day limits conclusions about other traffic and weather conditions.

The source combines the DataSF arrival-operation roster and available SFO Museum observed paths. Pairing uses observed entry times. The snapshot occurs at the later entry observation; the earlier position remains stale by at most 300 seconds. Synthetic positions and inferred altitudes are excluded. Only two of the 282 validation aircraft have observed beacon altitudes; other heights are null.

Models receive anonymous IDs, distance, bearing, groundspeed, track, observation age, available observed altitude, simplified wake category, and a direct-to-airport time estimate. They also receive the fixed synthetic runway rules. They do not receive callsigns, source IDs, dates, recorded operation times, future paths, historical runway assignments, or the answer.

The time estimate is `max(0, distance_nm / groundspeed_kt * 3600 - age_seconds)`. It does not recover a controller's estimated arrival time. See [data quality](data-quality.md) and [the full schema](contracts.md).

## Primary objective function

For case `i`, let `y_i` be the two IDs sorted by recorded arrival-operation timestamp. Let `a_i` be the model's complete ordering.

```text
success_i = 1 if the response is valid and a_i equals y_i; otherwise 0
score     = sum(success_i) / N
objective = maximize score
```

`N` is every case in the frozen split: **141 for validation**, including failed requests. Multiply the score by 100 for percentage accuracy. Each case has equal weight. A valid response has exactly this shape:

```json
{"order":["A2","A1"]}
```

Every supplied ID must appear exactly once. Extra fields, duplicate JSON keys, unknown IDs, missing IDs, explanations, incomplete generations, timeouts, and API errors score zero. Do not repair responses or substitute a scripted answer. With two aircraft, exact-order accuracy, next-arrival accuracy, and pairwise agreement are the same binary metric.

The target comes from operation timestamps, which are not verified touchdown times. Matching it perfectly is a label-agreement ceiling, not a measured human controller score. A different order can be operationally valid.

Report two additional diagnostics separately:

- **Own-valid accuracy:** correct answers divided by that model's valid responses. Models can have different case membership here.
- **Common-success accuracy:** score on cases where every compared model returned a valid response. The completed experiment shares 90 cases. Provider success selects this subset; it is not an unbiased replacement for the full split.

Report availability, failure counts, latency, token usage, and estimated cost alongside accuracy. Do not merge them into an undocumented reward.

## Secondary synthetic scheduling objective

`core.schedule_action` assigns runway times from the returned permutation. Each time is at least the aircraft's free-flow estimate, runway availability, and the previous slot plus its leader's spacing: 90 seconds for medium wake, 150 for heavy wake.

```text
delay_seconds = sum(max(0, slot_time - free_flow_seconds))
backlog       = number of aircraft with slot_time > 3600 seconds
penalized_delay_seconds = delay_seconds + 3600 * backlog
```

`teacher_action` enumerates permutations and minimizes `(backlog, delay_seconds, maximum_delay_seconds, ID_order)` lexicographically. The final ID order breaks ties. This oracle uses public inputs and optimizes the synthetic scheduler; it is not the primary historical target.

`core.check_schedule` independently checks slots and spacing. These rules do not implement full FAA separation, runway occupancy, aircraft motion, or radio behavior. Constructed schedules passing the checker do not establish ATC safety. Keep these secondary metrics out of the historical-agreement leaderboard.

## Verify the frozen benchmark without API calls

Run commands from the repository root:

```sh
uv sync --project pipeline --frozen
pipeline/.venv/bin/python -m benchmark.verify
pipeline/.venv/bin/python -m benchmark.run_baseline --help
```

Verification checks file/code hashes, split dates, source disjointness, unique public prompts, identity exclusion, and every case through the fixed scheduler/checker. It uses the committed JSONL files and needs no database or model key. Do not rebuild or edit the frozen data to evaluate a new model.

## Run another Crusoe model

Set `CRUSOE_API_KEY` in the ignored root `.env.local` or environment. Use the existing inference key; a Cloud management key is unnecessary. Never put keys in commands, reports, or Git.

1. Create a plan with a new output directory and one shared budget ID for the comparison:

```sh
pipeline/.venv/bin/python -m benchmark.run_baseline \
  --out benchmark/results/my-gpt-oss-validation \
  --model openai/gpt-oss-120b --controller-name gpt_oss_120b \
  --split validation --max-cases 141 --max-tokens 1024 --seed 17 \
  --min-request-interval-seconds 2.2 --cap-usd 1 \
  --budget-id my-frozen-comparison
```

This performs read-only provider discovery and saves `plan.json`; it sends no generation requests. Review the model, complete case count, prices, generation settings, and worst-case reservation.

2. Execute the same command with `--execute` appended when a new paid run is intended. That flag sends paid inference requests. No new calls are needed to read the completed results.

The reviewed models are listed in `provider.MODEL_POLICIES` and [comparison methods](model-comparison.md). The provider rejects other IDs until an explicit generation policy is added. Different models need different output directories. Keep the ledger and budget ID shared to enforce a combined cap; the runner allows at most $1 per budget. Unknown charges retain their full reservations.

The completed runs use temperature 0, top-p 1, seed 17, 1,024 output tokens, JSON object output, and one request per case. Nemotron and Qwen disable thinking. GPT-OSS uses low reasoning because its documented controls lack an off setting. These are bounded deployment settings, not equal internal computation or each model's best possible configuration.

The runner spaces request starts by at least 2.2 seconds per model. Rate limits and transport failures can still occur; preserve them. It makes no paid retries. Interrupted runs can reuse the same directory and persistent ledger; completed runs are immutable. Do not delete the ledger or change request IDs to retry failed cases inside the same reported experiment.

Each completed run saves exact prompts, raw requests/responses, scores, usage, failures, a summary, and frozen source snapshots under `benchmark/results/`. These raw logs remain local and ignored by Git.

## Generate a comparison report

Pass completed **full validation runs**, not selected cases:

```sh
pipeline/.venv/bin/python -m benchmark.report \
  benchmark/results/my-gpt-oss-validation \
  benchmark/results/my-other-model-validation \
  --output benchmark/reports/my-comparison
```

Replace the example paths with actual completed run directories. Reporting sends no API requests. It verifies saved artifact/source hashes, exact public prompts, request payloads, generation settings, unique case membership, and zero paid retries. It parses raw responses again and independently recomputes every score.

The output contains Markdown, aggregate JSON, per-case predictions, common-case membership, conditional confidence intervals, and exploratory paired comparisons. Rebuilding the existing report requires its local raw run directories. A clean checkout can read the committed report immediately or generate new evidence through new runs.

## Connect another inference backend

Keep `core.SYSTEM_PROMPT`, `core.model_messages(case)`, case membership, and the parser unchanged. Send only `model_messages(case)` to the model. The full case includes private answers and must remain inside the trusted scorer.

For a local integration, the essential scoring path is:

```python
from benchmark import core

def evaluate_model(predict):
    cases = core.load_cases("validation")
    correct = valid = 0
    for case in cases:
        # predict receives public messages and returns raw model text.
        try:
            raw = predict(core.model_messages(case))
            action = core.parse_action(raw, case["input"])
        except Exception:
            # Preserve the actual error and raw response in the adapter's audit log.
            continue
        valid += 1
        correct += core.evaluate_action(case, action)["exact_sequence_correct"]
    return {"correct": correct, "cases": len(cases),
            "accuracy": correct / len(cases), "valid_responses": valid}
```

The callback example computes the primary score; it does not create the raw provenance required by `benchmark.report`. A new leaderboard adapter must save the same plan, prompts, calls, scores, summary, and frozen-source contract as `run_baseline.py`. Record model identity, reasoning controls, finish reason, usage, timeout, and errors. Freeze those choices before comparing validation scores.

## Read the minimal Railway dataset

The comparison upload has dataset ID `sfo-arrival-order-model-comparison-2026-08-03_07-v1`. It contains five artifacts: validation cases, the benchmark manifest, mechanical verification, comparison results with per-case predictions, and the upload manifest. Raw API logs, source code, unused development payloads, and final test payloads were excluded from this upload.

With server-only `DATABASE_URL` in `.env.local`, download and verify it:

```sh
pipeline/.venv/bin/python -m pipeline.uita_data.store download \
  --dataset-id sfo-arrival-order-model-comparison-2026-08-03_07-v1 \
  --directory /tmp/uita-benchmark
```

The download verifies each stored SHA-256 checksum. Read `comparison.json` for aggregate scores and all 141 cases' model predictions. The minimal download omits development payloads; run `benchmark.verify` against the repository's full frozen files. See [Railway verification](reports/2026-10-17/railway-verification.json).

## Interpret results and preserve the final test

GPT-OSS led the five models at 91/141, matching the free-flow rule. Always choosing A1 scored 88/141, showing label imbalance. Ordering the older observed entry first scored 100/141, but that rule was added after the initial run and is a posthoc diagnostic. Validate it on later untouched data before claiming a general improvement.

Do not tune prompts or select models using August 8–9. The current builder and runner cannot select those test dates. A future final evaluation needs separately versioned cases, a frozen model/prompt/configuration, and a trusted evaluator. Broader ATC claims require complete simulator scenarios, independent safety checks, and qualified humans controlling the same scenarios.

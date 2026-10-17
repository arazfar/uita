# Historical arrival sequencing pilot

This benchmark measures whether a model predicts the recorded order of two SFO arrivals from causal observed entry snapshots. It does not recover authentic controller commands. No human ATC safety, delay or command-performance score exists in the source bundle.

The five-model comparison is complete. Read [results](reports/2026-10-17/comparison.md), [how to test and the exact objective function](TESTING.md), and [Railway verification](reports/2026-10-17/railway-verification.json). The database upload contains only the 141 validation cases, predictions/results, and verification metadata. Fine-tuning is deferred.

Two designs were considered. Reusing the backend planner would preserve its richer scheduling constraints, but its current cases are synthetic mixed arrivals/departures and its model revises observation programs rather than directly ordering real arrivals. A dedicated arrival-pair task supports the same compact input/action contract across different untuned models. We chose the dedicated task for this experiment and report its narrow scope.

```text
filtered observed entries (Aug 3–7 only) -> disjoint entry-time pairs
                                               |
                         causal public input -> model -> permutation
                                               |               |
               recorded operation order -> agreement           |
                                     fixed synthetic scheduler -> delay/backlog
```

There are **488 distinct development encounters** from August 3–6 and **141 validation encounters** from August 7. Each encounter contains two source flights, meaning two recorded arrival operations. No source arrival operation repeats across encounters. Physical aircraft can appear in multiple operations. No augmented copies inflate these counts. Encounter grouping uses observed entry times, not future operation-order adjacency. The final August 8–9 test dates remain sealed. The builder does not query their rows, open their scenario files, or produce test examples.

The primary target is recorded arrival-operation order. Calling its exact reconstruction “human performance” would be misleading: it is a label agreement ceiling by construction. A different order can be valid. Different untuned models use the exact same prompt, cases and bounded generation settings, with disclosed model-specific reasoning controls. No fine-tuning is performed.

The secondary checker schedules a submitted permutation through a single shared synthetic runway resource. It reports modeled delay, completion and backlog, using fixed direct-to-airport travel estimates and 90/150-second leader wake spacing. These assumptions do not reproduce full FAA rules. A batch action-to-schedule evaluation is not a closed-loop full-ATC rollout. The exhaustive `teacher_action` oracle optimizes only this secondary model and supplies a separate reference.

## Reproduce the frozen data

Run from the repository root:

```sh
pipeline/.venv/bin/python -m benchmark.build
pipeline/.venv/bin/python -m benchmark.verify
```

The source is the existing `pipeline/build/sfo.duckdb`. The builder issues a date-restricted SQL query and accepts only `position_provenance='observed'`. It uses the first usable observed entry, with a maximum observation age of 300 seconds. Only beacon-reported actual altitudes are retained; missing heights become null. Synthetic spawn positions, inferred spawn times and inferred heights are excluded. No future track or weather sample enters the input.

`data/manifest.json` records exact split dates, source query, selected-source hash, artifact/code hashes, exclusions and actual counts. Commit the generated compact JSONL files and manifest so the experiment does not depend on a new mutable extraction. The source database and credentials remain outside Git.

Read [contracts.md](contracts.md) for the exact prompt, strict permutation parser, data fields and evaluator interfaces. Provider calls and model comparison results are implemented separately by the other benchmark modules. Do not include any `private` fields in prompts. The existing split filenames preserve the frozen contract; `train.jsonl` serves as development data in this untuned-model comparison.

Historical agreement and synthetic scheduling performance answer different questions. Keep their results separate. Pairs reduce the task to one binary ordering decision, and the week supplies only four development days and one validation day. Confidence must reflect that limited day diversity. Final held-out test results require a later explicitly frozen evaluation; this pilot does not run them.

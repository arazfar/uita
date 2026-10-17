# Historical-order fine-tuning pilot

**Status: deferred.** The user now requests untuned model comparisons. No approved training export, upload or fine-tuning job was produced by this preparation workflow. Candidate and audit artifacts remain available as data-quality evidence only.

The pilot predicts the order of two recorded SFO arrival operations. It uses 488 independent encounters from August 3–6 for fitting and 141 from August 7 for validation. Each aircraft appears once. No examples are duplicated or augmented. August 8–9 remain unopened and unexported.

The targets are **historical arrival-operation order proxies**. The source has no authentic clearances, controller intent or qualified human ratings. These targets can measure agreement with recorded order. They cannot measure how much worse AI is than human ATC, or establish a safe controller.

## Choice of target

| Approach | Benefit | Limit | Pilot decision |
| --- | --- | --- | --- |
| Predict recorded operation order from past observed positions | Real observational target; matches the untuned benchmark prompt | Recorded order need not be the best control action; missing context can make it unpredictable | Primary supervised target |
| Imitate a scheduler that enumerates every order under simplified spacing rules | Optimal label for the disclosed synthetic objective; no hidden future outcome needed | Teaches that scheduler and its assumptions; does not isolate learning historical order | Separate secondary reference; excluded from this training corpus |

Training to match one target and reporting improvement against the other would mix two tasks. The small pilot keeps its prompt, labels and primary evaluation task identical. The scheduler remains a separate descriptive reference.

## Causal input boundary

Model inputs contain local aliases, last-known observed entry positions, observation age, speed, altitude provenance and simplified wake class. They contain no callsigns, source IDs, date, historical runway, operation timestamp, later recorded position or future traffic queue. Historical operation timestamps supply private labels only.

Snapshots use the later entry observation in each encounter. The earlier observation is at most 300 seconds old. Features retain the last-known position; they do not interpolate through a later recorded point. Straight-line time to the airport subtracts observation age and is explicitly a surrogate. Missing observed altitude is null with `altitude_source: "unknown"`. Synthetic altitude profiles are excluded.

## Distinct review stages

1. Generate candidates with `pipeline/.venv/bin/python -m benchmark.training candidates`.
2. Audit candidates with `pipeline/.venv/bin/python -m benchmark.review`.
3. Have an independent agent inspect the generator, audit code, every audit result and a meaningful example sample.
4. Have that reviewer record one approval or rejection, a reason and exact candidate hash per example.
5. Export with `pipeline/.venv/bin/python -m benchmark.training export --decisions benchmark/review_attestation.json`.

Generation does not set an approval field. The audit does not approve rows. The independent reviewer decides after inspecting the evidence. This is agent review, not qualified human ATC review.

The audit queries only August 3–7 source rows from DuckDB. It independently recomputes features and labels, rather than accepting candidate claims. Each row must pass checks for the allowed split, exact baseline messages, feature allowlist, causal timestamps, observed position provenance, source operation order, complete action permutation and aircraft/encounter uniqueness.

The export requires both a passing all-row audit and a separately authored reviewer attestation. Their file hashes and every candidate hash must match. Rejected examples are omitted and counted. Approved examples use the exact shared `benchmark.core.model_messages` prompt, followed by one JSON assistant response. Export refuses missing validation rows, unknown dates, changed source cases or changed labels.

## Artifacts and review contract

`benchmark/artifacts/training/` contains candidate JSONL, a generation manifest and the mechanical audit. Approved Crusoe files are written to its `export/` directory. `train.jsonl` and `validation.jsonl` are separate conversation files. Never concatenate them for fitting or use an automatic random holdout instead of the dated validation file.

The reviewer writes this shape. Each decision needs a concrete per-example reason.

```json
{
  "reviewer": "independent reviewer identity",
  "reviewer_role": "independent_agent_review",
  "review_scope": "Description of code review, all-row audit and sampled examples.",
  "candidate_file_sha256": "exact candidate file hash",
  "audit_file_sha256": "exact audit file hash",
  "decisions": [{
    "example_id": "example identifier from the audit",
    "candidate_sha256": "exact canonical candidate hash from the audit",
    "decision": "approve",
    "reason": "Specific evidence supporting this example, including any limitation."
  }]
}
```

`export-manifest.json` records train/validation file hashes, review provenance and encounter grouping. The exporter submits no upload, paid inference or training job. A one-epoch experiment can proceed after independent review and provider preflight. Its meaningful result is the paired change on August 7 relative to the same untuned model, prompt and inference settings. Two-aircraft agreement remains a narrow pilot outcome.

# Benchmark data and label quality

This benchmark predicts **which of two observed arrivals appears first in the recorded runway-arrival-operation roster**. It does not recover controller commands or measure human ATC performance. The current user direction is to compare untuned models; fine-tuning and training export are deferred.

## Frozen data

| Split | SFO local dates | Disjoint pairs | Distinct source operation records | Missing observed altitudes |
| --- | --- | ---: | ---: | ---: |
| Development | August 3–6, 2026 | 488 | 976 | 968 |
| Validation | August 7, 2026 | 141 | 282 | 280 |
| Total accessible | Five historical days | 629 | 1,258 | 1,248 |

August 8–9 payloads and labels remain held out. The builder and independent audit use date-filtered SQL covering only August 3–7. No test scenario file is opened. Final artifacts are pinned in `benchmark/data/manifest.json` with source-query, code and file hashes.

Each source operation appears once across the accessible pairs. **1,258 source operation records does not mean 1,258 physical aircraft.** The same physical airframe can operate multiple flights. Registration is not exposed to the model, and this benchmark does not establish physical-airframe independence.

The source query finds 1,485 observed entry records on the permitted dates. Pair construction retains 1,258. It excludes 215 records without a sufficiently recent partner and six pairs outside feature bounds. This observed-position subset does not represent all historical arrival demand. Non-overlapping source operations prevent repeated snapshots; they do not make 629 pairs equivalent to 629 independent traffic days.

Development cases per day are 129, 116, 113 and 130. Validation contains 141 cases from one day. Label order starts with alias A1 in 262/488 development cases and 88/141 validation cases. Alias order is shuffled independently of operation timestamps. Report the label imbalance when interpreting small model differences.

## What a model receives

The model receives one static snapshot, containing two arbitrary local aliases and these features:

| Feature | Meaning and source |
| --- | --- |
| Distance and bearing | Great-circle geometry from each last-known observed entry position to the fixed airport reference point |
| Groundspeed and track | Derived from prior observed points during source preparation |
| Observation age | Snapshot time minus the entry observation time; never more than 300 seconds |
| Altitude and provenance | Beacon-reported altitude when present; otherwise null with `altitude_source: "unknown"` |
| Wake category | Disclosed, simplified medium/heavy mapping from aircraft type |
| Free-flow seconds | `max(0, distance / groundspeed * 3600 - observation_age)`; a straight-line estimate |
| Runway and rules | A shared synthetic resource and fixed simplified spacing rules for secondary scheduling metrics |

Each snapshot occurs at the later of its two entry observations. Earlier positions remain stale observations. The builder does not interpolate using a future recorded point. Inputs exclude callsigns, source identifiers, dates, historical operation times, historical runway assignments, future positions, future traffic and historical order.

Only ten of 1,258 inputs have observed beacon altitudes: eight development and two validation. Every encounter has at least one unknown altitude. Synthetic distance-profile heights from the source pipeline are removed before the model boundary. These data cannot support a meaningful altitude-control or vertical-separation benchmark.

## What the target means

Private source operation timestamps establish the recorded order. The builder excludes already-completed arrivals at the snapshot and rejects tied timestamps. Operation timestamps are not verified touchdown times. Close timestamp differences can make labels sensitive to source precision: 31 pairs differ by at most 30 seconds, including eight at most ten seconds.

The source lacks authentic clearances, controller intent, all traffic context and complete operating constraints. The recorded order is an observational reference. A mismatch does not establish unsafe behavior, inferior control or a failure to reproduce a human decision. No qualified human controller labels or simulator sessions are included.

All actual encounters contain **two aircraft**, despite the action contract permitting larger encounters. Next-arrival accuracy, exact-sequence accuracy and pairwise agreement therefore describe the same binary decision on valid responses. Invalid JSON or incomplete permutations fail the action contract. Secondary delay metrics use a synthetic scheduler; they do not measure historical human delay.

There is no evolving traffic simulation, heading instruction, altitude instruction, runway choice, radio exchange, go-around or full-airport traffic plan in this task. Every candidate model must receive the same frozen messages and output the same complete ordering schema. Broader ATC performance needs a separate closed-loop simulator benchmark and qualified human comparison sessions.

## Independent checks

The mechanical all-row audit reconstructs source features and targets through a separate SQL query and feature implementation. All 629 examples passed split, causality, provenance, schema, exact-prompt, label and disjointness checks. Each audit result records its reasons. The distinct reviewer examines the implementation, all-row findings and a sample including difficult and beacon-altitude cases; see `benchmark/independent_review.md`.

The audit validates the dataset's stated observational target. It does not establish that the target is optimal, that inputs contain enough context to predict every label, or that any generated ordering is safe ATC behavior. No training files were approved, exported or uploaded by this preparation workflow.

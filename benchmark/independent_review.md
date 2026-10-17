# Independent benchmark review

Reviewed October 17, 2026 by `/root/independent_review`, a separate agent from the benchmark, provider, and candidate-data authors.

**Accepted for a narrow recorded-arrival-order prediction experiment.** The frozen data contain 488 training pairs and 141 validation pairs. They do not support a human-versus-AI ATC quality claim. No authentic controller decisions or measured human safety/delay scores exist in these records.

The user cancelled fine-tuning during review. This document records benchmark and label-quality findings. It does not approve training, export, upload, or a paid job. No training review attestation was issued.

## Independent checks performed

I inspected `core.py`, `build.py`, `contracts.md`, `README.md`, `verify.py`, `provider.py`, `run_baseline.py`, `training.py`, and `review.py`. I separately reconciled every frozen case against date-filtered source SQL. I did not use the candidate author's audit as the source of the reconciliation.

The source query joined `entries.flight_id` to `arrivals.id`, restricted **both tables** to August 3–7, and selected `position_provenance = 'observed'`. This returned 1,485 source entry rows. No August 8–9 payload, scenario, observation, or outcome row was opened or evaluated.

All 629 cases passed these checks:

- The private target equals the ordering of the two source arrival-operation timestamps. Both operations occur after the snapshot; their timestamps differ.
- The snapshot equals the latest member entry time. Every observation precedes or equals that snapshot, with age from 0 through 300 seconds.
- Distance and bearing independently reproduce the source coordinates. Free-flow time reproduces `max(0, distance / groundspeed * 3600 - age)` within rounding tolerance.
- Groundspeed, track, wake category, altitude provenance, and private entry times match their source fields. Motion provenance is backward differences of observed points.
- Public inputs contain only the stated field allowlist. They exclude callsigns, source identities, dates, operation timestamps, future tracks, templates, and labels.
- Model messages contain exactly the public input. All 629 public messages are unique.
- All 1,258 source arrival-operation identities are distinct. This means no source flight is reused; it does **not** establish distinct physical airframes or independent traffic days.
- Alias assignment and candidate-list order reproduce the declared hash-seeded shuffles. The shuffle seed excludes operation timestamps and target order. Grouping uses entry-time adjacency.
- Candidate messages and labels match the same frozen baseline prompt, input, and recorded-order target. This is a provenance check, not training approval.

Altitude deserves explicit qualification: 1,248 of 1,258 aircraft rows have unknown height and carry `altitude_ft: null`. Only ten rows retain beacon-reported heights. All 629 cases contain at least one unknown height. Inferred distance-profile heights were removed before the reviewed freeze.

The source pipeline's accepted entry speed uses current and prior points. Its optional spike look-ahead branch is not entered for an accepted 90–550-knot entry point. This supports causal entry features, conditional on the existing offline flight matching and cleaning. I did not re-ingest the raw archive during this review.

## Sampled agent judgment

I inspected a deterministic random sample of 30 cases, using Python seed `20261017` on training cases followed by validation cases. I added the six smallest recorded-time gaps, six smallest free-flow gaps, first six free-flow disagreements, six stalest encounters, and every case with a beacon height. Removing overlaps leaves **59 inspected cases**.

Examples illustrate why roster provenance and good control must remain separate:

| Case | Observation and judgment |
| --- | --- |
| `seq-57ba1611ace5c55c8f25` | A2 has a 300-second-old entry and a smaller free-flow estimate. A1 appears 813 seconds earlier in the roster. The label is correct for the stated task; the input does not establish why that order occurred. |
| `seq-18dc20876b496b3a1777` | Recorded operations differ by one second. The literal target is reproducible, but it is weak evidence of a deliberate controller preference. |
| `seq-9e4a71647e3fe323e18e` | A validation pair also has a one-second recorded gap. It remains in the frozen dataset; it is not silently discarded after inspection. |
| `seq-ce4452b3f377549df186` | Free-flow estimates differ by about 0.22 seconds; recorded operations differ by five seconds. Small numeric differences do not establish operational superiority. |
| `seq-b95af7eb76035fd58092` | Free-flow estimates differ by about 0.42 seconds, while recorded operations differ by 613 seconds. Matching the heuristic is not the target. |
| `seq-b2152e14ee0a435d3cd2` | Staleness adjustment clips A1's free-flow estimate to zero although its recorded operation occurs 202 seconds later. The estimate is a disclosed heuristic, not an actual arrival time. |
| `seq-331186d43c156fbe7376` | One beacon height is 11,100 feet at about 8.45 NM. Retaining a reported value does not establish physical plausibility or enough state for safety evaluation. |
| `seq-ba96b41b37e7172dd86e` | A heavy aircraft's roster order agrees with the source. This does not validate the simplified scheduler's wake policy as a complete operational rule. |

No sampled case showed a mislabeled literal roster order or a future observation in its public features. I accept these labels for observational order prediction. I reject their interpretation as expert-approved commands, optimal actions, or human performance measurements.

## Scoring and comparison limits

Each case has two aircraft. Exact-sequence accuracy, next-arrival accuracy, and pairwise agreement are therefore the **same binary score**, not three independent measures.

The aliases are randomized, but the frozen validation sample has a substantial class imbalance:

| Deterministic reference | Training | Validation |
| --- | ---: | ---: |
| Always A1 first | 262/488 = 53.69% | 88/141 = 62.41% |
| Candidate-list order | 247/488 = 50.61% | 64/141 = 45.39% |
| Smaller free-flow estimate first | 315/488 = 64.55% | 91/141 = 64.54% |

Always A1 is also the constant class selected from training, so its validation result does not require selecting a class on validation labels. Report it alongside physics heuristics. A model can exceed 50% here through alias preference alone.

Twenty-two training pairs and nine validation pairs have recorded gaps of at most 30 seconds. Five and three, respectively, have gaps of at most ten seconds. These remain literal roster labels. The source does not establish that such small gaps represent meaningful ATC choices.

There are only four training days and one validation day. Flight pairs are disjoint, but weather, routing, runway usage, and traffic patterns remain shared. A case-level confidence interval describes this selected day's cases under additional independence assumptions; it does not establish performance across unseen days. Do not treat repeated calls, pairs, or seeds as additional independent historical days. Keep August 8–9 sealed until a later frozen final evaluation.

The synthetic scheduler enforces its own release and spacing rules after receiving the model's permutation. Consequently, zero constructed schedule violations do not demonstrate model safety. Delay and backlog are secondary results under those synthetic rules. There are no heading, altitude, landing-clearance, continuous-separation, communication, or full-traffic decisions in this task.

## Provider and first live-run review

Static provider review found a bounded output, fixed inference settings, persistent spend reservations, and no automatic paid retries. A lost response retains its reservation. Credentials are read without shell execution and are absent from the stored request. The action parser checks the original raw response; it rejects duplicate keys, extra text, extra fields, missing IDs, and repeated IDs. Invalid output is not repaired or replaced with a heuristic.

I independently inspected and rescored the first Lightning validation run at `results/untuned-lightning-validation-20261017`. All 141 calls used the exact frozen public messages. Its artifact hashes match the summary. There were 121 valid responses and 20 HTTP 429 rate-limit failures, with no retries. The model matched 39 labels:

- Overall score, counting availability failures as incorrect: **39/141 = 27.66%**.
- Score on valid responses: **39/121 = 32.23%**.
- On those same 121 successful-call cases: free-flow reference **77/121 = 63.64%**, always-A1 **72/121 = 59.50%**, candidate-list order **54/121 = 44.63%**.

These are different denominators. The successful subset excludes cases because of rate limiting, so its result is not a replacement for the complete operational score. For later model comparisons, report availability separately and compare capability on a shared successful-case subset when needed. Keep exact run directories and settings distinct. This review does not certify later model runs.

## Executed verification and frozen hashes

`pipeline/.venv/bin/python -m benchmark.verify` passed against all 629 cases. It verified hashes, split dates, unique public messages, source disjointness, and every scripted, historical, and oracle schedule. A separate runtime probe rejected seven malformed actions, rejected the `test` split before file access, and rejected a deliberately invalid spacing schedule.

The independent reconciliation described above passed for all cases and candidates. These hashes bind this review to the inspected bytes; later changes require a new review.

| Artifact | SHA-256 |
| --- | --- |
| `core.py` | `9b18d15e6e9af86004d6a26e14a5515b0dd772020370a17c63c41e6a082e99d9` |
| `build.py` | `888a7c50a8ca04ba88f5d1e8c21d1326f383ec62f70f3148a611dea11931003f` |
| `data/manifest.json` | `c0513a38a742ad1ab53b5b63299dfd700db573a45612f48087ba7971e0c20d53` |
| `data/train.jsonl` | `ee1821c0be23007dca4f1ab4042297886552a5a6fb15ba10f2bfb11332fe7254` |
| `data/validation.jsonl` | `bcbcb8d74ba3f54d65f82945c7ce231bdc9e91c31ef980fd586e5cb16f600b11` |
| `provider.py` | `32b3b059c3e28ae33c60d3fb1a770e286197e96870bb3c3ed1b7ac85f74c1574` |
| `run_baseline.py` | `644de2a5c540f06cbc770f53b0c5b991351480025a5d336dfae820110a891a4b` |
| `artifacts/training/candidates.jsonl` | `5361fec1e1c3b49ac89e0173fd39c553910d52e5171d7090884164ea8d87e05e` |
| `artifacts/training/audit.json` | `8922c7ee82d184db7a69e29f8e64bbf32ec07e935353f55fc8edfe68517c5836` |
| `results/untuned-lightning-validation-20261017/summary.json` | `99087058c62a69f34229f8e5f2c8b4f4b554710816443f29f2b2974b189aa832` |

## Completed five-model comparison review

After the initial review, I separately audited all five completed comparison runs. Every run contains exactly 141 unique call identities and the same 141 exact public prompts. Each raw successful response passes the strict parser and equals its saved action. Independently recomputed metrics match the saved scores. Summary artifact hashes and the archived source hashes match their run plans. There were no automatic paid retries.

The comparison uses the paced Lightning run; the earlier Lightning run remains a separate availability observation. The current provider and runner are archived inside each run's `frozen_source` directory. They are separate from the initial source hashes above. The model architectures use disclosed controls: GPT-OSS uses low reasoning effort; the other four use thinking disabled. Latency therefore includes provider service conditions and these configurations, not just model architecture.

| Model | Correct across all 141 cases | Correct among its valid responses | Correct on the same 90 successful cases |
| --- | ---: | ---: | ---: |
| Nemotron 3.5 Lightning | 26/141 = 18.44% | 26/98 = 26.53% | 23/90 = 25.56% |
| Nemotron 3 Nano | 47/141 = 33.33% | 47/137 = 34.31% | 27/90 = 30.00% |
| Nemotron 3.5 Super VL | 76/141 = 53.90% | 76/136 = 55.88% | 45/90 = 50.00% |
| GPT-OSS 120B | 91/141 = 64.54% | 91/137 = 66.42% | 55/90 = 61.11% |
| Qwen 3.8 27B | 79/141 = 56.03% | 79/136 = 58.09% | 50/90 = 55.56% |

Lightning had 39 HTTP 429 failures and four ambiguous transport failures. Nano and GPT-OSS each had four transport failures. Super VL and Qwen each had five. These failures count as incorrect only in the first accuracy column. The per-model valid-response columns use different subsets; the last column uses identical case identities across all five models.

The shared 90-case set is selected by successful provider responses. It is a useful paired diagnostic, not an unbiased sample or a replacement benchmark. Success can depend on request timing, provider load, and prompt properties. Report its selected nature beside the values.

The additional older-entry reference orders the pair by observation age, oldest first. It scores **100/141 = 70.92%**, and **68/90 = 75.56%** on the shared successful subset. This rule was added after inspecting the validation run, so it is a **posthoc diagnostic reference**. It is not authentic controller first-come priority. It does not establish performance on other traffic days. On the shared 90 cases, free-flow scores 52/90, always-A1 scores 55/90, and candidate-list order scores 40/90.

GPT-OSS is the best model in these runs. It ties the free-flow reference's 91 correct predictions across all 141 cases. On the selected 90 cases it ties always-A1, with 55 correct predictions. None of the five models exceeds the posthoc older-entry reference on either set. These statements describe recorded-order agreement under the supplied inputs, not human ATC ability.

I reviewed the comparison reporter's numerical formulas. Its Wilson interval and exact discordant-pair test are mathematically correct. The paired test compares full-split model outcomes against free-flow, including availability failures. Its unadjusted values remain exploratory because there are five comparisons and only one traffic day. The simple case-level statistical model does not account for within-day traffic dependence.

The initial reporter needed three presentation/provenance improvements, which I sent to its author: expose all three accuracy denominators in Markdown; label the shared subset and posthoc reference; and verify raw call identities, exact prompts, actions, and artifact hashes before aggregation. The independent reconciliation above already establishes those facts for these specific completed runs. Changes to report code should retain those checks. Costs must show unknown-cost request counts, and latency labels must specify whether they require a valid action or only a completed provider response.

Final run-summary hashes independently verified:

| Run directory under `results/` | SHA-256 of `summary.json` |
| --- | --- |
| `lightning35-paced-validation-20261017` | `0a4afab48e935f386b4579be9c54aa4fd10535de2afbe495360f4e071628769e` |
| `untuned-nano3-validation-20261017` | `116782643dfa0534220cc8ca6331d25156622be8dfc4931ff07e9fc972420c88` |
| `super35vl-validation-20261017` | `9e4a450dc9eb4a1400e4467736dd2b896672ce10ed41cb246dbf7102e0db4f99` |
| `gpt-oss-120b-validation-20261017` | `05880d42a3f7cf74e313d02b567076bd8d04131625781595abbc1a65ca8c1c6f` |
| `qwen38-validation-20261017-final` | `7801f2b09e42541aeae026dc2f12658b5bc2d12642064c0656b270e45cb0e204` |

## Final reporter recheck: passed

The reporter fixes are complete. I inspected the revised `report.py` and the generated `reports/2026-10-17/comparison.json` and `comparison.md`. I executed the reporter's read-only raw-run audit across all five runs, then independently checked its exported aggregates and per-case records.

All **705 raw decisions** passed the provenance checks. The reporter now verifies exact call membership, unique request identities, request payload hashes, public messages, generation settings, original response parsing, saved decisions, score recomputation, artifact checksums, and archived source checksums. Every one of the 141 exported per-case records agrees with the frozen validation label and the five raw-run decisions.

All three accuracy denominators now appear in the Markdown table. The shared successful-case list contains the same 90 identities I reconstructed independently. All model numerators, baseline numerators, valid-action counts, known token costs, unknown-cost counts, valid-response medians, and valid-response p95 values match recomputation. The report labels the older-entry reference as posthoc and the common subset as selected by provider success. It preserves the one-day and human-performance limitations. No unresolved numerical or provenance finding remains for these report files.

No held-out payload was opened and no new inference occurred during this recheck. This acceptance covers the files below, not a future benchmark or a broader ATC performance claim.

| Final artifact | SHA-256 |
| --- | --- |
| `report.py` | `d1ce3593037a90f1681a9d73b335a54951793dc52862d4fcd1b8907245322bac` |
| `reports/2026-10-17/comparison.json` | `5678854a2fe7564307ed964e36f653b7e1d51fe8cd6dcca20d9556c1b89e7a74` |
| `reports/2026-10-17/comparison.md` | `11dabb15e3afbb16b21b2600861b9d4ca5458579a8c6155ee0d43c5a8d453a9b` |

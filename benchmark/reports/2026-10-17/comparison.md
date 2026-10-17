# Model comparison on historical arrival order

All runs use the same 141 validation pairs from August 7, 2026. August 8–9 remain untouched. No fine-tuning ran.

The task predicts which of two arrivals appears first in the recorded operation roster. It does not grade authentic ATC commands or human control quality.

| Model | Full 141 accuracy | Valid responses | Accuracy on own valid responses | Common 90 accuracy | Median valid response | Known token cost / unknown requests |
|---|---:|---:|---:|---:|---:|---:|
| openai/gpt-oss-120b | 91/141 = 64.5% | 137/141 | 91/137 = 66.4% | 55/90 = 61.1% | 1.57s | $0.00577 / 4 |
| Qwen/Qwen3.8-27B | 79/141 = 56.0% | 136/141 | 79/136 = 58.1% | 50/90 = 55.6% | 1.27s | $0.01660 / 5 |
| nvidia/NVIDIA-Nemotron-3.5-Super-VL | 76/141 = 53.9% | 136/141 | 76/136 = 55.9% | 45/90 = 50.0% | 1.44s | $0.00666 / 5 |
| nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B | 47/141 = 33.3% | 137/141 | 47/137 = 34.3% | 27/90 = 30.0% | 1.12s | $0.00335 / 4 |
| nvidia/Nemotron-3.5-Lightning-30B-A3B | 26/141 = 18.4% | 98/141 | 26/98 = 26.5% | 23/90 = 25.6% | 1.03s | $0.00240 / 43 |

## Simple reference rules

- free_flow_heuristic: 91/141 = 64.5%; same common 90: 52/90.
- older_observed_entry_first (posthoc diagnostic): 100/141 = 70.9%; same common 90: 68/90.
- always_A1: 88/141 = 62.4%; same common 90: 55/90.
- candidate_list_order: 64/141 = 45.4%; same common 90: 40/90.

Common successful-case intersection: 90/141. Invalid or unavailable responses count as incorrect in the full-split accuracy above.

With two aircraft, next-arrival accuracy, exact-order accuracy and pairwise agreement are the same binary metric. Synthetic scheduling checks are kept out of the primary leaderboard.

The common subset depends on provider success and is a selected diagnostic, not an unbiased test. Own-valid columns use different cases for each model. Full-split accuracy counts unavailable decisions as incorrect.

## Service failures

- nvidia/Nemotron-3.5-Lightning-30B-A3B: {"HTTP 429": 39, "ambiguous_failure": 4}.
- nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B: {"ambiguous_failure": 4}.
- nvidia/NVIDIA-Nemotron-3.5-Super-VL: {"ambiguous_failure": 5}.
- openai/gpt-oss-120b: {"ambiguous_failure": 4}.
- Qwen/Qwen3.8-27B: {"ambiguous_failure": 5}.

## Limits

- One binary recorded-operation-order prediction per two-arrival encounter.
- Agreement with recorded order does not measure human ATC quality, safety or causal efficiency.
- Position features are observed-entry snapshots, not full current radar histories.
- All models receive the same inputs and task prompt; architecture-specific thinking controls are disclosed.
- Intervals condition on this one validation day and do not establish generalization to other days.
- The common-success intersection is a provider-success-selected diagnostic subset, not an unbiased test.
- Older observed entry first was added after the initial run; it is a posthoc diagnostic reference.
- Paired tests compare full-split operational outcomes including unavailable responses against free flow.
- Unadjusted paired tests are exploratory; no multiple-comparison correction or model selection on final test.
- Token costs are provider-usage estimates, not invoices; unknown charges are reported separately.
- Fine-tuning was deferred by the user; no datasets uploaded or jobs submitted.

Detailed scores, generation settings, confidence intervals, paired comparisons and run hashes are in comparison.json and each source run directory.

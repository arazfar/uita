# Nemotron error analysis

This analysis reuses the five completed validation runs. It sends no new inference requests, changes no benchmark targets, and accesses no final test data. All 705 raw calls were checked again against frozen prompts, payloads, source snapshots, and strict response parsing. [Machine-readable diagnostics and example inputs](error-analysis.json) preserve the counts below.

The result compares specific served configurations on recorded arrival-order prediction. It does not establish an overall capability ranking or measure human ATC decision quality.

## Wrong predictions versus service failures

Each row contains 141 attempted cases. “Wrong valid answer” means a complete, valid permutation that disagrees with the recorded roster order.

| Model | Correct | Wrong valid answer | HTTP 429 | Transport failure | Invalid output | Accuracy when valid |
|---|---:|---:|---:|---:|---:|---:|
| Nemotron 3.5 Lightning | 26 | 72 | 39 | 4 | 0 | 26/98 = 26.5% |
| Nemotron 3 Nano | 47 | 90 | 0 | 4 | 0 | 47/137 = 34.3% |
| Nemotron 3.5 Super VL | 76 | 60 | 0 | 5 | 0 | 76/136 = 55.9% |
| GPT-OSS-120B | 91 | 46 | 0 | 4 | 0 | 91/137 = 66.4% |
| Qwen3.8-27B | 79 | 57 | 0 | 5 | 0 | 79/136 = 58.1% |

HTTP 429 is a rate-limit rejection. Transport failures include lost connections or timeouts without a usable response; the audit does not identify their exact infrastructure cause. They receive no paid retry. They count as failed decisions in the operational score, but they are not wrong model predictions.

Super VL had no rate-limit failures. Its five unavailable responses cannot explain its 60 wrong answers. Even replacing all five failures with correct answers would yield 81/141, below GPT's observed 91/141. That is a numerical upper bound, not an estimate of how the missing responses would behave.

On the **133 cases where Super and GPT both returned valid answers**:

| Outcome | Cases |
|---|---:|
| Both correct | 70 |
| GPT correct, Super wrong | 17 |
| Super correct, GPT wrong | 4 |
| Both wrong | 42 |

Super scored 74/133 = 55.6%; GPT scored 87/133 = 65.4%. This removes response availability from their paired comparison. The subset is still selected by provider success and covers one validation day. The exploratory paired exact test gives p = 0.00720; it does not establish general capability or performance on independent days.

## What the model outputs show

The simple free-flow rule sorts the supplied `free_flow_seconds` from smallest to largest. On Super's 136 valid cases it gets 87 correct. Super changes 15 of those orders: 13 changes break a correct prediction and two fix an error. Thus `87 - 13 + 2 = 76`.

All 15 changes choose the aircraft with the newer observation. This is consistent with over-weighting observation recency or misreading stale state, but the JSON answers do not prove an internal cause. A controlled input ablation is needed to distinguish age handling, list order, alias effects, and other features.

GPT changes eight free-flow orders on its own valid cases: three changes hurt and five help. Thus `89 - 3 + 5 = 91`. These own-valid subsets differ; the 133-case paired table above supplies the direct model comparison.

The smaller Nemotron models show a stronger recency pattern. Excluding equal-age cases, Lightning selects the newer observation in **93/95** cases and Nano in **114/132**. The older-observation rule happens to match this day's roster well. Choosing newer observations therefore produces many wrong historical predictions. This finding describes outputs; it does not recover either model's reasoning.

No valid response ended because of the token limit. Every valid response finished normally. JSON formatting and truncation do not explain the gap.

## Configuration limits the capability claim

The requests explicitly disable Nemotron thinking. Super's 136 usage records each report zero reasoning tokens. GPT uses `reasoning_effort: "low"`; all 137 valid responses contain a nonempty provider reasoning field. Therefore, identical temperature and output-token limits did not produce equivalent reasoning modes.

NVIDIA released Super VL on October 15, 2026. Its official model card supports reasoning off, on, and medium effort. Its text example enables thinking, uses temperature 1.0 and top-p 0.95, and allows 16,384 output tokens. Our run used thinking off, temperature 0, top-p 1, and a 1,024-token bound. The effects of those settings were not isolated in this experiment. [NVIDIA model card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-BF16/blob/main/README.md), [release announcement](https://developer.nvidia.com/blog/nvidia-nemotron-3-5-super-vl-powers-specialized-agents-with-multimodal-reasoning/).

The supported off setting is valid for a low-compute comparison. It does not measure the model's best reasoning capability. A recent release or broader benchmark strength also does not guarantee a win on one sparse observational target. This experiment uses text snapshots, not images, tools, or extended agent workflows.

## Concrete examples

All examples below come from August 7 validation data. Times are the already age-adjusted free-flow estimates, not recorded arrival times. Full inputs and every model's final action are in `error-analysis.json`. Both aircraft have medium wake categories and unknown altitudes in these examples.

### 1. Super makes a wrong prediction while GPT is correct

Case `seq-eb6c4b9f7ac7066a7b0a`:

| Aircraft | Distance | Groundspeed | Observation age | Free-flow estimate |
|---|---:|---:|---:|---:|
| A1 | 70.97 NM | 431.98 kt | 115 s | 476.43 s |
| A2 | 74.67 NM | 318.84 kt | 0 s | 843.07 s |

The recorded order is **A1 → A2**. GPT and Qwen return that order. All three Nemotron models return **A2 → A1**, despite A1's shorter estimate. Each Nemotron response is valid JSON from a successful HTTP 200 request. This is a wrong historical prediction, not an API failure. The answer alone does not reveal why the model chose it.

### 2. Super is correct while GPT is wrong

Case `seq-f0738f539bf128a489ff`:

| Aircraft | Distance | Groundspeed | Observation age | Free-flow estimate |
|---|---:|---:|---:|---:|
| A1 | 54.81 NM | 419.70 kt | 0 s | 470.15 s |
| A2 | 71.72 NM | 296.02 kt | 204 s | 668.23 s |

The recorded order is **A1 → A2**. Super, Nano and Qwen return that order. GPT returns **A2 → A1**. The free-flow estimate already accounts for observation age; subtracting age again would incorrectly move A2 ahead in this case. This illustrates why a higher aggregate agreement score does not establish consistently better interpretation of the input fields.

### 3. Every model disagrees with the recorded order

Case `seq-a588cbe48d28bba5620b`:

| Aircraft | Distance | Groundspeed | Observation age | Free-flow estimate |
|---|---:|---:|---:|---:|
| A1 | 69.37 NM | 427.84 kt | 0 s | 583.72 s |
| A2 | 75.95 NM | 130.05 kt | 229 s | 1,873.48 s |

Every model predicts **A1 → A2**. The recorded roster says **A2 → A1**. The static estimates favor A1, but complete routes, subsequent speeds, controller intent, and runway context are absent. This is evidence of an incomplete prediction setting, not proof that the label is wrong or every model would make an unsafe clearance.

### 4. An unavailable response, not a wrong prediction

Case `seq-2b2fbc274422140bcd73`: Super returns no usable response after about 65 seconds; GPT also has a transport failure. Lightning receives HTTP 429. There is no returned order to inspect for those three models. The operational scorer records failures, while this analysis keeps them separate from wrong answers.

## What would identify the cause

First compare Super reasoning off versus on with the same frozen public inputs and prompt. Use a sufficient common output budget, record actual reasoning tokens, and keep sampling fixed for that ablation. Keep successful-answer accuracy separate from provider availability.

Then compare each model's documented recommended configuration as a separate experiment. Report cost and latency with accuracy. Use development cases for age-field wording, alias, candidate-order, and distracting-rule ablations; mark these as new protocols rather than overwriting the frozen v1 leaderboard. Keep August 8–9 held out.

These tests would distinguish configuration sensitivity and prompt interpretation from a broader model limitation. The current data establish the wrong-answer patterns and service failures, but not their internal causal mechanism.

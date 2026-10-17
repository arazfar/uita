# Saved live-program reevaluation

Original generation job: `c48013be-0eeb-40c7-86e9-3a2f24623485`. Provider/model: Crusoe / `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`. Its **2 original calls**, 986 input tokens and 66 output tokens cost **$0.00006250**. These charges are historical; this reevaluation made **zero inference calls and incurred $0 fresh inference cost**.

The original artifact is preserved unchanged. Its SHA-256 is `64ed3ca0458b1439ec65e222ac6932152022019262a4afd4801aa49118a7860c`. Candidate and stateless program hashes and original request metadata are retained in the raw reevaluation artifact.

Final evaluator: `closed-loop-matched-eval-3`. Objective version: `normalized-research-objectives-1`. Configuration hash: `15b870294c336dabe4431ffba2be02b729fa4971b40162672bceb87ba91c26b0`.

All policies execute the same fixed development/validation seeds and event tapes, eight optional reads per decision, solver limits and normalized objectives. The fresh stateless model program was generated without an accepted parent and is reused only for this comparison; it is not a fresh LLM call at every decision.

| Policy | Validation score ↓ | Score stddev | Mean delay (s) | Mean backlog | Passing cases | Outcome |
|---|---:|---:|---:|---:|---:|---|
| FCFS | 1.4162 | 0.0362 | 1800.7 | 8.88 | 16/16 | Comparator |
| Strong static | 1.2597 | 0.0565 | 1570.2 | 8.25 | 16/16 | Comparator |
| Saved stateless model | 1.2597 | 0.0565 | 1570.2 | 8.25 | 16/16 | Comparator |
| Nemotron observation candidate | 1.2597 | 0.0565 | 1570.2 | 8.25 | 16/16 | rejected |

Final held-out status: **not-consumed-no-promotion**. Candidate outcomes are recomputed against the final fixed criteria, and no registry activation occurs in this script.

Score is the fixed normalized combination of delay, backlog, phase/wake-specific delay-equivalent fuel, relative day/night noise, synthetic-group service, starvation, instability and verified-replan recovery. Environmental values are proxies; admission/gate scheduling delay is not reported as actual airborne/taxi holding. Recovery refers to obtaining a passing replan, not restoring airport capacity.

Every raw seed/variant, event tape, decision, metric component, solver cost, rejection and unfinished-flight count is in [live-program-reevaluation.json](live-program-reevaluation.json).

Reproduce: `PYTHONPATH=backend .venv/bin/python scripts/reevaluate_live.py docs/research/live-experiment-2026-10-17.json --output docs/evaluation/live-program-reevaluation.json`

# Five-model reasoning comparison: August 24–30, 2026

All ten model configurations completed the same 42 evaluation windows. Each received 1,029 historical arrival requests. All initial states use synthetic development templates. These are not observed late-August paths.

**The deterministic planner beats every model configuration under the declared objective.** Safety eligibility comes first, then fewer unfinished arrivals, then lower penalized delay. The best model system completed 426 arrivals versus 427 for the planner. Its 87.1% fallback rate prevents attributing that score to the model alone.

| Controller | Reasoning | Completed / 1,029 | Mean accrued delay | P95 delay | Usable responses | Checked fallbacks |
|---|---|---:|---:|---:|---:|---:|
| Scripted | N/A | 408 | 1288.7s | 2350.3s | N/A | 0 |
| Deterministic | N/A | 427 | 1277.0s | 2622.1s | N/A | 0 |
| Nemotron 3.5 Super VL | OFF | 412 | 1290.1s | 2416.9s | 539/566 | 27 |
| Nemotron 3.5 Super VL | ON | 425 | 1275.6s | 2633.1s | 223/566 | 343 |
| Nemotron 3.5 Lightning | OFF | 395 | 1345.3s | 2618.0s | 364/570 | 206 |
| Nemotron 3.5 Lightning | ON | 426 | 1276.9s | 2619.9s | 56/566 | 510 |
| Nemotron 3 Nano | OFF | 397 | 1348.3s | 2625.5s | 334/569 | 235 |
| Nemotron 3 Nano | ON | 426 | 1276.4s | 2622.1s | 73/566 | 493 |
| Qwen 3.8 27B | OFF | 409 | 1299.7s | 2492.7s | 542/566 | 24 |
| Qwen 3.8 27B | ON | 425 | 1276.6s | 2649.2s | 184/566 | 382 |
| Gemma 4 31B | OFF | 410 | 1288.5s | 2354.8s | 547/566 | 19 |
| Gemma 4 31B | ON | 425 | 1276.8s | 2619.8s | 94/566 | 472 |

All twelve systems had zero checked executed violations and zero unresolved decisions. Shared synthesis and verification enforce this limited safety model. Upstream feeder and queue safety remain outside scope. Delay measures modeled admission waiting, including censored waiting for unfinished demand. It is not historical airline delay.

Reasoning-ON scores are dominated by checked fallbacks. The [failure analysis](failure-analysis.md) separates action mistakes, transport failures, HTTP errors and output-token truncations. The common 8,192-token budget and 60-second socket timeout bound this comparison. Measured wall latency can exceed 60 seconds. No pure reasoning-capability or human-controller superiority claim follows.

Independent replay passed all 504 results, 6,799 decisions and 5,667 scored raw requests. Ten development preflights are separate. No paid POST was retried. Two interrupted windows were recovered from preserved calls and snapshots. Four original fallback producers and solver details remain unknown. See [verification](verification.json) and [review](../../review.md).

Known usage cost was $10.15734. The 980 unknown charges retain $5.11866 of exposure. Known cost plus unknown exposure totaled $15.27599, below the $30 cap.

August 8–9 remain excluded from generated datasets, model inputs and evaluation. No fine-tuning or model promotion occurred.

[Interactive leaderboard](index.html) · [CSV](leaderboard.csv) · [Completion chart](completion.svg) · [Delay chart](delay.svg) · [Testing and objective](../../README.md)

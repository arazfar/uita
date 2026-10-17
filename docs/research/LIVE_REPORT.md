# Live Crusoe / NVIDIA Nemotron verification

On 2026-10-17, the user's credential successfully authenticated capability discovery and two generation requests. The exact discovered and used model was `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`; the public catalog omitted `NVIDIA-` from its spelling. The adapter pinned the authenticated identifier. Credentials are not included in this report or repository.

The first live job was `c48013be-0eeb-40c7-86e9-3a2f24623485`. It queued in 57 ms and completed in approximately 3.94 seconds, including development evaluation, candidate and stateless proposal calls, and isolated evaluation. The persistent aggregate spend cap was $0.05. Actual reported usage was 986 input tokens and 66 output tokens across two calls, with **estimated cost $0.0000625** using discovered rates cross-checked against Crusoe's per-million-token pricing. This is an estimate, not an invoice. Worst-case reservations remain charged against the application's cap even after lower actual usage.

The model received a compact summary of two reproducible development cases, permitted observations, and the current parent program. A second call received the same development evidence without an accepted parent or registry memory. Both returned ordered optional observations `exit_occupancy, gate_ready, wake, weather`. The verifier and mandatory observations remained fixed; each decision allowed eight optional reads. The stateless baseline is one fresh proposal fixed for the experiment, not a new LLM call at every control decision.

## First live evaluation result

Sixteen validation episodes paired four fixed seeds with baseline, exit-congestion, departure-bank and transfer variants. Each episode executed plans, advanced logical time and replayed the same arrival-demand and gate-delay event tape. The horizon was 2,700 logical seconds, starting at 400. The reported tail column is the maximum episode p95, not a pooled percentile.

| Policy | Feasible episodes | Mean delay, s | Worst episode p95, s | Mean remaining backlog | Mean delay-plus-backlog score |
|---|---:|---:|---:|---:|---:|
| FCFS | 16/16 | 1,800.69 | 3,841 | 8.875 | 32,335.44 |
| Hand-authored static | 16/16 | 1,570.19 | 3,637 | 8.250 | 28,502.94 |
| Live candidate | 16/16 | 1,570.19 | 3,637 | 8.250 | 28,502.94 |
| Stateless Nemotron | 16/16 | 1,570.19 | 3,637 | 8.250 | 28,502.94 |

The candidate was **rejected**: it did not improve static and parent validation score by the fixed 1% threshold. No candidate was promoted and no final held-out set was consumed. These results do not establish accumulated-learning benefit. The large delays and backlogs are consequences of a deliberately restrictive shared runway/surface research model; they are not estimates of real SFO capacity.

Raw provider settings, capability metadata, proposal, lineage, fixed criteria/configuration hash, every episode, event tape, observation trace, solver timings and unfavorable results are retained in [live-experiment-2026-10-17.json](live-experiment-2026-10-17.json). This is the first live integration run; subsequent model changes and final reproducible evaluation reports are versioned separately rather than rewriting this evidence.

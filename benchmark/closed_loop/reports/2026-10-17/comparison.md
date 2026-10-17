# Historical-demand closed-loop comparison

Six August 7 validation windows; 136 arrival requests per controller; seed 17; nominal conditions. August 8–9 stay held out.

| Controller | Completed | Backlog | Executed violations | Mean accrued added delay, all demand | P95 accrued delay | Controller failures | Checked fallback decisions |
|---|---:|---:|---:|---:|---:|---:|---:|
| scripted | 62/136 | 74 | 0 | 1177.8s | 2228.0s | 0 | 0 |
| deterministic | 63/136 | 73 | 0 | 1164.6s | 2520.5s | 0 | 0 |
| ai | 63/136 | 73 | 0 | 1168.9s | 2585.1s | 50 | 50 |

Delay values include accrued waiting for unfinished demand, censored at the common end time. Interpret them together with backlog; completed-only means select different aircraft.

The deterministic planner completed one more arrival than the scripted baseline and reduced mean accrued added delay by 1.12%. The AI-plus-fallback system also completed one more arrival and reduced that mean by 0.76%. Its mean was 4.28 seconds higher than the deterministic planner's.

Tail delay worsened: P95 increased from 2,228.0 seconds for scripted control to 2,520.5 for the planner and 2,585.1 for AI plus fallbacks. These results do not justify promoting the AI controller as an efficiency improvement over the deterministic planner.

Only 33 of 83 AI requests produced usable orders. The 50 fallback decisions comprised 28 transport failures, 20 token-limit truncations, one invalid action, and one HTTP 500 response. These are retained failures, with no paid retries. The row measures the checked AI-plus-fallback system rather than a pure model controller.

Zero executed violations reflects the common serialized resource model, trajectory synthesizer and independent safety gate. It does not show that the language model learned safe unrestricted ATC. The high backlog also reflects this deliberately conservative shared-resource capacity.

Known token cost for the 83 included requests was $0.06928; 29 request charges were unknown. The complete shared budget reserved $0.24564 under its $1 cap, including four preflight requests excluded from the final matrix. Preliminary requests were retained locally and not selected for a better score.

## Limits

- Historical demand with reconstructed feeder and fixed final approaches; upstream feeder and waiting are not safety-modeled.
- Added delay is modeled admission waiting. Unfinished values are right-censored at the common drain end; backlog penalty is 3600 seconds.
- All controllers have the same announced synthetic occupancy and safety envelope. Safety is enforced by common synthesis and verification.
- AI outcomes include explicitly recorded deterministic/scripted fallbacks for API, contract, or verification failures.
- Simulation time pauses for controller computation. API wall latency is not added to simulated flight time.
- One nominal seed and six validation windows from one historical day do not establish operational safety or human-controller superiority.
- Independent AI windows ran concurrently to bound wall time; per-model dispatch pacing and the aggregate $1 cap remained enforced.
- August 8–9 remain held out.

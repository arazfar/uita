# Historical-data benchmark and Nemotron fine-tuning plan

Prepared October 17, 2026. Scope: simulated SFO arrivals seeded from August 3–9, 2026. Railway PostgreSQL replaces the initial Supabase storage request.

**Current status:** fine-tuning is deferred at Oscar's request. The separate, narrow historical arrival-order pilot is complete for five untuned models: [results](../benchmark/reports/2026-10-17/comparison.md), [objective and testing](../benchmark/TESTING.md). Its primary score measures recorded-order agreement, not human control quality. The broader simulator benchmark below remains a plan for the harness team.

## What we can measure

Use a benchmark now. It is necessary to distinguish an improved controller from a changed simulator or easier traffic.

The current data contain arrival-operation times and partial aircraft paths. They do **not** contain authentic clearances, full pilot intent, complete departures, verified touchdown times, historical closures, or a complete runway occupancy record. Thus, historical tracks are **traffic inputs and descriptive references**, not human command labels. A path change does not reveal which command caused it. Another valid command need not reproduce the same path.

Compare controllers under the same simulator and traffic first. To make a genuine human-versus-agent claim later, recruit an ATC subject-matter expert to control the **same simulator scenarios** under the same information and action limits. Keep the human sessions separate from the training corpus. Recovered radio audio would need legal access, transcription, aircraft association, time alignment, missing-channel handling and expert review; it is a larger project.

## Two approaches

| Approach | Benefit | Limitation | Decision |
|---|---|---|---|
| Match recorded trajectories or landing sequence | Fast, useful for replay sanity checks | Rewards imitation of unknown decisions; incomplete tracks and missing control context make causal claims invalid | Secondary descriptive reference only |
| Run identical traffic through a frozen simulator and independent checker | Measures safety, completion, delay and cost after new actions | Results depend on simulator fidelity and reconstructed initial states | Primary hackathon benchmark |

Keep the original agent, improved agent and a deterministic first-come sequencing baseline. If fine-tuning is added, compare it with the **same base model, prompt, tools, inference settings and checker**. A stronger model is a useful separate baseline, but it does not isolate the fine-tuning effect.

## Small benchmark that works

1. Freeze August 3–6 for training and policy development, August 7 for validation, and August 8–9 for the final test. This makes the brief's development/validation split explicit.
2. Use six preselected windows per local day: 06:00, 09:00, 12:00, 15:00, 18:00 and 21:00. Each has 15 minutes of warmup, 30 minutes of demand, and 30 minutes to finish remaining traffic.
3. This yields 24 development, 6 validation and 12 test windows. Use fixed seeds 17, 29 and 43.
4. Start with the nominal variant. Then add a delayed readback and a temporary runway-unavailable variant. Label both disturbances synthetic. The simulator team must define their exact timing and effect once, then freeze them.
5. Expose only current simulated traffic, accepted clearances, known runway status and weather reports available by that clock. Keep future spawns and recorded outcomes inside the trusted scenario driver.
6. Fit missing-path templates on training days only. Report results separately for observed-position and synthetic-position entries. Run an observed-only sensitivity check; easier reduced demand is not comparable to the full-roster result.
7. Freeze simulator, checker, scoring, reconstruction rules, episode membership and controller version before final test runs. The improvement loop can use development and validation results; it cannot read test trajectories or incident details.

The initial matrix is 42 windows × 3 seeds = 126 runs per controller. Adding all three variants makes 378 runs per controller. For a quick iteration, use development windows with one seed; retain the full validation/test matrix for selection and reporting. Twelve test windows span only two historical days. Repeated seeds do not create independent traffic days.

## Score safety before efficiency

Use the fixed checker to report continuous violation episodes, their duration and minimum separation. Avoid counting the same violation once per simulation tick. The checker needs a documented simplified separation policy, approach exceptions, aircraft performance bounds and runway occupancy model. These are simulator assumptions; do not market them as a complete FAA compliance assessment.

Rank candidates in this order:

1. Fewer separation and runway violations, with each type also reported separately.
2. Fewer unfinished aircraft at `drain_end`. An agent cannot improve its score by refusing every landing.
3. Lower delay under the frozen free-flow reference. Include a fixed 3,600-second penalty for each unfinished aircraft in the ranking value. Also show raw delay and backlog.

Show completed/spawned, backlog, violation-free run rate, holding time, checker rejections, readback errors, decision latency and model cost. Keep readback errors as a separate harness metric until the simulator contract defines their counting. Count metrics over all admitted episode aircraft, including warmup, consistently across candidates.

Report paired differences on each historical window. Summarize uncertainty by historical window/day, not by treating every model call or seed as independent. Show per-day results alongside averages. With only two test days, evidence is preliminary. Historical operation counts and runway shares can appear as context; they are not a measured human safety or delay score.

## Should we fine-tune Nemotron?

**Prepare for a small supervised fine-tuning experiment, but first establish the untuned baseline. Never train on the final benchmark test set.** Fine-tune on a separate development corpus derived from the same scenario-building process.

A lightweight model update may help it emit valid commands, use tool results, follow the action contract and repeat effective local decisions. This is a hypothesis, not an established ATC performance result. Fine-tuning raw position arrays teaches trajectory patterns without supplying correct control decisions. It can also memorize callsigns, runway outcomes and time-of-day sequences.

Create state/action examples from a reviewed teacher or human simulator sessions. The fixed checker must accept each target; also review whether the target improves the whole encounter. Passing a short-horizon check does not prove the action is strategically good. Keep unsuccessful rollouts as diagnostic data, not positive targets. Include valid decisions to defer a clearance, hold, recover from a rejected action and handle a readback error. Preserve scenario/checker/model provenance.

Start with **1,000–3,000 reviewed decisions**, grouped into hundreds of encounters rather than near-identical adjacent ticks. Reserve validation examples from August 7. Start with 1–2 epochs and compare against the unchanged base model. Select by closed-loop simulation results; lower training loss alone is insufficient. Require no safety regression before accepting an efficiency or latency gain.

## How much history to pull

**For the demo: keep the current seven-day roster.** It has 4,220 arrivals and 2,164 matched paths, enough demand for initial scenarios. After cleaning, 2,099 initial positions are usable observations; 2,121 initial positions use labeled training templates. Adding more days does not fix missing command labels.

**For a stronger training experiment: target 28 additional days outside the frozen test week**, initially budgeting 14 days for training and policy development, 7 for validation, and 7 untouched for a broader test. Keep the current August 8–9 test separate. Select dates using training-only coverage/weather criteria, preserve boundaries and fit reconstruction only on training days. Do not reshuffle nearby snapshots across splits.

At the starter week's rate of about 603 arrivals/day, 28 days would contain roughly 17,000 arrivals. This is a planning estimate; actual availability, coverage, weather diversity and licenses need checking. Pull airport-local rosters and terminal trajectories, weather, and matching FAA cycles. Avoid global ADS-B archives until a measured coverage gap justifies their bandwidth. Expand to 5,000–10,000 reviewed decisions only if the first experiment shows a gain that persists on unseen encounters.

## Crusoe support and preparation

Crusoe documents supervised LoRA training with JSONL or Parquet conversation files, at most 3 GB per upload. Each row contains a `messages` array; assistant turns receive the training loss. Supply an explicit validation file rather than using its automatic 10% holdout, which does not enforce historical-day separation. Its documentation says multi-turn reasoning is not yet supported; use compact state-to-action examples for the first experiment.

Public docs list `nvidia/nemotron-3.5-lightning-30b-a3b`. The authenticated `/v1/models` response for this account on October 17 instead identifies:

- Model name: `crusoeai/NVIDIA-Nemotron-3.5-Nano-30B-A3B-BF16-07292026`
- API model ID: `ftmodel-6c22bf52-fb65-4bd5-94c4-736f0a7d33f0`
- `fine_tuning_available: true`, `inference_available: false`

Treat that as account-level fine-tuning availability, not proof that the resulting checkpoint can use shared serverless inference. Confirm the serving path and exact current model ID before submitting a paid job. The data exporter is ready, but authentic reviewed command targets do not exist in the supplied bundle. No paid training job or model deployment has been started.

Sources checked:

- [Crusoe model training guide](https://docs.crusoecloud.com/serverless-fine-tuning/fine-tune-a-model/index.html)
- [Crusoe supported models](https://docs.crusoecloud.com/serverless-fine-tuning/available-models/index.html)
- [Crusoe product page](https://www.crusoe.ai/cloud/serverless-fine-tuning)
- [FAA airport data effective August 6](https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/2026-08-06/)
- [IEM ASOS download parameters](https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?help)
- Local source details: `pipeline/bundle/README.md` and `pipeline/bundle/provenance.json`.

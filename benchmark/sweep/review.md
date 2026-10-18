# Independent review: late August model sweep

The sweep extends the frozen arrival admission benchmark to August 24–30, 2026. Its unit of comparison is a complete model configuration on the same 42 demand windows. Ten configurations must represent at least five distinct base model IDs. Scripted and deterministic references must run again on these windows; August 7 results are historical context, not a matched reference for different traffic.

## Acceptance conditions

1. Freeze all ten model configurations before scored inference. Record exact model ID, provider, reasoning controls, generation settings, timeout, output limit, prompt hash, and source hashes. Reasoning OFF requires a documented disabling control. Low reasoning is not OFF.
2. Require all 42 windows for every configuration and both references. Publish failures and unavailable configurations. Missing windows cannot silently disappear from a denominator or leaderboard.
3. Keep August 8–9 outside every source query, loader, model request, result, and verification step. Do not reinterpret the new dates as permission to open those sealed days.
4. Reuse the same engine, action decoder, verifier, fallback rules, causal input, simulator parameters, seed 17, and nominal conditions. A model supplies an exact pending-aircraft permutation, not hidden simulator access.
5. Bind each decision to its raw request and response, exact public view, model configuration, and unique request ID. Preserve incomplete responses and failures. Do not make paid retries for better scores.
6. Reconstruct every causal release and available weather report. Recheck each accepted plan, fixed commitment, simulated motion, flight outcome, censored added delay, and controller aggregate. Check CP-SAT feasibility and the recorded objective without assuming identical wall-time-bounded optimization output.
7. Report executed safety events separately from rejected hypothetical plans. Rank eligible systems by unfinished arrivals, then the frozen penalized delay objective. Show completion, backlog, mean and P95 delay together.
8. Label each scored row as the model plus the common checked fallback system. A fallback is not a valid model response. Report request status, strict action success, fallback rate, cost, unknown cost, and latency separately from simulated delay.
9. Compare reasoning ON and OFF within the same model and traffic. Expose actual settings. Shared output limits include reasoning tokens, so truncation and latency are meaningful service outcomes, not proof of inferior scheduling capability.
10. Do not infer full human ATC performance, operational safety, measured airline delay, unrestricted flight control, or safety of the upstream feeder/queue. Synthetic occupancy and fixed single-resource approaches remain disclosed.

## Verification method

`benchmark.sweep.verify` independently reconstructs the complete result matrix. It reuses the frozen original verifier's resource, solver-objective, plan-binding, and negative safety checks. It repeats causal episode replay with each immutable model configuration and verifies exact raw inference binding. It makes no provider calls and does not inspect held-out days.

Final runtime verification and result interpretation will be appended after the complete experiment matrix exists.

## Source and reference replay: passed

Independent source reconstruction matched every field of all **1,029 selected entries**. The raw date-filtered roster contains 4,126 records. Excluding 50 entries without a named runway leaves 4,076 eligible historical arrival operations. The 42 windows select 1,029 unique operations. All selected initial states are synthetic, derived by the unchanged deterministic selection of August 3–6 development templates. The 1,152 template donors are confined to development dates. Their hash matches the existing frozen template artifact.

The reviewer separately checked source weather bytes, observation times, the disclosed 300-second receipt assumption, causal packed report selection, and numeric weather values. The whole-month path archive was not opened during this verification. The source discovery audit notes that an earlier timestamp-column scan preceded the final date-filtered builder. The supported holdout claim is that August 8–9 are excluded from generated datasets, prompts, and evaluation.

All **84 matched reference outcomes and 1,132 decisions** passed causal replay using the new demand. Both references have zero checked executed violations and zero unresolved decisions.

| Reference | Completed / demand | Backlog | Mean all-demand added delay | P95 added delay |
| --- | ---: | ---: | ---: | ---: |
| Scripted | 408 / 1,029 | 621 | 1,288.7 seconds | 2,350.3 seconds |
| Deterministic planner | 427 / 1,029 | 602 | 1,277.0 seconds | 2,622.1 seconds |

The deterministic planner completes 19 more arrivals, with a lower mean and higher P95 delay. This is a new matched baseline for the requested week. It does not replace or alter the August 7 report.

The generalized verifier also replayed the original 18 controller/window outcomes, all 249 decisions, and all 83 selected inference records successfully. This check used the existing recorded requests and responses, made no provider calls, and changed no original benchmark artifact.

## Provider controls and early scored traces: passed

All ten development preflight requests passed independent payload, raw-response, strict-action, reservation, and reported-token-charge checks. They used the same two already-released August 3 development entries, not late-August evaluation states. OFF emitted zero reasoning-channel characters in all five models. ON emitted nonempty reasoning channels in all five. Known total preflight cost was $0.00641508. These calls remain unscored and are accounted separately in the shared ledger.

The first complete OFF window for each model passed the new causal replay: 68 recorded decisions in total. All actions and fallback decisions matched their actual raw responses, decoder outputs, accepted reservations, executed trajectories, and flight metrics. Early ON verification and complete-matrix attestation remain pending. No scored result led to changing the frozen model or simulation configuration.

## Concurrent execution amendment

After observing slow bounded API requests, the runner added an explicit execution-only amendment. A separate helper owns the 180 model/window jobs for August 28–30. It imports the same frozen job function, model configurations, traffic, simulator, decoder, and safety checks. It keeps the 2.2-second shared model dispatch spacing and the same $30 settled-cost-plus-unknown-exposure cap. It adds 18 workers per base model to the original six. The immutable original experiment plan is retained alongside the amendment and helper source hash.

There is a concrete ownership risk: the original runner does not acquire a new helper lock. Final verification therefore requires evidence that every one of the 180 corresponding original futures returned an already completed cached row. It checks both completion logs, unique raw request identities, ledger reconciliation, the helper completion record, unchanged source hashes, and the complete 504-row causal replay. An ownership collision or incomplete helper prevents final attestation. Higher concurrency is an execution change disclosed in the report; it is not an outcome-selected model or prompt change.

Subsequent early runtime replay passed complete ON and OFF windows for all five models: **58 model/window outcomes and 802 bound scored requests** at that checkpoint. This is progress evidence, not a complete sweep result. No frozen configuration changed after these results.

## Interrupted-response recovery

Two original jobs stopped after `http.client.IncompleteRead` escaped the frozen provider exception list. The provider's `finally` block had already saved the ambiguous response audit and its unknown charge. The recovery helper reuses every prior request with the exact original payload. It never repeats a paid POST. Only new decision identities can dispatch.

Super OFF on August 25 at 15:00 had one earlier usable order and one interrupted call. Its resumed complete 14-decision outcome passed independent replay. Lightning ON on August 24 at 12:00 had four earlier checked fallbacks before the interrupted fifth call. Their original CP-SAT versus secondary-scripted producer and original proposal verdict were not serialized. Their original solver metadata was not saved. Each immediately subsequent raw request reveals the previous applied landing commitments. The helper reconstructs those exact slots and labels them `RECOVERED_FEASIBLE`, with original solver status, bound, and timing explicitly unknown. It does not select another optimizer solution for those four prior commits.

Final verification independently derives each reconstructed slot from the next actual causal view, checks the resource and backend safety contracts, recomputes the objective, and later binds that next public view to the complete replay. It checks original audit/progress hashes, unchanged prefix records, explicit recovery source snapshots, completed recovery manifests, and no repeated paid identities. The crashed call itself had not committed a plan, so its ordinary checked fallback is computed during recovery.

The recovery execution amendment permits one additional worker for each affected base model. The maximum becomes 25 per model while that worker runs. The shared request pacing, spending cap, model settings, prompt, and scoring stay unchanged. The final main-run ownership proof must reconcile its 502 completed outcomes and two explicitly recovered failures with all 504 scored rows. It still requires all 180 concurrency-helper windows to return as cached results in the original runner.

The four reconstructed records establish exact applied slots and counted checked fallbacks. They do not establish four original CP-SAT solutions. Their applied-controller labels reflect the recovery replay policy. The final attestation explicitly preserves that provenance limit; trajectories, delay totals, and inference bindings are unchanged.

Both recovered windows subsequently passed independent full causal replay: **28 decisions**, with all original seven cached calls preserved and 21 genuinely new decisions. The Lightning replay independently reconstructed the four prior fallback commitments from their immediately next original requests. Manifest, original-prefix, progress, source-snapshot, execution-amendment, resource, objective, safety-gate, trajectory, flight, delay, and raw-response checks passed. Neither recovery repeated a paid POST. Both recovery processes completed without another incomplete-read event.

## Complete sweep replay: passed

Independent final verification passed all **504 controller/window outcomes**, **6,799 decisions**, and **5,667 scored raw inference records**. The matrix covers 42 windows, ten configurations, five distinct base models, and two matched local references. Every controller received the same 1,029 unique source operations. The independent rerun produced a byte-identical attestation to the root finalizer. No inference request occurred during verification.

All twelve systems had zero checked executed violations and zero unresolved decisions. These results concern the protected fixed approach/resource simulation. They do not establish unrestricted model safety or performance against human controllers.

| Controller | Completed / demand | Mean added delay | P95 added delay | Checked fallbacks | Usable model responses |
| --- | ---: | ---: | ---: | ---: | ---: |
| scripted | 408 / 1,029 | 1288.7 s | 2350.3 s | 0 | Not applicable |
| deterministic | 427 / 1,029 | 1277.0 s | 2622.1 s | 0 | Not applicable |
| nemotron-3.5-super-vl-off | 412 / 1,029 | 1290.1 s | 2416.9 s | 27 | 539 / 566 |
| nemotron-3.5-super-vl-on | 425 / 1,029 | 1275.6 s | 2633.1 s | 343 | 223 / 566 |
| nemotron-3.5-lightning-off | 395 / 1,029 | 1345.3 s | 2618.0 s | 206 | 364 / 570 |
| nemotron-3.5-lightning-on | 426 / 1,029 | 1276.9 s | 2619.9 s | 510 | 56 / 566 |
| nemotron-3-nano-off | 397 / 1,029 | 1348.3 s | 2625.5 s | 235 | 334 / 569 |
| nemotron-3-nano-on | 426 / 1,029 | 1276.4 s | 2622.1 s | 493 | 73 / 566 |
| qwen-3.8-27b-off | 409 / 1,029 | 1299.7 s | 2492.7 s | 24 | 542 / 566 |
| qwen-3.8-27b-on | 425 / 1,029 | 1276.6 s | 2649.2 s | 382 | 184 / 566 |
| gemma-4-31b-off | 410 / 1,029 | 1288.5 s | 2354.8 s | 19 | 547 / 566 |
| gemma-4-31b-on | 425 / 1,029 | 1276.8 s | 2619.8 s | 472 | 94 / 566 |

**No AI configuration beat the deterministic planner under the declared objective.** The planner completed 427 arrivals. The two leading AI systems completed 426. Nano ON ranked ahead of Lightning ON on the delay tie-break, but used 493 fallbacks in 566 decisions. Lightning ON used 510. A lower mean with fewer completed arrivals does not outrank the planner. These fallback-heavy results do not establish an independent model advantage.

All 180 helper-owned windows passed the ownership proof: the original runner later reused each completed row. Its log reconciled 502 ordinary finished outcomes and the two explicitly recovered failures. The four reconstructed fallback commitments passed their separate provenance checks. Their original fallback producer and optimizer metadata remain unknown. Every original paid request was preserved; no paid POST was retried.

The shared ledger reconciled all 5,677 dispatched requests, including ten unscored development preflights. Reported known charges total $10.15733646. The 980 requests with unknown charges retain $5.11865738 of reserved exposure. Known charges plus unknown exposure total $15.27599384, below the $30 cap. Cumulative reservations total $38.52894538 because settled unused headroom is released. Cumulative reservation volume is not the spending-cap measure.

The frozen inference setting is a **60-second socket timeout**, not a strict end-to-end deadline. Recorded API wall latency reached approximately 79.1 seconds. Queue time and inference time do not advance the logical flight clock.

Final attested artifact hashes:

| Artifact | SHA-256 |
| --- | --- |
| plan.json | 42c1d466f4ebefde663cad5fcd577b4f6a0a9f37fee24a4deb2e9b7d92f9b8ea |
| runs.json | c9d00f3b612a62896cd144230a3defde75f2d459a11826a305181b633f142198 |
| summary.json | 5b98e4745873121b5248bce06c5b18e137f6f7cca8b7ec8853d3b400a380d2be |
| verify.py | 58f53ecc44638604a714b42d305f8b172ac65262fb27a6aa1943a9e6ba1ea397 |

Final acceptance covers this complete, nominal, historical-demand reconstruction and its disclosed limits. August 8–9 are excluded from generated datasets, model inputs, and evaluation. No model promotion, fine-tuning, or human-performance claim follows from this sweep.

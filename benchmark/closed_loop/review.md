# Historical closed-loop integration review

Initial review: October 17, 2026. Scope: existing backend planner, trajectory generator, simulator, verifier, objectives, commit flow, and the new historical traffic loader. Reviewer: `/root/independent_review`. No held-out payloads or model calls were used.

## Smallest valid design

Two approaches are possible. Reconstructing continuous control from the historical 80-NM entries would need new motion, routing, altitude, and command logic. The existing backend instead supports checked synthetic terminal approaches and rolling admission reservations. The second approach is the smaller valid pilot.

Use historical entries as a private demand queue. Release requests causally, select their admission sequence and available arrival runway, verify the resulting synthetic paths, commit passing proposals, advance motion, and repeat. The controller's accepted decisions must change subsequent paths and queue delays. This is a closed-loop terminal-admission and scheduling benchmark; it is not free heading/altitude/speed control or a faithful continuation of the historical tracks.

The common trusted runner should own trajectory synthesis, commit semantics, clocks, events, checks, and metrics. Scripted, deterministic, and AI controllers should receive the same current information and return the same bounded action contract. Their observation budgets and hidden simulator access must match.

## Integration findings

1. **Uncommitted requests can enter automatically.** `sample()` starts motion whenever the clock reaches `trajectory[0].t`. There is no generic accepted-plan flag. A request initialized with a plausible default schedule can start flying after a rejected proposal. Keep uncommitted requests outside the active backend state, or retain an explicit admission hold with an inert path beyond the episode horizon. Never credit their default schedules as executed completions.

2. **Hold flags and active classification disagree.** The planner and verifier classify an aircraft as active solely from `trajectory[0].t <= now`. `sample()` separately honors `admission_hold`. A held aircraft whose path start has passed can look pending in the UI while its reservation becomes immutable to the verifier. Maintain a strict invariant: every unadmitted path starts after the relevant clock, and its hold clears only during a passing commit.

3. **The existing learning commit loop does not clear holds.** The app commit path removes `admission_hold` after accepting a pending reservation. `learning.evaluate()` does not. Reusing that loop after a closure can retain held aircraft indefinitely despite passing plans. The new benchmark needs its own common commit helper with this invariant.

4. **Planner sorting can discard an AI action.** `planner.plan()` sorts pending requests internally. Reordering the input list does not apply an arbitrary AI permutation. Also, policy names `fcfs` and `priority` use the same sorting branch. An AI ordering action needs an explicit fixed-order synthesis boundary. Controller comparisons must reflect distinct actions, rather than different labels around the same planner behavior.

5. **Schedule bounds exclude epoch times and long runs.** The planner's decision variables are bounded to 0–20,000 seconds. Use episode-relative clocks and short windows. A full operation day or an epoch timestamp can make every plan infeasible. The planner then returns existing schedules as fallback values; those values are not an accepted solution. Check solver status and the independent verdict before any commit.

6. **No available runway produces an invalid fallback.** If every allowed runway is closed, the planner falls back to the first allowed runway anyway. The verifier rejects it. The safe outcome is an explicit hold, with unfinished demand counted. Reopening is not an existing `inject()` operation; any synthetic reopening needs trusted state/event handling and a revision change.

7. **A closure can change active motion before verification.** `inject(runway_closure)` immediately replaces an active arrival's future path with a synthetic climb-and-exit diversion. This mutation can conflict with other traffic even if no subsequent proposal passes. For the first pilot, a closure before admission is simpler. A midflight closure requires verification and measurement of the actual post-event motion; rejected proposals alone do not make the mutated state safe.

8. **Coverage and bounded batches need a shared definition.** The verifier requires a reservation for every aircraft in its state. If a controller sees only a bounded pending batch, other released requests must remain in a trusted outer queue. They still count toward demand, backlog, and delay. Never make omitted requests disappear from the metric denominator.

9. **The backend's weighted score is not the requested ranking.** `enrich_metrics()` replaces the legacy delay-plus-backlog score with a multi-objective proxy. Its environmental and fairness terms use synthetic assumptions. Rank the new benchmark explicitly by executed safety events, unfinished demand, and added delay. Keep secondary proxies separate.

10. **Existing delay is admission delay, not measured holding.** Define an unconstrained baseline for each released arrival. With the fixed six-minute approach, that baseline is `release_time + 360`. Added delay is `actual_touchdown - baseline`, not simply `scheduled - release_time`. Completed-flight delay must accompany unfinished counts and a fixed unfinished penalty. Actual airborne holding remains unavailable. Empty-state `metrics()` also raises `ZeroDivisionError`; avoid it or handle the empty clock explicitly.

11. **Proposal predictions are not executed incidents.** The verifier checks complete future proposal paths. Repeatedly summing its conflict evidence counts predictions multiple times. Report rejected/unsafe proposals separately. Actual safety metrics should examine committed motion over executed intervals and deduplicate continuous episodes by aircraft pair and interval. The existing analytical segment checker can support this without coarse simulation ticks.

12. **The fixed geometry is a research model.** Its arrivals start roughly 15 NM from the runway at 5,000 feet, with fixed approach segments. It serializes all runways through one resource. Its 3-NM/1,000-foot check applies only when both aircraft are at least 1,000 feet MSL; separate occupancy rules protect the near-runway region. Do not describe this as complete FAA compliance, historical parallel-runway operations, or exact August airport reconstruction.

## Causal boundary

The new traffic loader queries entries and episode membership only for August 3–7. Its entry allowlist excludes recorded operation times, assigned runways, historical future paths, and template donors. Weather access selects the last report available by the current clock. The complete episode object still contains a future queue and must remain runner-private.

Source flight IDs, callsigns, absolute source dates, and unrelated provenance should remain outside the model prompt. Use local `A<number>` aliases because the existing trajectory generator parses the numeric suffix. Expose only released pending demand, current simulated positions, current weather, open runways, and the controller's already accepted intentions. A known future reservation created by the controller is different from a hidden future historical outcome.

The loader preserves observed/synthetic strata. Synthetic spawn times can derive from historical operation times upstream. They can seed a disclosed reconstruction, but must not be called observed entry times or independent human decision labels. Report an observed-only sensitivity result without treating its reduced demand as the same traffic load.

## Runtime probes performed

Using the current backend modules without provider access:

- An uncommitted arrival with slot 600 was pending at time 0 and entered approach at time 300; its trajectory started at time 240.
- Setting its hold flag made `sample()` report pending, but the verifier rejected a new slot because it considered the old trajectory active.
- Calling backend metrics on an empty aircraft list raised `ZeroDivisionError`.
- Injecting a closure into an active arrival changed its path and marked it diverted without a passing proposal.

These probes establish concrete integration hazards. This initial review does not yet attest the new closed-loop runner, controller implementations, frozen results, or safety-event accounting. Those need review after their interfaces and artifacts freeze.

## New nominal runner review: passed before inference

I subsequently reviewed the new `engine.py`, `controllers.py`, `run.py`, and AI boundary. The new runner addresses the applicable integration findings: uncommitted requests use inert sentinel paths; passing commits clear holds; active trajectories remain immutable; explicit AI orders reach a common decoder; CP-SAT optimizes released pending reservations; episode clocks stay within the schedule bound; and nominal-only episodes avoid unverified closure mutations.

All methods receive the same announced synthetic occupancy. The fixed reservation uses a uniform worst-visibility buffer. The AI prompt explicitly states the current `clock+360` minimum landing slot and completion at `landing+exit_occupancy+90`. It receives opaque episode aliases, relative clocks, released requests, and accepted commitments. The prompt also explains that active reservations cannot be reordered. This resolves the information mismatch identified during review.

The runner labels deterministic and scripted fallback decisions separately from applied AI decisions. Logical time pauses during computation; latency is a separate service metric. Thus its AI results describe an AI controller with a checked fallback system, rather than unassisted model performance. Executed safety eligibility also requires zero unresolved decisions, so holding every request cannot qualify as successful service.

Independent runtime QA used `benchmark/results/closed-loop-venv/bin/python`, Python 3.12 with OR-Tools 9.11.4210. It made no provider calls and did not open final-test data.

| Check | Observed result |
| --- | --- |
| Actual development traffic, August 3 at 12:00 | Both methods spawned 22 and completed 11. Scripted mean accrued added delay was 914.6909 seconds; deterministic mean was 906.1000 seconds. Both had zero executed violations, rejected proposals, and unresolved decisions. |
| Deliberately unsafe 30-second landing gap | The commit gate rejected the proposal without mutating state. Bypassing the gate deliberately made the independent executed audit detect separation, runway, surface, and wake violations. |
| Two separate unsafe crossings | The executed audit returned two exact intervals, `[140,260]` and `[540,660]`, rather than merging the altitude-eligible windows. |
| Performance violation | Both the backend verifier and executed audit rejected/detected a controlled 360-knot path above the 350-knot research envelope. |
| Public-view causality | All 14 observed AI views passed the strict allowlist. No raw source ID, source date, callsign, historical outcome, or future request appeared. The aircraft ID set exactly matched requests already released at that clock. |
| Future-input perturbation | Changing only the final future request left all eight earlier public views identical. |
| Controller equivalence | A fake controller using only the public view reproduced the scripted controller's full flight outcomes exactly. No hidden simulator access was needed. |
| Complete AI service failure | Fourteen fake unavailable decisions produced 14 explicitly recorded deterministic fallbacks. Their complete flight outcomes matched the deterministic reference exactly. |
| Both runways unavailable | No request completed; all 22 remained backlog. Fourteen unresolved decisions made safety eligibility false despite zero flown violations. |
| Boundary rejection | The AI boundary rejected future-known and extra private fields, duplicate JSON keys, repeated aircraft, unknown aircraft, and extra action fields. |

No known critical blocker remains for this frozen **nominal historical-demand admission pilot**. Acceptance retains the stated domain limits: the feeder and upstream queue are not safety-modeled; final approaches are synthetic; delay is censored modeled admission delay; occupancy is synthetic; and there is no human ATC performance claim. This review does not yet attest live model responses or the final validation report.

Source hashes at runtime review:

| Source | SHA-256 |
| --- | --- |
| `engine.py` | `1e89a176399d4c9378e9b8f54df79d80a2a6d4d84b72741d9b1d8dbf690ac71d` |
| `controllers.py` | `71af9bd21e2ad5421a8953fe63a6caafe70e82d8fc2843915d7278981a011fcb` |
| `traffic.py` | `710b255c327cada60bf9a8717ed54770ea7bf62ecd19754d218fbdb2d07ba6e7` |
| `ai.py` | `da4c28855596417ba83ee2cc03037e79a4b77494b7d2630c10129026ef32c8b3` |
| `run.py` | `b647323360692aec780c882841390202f1ff200f401ad6489e0f233db76b658a` |

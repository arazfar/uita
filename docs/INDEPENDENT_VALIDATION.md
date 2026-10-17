# Independent validation

Validation date: October 17, 2026. The verifier, simulator, storage and HTTP acceptance tests were authored by a separate agent from their implementation owner. That validation agent later took ownership of `learning.py`, `provider.py` and `objectives.py`; the learning/provider/objective regression tests therefore are **not** an independent review of those modules. This distinction matters when assessing assurance.

## Reproduce and actual result

From repository root:

```sh
PYTHONPATH=backend .venv/bin/pytest -q backend/tests
```

**70 passed in 7.80 seconds** on the local development machine. This includes 38 independent domain/storage/API checks, 22 learning/provider/objective implementation regression checks and 10 additional API/contingency checks from the backend owner. These suites use deterministic synthetic fixtures, temporary SQLite databases, a real spawned experiment process, and mocked inference HTTP responses. They make no paid inference calls. Authenticated live inference was independently executed by the integration owner: two Crusoe calls, 986 input tokens, 66 output tokens, reported cost $0.00006250. Its immutable programs were reevaluated without additional inference under the final configuration; see [saved live-program reevaluation](evaluation/live-program-reevaluation.md).

## Defects reproduced and fixed

The initial 23-check run produced 20 passes and three failures: a forged snapshot hash, changed snapshot truth without a revision change, and mismatched state rule-pack version could pass verification. Subsequent tests reproduced missing mandatory observations raising exceptions, verification of regenerated defaults instead of actual committed motion, explicit empty schedules silently reusing the current schedule, and a reader opening storage falsely marking a live worker interrupted. All these executable regressions now pass.

The verifier checks detect between-tick trajectory crossings, respect the modeled 3 NM and 1,000 ft boundaries, and distinguish disjoint intervals. Actual committed paths are checked and future conflict checks clip the current-time boundary. Missing mandatory weather/communications evidence yields unresolved. Omitted, duplicate, unknown, nonfinite and negative reservation inputs cannot manufacture a passing plan. Commit tests exercise current binding, expiry, disruptions, preservation of admitted trajectories, idempotency and duplicate-key rejection.

SQLite tests exercise atomic rollback, exact state/checkpoint persistence, and compare-and-swap rejection of a stale writer. HTTP tests prove replay does not mutate the live state. A real spawned experiment completes, persists its candidate registry, and remains readable after reopening the application. The abrupt-loss test starts an API and experiment in a separate process group, kills both while the persisted job is queued/running, verifies that a read-only store preserves its status, and then verifies explicit recovery marks it interrupted while retaining state and checkpoints. This is actual process interruption, not only a fabricated status record.

## Learning and inference evidence

The evaluator now executes eight commit/advance/replan decisions through logical second 2700. The paired policies receive identical initial snapshot hashes and explicit exogenous tapes, including arrival demand at second 1000 and an identified departure's gate delay at second 1600. Only verified plans modify pending reservations; rejected proposals cannot contribute their hypothetical optimized completions. Actual final completed aircraft IDs and unfinished traffic are retained. The fixed optional observation budget is eight reads per decision, so useful observations compete for the budget.

Tests enforce parent-based bounded mutations, immutable non-observation planner fields, cosmetic-name-independent executable hashes, and sealing the fixed final set after prior consumption. Held-out results do not enter provider prompts. A fresh nonpersistent live-model baseline, when supplied, receives the same tools and observation budget; it selects one program for that experiment, rather than making a fresh LLM call at every simulation decision. A negative improvement/promotion result is valid and does not justify changing thresholds.

Mocked provider tests cover exact account-discovered model identity, documented per-million-token pricing normalization, invalid/nonfinite prices, unsupported capabilities blocking paid generation, malformed programs, truncation with no paid retry, and aggregate spend reservations surviving a ledger reopen. The adapter retains conservative reservations after ambiguous paid failures. No credential or response body is included in the tests or this report. Model membership and supported parameters are checked before generation; pricing units are tied to the primary Crusoe pricing documentation, not guessed from numeric magnitude.

## Material limits

Passing these tests establishes bounded software behavior, not compliance with the entire aviation domain or operational safety. In particular:

- Runway closure now initiates an explicit synthetic climb-and-exit diversion for affected admitted airborne arrivals while preserving their executed trajectory prefix. Pending demand is held for replanning. This is a bounded hypothetical contingency, not a published go-around/diversion procedure or guarantee against every conflict; evidence still reports failing/unresolved cases.
- Fixed normalized objectives now combine mean/tail delay, unfinished fraction, phase/wake-specific delay-equivalent fuel, relative day/night noise, synthetic-group service disparity, starvation, schedule instability and verified-replan recovery. The normalizers/weights are versioned and included in evaluator configuration identity. Recovery means obtaining a passing replan, not restoration of airport capacity. Actual airborne/taxi holding is not inferred from admission/gate delay. No measured workload model or real-world emissions/acoustics validation is claimed.
- Conservative shared resources and broad synthetic performance limits do not replace exact local procedures, licensed navigation/performance data, validated sensing, or aviation expert review.
- SQLite and the local process lifecycle were exercised. PostgreSQL, hosted infrastructure, distributed worker ownership and production migrations were not validated. Exactly one API owner is required; explicit recovery is not a distributed lease protocol.
- Logical time catches up by full elapsed wall time on requests while playing. This is lazy server clock evaluation, not an independently demonstrated continuously running real-time simulation service.
- The reported test count excludes browser visual/accessibility/performance checks and any separate live inference run. Consult the corresponding integration evidence rather than inferring those results from this suite.

The final configuration is `15b870294c336dabe4431ffba2be02b729fa4971b40162672bceb87ba91c26b0`, evaluator `closed-loop-matched-eval-3`. The saved Nemotron candidate and stateless program matched the strong static policy (normalized validation score 1.2597; 16/16 passing cases) and the candidate was correctly rejected for no 1% improvement. FCFS scored 1.4162. No final held-out evaluation was consumed. Tests confirm postponing every flight cannot improve normalized score.

The result is a working, bounded research application with reproducible verification and experimentation evidence. It is not an operational ATC system, certification, or proof that every requirement in the broader research brief has been implemented.

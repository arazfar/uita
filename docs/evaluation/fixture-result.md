# Reproducible fixture evaluation

Evaluator: `closed-loop-matched-eval-3`. Config hash: `15b870294c336dabe4431ffba2be02b729fa4971b40162672bceb87ba91c26b0`.

Actual closed-loop results; no fresh model inference. Eight optional observations per decision. Candidates use the same fixed ordering, margin, objective, events and cases.

| Policy | Validation score ↓ | Mean delay (s) | Mean backlog | Passing cases | Outcome |
|---|---:|---:|---:|---:|---|
| FCFS | 1.4162 | 1800.7 | 8.88 | 16/16 | Comparator |
| Strong static | 1.2597 | 1570.2 | 8.25 | 16/16 | Comparator |
| Fixture observation mutation 1 | 1.4162 | 1800.6 | 8.88 | 16/16 | rejected |
| Fixture observation mutation 2 | 1.2597 | 1570.2 | 8.25 | 16/16 | rejected |
| Fixture observation mutation 3 | 1.3426 | 1680.9 | 8.38 | 16/16 | rejected |

Final held-out set: **not-consumed-no-promotion**. Selection is frozen before final evaluation. Rejected results remain in the raw artifact.

Raw per-seed event tapes, observations, decisions, solver timing and accepted slots: [fixture-result.json](fixture-result.json).

Score is a fixed normalized weighted sum of mean/tail delay, incomplete traffic, fuel and relative noise proxies, group service, starvation, plan stability and verified-replan recovery. Its versioned weights and normalizers are retained in every metrics record. A failed episode receives a 100,000-point feasibility penalty before quality comparison. Unfinished traffic stays in the denominator. Fuel/emissions/noise numbers are unvalidated proxies. These results describe the synthetic model, not real SFO operations.

Reproduce: `PYTHONPATH=backend .venv/bin/python scripts/evaluate.py`

# Matched investigator evaluation

Source: **offline-fixture**. Config `df2499f22c185ed8b76779191222689623f3b5a6662104db14c37cbe8b0f8843`.

Both arms use identical model settings/tools/development feedback budgets; persistent arm additionally receives accepted parent. This initial experiment has no learned accepted ancestor. Candidate selected on development, frozen, then independently validated. No held-out exposure.

| Arm | Validation score ↓ | Tail delay | Backlog | Passes | Outcome |
|---|---:|---:|---:|---:|---|
| FCFS | 1.416233 | 3841.0 | 8.875 | 16/16 | Comparator |
| Strong static v2 | 1.259719 | 3637.0 | 8.250 | 16/16 | Comparator |
| Previous single-proposal migration reference (replayed) | 1.259719 | 3637.0 | 8.250 | 16/16 | Comparator |
| stateless agent | 1.354570 | 3524.0 | 8.875 | 16/16 | rejected |
| persistent agent | 1.354570 | 3524.0 | 8.875 | 16/16 | rejected |

stateless: Frozen validation score did not improve strong static and accepted parent by 1%
persistent: Frozen validation score did not improve strong static and accepted parent by 1%

| Agent | Calls | Tools / dev evals | Input / output tokens | Verified cost | Reserved cost | Elapsed |
|---|---:|---:|---:|---:|---:|---:|
| stateless | 0 | 2 / 3 | 0 / 0 | $0.00000000 | $0.00000000 | 1.49s |
| persistent | 0 | 2 / 3 | 0 / 0 | $0.00000000 | $0.00000000 | 1.40s |

Raw per-case episodes, event tapes, rejected candidates, revisions, timings, tokens, costs and ordered tool provenance: [fixture-evaluation.json](fixture-evaluation.json).

Synthetic fixed suites only; no operational claims.
Fixtures exercise orchestration and are not evidence of model learning.
Single matched run does not establish statistical improvement.
Previous single proposal is a migration reference, not a matched current agent call.
Held-out benchmark remains sealed; original artifacts were not rewritten.

Reproduce: `PYTHONPATH=backend .venv-agent/bin/python scripts/evaluate_agent.py` (append `--live` only with the existing approved Crusoe budget configuration).

# Matched investigator evaluation

Source: **crusoe-live**. Config `eebd6e574b468f0c9bd0a05dd4827ebc47e0d6002d8d566b78350fcc4b17afd5`.

Both arms use identical model settings/tools/development feedback budgets; persistent arm additionally receives accepted parent. This initial experiment has no learned accepted ancestor. Candidate selected on development, frozen, then independently validated. No held-out exposure.

| Arm | Validation score ↓ | Tail delay | Backlog | Passes | Outcome |
|---|---:|---:|---:|---:|---|
| FCFS | 1.416233 | 3841.0 | 8.875 | 16/16 | Comparator |
| Strong static v2 | 1.259719 | 3637.0 | 8.250 | 16/16 | Comparator |
| Previous single-proposal migration reference (replayed) | 1.259719 | 3637.0 | 8.250 | 16/16 | Comparator |

stateless: provider_failure; ProviderError: Missing/inconsistent usage or incomplete output; reservation retained
persistent: provider_failure; ProviderError: Missing/inconsistent usage or incomplete output; reservation retained

| Agent | Calls | Tools / dev evals | Input / output tokens | Verified cost | Reserved cost | Elapsed |
|---|---:|---:|---:|---:|---:|---:|
| stateless | 1 | 0 / 0 | 0 / 0 | $0.00000000 | $0.00072920 | 0.00s |
| persistent | 1 | 0 / 0 | 0 / 0 | $0.00000000 | $0.00075810 | 0.00s |

Raw per-case episodes, event tapes, rejected candidates, revisions, timings, tokens, costs and ordered tool provenance: [live-evaluation.json](live-evaluation.json).

Synthetic fixed suites only; no operational claims.
Fixtures exercise orchestration and are not evidence of model learning.
Single matched run does not establish statistical improvement.
Previous single proposal is a migration reference, not a matched current agent call.
Held-out benchmark remains sealed; original artifacts were not rewritten.

Reproduce: `PYTHONPATH=backend .venv-agent/bin/python scripts/evaluate_agent.py` (append `--live` only with the existing approved Crusoe budget configuration).

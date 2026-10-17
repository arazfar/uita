# Independent development capacity audit

The complete legacy grammar contains 65 ordered subsets of four tools. All 65 were evaluated on the four existing development seeds and four existing scenarios, with eight verified commit/advance/replan decisions per case. This used 1,040 cases and 8,320 planner decisions, no inference, and **no validation or held-out cases**. Execution took 17.30 seconds. The fixed evaluator was `closed-loop-matched-eval-3`, configuration `15b870294c336dabe4431ffba2be02b729fa4971b40162672bceb87ba91c26b0`.

The legacy strong static policy is already the best feasible program in this entire development search space. Improving proposal quality or giving the same grammar more development feedback cannot improve this development result. This does not establish that Nemotron cannot improve with more expressive permitted observation allocation.

| Representative operations | Programs sharing schedules | Mean score (lower better) | Mean backlog |
|---|---:|---:|---:|
| exit_occupancy, gate_ready | 5 | 1.283846125 | 8.3125 |
| exit_occupancy | 11 | 1.290783875 | 8.3125 |
| gate_ready, exit_occupancy | 5 | 1.365556250 | 8.5625 |
| gate_ready | 11 | 1.434225813 | 9.0000 |
| empty | 33 | 1.435039563 | 9.0000 |

All programs passed all 16 development cases. Five distinct schedule/verdict outcomes emerged, so the planner is sensitive to some observation choices. `wake` and `weather` consume optional reads but do not change the corresponding planner inputs: wake and visibility are already mandatory inputs. Their main effect is to crowd useful readiness and occupancy out of the eight-read allowance. The legacy tool-major traversal also spends reads on already committed aircraft. These are identifiable grammar/interpreter limits, not evidence of a weak model proposal.

The smallest proposed extension keeps the same four operations and eight-read ceiling while making the aircraft selector and traversal allocation declarative: all/pending/pending-first and tool-major/aircraft-major. The implementation owner predeclared pending-first/tool-major as the upgraded static comparator before upgraded outcomes were inspected. The existing planner, verifier, metrics, rules, and old benchmark remain fixed. Any extension must preserve default legacy interpretation and executable hashes.

[Raw audit](legacy-capacity-audit.json) contains every program, per-case raw metrics/read counts, initial/event/final hashes, and all distinct decision schedules (deduplicated by behavior hash). It also records trusted source hashes. [Audit script](capacity_audit.py) evaluates development only and refuses to overwrite the recorded artifact. [Integrity manifest](legacy-integrity.json) binds historical results and trusted simulator/verifier/objective/rule sources captured before the upgrade. This audit was authored independently of the upgraded implementation; it is capacity evidence, not a learning or live-model improvement result.

## Version 2 follow-up: additional variation, no better development optimum

The exhaustive v2 census covered all 390 programs (65 ordered subsets × three selectors × two allocations), 6,240 development cases and 49,920 planner decisions. All programs passed all 16 development cases. It took 113.38 seconds and found 30 distinct schedule/verdict behaviors, compared with five in the legacy grammar.

The best v2 program was still `all` / `tool-major` / `exit_occupancy, gate_ready`, behaviorally identical to the original strong static policy: mean development score **1.283846125** and mean backlog **8.3125**. The predeclared upgraded static (`pending-first` / `tool-major` with the same operations) scored **1.3493995625**, with mean backlog **8.5**. These are negative findings about this bounded extension and fixed planner, not grounds to tune the evaluator or promotion threshold. The old strong static must remain a comparison and promotion gate; substituting the weaker predeclared v2 static would manufacture apparent headroom.

Following this finding, the implemented strong comparator retains the **original static behavior**, encoded with v2's explicit `all` / `tool-major` selectors. This preserves the existing hurdle. The earlier pending-first comparator and its unfavorable outcome remain recorded above and in the raw census; they are not silently relabeled as a successful upgrade.

The v2 grammar adds observable behavior but does not improve this development optimum. A model can still investigate and revise, and an independent frozen validation result may differ, but neither this census nor a tiny live sample supports a learning improvement claim. No validation/held-out episodes informed either capacity census or this conclusion.

The [v2 raw census](v2-capacity-audit.json) records every program's per-case metrics, feasibility, read/solver costs and matched snapshot/event hashes; the [v2 script](v2_capacity_audit.py) is reproducible and refuses to overwrite recorded evidence.

Reproduce without altering either historical artifact:

```sh
PYTHONPATH=backend .venv-agent/bin/python docs/agent-upgrade/capacity_audit.py --output /tmp/uita-legacy-capacity-replay.json
PYTHONPATH=backend .venv-agent/bin/python docs/agent-upgrade/v2_capacity_audit.py --output /tmp/uita-v2-capacity-replay.json
```

# SFOArrivalEnv-v1

A PortSim-style environment on top of the frozen closed-loop SFO arrival benchmark (`benchmark/closed_loop`). An agent
directs a shared arrival runway resource: at every 300 s decision point it orders the aircraft that have been announced
but not yet committed, and the trusted loop turns the order into landing slots, verifies them, and advances the clock.
`atc_env` reuses the engine's functions (`add_aircraft`, `view_for`, `propose`, `verify`, `commit`, `outcome`) and does
not modify them; the scripted FCFS agent reproduces `engine.simulate(episode, 'scripted')` exactly (tested).

## Tools

| Tool | Behaviour |
|---|---|
| `get_situation()` | Public view (`pending`, `active_commitments`, spacing rules, horizon) plus `task_id`, `split`, `decision_index`, `checks_remaining`, `done`, `instructions`. When done: the final `grade`. |
| `check_plan({"order": [...]})` | Decode the order, run the verifier, commit nothing. Returns status (`pass`/`rejected`/`invalid`), failed check ids, decoded slots, and this decision's added delay. It never reveals the reference. 3 checks per decision; over budget returns an error and changes nothing. |
| `submit_plan({"order": [...]})` | Same validation. A verified plan is committed. An invalid or rejected plan is replaced by the counted scripted FCFS fallback. Then advances to the next decision (returns the new situation) or the end (returns the grade). |

A plan is an exact permutation of the pending ids. Malformed plans never raise; they return `invalid` with a reason.
Runs are deterministic: same task and same plans give identical results.

## Reward (0 to 1)

Reference = the `deterministic` CP-SAT closed-loop controller on the same task (CP-SAT closed-loop reference, per-decision
optimisation; not a proven global optimum). It is precomputed in `atc_env/references/{train,validation}.json`.

- executed safety violations > 0: `0.0`
- any submitted plan rejected or invalid (fallback used): `0.2 * accepted_decisions / total_decisions`
- otherwise `gap = (agent_penalized - ref_penalized) / max(ref_penalized, 600)` and
  `reward = min(1, 0.2 + 0.8 * exp(-max(gap, 0) / 0.5))`. Beating the reference gives `1.0` and `beat_reference: true`.

`penalized_added_delay_seconds` is the closed-loop metric: summed added delay plus 3600 s per unfinished aircraft.

## Splits

`train` (Aug 3-6, 24 windows) and `validation` (Aug 7, 6 windows), loaded with checksum verification. The sealed Aug 8-9
test split is not reachable from this package.

## Run

Use the closed-loop venv (`benchmark/results/closed-loop-venv/bin/python`), from the repo root.

```
python -m atc_env.rollout --smoke                                   # scripted on 1 task, no keys, a few seconds
python -m atc_env.rollout --split validation --agents scripted,random,heavy_last,cpsat [--tasks N] [--out DIR]
python -m atc_env.references                                        # regenerate references (~80 s)
python -m atc_env.mcp_server --split validation                     # MCP stdio server, logs to stderr
python -m pytest tests/test_atc_env.py -q
```

Rollout writes `leaderboard.json` and `rollouts/<agent>/<task_id>.json` (default `showcase/candidates/data/arena`).
Built-in agents: `scripted` (FCFS), `random` (seed 17), `heavy_last` (earliest-first with a checked heavy/medium swap),
`cpsat` (submits the CP-SAT order, a sanity upper bound that reads the privileged CP-SAT proposal).
`nemotron` is an OpenAI-compatible tool-calling agent; it needs `--allow-paid` and `CRUSOE_API_KEY`
(optional `ATC_LLM_BASE_URL`, `ATC_LLM_MODEL`). It is never run by tests or smoke.

## Limitations

- Traffic entries are a mix of `observed` and `synthetic_training_template` positions; each aircraft keeps its provenance. Do not call synthetic entries observed.
- Occupancy times, feeder paths and the approach are synthetic and exogenous; upstream feeder and queue are not safety-modeled.
- The CP-SAT reference is a per-decision optimiser under a 0.25 s solver limit. A `FEASIBLE` status is not proof of optimum, and an agent can score `beat_reference`.
- The reference is close to FCFS on these windows (scripted scores about 0.96 mean), so the reward separates bad orderings (random) far better than good ones.
- Six validation windows are a small sample; this is a simulated admission-ordering task, not real ATC and not a human-controller comparison.

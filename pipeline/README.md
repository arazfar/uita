# SFO data pipeline and teammate integration

This pipeline follows `context/brief.md`: **August 3–9, 2026 in America/Los_Angeles**. The separate `data/` October ADS-B work is not an input here. Storage uses **Railway PostgreSQL**, following Oscar's updated instruction.

## Delivered contract

```text
DataSF arrival roster + SFO Museum observed paths + IEM weather + FAA airport cycles
                              |
                     immutable scenario build
                      /                 \
        replay/outcome artifacts     simulator-private spawn queues
                      |                      |
                Railway Postgres     ScenarioAdapter.advance(clock)
                                             |
                                new aircraft + current weather
                                             |
                                teammate simulator -> controller
```

`pipeline/build/manifest.json` identifies the version and SHA-256 of each artifact. `pipeline/build/sfo.duckdb` supports offline analysis. Generated payloads and credentials are ignored by Git. Source attribution and license are included in the database artifacts.

| Artifact | Consumer and meaning |
|---|---|
| `flights.json` | Historical arrival-operation roster. Compatible with the UI Flight shape; no fabricated departures. Operation time is not verified touchdown time. |
| `observations.json` | Cleaned observed points with segment boundaries, raw fields and provenance. Authoritative replay representation. |
| `tracks.json` | Compact UI tuples `[UTC seconds, longitude, latitude, altitude_ft or null, groundspeed_kt or null]`. This export loses segment IDs; use observations for gap-aware replay. |
| `entries.json` | All simulator initial states, with observed/synthetic flags. Simulator-private future queue. |
| `scenarios/YYYY-MM-DD.json` | One local operation-day pack, including entries, weather and date-matched airport cycles. Some entries precede local midnight. |
| `episodes.json` | 42 fixed benchmark windows: 24 train, 6 validation, 12 test. Three seeds and three disturbance variants per window. |
| `airport.json`, `runways.geojson` | FAA July 9 and August 6 cycles, four physical runways per cycle. No closure or active-runway history. |
| `weather.json` | 239 IEM METAR/SPECI reports, including pre-roll. Availability assumes report time + 300 seconds. |
| `templates.json` | Missing-path reconstruction fitted only on August 3–6; provenance identifies each donor flight. |
| `source/*` | Original starter roster, paths, coverage and quality notes. Preserve when auditing transformations. |
| `quality.json`, `verification.json`, `railway-verification.json` | Data limitations and checks actually run. |

Cleaning removes isolated position spikes and breaks segments at gaps over 120 seconds or implied speeds above 700 knots. These are dataset screening thresholds, not separation rules. Ground speed and track direction use the previous retained point in the same segment. Raw source speed remains unverified. Only C-suffixed beacon altitude values populate observed `altitude_ft`; ambiguous altitude strings remain null. Missing initial heights use a labeled distance profile. No interpolation creates observed points.

## Run

From the repository root:

```sh
uv sync --project pipeline --frozen
pipeline/.venv/bin/python -m pipeline.uita_data.references
pipeline/.venv/bin/python -m pipeline.uita_data.build
pipeline/.venv/bin/python -m pipeline.uita_data.verify
bun pipeline/verify-runtime.ts
pipeline/.venv/bin/python -m pipeline.uita_data.store upload
pipeline/.venv/bin/python -m pipeline.uita_data.store verify
pipeline/.venv/bin/python -m pipeline.uita_data.serve
```

`DATABASE_URL` comes from the root `.env.local` or environment. It is server-only. Upload creates only the dedicated `uita_data` schema. It uses a transaction and refuses changed contents under an existing dataset version. To change a frozen pack, bump `VERSION` in `common.py`. The DuckDB file is a local convenience; PostgreSQL stores the underlying tables and frozen artifacts.

The read-only adapter listens on `127.0.0.1:8100` by default. It checks Railway artifact hashes and loads matching local cache files into memory once; missing files download from Railway. Restart after changing dataset versions. Example URLs:

- `/api/data/health`
- `/api/data/manifest.json`
- `/api/data/episodes.json`
- `/api/data/scenarios/2026-08-06.json`
- `/api/data/weather.json`
- `/api/data/runways.geojson`

Default HTTP mode withholds test scenarios and whole-week replay/outcome artifacts. `--include-test` enables them for the trusted evaluator or a trusted historical replay viewer. Keep that service outside the improvement agent's tools. The server has no write endpoints or authentication; keep the default loopback binding or place it behind the team's authenticated backend. It is a local integration service, not a deployed Railway web service.

Offline recovery from Railway:

```sh
pipeline/.venv/bin/python -m pipeline.uita_data.store download --directory /tmp/uita-offline
```

### TypeScript simulator

Import `ScenarioAdapter` and `loadScenario` from `pipeline/typescript/scenario-adapter.ts`. They have no runtime dependencies and work with Bun or browser TypeScript.

```ts
const pack = await loadScenario('http://localhost:8100/api/data', '2026-08-06')
const source = new ScenarioAdapter(pack)
const frame = source.advance(simulationClockUnixSeconds)
// frame.spawned: add these aircraft to the simulator exactly once.
// frame.weather: last report whose assumed available_at <= clock, or null.
// Subsequent motion comes from the simulator. Never replay the historical future after a clearance.
```

Use one adapter instance per run. Clocks must advance monotonically. Reset by constructing a new instance. The first call emits every entry due by that clock. For an episode, filter the private entry queue to its `flight_ids`, start at `warmup_start`, admit entries until `end`, and run to `drain_end`. The entry payload is an explicit allowlist: it excludes historical runway, operation time, future path and template identity. Do not give the controller the pack, database connection, or manifest of future traffic. `replay-adapter.ts` supports causal historical replay using the last available point and a staleness limit. `airport-adapter.ts` selects the effective FAA cycle and normalizes runway ends, landing thresholds, dimensions and true headings.

Python harnesses use `pipeline.uita_data.adapter.ScenarioAdapter` with the same behavior.

The adapter does not replace the simulator, checker, agent harness, voice system or dashboard. Those remain teammates' integration work. No web UI files or fixtures were changed.

## Evaluation and fine-tuning

The completed five-model arrival-order pilot has [results](../benchmark/reports/2026-10-17/comparison.md) and [testing/objective documentation](../benchmark/TESTING.md). It predicts recorded order from observed snapshots. It does not measure human control quality or closed-loop controller performance. Fine-tuning is deferred.

The separate [closed-loop admission benchmark](../benchmark/closed_loop/README.md) now has a completed three-controller comparison on all six August 7 validation windows. Its [results](../benchmark/closed_loop/reports/2026-10-17/comparison.md) report executed safety, completion, backlog and modeled admission delay. AI includes counted fallbacks and did not beat the deterministic planner. Fixed synthetic approaches and a conservative shared resource limit the safety claim; upstream feeder and queue safety are outside scope. August 8–9 remain held out.

The [five-model reasoning sweep](../benchmark/sweep/README.md) extends that fixed simulator to 42 windows from August 24–30. It reruns both references on the new traffic. Its [leaderboard](../benchmark/sweep/reports/2026-08-24_30/index.html) and [results](../benchmark/sweep/reports/2026-08-24_30/comparison.md) cover all ten configurations. Historical demand seeds 1,029 explicitly synthetic entry states. The planner remains best under the declared objective. Compact traffic, protocol, aggregates and verification are archived in Railway; raw model audits remain local.

Read `context/data-benchmark-plan.md` for the broader simulator proposal. Its disturbance variants remain specifications for the simulator team; the completed pilot uses nominal conditions only. The generic summary interface below is separate from the pilot's frozen runner and objective.

`benchmark.py` accepts one complete result per episode/seed/variant/controller. Required fields are `episode_id`, `seed`, `variant`, `controller`, `finished: true`, `checker_version`, `simulator_version`, `completed`, `backlog`, `separation_violations`, `runway_violations`, `checker_rejections`, `delay_seconds_sum`, `holding_seconds_sum`, `decision_latency_p95_ms`, `cost_usd`. Counts cover all episode spawns, including warmup. The simulator defines and freezes delay's free-flow reference and violation episode counting before baseline runs.

```sh
pipeline/.venv/bin/python -m pipeline.uita_data.benchmark runs.jsonl --split validation --variants nominal
```

The training exporter requires genuine reviewed targets from simulator runs. Input JSONL fields: `episode_id`, `clock`, `state`, `action`, `checker_passed: true`, `reviewer_approved: true`, `checker_version`, `target_provenance` (`reviewed_teacher` or `human_simulator_session`). Use the controller's causal simulator state, not replay outcome artifacts.

```sh
pipeline/.venv/bin/python -m pipeline.uita_data.export_training decisions.jsonl --checker-version CHECKER_SHA
```

It writes separate Crusoe `train.jsonl` and `validation.jsonl` plus lineage. Unknown/test episodes, unreviewed targets, known future fields, future timestamps and duplicate states fail clearly. This is a data guard, not a proof that arbitrary caller-provided state is leak-free. The target action must already pass the teammate's real command validator and fixed checker. No command labels are invented from tracks; no training job is submitted.

## Existing teammate replay tools

The separate UI export includes both arrivals and departures. Preserve its existing build path:

```sh
cd pipeline
uv run extract_departures.py
uv run build_web_data.py
```

`extract_departures.py` builds `departures-bundle/` from DataSF and the cached August Museum Parquet. `build_web_data.py` writes `web/public/data/{flights,tracks}.json` and runway geometry. These files are separate from this arrival-controller benchmark. Its replay exporter interprets numeric altitude strings and raw speed with assumptions; use this pipeline's provenance-aware observations for benchmark checks. `load_supabase.py` and its SQL remain available as prior teammate work; the new authoritative arrival-data storage is Railway.

Archive the combined UI export in Railway as a second dataset:

```sh
pipeline/.venv/bin/python -m pipeline.uita_data.ui_replay
pipeline/.venv/bin/python -m pipeline.uita_data.serve --dataset-id sfo-traffic-replay-2026-08-03_09-v1 --include-test --directory pipeline/build/ui-replay --port 8101
```

The replay dataset contains 4,220 arrivals and 4,219 departures. Its files preserve the existing UI export and source provenance. It is separate from the arrival-controller benchmark because its altitude and speed fields carry the older exporter's assumptions. On port 8101, `/api/data/flights.json` and `/api/data/tracks.json` provide the current UI file contract. The UI team can point its loader there or continue using local files. No UI wiring was changed.

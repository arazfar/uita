# Immersive research showcase

Dashboard and tower share the same geographic aircraft states, selected aircraft,
clock and evidence. The full-screen scene keeps its original imagery/models;
Traffic & evidence opens a drawer (a bottom sheet on narrow screens). Camera
switches retain loaded renderers. Animation uses committed trajectory buffers;
interpolation never controls simulation or crosses missing altitude/segment gaps.

The default is **Scripted demo**, a clearly labeled deterministic simulation.
It is not Nemotron output. Authentic Nemotron attempts, including failures, remain
selectable in the recording catalog. Playback never makes inference calls.

## Reproducible startup without source data or provider access

Python 3.11 and Node 22.12+; from the repository root:

```sh
python3.11 -m venv .venv-demo
source .venv-demo/bin/activate
pip install -r requirements.lock
npm --prefix showcase ci
npm --prefix frontend ci
VITE_RESEARCH_V2=true npm --prefix frontend run build
python scripts/verify_showcase_package.py
export PYTHONPATH="$PWD/backend"
export DATABASE_URL="sqlite:///$PWD/uita-showcase.db"
export UITA_SHOWCASE=1 UITA_ACCESS_MODE=public_demo
alembic upgrade head
python -m uita.research.cli bootstrap
uvicorn uita.research.api:create_app --factory --host 127.0.0.1 --port 8001
```

In another terminal, use the same Python environment and database settings:

```sh
python -m uita.research.worker
```

Open http://127.0.0.1:8001/. To exercise the production frontend gateway:

```sh
UITA_ACCESS_MODE=public_demo UITA_SERVER_URL=http://127.0.0.1:8001 \
  PORT=5190 node showcase/server.mjs
```

The source database and provider key are unnecessary for packaged playback,
fixture runs and comparison. `bootstrap` verifies checksums and installs immutable
artifacts idempotently. It does not replace original source collections.
`GOOGLE_MAPS_API_KEY` on the API enables browser photoreal tiles; retain referrer
restrictions. Bundled imagery is the fallback. Optional `UITA_HISTORY_LOCAL=1`
mounts the existing read-only late-August router against PostgreSQL. It is separate
from the packaged early-August demo and is not needed for startup.

## Demo script

1. Open the guided simulation at its occupied +300-second opening. Play at 30×,
   select aircraft, or use Airport / Overview / Follow selected. Traffic & evidence
   contains the keyboard-accessible table and full event journal.
2. At +90 seconds from the opening, 28R closes. Inspect runway closure, verification,
   pilot responses and executed outcomes. Switch Dashboard/Tower without changing
   the source or clock. Missing altitude appears as labeled ground-projected map
   markers, never as a fabricated aircraft height; the tower omits those targets.
3. Compare the synchronized baseline, then export its complete evidence. The guided
   controller is the baseline: it makes no improvement claim.
4. Select Historical for real early-August observations. Coverage and source ages
   remain visible. Historical traffic is context, not a measured human counterfactual.
5. In the drawer, select Nemotron episode 2 for authentic model proposals,
   explanations, rejected actions and fallback. Episode 1 retains a provider timeout.
6. For interactive controls, create a free fixture run, play/pause, close 28R and
   freeze a comparison. A live Nemotron run requires explicit selection/action and
   a server-side worker key. Refreshing a live run URL reconnects to the same run.

## Packaged data and actual outcomes

The best available frozen early-August development hour contains **55 tracks,
868 observations and 61 measured-altitude samples**. It begins at Unix 1785952800;
selection maximizes measured-altitude samples with an earliest-hour tie break.
This sparse altitude coverage is a real limitation. Unknown heights stay unknown.
The earlier 14-track/18-altitude-sample artifact is retained.
Thirteen scenario replay artifacts are included; no late-August observations were
mixed into early-August scenarios.

The metered development scenario uses seed 42, 300 seconds of deterministic
pre-roll, closure at +390 seconds and a 1,500-second total horizon (20 presented
minutes). Up to seven aircraft are active; the opening has two. Only seven arrivals
are admitted during the horizon; unfinished demand is retained in backlog.

| Recording | Authentic model responses | Completions | Backlog | Modeled violations | Rejected proposals |
| --- | ---: | ---: | ---: | ---: | ---: |
| Guided scripted demo | 0 | 4 | 28 | 0 | 0 |
| Nemotron episode 1, provider timeout + fallback | 0 | 4 | 28 | 0 | 0 |
| Nemotron episode 2 | 40 | 3 | 29 | 0 | 10 |
| Matched deterministic baseline | 0 | 4 | 28 | 0 | 0 |

Episode 2 includes 19 proposed clearances, two go-arounds and one diversion.
It did **not** outperform the deterministic planner. Both attempted captures are
retained; episode 3 was not run. The older failure recording and published admission
benchmark remain separate. Passing means satisfying implemented research checks,
not operational safety certification or support for every FAA capability.

New capture campaign: **$0.0054961 known cost**, **$0.0980682 conservatively reserved**,
including a **$0.002347 uncertain timeout reservation**. No reservation was refunded.
The administrative capture process alone can use the $10 campaign/$2 episode caps.
Public live runs retain $0.50/run, $5/team/day and the existing aggregate allowance.
The old recording separately incurred $0.000797 known/$0.001867 reserved.

## Deployment and rollback

Keep the existing Railway frontend and server identities. All services build from
the same repository-root commit:

| Service | Config | Image / command |
| --- | --- | --- |
| frontend | `railway.showcase-frontend.toml` | `Dockerfile.showcase-frontend`; Node static gateway |
| server | `railway.showcase.toml` | `Dockerfile.showcase`; FastAPI |
| research-worker | `railway.showcase-worker.toml` | same backend image; durable worker |

Frontend: `UITA_SERVER_URL=http://server.railway.internal:8001`,
`UITA_ACCESS_MODE=public_demo`. Server: shared PostgreSQL `DATABASE_URL`,
`UITA_SHOWCASE=1`, `UITA_ACCESS_MODE=public_demo`, `UITA_HISTORY_LOCAL=1`, valid HTTPS
`UITA_ALLOWED_ORIGINS`. Worker: same PostgreSQL database; optional Crusoe key.
For services that cannot opt into legacy Config as Code, apply those settings via
Railway's service API/dashboard: builder `RAILPACK`, explicit Dockerfile path,
repository root `/`, server health `/health/demo`, and the commands above. Railway
detects and builds the configured Dockerfile. The legacy TOML templates remain for
existing Config-as-Code deployments. See [Railway configuration reference](https://docs.railway.com/config-as-code/reference).
Server pre-deploy runs `python -m uita.research.predeploy`, which executes Alembic
and checksummed bootstrap with checked exit codes. `/health/demo` fails
if required data, recordings or scenario checksums are absent. Deploy API and worker
before frontend. The supplied Railway project token can deploy the worker but
`serviceConnect` for its GitHub auto-deploy hook returned **Not Authorized**.
Until an account with repository-linking access connects it, explicitly deploy the
worker at the release commit; pushing main alone is insufficient. The gateway proxies API/SSE/config/history to the API on the same
public origin; mutable API responses are uncached. Assets use ETags and compression.

Before cutover save service settings/deployment IDs and a PostgreSQL public-schema
backup. This release used `pg_dump` 18.6; restoration of all 209 legacy records was
rehearsed in an isolated PostgreSQL instance. Source schemas were untouched.
Rollback restores the previous frontend/server deployments and their saved build,
root and start settings, then stops the new worker. Additive research tables may
remain. Never restore over a live database; restore into an isolated database,
reconcile subsequent writes, then repoint services if database recovery is needed.
The workstation's backup and service snapshot are under ignored `output/` and
must be retained securely by the operator.

Public visitors share the `research` team operator workspace. Other teams and
administrator actions remain inaccessible. `UITA_ACCESS_MODE=private` restores
sessions and login; only private mode requires `python -m uita.research.cli user
 demo --team research`. Secrets remain server-side. The diagnostic UI is `/workbench`.

## Validation and deferred work

Run backend pytest, showcase tests, both frontend builds, packaging checks, then
`showcase/scripts/browser-acceptance.js` with Playwright CLI against the API or
production gateway. That suite uses fixtures only and covers closure, comparison,
exports, rejected proposals, failed scenarios, reconnect and renderer failure.
See [current release evidence and blockers](SHOWCASE-CHECKLIST.md).

Deferred: new datasets, broader procedures/aircraft physics, policy evolution,
fine-tuning, microphone control, automatic promotion and operational ATC use.
Live comparisons export metrics/evidence; synchronized baseline animation uses
immutable recordings. No guaranteed model success or superiority over controllers
is claimed. Unsupported capabilities remain unresolved.

### Sparse showcase restoration

The presentation follows `origin/backup/71b23cc-sparse` at `2f2eb4b`:
full-screen airport, original camera icons and aircraft cards, bottom-right
3D simulation / Tower cab switch. `T` switches views; `1`/`2`/`3` select overview,
tower viewpoint, and aircraft follow; `C` toggles camera-only cinematic motion;
`D` toggles radar/flight strips; Space controls playback. Research modes, live
runs, closure injection, comparisons and exports are under **UITA · Menu**.

The compact controller panel renders timestamped proposal explanations and
verification outcomes from the event journal. Its aircraft button selects the
proposed aircraft; the flight card and runway highlight show its assigned
landing destination. Assignment is not a clearance. Issued clearances appear
separately, including their timestamps. The runway outline is geographic map
context (the existing OSM airport asset), not a predicted trajectory or a new
simulator geometry. Historical and baseline displays never inherit candidate
decisions. Recorded explanations are provider output, not hidden reasoning;
the guided default remains labeled synthetic/scripted.

Local checks: 282 backend tests and 21 showcase tests passed; both frontend
builds and asset packaging passed. Targeted browser checks cover selection,
speed, cached views, historical playback, baseline synchronization, and export.
The first camera round-trip including lazy tower initialization took 701 ms
on this local browser; this is not a steady-state switching benchmark.
Local visual review used the bundled airport imagery fallback because no map
key was configured. No paid model calls were made for this restoration.

The extended browser suite also passed injected model failure, exhausted budget,
rejected proposals, closure, reconnect, failed-scenario reporting, export
isolation, and blocked renderer loading. A 3-second desktop animation-frame
sample measured 60.15 callbacks/sec; two cached camera clicks took 461 ms
including Playwright action overhead. This is not a GPU frame-time measurement
or a physical mobile benchmark. The recording-window response now retains the
last 128 prior verification/clearance events so seeking preserves decision
context. New source selection and historical/baseline filtering remain isolated.
These changes are local; production rollout has not been performed in this task.
Final confirmation: both browser flows passed; the repeated cached camera
round-trip measured 60 ms and the 3-second animation-frame sample was 60.11/sec.
All 282 backend and 21 showcase tests passed after the replay-context change.

### Historical / simulation switching and arrivals

The always-visible source switch remembers each mode's clock, playback speed,
selection and data. Changing a recording or historical source loads it directly;
no second Load action is needed. The previous scene remains usable until a new
frame is ready, with a separate Retry switch action on failure. Camera views
remain cached. Live workers continue while historical browsing is visible.
Immutable playback windows use a four-source LRU with three 120-second windows
per source; overlapping requests share transport and superseded consumers cancel.
Next windows are prefetched as playback approaches the buffered edge.

`PresentationAircraft.arrival_cue` is optional and additive. It identifies phase,
evidence basis/time, supported runway and distance for focus ordering. Simulated
landing authority comes from committed state or causal issued/acknowledged
clearance events, never a proposal or its verifier verdict. Old recording
artifacts and their checksums remain unchanged; read-only windows are enriched.
Compare's baseline receives its own cues without candidate authorization events.

Historical “Approaching SFO · inferred” requires two same-segment measured-altitude
observations 10–60 seconds apart, latest freshness ≤15 seconds, ≥100 feet descent,
latest height 200–5,000 feet, decreasing range within 8 NM, and a track within
30 degrees of the bearing toward SFO. These are presentation heuristics, not FAA
rules. Inference grants neither runway assignment nor landing confirmation.
An audit of both packaged historical windows found **zero qualifying observations**
under these criteria. Their limited altitude/track coverage remains visible;
absence of a highlight does not mean absence of historical arrivals.

**Follow landing** selects authorized approaches before other approaches, then
orders by destination distance and identity. It is an explicit camera action;
switching source never automatically moves the camera. Runway highlights remain
assigned destinations, not predicted trajectories.

Validation: 285 backend tests and 25 showcase tests passed; both frontend builds
and packaging checks passed. Browser
checks for clocks/selection, rapid toggles, failed loading/retry, compare isolation,
both cameras, fixture live-worker continuation, and desktop/390px layouts passed.
Playback crossed multiple cached windows at 60× without stalling (195 simulated
seconds advanced). The full backend suite requires `PYTHONPATH="$PWD/backend"`
for its subprocess recovery test, as in the startup instructions above.
The final local warm mode switch measured 33.2 ms (click to painted frame) on the
existing M1 Pro/Chromium test machine. This is a local measurement; hosted network
latency and physical-mobile performance were not measured for this change.
No paid inference, new datasets, migrations or production rollout were performed.

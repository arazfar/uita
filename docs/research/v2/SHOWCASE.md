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

### Busy arrivals demonstration (dense-demo-v1)

The default is now **San Francisco · busy arrivals · synthetic**, controlled by
`static-2`, not Nemotron. Original guided and authentic model recordings remain
selectable. No inference or provider key is needed for this episode.

Rebuild with `PYTHONPATH=backend python scripts/build_dense_demo.py`. The builder
uses early-August development identities/types, seven staggered initial arrivals,
a synthetic 104 NM approach corridor, 240-second replenishment and a 300-second
pre-roll. These are presentation assumptions, not published routes or measured
SFO operating practices. The 28R closure occurs 90 seconds after the recommended
opening. It does not imply a forced runway reassignment: the conservative
controller uses 28L. No verifier, separation or runway thresholds were changed.

The presentation lasts 1,200 seconds, with 5-second motion checkpoints. Across
those checkpoints, airborne traffic has **minimum 6, median 7, peak 8**, with
**100%** of samples in the 6–10 target. These are renderable positions within
110 NM of SFO, excluding completed/surface traffic and unknown altitude. The
traffic overview fits that regional extent; **Airport** returns to airport detail,
and **Follow landing** explicitly follows an aircraft. Camera changes during
source switching remain user-controlled.

For the same 110 NM extent, the packaged historical windows have visible measured-
altitude occupancy min/median/peak **0/0/2 (v1)** and **0/1/4 (v2)**, sampled every
five seconds using observations no older than 60 seconds. This measures available
coverage, not total historical demand; the synthetic scene is deliberately denser.
Unknown historical altitude remains unknown.

The candidate and independently executed deterministic baseline reproduce identical
state hashes and outcomes: **6 completions, 0 diversions, 0 recorded violations**
over the full recording including pre-roll. The run remains running at the fixed
horizon with backlog, rather than claiming all demand completed. No improvement
over the baseline or human controllers is claimed. A second build produced
identical compressed scenario and recording bytes.

A compact decision card shows causal proposals, issuance, acknowledgments,
cancellations, go-arounds, touchdown and completion. It dismisses after eight
foreground seconds, pauses while hovered/focused, and shows an at-time label after
seeking. Its highlight does not change manual selection or move the camera.
The arrivals queue shows three aircraft; click one to inspect, or expand to the
traffic/evidence table. Landing authorization requires committed lifecycle evidence.

Deployment content is bundled in `dense_demo.json.gz` and
`recordings/dense-demo-v1.json.gz`; the existing pre-deploy/bootstrap command
installs both with checksum verification and repeat-safe artifact insertion.
`/health/demo` rejects a release missing the dense scenario or default recording.
An empty local database was migrated and bootstrapped without source DB access
or provider credentials. Existing recordings were not rewritten.

Local validation: 286 backend tests; 31 showcase tests; fixture browser regression
including rejected proposals, budget/model failures, reconnect and export; frontend and
trace builds; packaging; dense decision flow in dashboard/tower and 390px layout;
source-switch regression; deterministic artifact rebuild and empty-DB install.
Desktop Cesium rendering measured **30.4 FPS** on the existing M1 Pro/Chromium
setup, consistent with its unchanged 30 FPS cap. Physical-mobile and hosted
performance were not measured. Offline regional imagery is low resolution;
airport imagery and configured photoreal rendering remain available. No paid
inference or production rollout was performed.

## Interactive disruption sandbox (sandbox-3)

Choose **Try a disruption → Start sandbox**. The worker prepares the new
`early-august-sandbox-v1` scenario through 300 simulated seconds of pre-roll.
The recording stays visible until preparation succeeds. This opens seven airborne
synthetic aircraft; it does not resume the recording's arbitrary playback position.
Start/reset creates a separate run; old evidence remains available. No model or
provider key is used. Bootstrap installs this derived scenario idempotently from
the packaged dense scenario; `/health/demo` checks its checksum. Use the startup
commands above, including migrations, bootstrap, API and worker. Existing recordings
and their simulator versions are unchanged. Deploy API and worker together;
production rollout has not been performed for this change.

Preset scripts:

1. **Runway restriction and recovery:** restrict 28L, observe causal controller cards
   and pending clearances; watch automatic recovery after 120 simulated seconds.
   Any temporary speed reduction is restored through a separately verified command.
   “Recover now” requests early recovery; a separate permanent closure stays closed.
2. **Priority under traffic:** choose an approaching aircraft, request priority.
   The queue considers emergency status but existing commitments and the single
   corridor may require waiting. This is not a model of professional emergency handling.
3. **Delayed acknowledgment + extra demand:** pilot responses take 15 seconds for
   120 seconds. The extra aircraft waits privately for a safe admission slot;
   subsequent unobserved demand shifts by 240 seconds. Admission is not immediate.
   At most three extra requests are allowed. Unadmitted traffic remains backlog at
   the run horizon. No decorative aircraft are inserted.

The map card links explicit disruption identifiers to controller decisions,
acknowledgments and executed outcomes. The drawer retains complete evidence.
**Compare without this disruption** simulates both branches from the persisted
checkpoint immediately before that intervention, preserving other recorded
interventions and seed. The comparison has a bounded horizon (UI: 300 seconds,
expanded to cover already elapsed time, API maximum: 1,200). Both branches are
simulated; they are not measured real-world counterfactuals. Export includes the
selected comparison and its admission differences. Late comparisons beyond the
bound are rejected explicitly.

Validation on local macOS, Python 3.11, SQLite, headless Chromium:

- 294 backend tests and 32 showcase tests passed; both frontend builds and packaging
  checks passed. Fresh database migration/bootstrap succeeds without source DB or
  provider credentials. Existing large-bundle build warnings remain.
- Each of the four interventions was replayed twice through 1,200 simulated seconds
  with equal state hashes and no motion failure. Delay plus extra demand also passed;
  unsafe admission remains deferred. Weather recovery regression covers the formerly
  persistent speed reduction that caused a later conflict.
- Worker recreation during pre-roll, checkpoint comparison, idempotency, overlapping
  permanent/temporary closures, limits and recovery are covered by backend tests.
- Browser: recording → sandbox → restriction → recovery → combined preset → priority
  → comparison → export; dashboard/tower, historical return, reload and 390px layout.
  Final click-to-confirmation measurement: **100 ms locally** (one sample, not p95).
  Controller reconsideration occurs on the next simulation tick; aircraft response
  takes simulated time. This is not a hosted-latency or FPS measurement.

Remaining release checks: deployed PostgreSQL/container smoke and worker restart,
failed-scenario injection in the new browser flow, and hosted performance.
A short blocked-network test retained the scene and reconnected to the same run;
a prolonged network partition has not been tested.
No production acceptance or operational FAA compliance is claimed. The versioned
`SANDBOX_REFERENCES` register in `standards.py` links FAA priority/weather/runway
context; current pages are not asserted to be archived August authority. Separation,
verification and inference budgets remain unchanged.

## Converging arrival flows (arrival-flows-v1)

The opening recording and **Try a disruption** sandbox now use
`early-august-arrival-flows-v1` / `kinematic-arrival-flows-4` /
`static-arrival-flows-1`. All older recordings and the sandbox-3 simulator remain
available with their original behavior. This is a new synthetic demonstration,
not a reconstruction of a historical controller session or expert validation.

Two lateral families are supported by the existing frozen development tracks:
three eastern tracks and four southern tracks. Representative IDs and every
source checksum are in `sfo-arrival-context-v1`. The builder rejects discontinuities,
intervals over 120 seconds, jumps over 600 knots, insufficient observations and
unsupported families. It requires a terminal endpoint within 3 NM of SFO.
These are data-quality screening thresholds, not ATC standards. The evidence is
operation-linked SFO replay; other traffic is not manufactured into SFO demand.

The route templates retain representative observed shape, round corners, and
connect to a common final. They include a clearly synthetic 35-NM upstream
extension to maintain regional traffic density. **All altitude profiles, speed
profiles, admission times and initial states are synthetic.** Runway thresholds
and true bearings come from FAA AIP KSFO AD 2.12; this contextual snapshot does
not establish date-matched procedure or terrain authority. Generic heading,
altitude, direct-to and published-approach commands remain unresolved.

Measured packaged episode (300-second pre-roll, 1,200-second presentation):

| Measure | Result |
|---|---:|
| Airborne targets inside 125 NM: minimum / median / peak | 7 / 7 / 8 |
| Presentation samples with 6–10 airborne targets | 100% |
| Maximum heading change | 2.673° per second |
| Maximum descent | 1,500 ft/min |
| Airborne indicated speed range | 145–190 kt |
| Maximum ground-track error inside 3 NM remaining | 0.225° |
| Executed completed arrivals by end, including pre-roll | 5 |
| Executed violations / diversions in default episode | 0 / 0 |
| Synthetic altitude fraction | 100% |

Lateral template-to-representative-track deviation over the supported 20–70 NM
radial region: east mean **0.330 NM**, maximum **0.852 NM**; south mean **0.379 NM**,
maximum **1.308 NM**. These describe template geometry, not accuracy of simulated
control or observed descent. Final connections and upstream extensions are excluded.

Select an aircraft to see its route family, phase, distance along route and intended
merge position. Dashed lines show **intended synthetic routes**; executed trails
remain separate. The tower traffic display uses the same route and aircraft state.
An overview includes the regional streams; Airport and Follow remain explicit
camera actions. The tower cab naturally cannot show distant aircraft visually;
its traffic screen and shared table retain inspection access.

The controller schedules by remaining route travel time, protects current landing
commitments, and uses verified speed adjustments when a merge or restriction
requires spacing. Emergency priority cannot override physical order or create
unsupported vectors. Weather recovery restores profile speed through another
verified instruction. Final changes between runways are unavailable once within
15 NM along route. Go-arounds are explicitly synthetic runway-heading climbs;
intended arrival-path previews disappear during a contingency.

Independent verification retains all original separation, wake and runway checks,
adds continuity/turn/corridor/final/touchdown checks, and projects current traffic
at one-second resolution through the merge for 900 seconds. This prediction ends
at 10 NM remaining; executed-motion and runway checks continue through landing.
It does not assert feasibility beyond its horizon. Extra arrivals try both routes
in earliest route-travel-time order, with route ID as tie-breaker, using a longer
1,800-second admission forecast. If neither passes, the request stays deferred.
No future private demand is passed to the controller.

Rebuild reproducibly without source database access or provider credentials:

```sh
PYTHONPATH=backend python scripts/build_arrival_flows.py
python -m uita.research.cli bootstrap
```

The builder checks full-episode verification, replay hashes, density and recording
integrity before writing the new pack. Diagnostics are retained under
`output/arrival-flow-attempts/`. Bootstrap verifies checksums and preserves earlier
artifacts. Rebuilding an already installed immutable version with different content
requires a new version; do not overwrite installed artifacts. For ordinary startup,
use the packaged assets and the API/worker commands above. `/health/demo` now requires
the route catalog, scenario and recording. Roll back by deploying the previous
matched API/worker/frontend release; the additive artifacts may remain in PostgreSQL.

Validation includes full-horizon baseline, restriction, priority, pilot-delay,
extra-arrival and combined presets; JSON checkpoint round-trip during route flight;
unsafe future merge detection; wind correction; teleport/turn/touchdown rejection;
and unsupported-heading checks. Browser acceptance covers recorded and live playback,
both camera views, disruption/recovery, admitted extra demand, comparison/export,
shared route inspection, desktop and 390px layouts, and short reconnect testing.
No inference was purchased. Production rollout, deployed-container/PostgreSQL smoke,
extended rendering soak and professional review remain separate checks. Local
imagery availability does not establish hosted photoreal tile availability.

Final local checks: the 304-test backend suite passed, followed by a targeted
unsupported-controller guard test; all 32 showcase tests, both frontend builds,
asset packaging and empty-database readiness passed. Routed comparisons currently
support the implemented static policy; unsupported controllers fail explicitly
rather than being labeled as a different algorithm. Browser disruption feedback
measured **166 ms** in the final fresh-database run. The dashboard rendered
**29.98 FPS** over a three-second playback sample on an Apple M1 Pro in Chromium,
matching the existing renderer's 30-FPS cap. This is a short local measurement,
not a mobile hardware benchmark or extended soak result. Bundle-size warnings
and the existing test-client deprecation warning remain.

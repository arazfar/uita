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

The best available frozen early-August development hour contains **14 tracks,
438 observations and 18 measured-altitude samples**. It begins at Unix 1785956400;
selection maximizes measured-altitude samples with an earliest-hour tie break.
This sparse altitude coverage is a real limitation. Unknown heights stay unknown.
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
Server pre-deploy runs `alembic upgrade head` and `bootstrap`. `/health/demo` fails
if required data, recordings or scenario checksums are absent. Deploy API and worker
before frontend. The gateway proxies API/SSE/config/history to the API on the same
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

# Connected showcase demo

The existing SFO dashboard and tower cab now share the research backend's runs,
coordinates, selected aircraft, event journal and playback position. The default
is a read-only, authentic Nemotron recording. Fixture runs are explicitly labeled.
The legacy hosted Vite entry remains unchanged; staging uses FastAPI directly.

## Reproducible local startup

From the repository root (Python 3.11, Node 22.12+):

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
export UITA_SHOWCASE=1
export UITA_ACCESS_MODE=public_demo
alembic upgrade head
python -m uita.research.cli bootstrap
python scripts/run_research_local.py
```

Open http://127.0.0.1:8012/. In another terminal, activate the environment,
set the same `PYTHONPATH` and `DATABASE_URL`, then run:

```sh
python -m uita.research.worker
```

No provider key is needed for the recording, fixture runs or comparison.
For live inference, set `CRUSOE_API_KEY` on the worker service, not in browser
configuration.
The optional server-side `GOOGLE_MAPS_API_KEY` supplies photoreal tiles; restrict
its browser use by HTTP referrer. The local SFO imagery/building pack remains the
fallback. Set `UITA_HISTORY_SERVER_URL` to the existing history API's base URL to
browse the separate late-August archive. Its allowlisted read-only adapter never
forwards application credentials. Missing source service is an explicit error.

## Presentation script

1. Open the demo. The saved August 6 recording loads automatically, initially paused.
2. Select Historical to inspect available observed positions, missing heights and
   source ages. The metered variant alters spawn timing; historical paths provide
   context and are not a matched human-controller baseline.
3. Select Simulation and Play. At +30 seconds inspect `model response`; at +60
   seconds inspect `controller fallback`; at +90 seconds inspect the closure and
   its verifier evidence. Aircraft motion after fallback is deterministic.
4. Switch Dashboard/Tower. Clock, run and aircraft selection remain shared. Use
   the aircraft table when imagery, WebGL or altitude coverage is unavailable.
5. Select Compare. Switch the rendered controller at the same playback position;
   inspect final completion, backlog and delay together. Export evidence includes
   the response records, checksums, full event journal and comparison.
6. For an interactive demonstration, expand Run a new simulation. Choose the
   authored fixture, create a run, Play, Pause, Close 28R, then freeze and compare.
   New runs are isolated; reloading their `?run=` URL reconnects to the same run.

Recorded playback is immutable. Live run reads do not advance time; only the
worker does. Completed-only delay must be considered alongside unfinished demand.
Comparison uses the executed horizon and the same timed disruption tape. The
published August 7 admission benchmark is a separate expandable report.

## Actual Nemotron result

The single predefined capture used scenario `2026-08-06-1500-research-v2-metered`,
seed 42, 28R closure at +90 seconds and a 1,200-second horizon. Nemotron returned
one valid no-aircraft/no-clearance proposal, followed by an invalid response.
The worker visibly switched to the deterministic baseline. No flight-changing
Nemotron clearance was executed in this recording.

Both candidate-plus-fallback and baseline completed **3** arrivals, with **29**
unfinished, **0** modeled violations and **77.01 seconds** completed-only mean
and P95 delay. There is **no demonstrated efficiency improvement**. Final
candidate state is paused at the presentation horizon, not scenario completion.
The baseline's `running` result likewise means unfinished at that fixed horizon.

This capture incurred **$0.000797 known cost**, reserving **$0.001867**. Prior
research probes remain in the same ledger. Reservations are never refunded after
ambiguous failures. Default playback makes no calls. Optional live Nemotron runs
require a server-side `CRUSOE_API_KEY` and enforce $0.50/run, $5/team/day and the
existing $5 validation ceiling. No automatic paid retry or alternate provider.

`record_showcase.py` captures this single predetermined episode through the real
worker and publishes an integrity-checked recording. Its stable idempotency key
prevents rerunning the same capture. Preserve the original ledger and outcomes;
do not reset it or choose successful attempts for presentation.

## Isolated staging

Use `Dockerfile.showcase`, `railway.showcase.toml` for the API, and
`railway.showcase-worker.toml` for its worker. Both share a separate staging
PostgreSQL database. The API pre-deploy command runs Alembic and bootstrap;
startup never creates tables. Only the API needs a domain. Configure
`UITA_ALLOWED_ORIGINS` to that exact HTTPS origin. Create team accounts explicitly.
Keep the live key unset for initial staging acceptance.

The image explicitly packages candidate pages, models, imagery, Three.js and
Cesium rather than relying on the unrelated showcase Vite build output.
Authentication guards showcase pages, vendor assets, data and event streams.
Same-origin framing is permitted; other origins cannot embed the application.
The diagnostic research workbench remains at `/workbench`.

Do not repoint existing production services. The existing Vite server preserves
`app-legacy.html` until a deliberate cutover. Staging deployment, image build,
backup restoration and hosted worker restart still require their release gates.
Docker is unavailable in the current environment; no hosted deployment is claimed.

## Deferred

No new datasets, procedure coverage, aircraft models, policy evolution,
fine-tuning, microphone control or human-controller superiority claims. Live
comparison currently exports final metrics/evidence; synchronized controller
animation is provided by immutable recordings. All unsupported ATC capabilities
retain unresolved verdicts. Photoreal provider coverage and a new model producing
useful commands are not substituted with fabricated visuals or decisions.

## Repeat browser acceptance

With the API and worker running, open and sign in using Playwright CLI, then run:

```sh
npx --yes --package @playwright/cli playwright-cli open http://127.0.0.1:8012/ --headed
# Public demo needs no login; sign in only when using private mode.
npx --yes --package @playwright/cli playwright-cli run-code --filename showcase/scripts/browser-acceptance.js
```

The script creates free fixture runs, tests the recorded comparison and faults,
and ends by clearing its own browser session to verify expiry. It makes no paid
calls. Worker SIGKILL/takeover and Docker/hosted checks are separate gates in the
[release checklist](SHOWCASE-CHECKLIST.md).

## Access mode

The showcase image defaults to `UITA_ACCESS_MODE=public_demo`: no account or cookie
is needed. All visitors share the `research` team's operator controls and runs,
including explicitly started paid live runs. Existing per-run, daily-team and
aggregate budget reservations still apply. Recorded playback remains the default.
Other teams are inaccessible. No provider secret is exposed to the browser.

Set `UITA_ACCESS_MODE=private` to restore login and session expiration. In that mode,
create an account with `python -m uita.research.cli user demo --team research`.
Non-showcase deployments default to private mode. Production configuration is
unchanged; hosted staging and container acceptance remain separate release gates.

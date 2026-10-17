# Uita hackathon research demo

This release delivers one local demo flow: **select an early-August synthetic
variant → autonomous fixture control → runway closure → decision/verifier evidence
→ matched deterministic comparison → export**. Existing Railway production is
unchanged. Staging configuration is prepared but has not been deployed or verified.

See [release checklist](RELEASE-CHECKLIST.md) for current gates and
[deferred work](DEFERRED.md) for the separate roadmap.

## Start from a clean checkout

Requires Python 3.11 and Node 22. From the repository root:

```sh
python3.11 -m venv .venv-demo
source .venv-demo/bin/activate
python -m pip install -r requirements.lock
npm --prefix frontend ci
VITE_RESEARCH_V2=true npm --prefix frontend run build
export PYTHONPATH="$PWD/backend"
export DATABASE_URL="sqlite:///$PWD/uita-demo.db"
alembic upgrade head
python -m uita.research.cli bootstrap
python -m uita.research.cli user demo --role administrator
python scripts/run_research_local.py
```

The account command prompts for your password; no default account is created.
Open `http://127.0.0.1:8012/login`. The local helper binds loopback and permits
HTTP cookies. The hosted factory always uses Secure, HttpOnly, SameSite cookies.

In a second terminal, activate the same environment and set the same database:

```sh
source .venv-demo/bin/activate
export PYTHONPATH="$PWD/backend"
export DATABASE_URL="sqlite:///$PWD/uita-demo.db"
python -m uita.research.worker
```

Bootstrap validates and loads three frozen artifacts: a small synthetic fixture,
the original August 6 reconstruction, and its explicitly synthetic metered variant.
No source database credentials or data downloads are needed. It is safe to rerun
bootstrap against the same artifacts. Original application records are untouched.

## Demo script

1. Select `2026-08-06-1500-research-v2-metered`. Use **Autonomous fixture · free**
   with **Normal proposals**. Create a run, select 30×, then Play.
2. After the first aircraft appears, Pause and select **Close 28R**. The fixture
   prefers 28R, so closing it demonstrates cancellation and a synthetic go-around.
3. Open **Evidence**. Expand `runway closure response`, `model response`, and
   `proposal verified`. Read the source references, research assumptions and
   numerical evidence. Continue Play for approximately 30–60 wall-clock seconds.
4. Select **Compare**, then **Compare with deterministic baseline**. This pauses
   and freezes the candidate. A durable job runs the baseline with the same
   scenario, seed, elapsed simulation time and timed disruption tape. It makes no
   paid calls. Completed counts are executed completions; remaining demand stays
   in the backlog, including diverted aircraft.
5. Download **Export comparison evidence**. Return to Simulate and download
   **Export** for the complete candidate event journal and standards register.

Fixture proposals are authored test behavior, not an LLM or measured controller
behavior. The fixture deliberately prefers a different runway from the baseline;
its results need not be better. A comparison stopping at the captured horizon can
show a baseline state of `running`; this means it had not reached the scenario end,
not that the comparison job remains active.

For failure demonstrations, choose `fixture-august-v2` and use **Simulate model
failure** or **Simulate budget exhaustion**, then step ten seconds. These are
labeled free fault injections. Actual shared-ledger rejection and concurrent caps
are tested separately. The original unmetered August 6 scenario intentionally
retains a reconstruction conflict at 151 seconds; it must report failure.

## Inference and persistence

Fixture mode is the default and free. Optional live Crusoe mode requires a
server-side `CRUSOE_API_KEY`. Every paid call reserves cost in PostgreSQL first;
limits are $0.50/run, $5/day/team, and $5 aggregate validation. Ambiguous requests
keep their reservations. No automatic paid retries are made. Failure switches
visibly to the deterministic controller without stopping existing aircraft motion.

Runs pin policy, simulator and rule versions. Incompatible workers pause runs.
Commands enforce revisions and idempotency. Checkpoints, events and mutation results
commit atomically. Worker leases last 45 seconds; a replacement can recover after
lease expiry. Reads never advance simulation time. Comparisons execute off the
live-clock thread and retain their disruption tape and candidate evidence.

## Railway staging configuration — not deployed

The provided project token could read production but Railway rejected isolated
staging creation. At the user's request, this release provides configuration only.
Do not deploy it onto an existing production service.

With a Railway account that can create staging:

1. Create an **empty** `research-staging` environment, a separate PostgreSQL service,
   and two empty services named `research-api` and `research-worker`. Do not clone
   production variables, volumes or application data.
2. Both services build `Dockerfile.research` from this repository. Set the API
   config path to `railway.research.toml`, and the worker config path to
   `railway.worker.toml`. Use the staging PostgreSQL private `DATABASE_URL` on both.
   Leave `CRUSOE_API_KEY` unset for fixture-only acceptance.
3. Deploy the API first. Its pre-deploy command runs Alembic and bootstrap. Failed
   migration blocks deployment. Readiness is `/health/ready`; liveness is
   `/health/live`. Deploy the worker after the API migration succeeds.
4. Generate an HTTPS domain only for `research-api`. It serves frontend and API at
   the same origin. Set `UITA_ALLOWED_ORIGINS` to that exact origin. No worker domain
   is necessary. Create a team account using an interactive Railway SSH session:
   `python -m uita.research.cli user demo --role administrator`.
5. Verify anonymous data/API access returns 401 and the login cookie is Secure and
   HttpOnly. Run the demo and fault/reconnect cases over HTTPS. Restart the worker
   during a run and verify takeover after its 45-second lease expires.
6. Enable Railway PostgreSQL backups and restore into a separate staging database.
   A local logical checkpoint round trip is not a hosted database restoration test.
   Observe `/api/v2/operations` with an authenticated session for lag, expired leases,
   queued jobs, database latency and inference reservations. Railway deployment
   healthchecks are not continuous monitoring.

Example upload commands after services/configuration exist:

```sh
railway up --project PROJECT_ID --environment research-staging --service research-api --detach
railway up --project PROJECT_ID --environment research-staging --service research-worker --detach
```

The Docker daemon was unavailable locally, so the image build remains a staging
gate. Production cutover, hosted load tests, role-separated database grants,
backup restoration and continuous monitoring are not claimed complete.

Rollback: stop the staging worker and redeploy the prior image/configuration.
Preserve additive tables and source artifacts; destructive migration downgrade is
intentionally disabled. Existing production requires no rollback because it was
not changed.

## Reproduce checks

```sh
PYTHONPATH=backend python -m pytest -q
PYTHONPATH=backend python scripts/evaluate_research.py
PYTHONPATH=backend python scripts/export_research_schema.py
frontend/node_modules/.bin/openapi-typescript docs/research/v2/api.openapi.json -o frontend/src/research.generated.d.ts
```

`scripts/validate_research_postgres.py` creates and removes a uniquely named test
schema. Run it only with an explicitly chosen validation PostgreSQL URL; it tests
migration, concurrent idempotency, fencing/lease takeover, budget serialization
and a logical checkpoint restore. It does not touch source schemas.

Optional paid validation is deliberately opt-in:
`UITA_VALIDATE_PAID=1 python scripts/validate_research_live.py`. The shared ledger
still applies. No further live call is needed to demonstrate the fixture release.

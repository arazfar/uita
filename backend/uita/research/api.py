"""Private-team v2 API. No startup schema mutations or clock advancement on reads."""

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text
from starlette.middleware.gzip import GZipMiddleware

from . import security, service
from .contracts import (
    AirportRulePack,
    Commit,
    Compare,
    CompareRun,
    CompareIntervention,
    Control,
    Disruption,
    Fork,
    Login,
    Propose,
    RunCreate,
    RunEvent,
    RunView,
)
from .database import (
    Artifact,
    Budget,
    Checkpoint,
    Database,
    Event,
    Job,
    Run,
)
from .standards import PACK

log = logging.getLogger(__name__)


def create_app(database=None, secure_cookies=True):
    access_mode = os.getenv("UITA_ACCESS_MODE", "private")
    if access_mode not in {"private", "public_demo"}:
        raise ValueError("UITA_ACCESS_MODE must be private or public_demo")
    database = database or Database()

    @asynccontextmanager
    async def lifespan(app):
        yield
        database.close()

    app = FastAPI(title="Uita Research", version="2.0.0", lifespan=lifespan)
    app.state.database = database
    app.add_middleware(GZipMiddleware, minimum_size=1500)

    @app.middleware("http")
    async def boundary(request, call_next):
        started = time.monotonic()
        path = request.url.path
        if path == "/login" and access_mode == "public_demo":
            return RedirectResponse("/", status_code=303)
        public = path in (
            "/health/live",
            "/health/ready",
            "/health/demo",
            "/api/v2/login",
            "/login",
            "/favicon.svg",
        ) or path.startswith("/assets/")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            allowed = set(os.getenv("UITA_ALLOWED_ORIGINS", "").split(",")) | {
                str(request.base_url).rstrip("/")
            }
            if origin and origin not in allowed:
                return JSONResponse({"detail": "Origin not allowed"}, 403)
        if not public:
            with database.sessions() as db:
                user = security.resolve_principal(
                    db, request.cookies.get("uita_session"), access_mode
                )
                if user is None:
                    if path == "/":
                        return RedirectResponse("/login", status_code=303)
                    return JSONResponse({"detail": "Sign in required"}, 401)
                request.state.user = user
            if (
                request.method not in ("GET", "HEAD", "OPTIONS")
                and request.state.user["role"] == "viewer"
                and path != "/api/v2/logout"
            ):
                return JSONResponse({"detail": "Operator permission required"}, 403)
        response = await call_next(request)
        static_content = path.startswith(
            ("/vendor/", "/candidates/assets/", "/candidates/sfo-pack/")
        )
        response.headers["Cache-Control"] = (
            "public, max-age=86400"
            if static_content
            else (
                "no-store"
                if not path.startswith("/assets/")
                else "public, max-age=31536000, immutable"
            )
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
        log.info(
            json.dumps(
                {
                    "event": "http_request",
                    "method": request.method,
                    "route": getattr(request.scope.get("route"), "path", "unmatched"),
                    "status": response.status_code,
                    "duration_ms": round((time.monotonic() - started) * 1000, 2),
                }
            )
        )
        return response

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": str(exc)}, 409)

    @app.exception_handler(LookupError)
    async def missing(request, exc):
        return JSONResponse({"detail": str(exc)}, 404)

    @app.exception_handler(PermissionError)
    async def forbidden(request, exc):
        return JSONResponse({"detail": str(exc)}, 403)

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready():
        try:
            with database.sessions() as db:
                revision = db.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar()
                if revision != "0001_research":
                    raise RuntimeError("Schema mismatch")
            return {"status": "ready"}
        except Exception:
            return JSONResponse({"status": "not_ready"}, 503)

    @app.get("/health/demo")
    def demo_ready():
        try:
            with database.sessions() as db:
                import gzip
                import json

                for name in ("showcase_data.json.gz", "dense_demo.json.gz"):
                    pack = json.loads(
                        gzip.decompress(
                            (Path(__file__).parent / "assets" / name).read_bytes()
                        )
                    )
                    for expected in pack["artifacts"]:
                        installed = db.get(Artifact, expected["id"])
                        if (
                            installed is None
                            or installed.checksum != expected["checksum"]
                        ):
                            raise ValueError("Current demo pack missing or mismatched")
                from .sandbox import SCENARIO, scenario_from
                from .data import digest

                source = db.get(Artifact, "early-august-dense-demo-v1")
                sandbox_artifact = db.get(Artifact, SCENARIO)
                if (
                    source is None
                    or sandbox_artifact is None
                    or sandbox_artifact.checksum
                    != digest(scenario_from(source.payload))
                ):
                    raise ValueError("Sandbox scenario missing or mismatched")
                dense = db.get(Artifact, "dense-demo-v1")
                if dense is None or dense.kind != "demo_recording":
                    raise ValueError("Default dense recording missing")
                recordings = list(
                    db.scalars(
                        select(Artifact).where(Artifact.kind == "demo_recording")
                    )
                )
                if not recordings:
                    raise ValueError("Recording missing")
                from .presentation import validate_recording

                for row in recordings:
                    manifest = validate_recording(row.payload)
                    scenario = db.get(Artifact, manifest.scenario_id)
                    if (
                        scenario is None
                        or scenario.checksum != manifest.scenario_checksum
                    ):
                        raise ValueError("Recording scenario missing")
            return {"status": "ready", "demo": "immersive-v1"}
        except Exception:
            return JSONResponse(
                {"status": "not_ready", "detail": "Demo data validation failed"}, 503
            )

    @app.post("/api/v2/login")
    def login(command: Login, request: Request):
        # Persistent account-scoped quota, independent of spoofable proxy/IP headers.
        key = (
            "login:"
            + security.token_hash(command.username.lower())
            + ":"
            + str(int(time.time() // 300))
        )
        with database.transaction() as db:
            # The global budget row serializes first insert under PostgreSQL.
            db.scalar(
                select(Budget).where(Budget.id == "validation-v2").with_for_update()
            )
            quota = db.get(Budget, key)
            if quota is None:
                quota = Budget(id=key, cap=10, reserved=0)
                db.add(quota)
            if quota.reserved >= quota.cap:
                return JSONResponse(
                    {"detail": "Too many attempts; retry in five minutes"}, 429
                )
            quota.reserved += 1
            token = security.login(db, command.username, command.password)
        if token is None:
            return JSONResponse({"detail": "Invalid credentials"}, 401)
        response = JSONResponse({"authenticated": True})
        response.set_cookie(
            "uita_session",
            token,
            httponly=True,
            secure=secure_cookies,
            samesite="strict",
            max_age=43200,
            path="/",
        )
        return response

    @app.post("/api/v2/logout")
    def logout(request: Request):
        with database.transaction() as db:
            security.logout(db, request.cookies.get("uita_session"))
        response = JSONResponse({"authenticated": False})
        response.delete_cookie("uita_session")
        return response

    @app.get("/api/v2/me")
    def me(request: Request):
        return request.state.user

    @app.get("/api/v2/operations")
    def operations(request: Request):
        started = time.monotonic()
        now = time.time()
        team = request.state.user["team"]
        with database.sessions() as db:
            active = list(
                db.scalars(select(Run).where(Run.team == team, Run.status == "running"))
            )
            queues = dict(
                db.execute(
                    select(Job.status, func.count())
                    .where(Job.team == team)
                    .group_by(Job.status)
                ).all()
            )
            run_ids = select(Run.id).where(Run.team == team)
            from .database import Reservation

            cost = db.execute(
                select(
                    func.sum(Reservation.amount), func.sum(Reservation.actual)
                ).where(Reservation.run_id.in_(run_ids))
            ).one()
        return {
            "observed_at": now,
            "active_runs": len(active),
            "max_clock_lag_seconds": max(
                (max(0, now - r.next_tick) for r in active), default=0
            ),
            "expired_run_leases": sum(r.lease_until < now for r in active),
            "jobs_by_status": queues,
            "inference_reserved_usd": cost[0] or 0,
            "inference_actual_usd": cost[1] or 0,
            "database_latency_ms": round((time.monotonic() - started) * 1000, 2),
        }

    @app.get("/api/v2/standards", response_model=AirportRulePack)
    def standards():
        return PACK.model_dump()

    @app.get("/api/v2/scenarios")
    def scenarios():
        with database.sessions() as db:
            return [
                {
                    "id": a.id,
                    "checksum": a.checksum,
                    **{
                        k: a.payload[k]
                        for k in (
                            "dataset_id",
                            "split",
                            "start",
                            "end",
                            "provenance",
                            "coverage",
                        )
                        if k in a.payload
                    },
                }
                for a in db.scalars(select(Artifact).where(Artifact.kind == "scenario"))
                if a.id
                in (
                    "fixture-august-v2",
                    "2026-08-06-1500-research-v2",
                    "2026-08-06-1500-research-v2-metered",
                )
            ]

    @app.get("/api/v2/datasets")
    def datasets():
        with database.sessions() as db:
            return [
                a.payload
                for a in db.scalars(select(Artifact).where(Artifact.kind == "manifest"))
            ]

    @app.get("/api/v2/replay")
    def historical(scenario_id: str, clock: float, window_seconds: int = 120):
        import math

        from .geometry import local

        if not math.isfinite(clock) or not 1 <= window_seconds <= 300:
            raise HTTPException(422, "Invalid replay window")
        with database.sessions() as db:
            scenario = service.scenario_for(db, scenario_id)
            if not scenario["start"] <= clock <= scenario["end"]:
                raise HTTPException(422, "Clock outside scenario")
            aircraft = []
            for entry in scenario["entries"]:
                row = db.get(Artifact, "replay:" + entry["id"])
                if row is None:
                    continue
                points = [
                    p
                    for p in row.payload["points"]
                    if clock - window_seconds <= p["t"] <= clock
                ]
                if not points:
                    continue
                p = max(points, key=lambda p: p["t"])
                x, y = local(p["lon"], p["lat"])
                aircraft.append(
                    {
                        "id": entry["id"],
                        "callsign": entry["callsign"],
                        "x_nm": x,
                        "y_nm": y,
                        "longitude": p["lon"],
                        "latitude": p["lat"],
                        "altitude_ft": p["altitude_ft"],
                        "groundspeed_kt": p["groundspeed_kt"],
                        "track_deg_true": p.get("track_deg_true"),
                        "status": "observed",
                        "age_seconds": clock - p["t"],
                        "runway": "unknown",
                        "type": entry["aircraft_type"],
                        "provenance": {
                            "kind": "observed",
                            "source": row.payload.get("source"),
                        },
                        "trail": points,
                    }
                )
            return {
                "clock": clock,
                "aircraft": aircraft,
                "coverage": scenario.get("coverage", {}),
                "provenance": scenario["provenance"],
            }

    @app.get("/api/v2/runs")
    def runs(request: Request):
        with database.sessions() as db:
            return [
                {
                    "id": r.id,
                    "revision": r.revision,
                    "status": r.status,
                    "scenario_id": r.state["scenario_id"],
                    "clock": r.state["clock"],
                }
                for r in db.scalars(
                    select(Run)
                    .where(Run.team == request.state.user["team"])
                    .order_by(Run.created.desc())
                    .limit(100)
                )
            ]

    @app.post("/api/v2/runs", response_model=RunView)
    def create(command: RunCreate, request: Request):
        with database.transaction() as db:
            return service.create_run(db, request.state.user["team"], command)

    @app.get("/api/v2/runs/{run_id}", response_model=RunView)
    def snapshot(run_id: str, request: Request):
        with database.sessions() as db:
            return service.view(service.get_run(db, run_id, request.state.user["team"]))

    @app.post("/api/v2/runs/{run_id}/control", response_model=RunView)
    def control(run_id: str, command: Control, request: Request):
        with database.transaction() as db:
            return service.mutate(
                db, request.state.user["team"], run_id, "control", command
            )

    @app.post("/api/v2/runs/{run_id}/disruptions", response_model=RunView)
    def disruption(run_id: str, command: Disruption, request: Request):
        with database.transaction() as db:
            return service.mutate(
                db, request.state.user["team"], run_id, "disruption", command
            )

    @app.post("/api/v2/runs/{run_id}/proposals", response_model=RunView)
    def propose(run_id: str, command: Propose, request: Request):
        with database.transaction() as db:
            return service.mutate(
                db, request.state.user["team"], run_id, "propose", command
            )

    @app.post("/api/v2/runs/{run_id}/commit", response_model=RunView)
    def commit(run_id: str, command: Commit, request: Request):
        with database.transaction() as db:
            return service.mutate(
                db, request.state.user["team"], run_id, "commit", command
            )

    @app.post("/api/v2/runs/{run_id}/fork", response_model=RunView)
    def fork(run_id: str, command: Fork, request: Request):
        with database.transaction() as db:
            return service.fork(db, request.state.user["team"], run_id, command)

    @app.get("/api/v2/runs/{run_id}/checkpoints")
    def checkpoints(run_id: str, request: Request):
        with database.sessions() as db:
            service.get_run(db, run_id, request.state.user["team"])
            return [
                {"revision": c.revision, "clock": c.state["clock"]}
                for c in db.scalars(
                    select(Checkpoint)
                    .where(Checkpoint.run_id == run_id)
                    .order_by(Checkpoint.revision.desc())
                    .limit(1000)
                )
            ]

    @app.get("/api/v2/runs/{run_id}/replay/{revision}", response_model=RunView)
    def replay(run_id: str, revision: int, request: Request):
        from .dynamics import public_state

        with database.sessions() as db:
            service.get_run(db, run_id, request.state.user["team"])
            checkpoint = db.scalar(
                select(Checkpoint).where(
                    Checkpoint.run_id == run_id, Checkpoint.revision == revision
                )
            )
            if checkpoint is None:
                raise LookupError("Checkpoint not found")
            return {
                "id": run_id,
                "revision": revision,
                "status": "replay",
                "state": public_state(checkpoint.state),
            }

    @app.get("/api/v2/runs/{run_id}/events", response_model=list[RunEvent])
    def events(run_id: str, request: Request, after: int = 0):
        with database.sessions() as db:
            service.get_run(db, run_id, request.state.user["team"])
            return [
                {
                    "sequence": e.sequence,
                    "clock": e.clock,
                    "kind": e.kind,
                    "payload": e.payload,
                }
                for e in db.scalars(
                    select(Event)
                    .where(Event.run_id == run_id, Event.sequence > after)
                    .order_by(Event.sequence)
                    .limit(500)
                )
            ]

    @app.get("/api/v2/runs/{run_id}/stream")
    async def stream(run_id: str, request: Request, after: int = 0):
        try:
            cursor = max(after, int(request.headers.get("last-event-id", "0")))
        except ValueError:
            raise HTTPException(400, "Invalid event cursor")
        with database.sessions() as db:
            service.get_run(db, run_id, request.state.user["team"])

        async def generate():
            nonlocal cursor
            while not await request.is_disconnected():
                with database.sessions() as db:
                    current_user = security.resolve_principal(
                        db, request.cookies.get("uita_session"), access_mode
                    )
                    if (
                        current_user is None
                        or current_user["team"] != request.state.user["team"]
                    ):
                        return
                batch = events(run_id, request, cursor)
                for item in batch:
                    cursor = item["sequence"]
                    yield f"id: {cursor}\ndata: {json.dumps(item)}\n\n"
                if not batch:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    @app.get("/api/v2/runs/{run_id}/export")
    def export(run_id: str, request: Request):
        with database.sessions() as db:
            run = service.get_run(db, run_id, request.state.user["team"])
            return {
                "run": service.view(run),
                "standards": PACK.model_dump(),
                "events": [
                    {
                        "sequence": e.sequence,
                        "clock": e.clock,
                        "kind": e.kind,
                        "payload": e.payload,
                    }
                    for e in db.scalars(
                        select(Event)
                        .where(Event.run_id == run_id)
                        .order_by(Event.sequence)
                    )
                ],
            }

    @app.post("/api/v2/comparisons")
    def compare(command: Compare, request: Request):
        with database.transaction() as db:
            service.scenario_for(db, command.scenario_id)
            key = request.state.user["team"] + ":compare:" + command.idempotency_key
            previous = service.previous(db, key, command.model_dump())
            if previous:
                return previous
            job = Job(
                id=service.identifier(),
                team=request.state.user["team"],
                payload=command.model_dump(),
            )
            db.add(job)
            response = {"id": job.id, "status": "queued"}
            service.record(db, key, command.model_dump(), response)
            return response

    @app.post("/api/v2/runs/{run_id}/compare")
    def compare_run(run_id: str, command: CompareRun, request: Request):
        from .data import digest

        with database.transaction() as db:
            run = service.get_run(db, run_id, request.state.user["team"], lock=True)
            key = (
                request.state.user["team"]
                + ":compare-run:"
                + run_id
                + ":"
                + command.idempotency_key
            )
            previous = service.previous(db, key, command.model_dump())
            if previous:
                return previous
            if run.revision != command.expected_revision:
                raise ValueError("Stale revision; refresh the run")
            seconds = int(run.state["clock"] - run.state["start"])
            if not 1 <= seconds <= 10800:
                raise ValueError(
                    "Comparison requires 1–10800 executed simulated seconds"
                )
            journal = [
                {"kind": e.kind, "clock": e.clock, "payload": e.payload}
                for e in db.scalars(
                    select(Event).where(Event.run_id == run.id).order_by(Event.sequence)
                )
            ]
            candidate = {
                "controller": run.state["policy_version"],
                "status": run.status,
                "clock": run.state["clock"],
                "metrics": service.view(run)["state"]["metrics"],
                "state_hash": digest(run.state),
                "events": journal,
            }
            job = Job(
                id=service.identifier(),
                team=run.team,
                payload={
                    "scenario_id": run.state["scenario_id"],
                    "seed": run.state["seed"],
                    "controllers": ["static"],
                    "seconds": seconds,
                    "source_run_id": run.id,
                    "source_revision": run.revision,
                    "candidate": candidate,
                    "event_tape": [e for e in journal if e["kind"] == "disruption"],
                },
            )
            db.add(job)
            response = {"id": job.id, "status": "queued"}
            service.record(db, key, command.model_dump(), response)
            return response

    @app.post("/api/v2/runs/{run_id}/compare-intervention")
    def compare_intervention(
        run_id: str, command: CompareIntervention, request: Request
    ):
        with database.transaction() as db:
            run = service.get_run(db, run_id, request.state.user["team"], lock=True)
            key = run.team + ":counterfactual:" + run.id + ":" + command.idempotency_key
            prior = service.previous(db, key, command.model_dump())
            if prior:
                return prior
            if run.revision != command.expected_revision:
                raise ValueError("Stale revision; refresh the run")
            intervention = next(
                (
                    i
                    for i in run.state.get("interventions", [])
                    if i["id"] == command.intervention_id
                ),
                None,
            )
            if not intervention:
                raise ValueError("Intervention not found")
            checkpoint = db.scalar(
                select(Checkpoint).where(
                    Checkpoint.run_id == run.id,
                    Checkpoint.revision == intervention["before_revision"],
                )
            )
            if checkpoint is None:
                raise ValueError("Pre-intervention checkpoint unavailable")
            horizon = max(
                command.seconds, int(run.state["clock"] - checkpoint.state["clock"])
            )
            if horizon > 1200:
                raise ValueError(
                    "Comparison checkpoint is outside the 1200-second comparison limit"
                )
            journal = [
                {"kind": e.kind, "clock": e.clock, "payload": e.payload}
                for e in db.scalars(
                    select(Event)
                    .where(
                        Event.run_id == run.id,
                        Event.sequence > checkpoint.state["event_sequence"],
                        Event.kind == "disruption",
                    )
                    .order_by(Event.sequence)
                )
            ]
            job = Job(
                id=service.identifier(),
                team=run.team,
                payload={
                    "scenario_id": run.state["scenario_id"],
                    "seed": run.state["seed"],
                    "seconds": horizon,
                    "controllers": ["with_intervention", "without_intervention"],
                    "initial_state": checkpoint.state,
                    "omitted_intervention": command.intervention_id,
                    "event_tape": journal,
                    "source_run_id": run.id,
                    "source_revision": run.revision,
                },
            )
            db.add(job)
            response = {"id": job.id, "status": "queued"}
            service.record(db, key, command.model_dump(), response)
            return response

    @app.get("/api/v2/jobs/{job_id}")
    def job(job_id: str, request: Request):
        with database.sessions() as db:
            row = db.scalar(
                select(Job).where(
                    Job.id == job_id, Job.team == request.state.user["team"]
                )
            )
            if row is None:
                raise LookupError("Job not found")
            return {"id": row.id, "status": row.status, "result": row.result}

    from .presentation import routes

    routes(app, database)
    showcase = Path(
        os.getenv(
            "UITA_SHOWCASE_DIR", str(Path(__file__).resolve().parents[3] / "showcase")
        )
    )
    if os.getenv("UITA_SHOWCASE") == "1":
        for route, folder in [
            ("/candidates", showcase / "candidates"),
            ("/vendor/three", showcase / "node_modules/three186"),
            ("/vendor/cesium", showcase / "node_modules/cesium/Build/Cesium"),
        ]:
            if folder.exists():
                app.mount(route, StaticFiles(directory=folder), name=route)

        @app.get("/login")
        def showcase_login():
            return FileResponse(showcase / "candidates/research-login.html")

        @app.get("/")
        def showcase_index():
            return FileResponse(showcase / "candidates/app.html")

    dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/favicon.svg")
        def favicon():
            return FileResponse(dist / "favicon.svg")

        @app.get("/login")
        @app.get("/workbench")
        def index():
            return FileResponse(dist / "index.html")

        if os.getenv("UITA_SHOWCASE") != "1":
            app.add_api_route("/", index)

    if os.getenv("UITA_HISTORY_LOCAL") == "1":
        from ..history import router

        # Exact routes take precedence over the optional upstream adapter.
        app.router.routes = [
            r
            for r in app.router.routes
            if getattr(r, "path", "") != "/uita/api/history/{endpoint}"
        ]
        app.include_router(router, prefix="/uita")
        app.include_router(router)  # Preserve existing history-service clients.
    return app

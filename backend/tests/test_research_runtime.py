import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from uita.research.api import create_app
from uita.research.budget import reserve
from uita.research.data import (
    causal_forecasts,
    causal_weather,
    frozen_fixture,
    save_artifact,
)
from uita.research.database import Base, Budget, Database, Event, Run
from uita.research.security import add_user
from uita.research.worker import Worker


@pytest.fixture
def runtime(tmp_path):
    database = Database("sqlite:///" + str(tmp_path / "research.db"))
    Base.metadata.create_all(database.engine)
    with database.transaction() as db:
        scenario = frozen_fixture()
        save_artifact(db, scenario["id"], "scenario", scenario)
        add_user(db, "operator", "long-test-password", "one", "operator")
        add_user(db, "viewer", "long-test-password", "one", "viewer")
        add_user(db, "outsider", "long-test-password", "two", "operator")
        db.add(Budget(id="validation-v2", cap=5.0, reserved=0.0))
    with TestClient(create_app(database, False)) as client:
        yield database, client


def sign_in(client, username="operator"):
    assert (
        client.post(
            "/api/v2/login",
            json={"username": username, "password": "long-test-password"},
        ).status_code
        == 200
    )


def create(client, key="create-test"):
    response = client.post(
        "/api/v2/runs",
        json={"scenario_id": "fixture-august-v2", "idempotency_key": key},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_private_reads_and_team_isolation(runtime):
    database, client = runtime
    assert client.get("/api/v2/scenarios").status_code == 401
    sign_in(client)
    run = create(client)
    sign_in(client, "outsider")
    assert client.get("/api/v2/runs/" + run["id"]).status_code == 404
    assert client.get("/api/v2/runs/" + run["id"] + "/events").status_code == 404
    sign_in(client, "viewer")
    assert client.get("/api/v2/runs/" + run["id"]).status_code == 200
    assert (
        client.post(
            "/api/v2/runs",
            json={"scenario_id": "fixture-august-v2", "idempotency_key": "viewer-run"},
        ).status_code
        == 403
    )


def test_read_only_clock_idempotency_and_stale_revision(runtime):
    database, client = runtime
    sign_in(client)
    run = create(client)
    assert create(client)["id"] == run["id"]
    url = "/api/v2/runs/" + run["id"]
    assert client.get(url).json() == client.get(url).json()
    command = {
        "expected_revision": 1,
        "idempotency_key": "one-step",
        "action": "step",
        "seconds": 10,
    }
    response = client.post(url + "/control", json=command)
    assert response.status_code == 200, response.text
    stepped = response.json()
    assert stepped["state"]["clock"] == run["state"]["clock"] + 10
    assert client.post(url + "/control", json=command).json() == stepped
    assert (
        client.post(url + "/control", json={**command, "seconds": 20}).status_code
        == 409
    )
    assert (
        client.post(
            url + "/control", json={**command, "idempotency_key": "new-step"}
        ).status_code
        == 409
    )
    assert (
        client.get(url + "/replay/1").json()["state"]["clock"] == run["state"]["clock"]
    )


def test_worker_advances_without_read_requests(runtime):
    database, client = runtime
    sign_in(client)
    run = create(client)
    client.post(
        "/api/v2/runs/" + run["id"] + "/control",
        json={"expected_revision": 1, "idempotency_key": "start-run", "action": "play"},
    )
    worker = Worker(database)
    assert worker.tick()
    with database.sessions() as db:
        saved = db.get(Run, run["id"])
        assert saved.state["clock"] == run["state"]["clock"] + 1
        assert saved.owner == worker.id
    assert not Worker(database).tick()


def test_atomic_budget_caps(runtime):
    database, _ = runtime
    with database.transaction() as db:
        reserve(db, "one", "run", 0.4)
    with pytest.raises(ValueError), database.transaction() as db:
        reserve(db, "one", "run", 0.2)
    with database.sessions() as db:
        assert db.get(Budget, "validation-v2").reserved == 0.4


def test_weather_and_forecast_causality():
    reports = [{"observed_at": 10, "available_at": 15, "visibility_sm": 1}]
    assert causal_weather(reports, 14)["stale"]
    assert causal_weather(reports, 15)["visibility_sm"] == 1
    forecasts = [{"issued_at": 20, "valid_until": 100, "visibility_sm": 1}]
    assert causal_forecasts(forecasts, 19) == []


def test_fork_and_origin(runtime):
    database, client = runtime
    sign_in(client)
    run = create(client)
    url = "/api/v2/runs/" + run["id"]
    assert (
        client.post(
            url + "/control",
            headers={"Origin": "https://hostile.example"},
            json={
                "expected_revision": 1,
                "idempotency_key": "hostile-step",
                "action": "step",
            },
        ).status_code
        == 403
    )
    response = client.post(
        url + "/fork",
        json={
            "expected_revision": 1,
            "checkpoint_revision": 1,
            "idempotency_key": "fork-test",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["id"] != run["id"]


def test_inference_does_not_block_clock_and_is_rechecked(runtime, monkeypatch):
    import threading
    import time

    from uita.research.contracts import Clearance, ControllerProposal

    gate = threading.Event()

    def generate(*args):
        gate.wait(2)
        return ControllerProposal(
            clearances=[
                Clearance(aircraft_id="fixture-0", kind="landing", target="28L")
            ]
        ), {"fixture": True}

    monkeypatch.setattr("uita.research.worker.generate", generate)
    database, client = runtime
    sign_in(client)
    run = client.post(
        "/api/v2/runs",
        json={
            "scenario_id": "fixture-august-v2",
            "controller": "crusoe",
            "idempotency_key": "async-inference",
        },
    ).json()
    client.post(
        "/api/v2/runs/" + run["id"] + "/control",
        json={
            "action": "play",
            "expected_revision": 1,
            "idempotency_key": "async-start",
        },
    )
    worker = Worker(database)
    started = time.monotonic()
    assert worker.tick()
    assert time.monotonic() - started < 1
    with database.transaction() as db:
        db.get(Run, run["id"]).next_tick = 0
    assert worker.tick()
    gate.set()
    worker.inference_pool.shutdown(wait=True)
    worker.collect_inference()
    with database.sessions() as db:
        saved = db.get(Run, run["id"])
        assert saved.state["clock"] == run["state"]["clock"] + 2
        assert saved.state["clearances"][0]["kind"] == "landing"
        assert any(
            e.kind == "model_response"
            for e in db.scalars(select(Event).where(Event.run_id == run["id"]))
        )


def test_terminal_run_cannot_be_resumed_through_pause(runtime):
    database, client = runtime
    sign_in(client)
    run = create(client)
    with database.transaction() as db:
        row = db.get(Run, run["id"])
        row.state = {**row.state, "status": "failed"}
        row.status = "failed"
    for action in ("pause", "play", "step", "speed"):
        response = client.post(
            "/api/v2/runs/" + run["id"] + "/control",
            json={
                "action": action,
                "expected_revision": 1,
                "idempotency_key": "terminal-" + action,
            },
        )
        assert response.status_code == 409
    assert client.get("/api/v2/runs/" + run["id"]).json()["status"] == "failed"


def test_comparison_failure_is_durable(runtime, monkeypatch):
    from uita.research.database import Job

    database, client = runtime
    sign_in(client)
    response = client.post(
        "/api/v2/comparisons",
        json={
            "scenario_id": "fixture-august-v2",
            "idempotency_key": "comparison-error",
        },
    )
    worker = Worker(database)

    def fail(*args):
        raise RuntimeError("private internal detail")

    monkeypatch.setattr(worker, "execute_job", fail)
    assert worker.job()
    with database.sessions() as db:
        job = db.get(Job, response.json()["id"])
        assert job.status == "failed"
        assert job.result == {
            "reason": "comparison_failed",
            "error_type": "RuntimeError",
        }
    worker.close()


def test_comparison_runs_off_clock_thread(runtime, monkeypatch):
    import threading

    database, client = runtime
    sign_in(client)
    run = create(client)
    client.post(
        "/api/v2/runs/" + run["id"] + "/control",
        json={
            "action": "play",
            "expected_revision": 1,
            "idempotency_key": "job-clock-start",
        },
    )
    worker = Worker(database)
    entered, release = threading.Event(), threading.Event()

    def slow_job():
        entered.set()
        release.wait(3)

    monkeypatch.setattr(worker, "job", slow_job)
    worker.dispatch_job()
    assert entered.wait(1)
    assert worker.tick()
    release.set()
    worker.close()
    assert (
        client.get("/api/v2/runs/" + run["id"]).json()["state"]["clock"]
        == run["state"]["clock"] + 1
    )


def test_worker_fences_incompatible_runtime(runtime):
    database, client = runtime
    sign_in(client)
    run = create(client)
    with database.transaction() as db:
        row = db.get(Run, run["id"])
        row.state = {
            **row.state,
            "status": "running",
            "simulator_version": "future-version",
        }
        row.status = "running"
    worker = Worker(database)
    assert worker.tick()
    worker.close()
    result = client.get("/api/v2/runs/" + run["id"]).json()
    assert result["status"] == "paused"
    assert result["state"]["clock"] == run["state"]["clock"]


def test_event_payloads_are_immutable_within_batch():
    from uita.research.dynamics import event

    state = {"clock": 1, "_events": []}
    clearance = {"status": "issued"}
    event(state, "clearance_issued", clearance=clearance)
    clearance["status"] = "completed"
    assert state["_events"][0]["payload"]["clearance"]["status"] == "issued"


def test_demo_closure_comparison_and_export(runtime):
    database, client = runtime
    sign_in(client)
    run = create(client, "demo-vertical-flow")
    url = "/api/v2/runs/" + run["id"]
    run = client.post(
        url + "/control",
        json={
            "action": "step",
            "seconds": 30,
            "expected_revision": run["revision"],
            "idempotency_key": "demo-first-step",
        },
    ).json()
    assert run["state"]["aircraft"][0]["runway"] == "28R"
    closure_clock = run["state"]["clock"]
    run = client.post(
        url + "/disruptions",
        json={
            "kind": "runway_closure",
            "runway": "28R",
            "expected_revision": run["revision"],
            "idempotency_key": "demo-closure",
        },
    ).json()
    run = client.post(
        url + "/control",
        json={
            "action": "step",
            "seconds": 60,
            "expected_revision": run["revision"],
            "idempotency_key": "demo-after-closure",
        },
    ).json()
    assert run["state"]["aircraft"][0]["status"] == "go_around"
    job = client.post(
        url + "/compare",
        json={"expected_revision": run["revision"], "idempotency_key": "demo-compare"},
    )
    assert job.status_code == 200, job.text
    worker = Worker(database)
    assert worker.job()
    worker.close()
    report = client.get("/api/v2/jobs/" + job.json()["id"]).json()
    assert report["status"] == "complete"
    baseline, candidate = report["result"]["results"]
    assert baseline["clock"] == candidate["clock"] == run["state"]["clock"]
    assert (
        next(e for e in baseline["events"] if e["kind"] == "disruption")["clock"]
        == closure_clock
    )
    assert candidate["controller"] == "fixture-2"
    exported = client.get(url + "/export").json()
    assert any(e["kind"] == "proposal_verified" for e in exported["events"])
    assert "standards" in exported


@pytest.mark.parametrize("fault", ["provider_timeout", "budget_exhausted"])
def test_fixture_failure_records_visible_free_fallback(runtime, fault):
    database, client = runtime
    sign_in(client)
    run = client.post(
        "/api/v2/runs",
        json={
            "scenario_id": "fixture-august-v2",
            "controller": "fixture",
            "fixture_fault": fault,
            "idempotency_key": "fault-test-" + fault,
        },
    ).json()
    run = client.post(
        "/api/v2/runs/" + run["id"] + "/control",
        json={
            "action": "step",
            "expected_revision": 1,
            "seconds": 10,
            "idempotency_key": "fault-test-step",
        },
    ).json()
    assert run["state"]["fallback_reason"] == fault
    assert run["state"]["controller"] == "static"
    assert run["state"]["clock"] > run["state"]["start"]
    with database.sessions() as db:
        assert db.get(Budget, "validation-v2").reserved == 0

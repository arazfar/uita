import copy
import gzip
import json
from pathlib import Path

import pytest

from uita.research import sandbox
from uita.research.contracts import Disruption
from uita.research.dynamics import initial_state, observation, public_state
from uita.research.service import advance_one, apply_disruption
from uita.research.data import digest


def prepared():
    source = json.loads(
        gzip.decompress(
            Path("backend/uita/research/assets/dense_demo.json.gz").read_bytes()
        )
    )["artifacts"][0]["payload"]
    scenario = sandbox.scenario_from(source)
    state = initial_state(scenario, 42, "static")
    sandbox.initialize(state)
    for _ in range(300):
        advance_one(state, scenario)
        state["_events"] = []
    state["initialization_until"] = None
    assert state["status"] == "running"
    return state, scenario


def inject(state, kind, key="test-event", **kw):
    return Disruption(kind=kind, idempotency_key=key, expected_revision=1, **kw)


def test_timed_recovery_does_not_reopen_permanent_closure():
    state, scenario = prepared()
    apply_disruption(
        state, inject(state, "weather_restriction", runway="28R"), scenario
    )
    apply_disruption(
        state,
        inject(state, "runway_closure", key="permanent-close", runway="28R"),
        scenario,
    )
    for _ in range(121):
        advance_one(state, scenario)
    assert "28R" in state["closed_runways"]
    assert state["interventions"][0]["status"] == "recovered"
    assert any(
        e["kind"] == "controller_response"
        and "i-test-event" in e["payload"]["cause_ids"]
        for e in state["_events"]
    )


@pytest.mark.parametrize(
    "kind", ["weather_restriction", "pilot_delay", "emergency", "extra_arrival"]
)
def test_interventions_replay_deterministically(kind):
    state, scenario = prepared()
    kw = (
        {"aircraft_id": state["aircraft"][2]["id"]}
        if kind == "emergency"
        else {"runway": "28L"}
    )
    command = inject(state, kind, **kw)
    apply_disruption(state, command, scenario)
    clone = json.loads(json.dumps(state))  # Durable JSON checkpoint round-trip.
    for value in (state, clone):
        for _ in range(1200):
            advance_one(value, scenario)
            if value["status"] == "failed":
                break
    assert digest(state) == digest(clone)
    assert any(e["kind"] == "controller_response" for e in state["_events"])
    assert state["status"] != "failed", state["_events"][-1:]
    if kind == "extra_arrival":
        assert state["admission_requests"][0]["status"] == "admitted"
        assert "_admission_schedule" not in public_state(state)
        assert "admission_requests" not in observation(state)
    if kind == "pilot_delay":
        assert state["communications_delay"] == 2


def test_request_limits_and_duplicate_key():
    state, scenario = prepared()
    command = inject(state, "extra_arrival")
    apply_disruption(state, command, scenario)
    apply_disruption(state, command, scenario)
    assert len(state["admission_requests"]) == 1
    for key in ("second-flight", "third-flight"):
        apply_disruption(state, inject(state, "extra_arrival", key=key), scenario)
    with pytest.raises(ValueError, match="Three"):
        apply_disruption(
            state, inject(state, "extra_arrival", key="fourth-flight"), scenario
        )
    apply_disruption(state, inject(state, "pilot_delay", key="first-delay"), scenario)
    with pytest.raises(ValueError, match="already active"):
        apply_disruption(
            state, inject(state, "pilot_delay", key="another-delay"), scenario
        )


def test_worker_restart_and_checkpoint_counterfactual(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from uita.research.api import create_app
    from uita.research.database import Base, Database, Run
    from uita.research.data import save_artifact
    from uita.research.worker import Worker

    monkeypatch.setenv("UITA_ACCESS_MODE", "public_demo")
    database = Database(f"sqlite:///{tmp_path}/worker.db")
    Base.metadata.create_all(database.engine)
    _, scenario = prepared()
    with database.transaction() as db:
        save_artifact(db, scenario["id"], "scenario", scenario)
    client = TestClient(create_app(database, False))
    created = client.post(
        "/api/v2/runs",
        json={
            "scenario_id": scenario["id"],
            "sandbox": True,
            "controller": "static",
            "idempotency_key": "sandbox-create",
        },
    ).json()
    run_id = created["id"]
    for _ in range(10):
        with database.transaction() as db:
            run = db.get(Run, run_id)
            run.lease_until = 0
            run.next_tick = 0
        worker = Worker(database)
        assert worker.tick()
        worker.close()
    ready = client.get(f"/api/v2/runs/{run_id}").json()
    assert ready["state"]["clock"] == scenario["start"] + 300
    assert ready["state"]["initialization_until"] is None
    assert ready["status"] == "paused"
    response = client.post(
        f"/api/v2/runs/{run_id}/disruptions",
        json={
            "kind": "pilot_delay",
            "expected_revision": ready["revision"],
            "idempotency_key": "delay-test",
        },
    )
    assert response.status_code == 200, response.text
    changed = response.json()
    extra = client.post(
        f"/api/v2/runs/{run_id}/disruptions",
        json={
            "kind": "extra_arrival",
            "expected_revision": changed["revision"],
            "idempotency_key": "extra-test",
        },
    ).json()
    command = {
        "intervention_id": "i-delay-test",
        "expected_revision": extra["revision"],
        "idempotency_key": "compare-test",
        "seconds": 300,
    }
    response = client.post(f"/api/v2/runs/{run_id}/compare-intervention", json=command)
    assert response.status_code == 200, response.text
    job = response.json()
    assert (
        client.post(f"/api/v2/runs/{run_id}/compare-intervention", json=command).json()
        == job
    )
    worker = Worker(database)
    assert worker.job()
    worker.close()
    result = client.get("/api/v2/jobs/" + job["id"]).json()
    assert result["status"] == "complete", result
    branches = result["result"]["results"]
    assert len(branches) == 2
    for branch in branches:
        assert branch["metrics"]["violations"] == 0
        assert branch["admission_requests"][0]["status"] == "admitted"
    assert not any(
        e["payload"].get("disruption_id") == "i-delay-test"
        for e in branches[1]["events"]
    )
    assert branches[0]["state_hash"] != branches[1]["state_hash"]


def test_combined_preset_and_unsafe_admission(monkeypatch):
    state, scenario = prepared()
    for kind in ("pilot_delay", "extra_arrival"):
        apply_disruption(state, inject(state, kind, key=kind), scenario)
    clone = copy.deepcopy(state)
    for _ in range(1200):
        advance_one(state, scenario)
        assert state["status"] != "failed"
    assert state["metrics"]["completed"] > 0
    assert state["admission_requests"][0]["status"] == "admitted"
    request = clone["admission_requests"][0]
    clone["clock"] = request["scheduled_at"] - 1
    monkeypatch.setattr(
        sandbox, "verify_motion", lambda *_: {"status": "unresolved", "checks": []}
    )
    sandbox.before_step(clone, scenario)
    assert request["status"] == "deferred"
    assert not any(a["id"] == request["aircraft_id"] for a in clone["aircraft"])
    assert request["scheduled_at"] > clone["clock"] + 1

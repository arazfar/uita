import copy
import gzip
import json
from pathlib import Path

import pytest
from uita.research import arrival_routes as routes
from uita.research import sandbox
from uita.research.contracts import Clearance, Disruption
from uita.research.data import digest
from uita.research.dynamics import initial_state
from uita.research.service import advance_one, apply_disruption
from uita.research.verification import verify_clearance, verify_motion


def scenario():
    return next(
        a["payload"]
        for a in json.loads(
            gzip.decompress(
                Path("backend/uita/research/assets/arrival_flows.json.gz").read_bytes()
            )
        )["artifacts"]
        if a["kind"] == "scenario"
    )


def prepared():
    s = scenario()
    state = initial_state(s, 42, "static")
    sandbox.initialize(state)
    for _ in range(300):
        advance_one(state, s)
        state["_events"] = []
    state["initialization_until"] = None
    assert state["status"] == "running"
    return state, s


@pytest.mark.parametrize(
    "preset", ["none", "weather", "priority", "delay", "extra", "combined"]
)
def test_full_horizon(preset):
    state, s = prepared()
    tape = []
    if preset in ("weather", "combined"):
        tape.append({"kind": "weather_restriction", "runway": "28L"})
    if preset in ("priority", "combined"):
        tape.append({"kind": "emergency", "aircraft_id": state["aircraft"][3]["id"]})
    if preset in ("delay", "combined"):
        tape.append({"kind": "pilot_delay"})
    if preset in ("extra", "combined"):
        tape.append({"kind": "extra_arrival"})
    for i, kw in enumerate(tape):
        apply_disruption(
            state,
            Disruption(**kw, idempotency_key="preset-" + str(i), expected_revision=1),
            s,
        )
    for t in range(1200):
        advance_one(state, s)
        assert state["status"] != "failed", (preset, t, state["_events"][-1])
        state["_events"] = []
    assert state["metrics"]["completed"] > 0
    assert state["metrics"]["violations"] == 0
    if preset in ("extra", "combined"):
        assert state["admission_requests"][0]["status"] in ("admitted", "deferred")


def test_geometry_and_unknown_authority():
    state, _s = prepared()
    a = next(a for a in state["aircraft"] if a["status"] == "approach")
    assert (
        verify_clearance(
            state, Clearance(aircraft_id=a["id"], kind="heading", value=270)
        )["status"]
        == "unresolved"
    )
    changed = copy.deepcopy(state)
    b = next(b for b in changed["aircraft"] if b["id"] == a["id"])
    b["x_nm"] += 10
    assert verify_motion(state, changed)["status"] == "fail"
    changed = copy.deepcopy(state)
    b = next(b for b in changed["aircraft"] if b["id"] == a["id"])
    b["heading_deg_true"] += 20
    assert verify_motion(state, changed)["status"] == "fail"


def test_catalog_recording_and_checkpoint():
    s = scenario()
    catalog = s["route_catalog"]
    assert len(catalog["routes"]) == 2
    assert all(
        len(r["source_ids"]) >= 2 and r["source_checksums"] for r in catalog["routes"]
    )
    recording = json.loads(
        gzip.decompress(
            Path(
                "backend/uita/research/assets/recordings/arrival-flows-v1.json.gz"
            ).read_bytes()
        )
    )
    from uita.research.presentation import validate_recording

    validate_recording(recording)
    assert recording["manifest"]["coverage"]["fraction_6_to_10"] >= 0.8
    state, s = prepared()
    restored = json.loads(json.dumps(state))
    for x in (state, restored):
        for _ in range(120):
            advance_one(x, s)
            x["_events"] = []
    assert digest(state) == digest(restored)


def test_merge_prediction_detects_future_crossing():
    from uita.research.dynamics import step
    from uita.research.route_verification import predict_merge

    s = scenario()
    s["entries"] = s["entries"][:2]
    for e in s["entries"]:
        r = e["route"]
        progress = r["length_nm"] - 50
        e["x_nm"], e["y_nm"] = routes.at(r["points"], r["distances_nm"], progress)
        target = routes.at(r["points"], r["distances_nm"], progress + 1)
        from uita.research.geometry import heading

        e["track_deg_true"] = heading(target[0] - e["x_nm"], target[1] - e["y_nm"])
        e["route_progress_nm"] = progress
        e["altitude_ft"], speed = routes.profile(50)
        e["groundspeed_kt"] = speed * (1 + e["altitude_ft"] / 50000)
    state = initial_state(s, 42, "static")
    sandbox.initialize(state)
    step(state, s)
    assert verify_motion(state, state)["status"] == "pass"
    verdict = predict_merge(state, 900)
    assert verdict["status"] == "fail", verdict


def test_route_wind_and_touchdown_geometry():
    state, s = prepared()
    state["weather_override"] = {
        **state["weather"],
        "wind_speed_kt": 12,
        "wind_from_deg_true": 230,
    }
    for _ in range(90):
        advance_one(state, s)
        state["_events"] = []
        assert state["status"] != "failed"
    a = next(a for a in state["aircraft"] if a["status"] == "approach")
    assert abs(a["heading_deg_true"] - a["track_deg_true"]) > 0.1
    bad = copy.deepcopy(state)
    b = next(b for b in bad["aircraft"] if b["id"] == a["id"])
    b.update(status="taxi", landing_authorized=True)
    bad["runway_occupant"] = a["id"]
    assert verify_motion(state, bad)["status"] == "fail"


def test_unsupported_routed_controller_is_not_mislabeled():
    from uita.research.worker import Worker

    with pytest.raises(ValueError, match="not implemented"):
        Worker.execute_job(None, "unused", 0, {"controllers": ["fcfs"]}, scenario())

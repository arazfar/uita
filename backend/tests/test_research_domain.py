import copy

from uita.research.contracts import Clearance
from uita.research.data import frozen_fixture
from uita.research.dynamics import initial_state, issue, observation, step
from uita.research.procedures import parse
from uita.research.service import advance_one
from uita.research.verification import verify_clearance, verify_motion


def state():
    scenario = frozen_fixture()
    s = initial_state(scenario, 42, "static")
    step(s, scenario)
    return s, scenario


def test_august_configuration_and_hidden_future():
    s, scenario = state()
    assert "01L" in s["closed_runways"] and "01R" in s["closed_runways"]
    assert len(observation(s)["aircraft"]) == 1
    assert "spawn_cursor" not in observation(s)
    assert "entries" not in observation(s)


def test_unsupported_vector_and_late_speed():
    s, _ = state()
    a = s["aircraft"][0]
    assert (
        verify_clearance(s, Clearance(aircraft_id=a["id"], kind="heading", value=90))[
            "status"
        ]
        == "unresolved"
    )
    a["x_nm"] = 1
    a["y_nm"] = 1
    assert (
        verify_clearance(s, Clearance(aircraft_id=a["id"], kind="speed", value=180))[
            "status"
        ]
        == "fail"
    )


def test_below_1000_and_between_tick_conflict():
    s, _ = state()
    a = s["aircraft"][0]
    a.update(x_nm=-6, y_nm=0, altitude_ft=500)
    b = copy.deepcopy(a)
    b.update(id="other", x_nm=6)
    s["aircraft"].append(b)
    after = copy.deepcopy(s)
    after["aircraft"][0]["x_nm"] = 6
    after["aircraft"][1]["x_nm"] = -6
    verdict = verify_motion(s, after)
    assert verdict["status"] == "fail"
    assert any(
        c["rule"] == "separation" and c["evidence"]["lateral_nm"] == 0
        for c in verdict["checks"]
    )


def test_readback_error_does_not_apply_instruction():
    s, scenario = state()
    a = s["aircraft"][0]
    s["readback_error"] = True
    issue(s, {"aircraft_id": a["id"], "kind": "speed", "value": 180, "target": None})
    step(s, scenario)
    step(s, scenario)
    assert a["target_ias_kt"] == 210
    assert s["clearances"][0]["status"] == "corrected"
    for _ in range(3):
        step(s, scenario)
    assert a["target_ias_kt"] == 180


def test_deterministic_completed_arrivals():
    scenario = frozen_fixture()
    states = []
    for _ in range(2):
        s = initial_state(scenario, 42, "static")
        s["status"] = "running"
        for i in range(1800):
            advance_one(s, scenario)
            s["_events"] = []
            if s["status"] == "failed":
                break
        states.append(s)
    assert states[0] == states[1]
    assert states[0]["metrics"]["completed"] >= 6
    assert states[0]["metrics"]["violations"] == 0


def test_procedure_leg_not_fabricated():
    p = parse(
        [
            {
                "airac": "2608",
                "procedure": "TEST",
                "route_type": "A",
                "transition": None,
                "seq": 1,
                "path_term": "CA",
                "lat": None,
                "lon": None,
            }
        ]
    )[0]
    assert not p["supported"] and p["unsupported_legs"] == ["CA"]


def test_metering_keeps_original_demand_and_accounts_for_backlog():
    from uita.research.data import metered_variant
    from uita.research.dynamics import public_state

    source = frozen_fixture()
    variant = metered_variant(source)
    assert source["entries"][1]["spawn_time"] != variant["entries"][1]["spawn_time"]
    assert (
        variant["entries"][1]["original_demand_time"]
        == source["entries"][1]["spawn_time"]
    )
    s = initial_state(variant, 42, "static")
    assert public_state(s)["metrics"]["backlog"] == 8
    assert all(e["provenance"]["kind"] == "synthetic" for e in variant["entries"])


def test_touchdown_never_snaps_across_the_descent_bound():
    from uita.research.data import frozen_fixture
    from uita.research.dynamics import initial_state, move, step

    scenario = frozen_fixture()
    state = initial_state(scenario, 42, "static")
    step(state, scenario)
    aircraft = state["aircraft"][0]
    aircraft.update(
        x_nm=0.1135486,
        y_nm=-0.0304313,
        altitude_ft=40.03449,
        runway="28R",
        landing_authorized=True,
        heading_deg_true=304.2,
        ias_kt=145,
    )
    previous = aircraft["altitude_ft"]
    for _ in range(10):
        move(aircraft, state)
        assert abs(aircraft["altitude_ft"] - previous) <= 25.001
        previous = aircraft["altitude_ft"]
        if aircraft["status"] == "taxi":
            break
    assert aircraft["status"] == "taxi"

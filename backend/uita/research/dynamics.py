"""Deterministic one-second research dynamics, independent of UI and persistence."""

import copy
import math

from .context import august_configuration, available_context
from .data import digest
from .geometry import heading
from .standards import VERSION

SIMULATOR_VERSION = "kinematic-research-2.1"
THRESHOLDS = {"28L": (0.0, -0.12), "28R": (0.04, 0.02)}
TERMINAL = {"complete", "diverted"}


def event(state, event_kind, **payload):
    # Later pilot/aircraft updates must never rewrite an earlier event in the batch.
    state["_events"].append(
        {"clock": state["clock"], "kind": event_kind, "payload": copy.deepcopy(payload)}
    )


def initial_state(scenario, seed, controller):
    configuration = august_configuration()
    if (
        not configuration["valid_from"]
        <= scenario["start"]
        < scenario["end"]
        <= configuration["valid_until"]
    ):
        raise ValueError("Scenario is outside the implemented airport rule-pack dates")
    return {
        "scenario_id": scenario["id"],
        "dataset_id": scenario["dataset_id"],
        "scenario_hash": digest(scenario),
        "simulator_version": SIMULATOR_VERSION,
        "rule_version": VERSION,
        "policy_version": controller + "-2",
        "clock": scenario["start"],
        "start": scenario["start"],
        "end": scenario["end"],
        "seed": seed,
        "controller": controller,
        "speed": 1,
        "aircraft": [],
        "spawn_cursor": 0,
        "clearances": [],
        "total_demand": len(scenario["entries"]),
        "closed_runways": ["01L", "01R", "19L", "19R"],
        **available_context(scenario, scenario["start"]),
        "airport_configuration": configuration,
        "last_model_clock": scenario["start"] - 30,
        "next_clearance": 0,
        "last_runway_use": scenario["start"] - 180,
        "runway_occupant": None,
        "readback_error": False,
        "communications_delay": 2,
        "status": "paused",
        "event_sequence": 0,
        "metrics": {
            "completed": 0,
            "diverted": 0,
            "violations": 0,
            "rejected": 0,
            "unresolved": 0,
            "readback_errors": 0,
            "holding_seconds": 0,
            "delay_seconds_sum": 0,
            "taxi_seconds": 0,
            "admission_delay_seconds": 0,
        },
        "provenance": scenario["provenance"],
        "_events": [],
    }


def observation(state):
    keys = (
        "id",
        "callsign",
        "type",
        "wake",
        "x_nm",
        "y_nm",
        "altitude_ft",
        "ias_kt",
        "groundspeed_kt",
        "track_deg_true",
        "status",
        "runway",
        "owner",
        "age_seconds",
        "emergency",
        "target_altitude_ft",
        "target_ias_kt",
    )
    return {
        "clock": state["clock"],
        "aircraft": [
            {k: a[k] for k in keys if k in a}
            for a in state["aircraft"]
            if a["status"] not in TERMINAL
        ],
        "weather": {
            k: v
            for k, v in state["weather"].items()
            if k
            in (
                "available",
                "stale",
                "visibility_sm",
                "ceiling_ft",
                "wind_from_deg_true",
                "wind_speed_kt",
                "observed_at",
            )
        },
        "closed_runways": list(state["closed_runways"]),
        "forecasts": copy.deepcopy(state.get("forecasts", [])),
        "advisories": copy.deepcopy(state.get("advisories", [])),
    }


def public_state(state):
    out = copy.deepcopy(state)
    out.pop("_events", None)
    out.pop("spawn_cursor", None)
    out["metrics"]["backlog"] = out["total_demand"] - out["metrics"]["completed"]
    out["metrics"]["admitted"] = len(out["aircraft"])
    delays = sorted(
        a.get("delay_seconds", 0) for a in out["aircraft"] if a["status"] == "complete"
    )
    out["metrics"]["mean_delay_seconds"] = sum(delays) / len(delays) if delays else 0
    out["metrics"]["p95_delay_seconds"] = (
        delays[max(0, math.ceil(len(delays) * 0.95) - 1)] if delays else 0
    )
    return out


def issue(state, clearance):
    a = next(a for a in state["aircraft"] if a["id"] == clearance["aircraft_id"])
    state["next_clearance"] += 1
    c = {
        **clearance,
        "id": f"c{state['next_clearance']}",
        "issued_at": state["clock"],
        "respond_at": state["clock"] + state["communications_delay"],
        "status": "issued",
        "expires_at": state["clock"] + 120,
    }
    state["clearances"].append(c)
    event(state, "clearance_issued", clearance=c, text=phrase(a, c))


def phrase(a, c):
    words = {
        "speed": f"maintain {c.get('value')} knots",
        "altitude": f"maintain {c.get('value')} feet",
        "heading": f"fly heading {c.get('value')}",
        "landing": f"runway {c.get('target')}, cleared to land",
        "takeoff": f"runway {c.get('target')}, cleared for takeoff",
        "approach": f"cleared {c.get('target')} approach",
        "hold": "hold on the simulated holding route",
        "direct": f"proceed direct {c.get('target')}",
        "go_around": "go around",
        "handoff": f"contact simulated {c.get('target')}",
    }
    return f"{a['callsign']}, {words[c['kind']]}"


def pilot_responses(state):
    for c in state["clearances"]:
        if c["status"] not in ("issued", "corrected"):
            continue
        if state["clock"] > c["expires_at"]:
            c["status"] = "expired"
            event(state, "clearance_expired", clearance_id=c["id"])
            continue
        if state["clock"] < c["respond_at"]:
            continue
        a = next(a for a in state["aircraft"] if a["id"] == c["aircraft_id"])
        if state["readback_error"]:
            state["readback_error"] = False
            state["metrics"]["readback_errors"] += 1
            c["status"] = "corrected"
            c["respond_at"] = state["clock"] + 3
            event(
                state,
                "readback_corrected",
                clearance_id=c["id"],
                expected=c,
                received={
                    "aircraft_id": a["id"],
                    "target": "incorrect simulated readback",
                },
            )
            continue
        c["status"] = "acknowledged"
        event(
            state,
            "pilot_acknowledged",
            clearance_id=c["id"],
            aircraft_id=a["id"],
            fields={k: c.get(k) for k in ("kind", "value", "target")},
            text=phrase(a, c),
        )
        kind = c["kind"]
        if kind == "speed":
            a["target_ias_kt"] = c["value"]
            a["assigned_speed"] = True
        elif kind == "altitude":
            a["target_altitude_ft"] = c["value"]
        elif kind == "heading":
            a["target_heading_deg"] = c["value"]
        elif kind == "landing":
            a["landing_authorized"] = True
            a["runway"] = c["target"]
        elif kind == "takeoff":
            a["status"] = "departure"
            a["runway"] = c["target"]
        elif kind == "go_around":
            a["status"] = "go_around"
            a["target_altitude_ft"] = max(a["altitude_ft"], 4000.0)
        elif kind == "hold":
            a["status"] = "holding"
        elif kind == "handoff":
            a["owner"] = c["target"]
        elif kind == "approach":
            a["status"] = "approach"
            a["assigned_speed"] = False
        c["status"] = "executing"
        # Discrete instructions complete on acknowledged state transition; continuous ones stay active.
        if kind in ("landing", "takeoff", "handoff", "approach", "hold", "go_around"):
            c["status"] = "completed"


def move(a, state):
    if a["status"] in TERMINAL or a["status"] == "pending":
        return
    if a["status"] == "taxi":
        a["surface_seconds"] += 1
        state["metrics"]["taxi_seconds"] += 1
        if a["surface_seconds"] >= 75:
            a["status"] = "complete"
            state["metrics"]["completed"] += 1
            state["runway_occupant"] = None
            a["delay_seconds"] = max(0, state["clock"] - a["nominal_finish_clock"])
            state["metrics"]["delay_seconds_sum"] += a["delay_seconds"]
            event(state, "arrival_completed", aircraft_id=a["id"])
        return
    target = THRESHOLDS[a["runway"]]
    distance = math.hypot(target[0] - a["x_nm"], target[1] - a["y_nm"])
    desired = heading(target[0] - a["x_nm"], target[1] - a["y_nm"])
    if a["status"] == "holding":
        desired = (a["heading_deg_true"] + 2) % 360
        state["metrics"]["holding_seconds"] += 1
    elif a["status"] in ("go_around", "departure"):
        desired = 297.0
    elif "target_heading_deg" in a:
        desired = a["target_heading_deg"]
    delta = (desired - a["heading_deg_true"] + 180) % 360 - 180
    a["heading_deg_true"] = (a["heading_deg_true"] + max(-3.0, min(3.0, delta))) % 360
    if a["status"] == "approach":
        target_alt = max(13.0, distance * 318.0)
        target_speed = (
            a["target_ias_kt"]
            if a.get("assigned_speed")
            else 145.0
            if distance < 10
            else a["target_ias_kt"]
        )
    else:
        target_alt, target_speed = a["target_altitude_ft"], a["target_ias_kt"]
    a["ias_kt"] += max(-2.0, min(2.0, target_speed - a["ias_kt"]))
    a["altitude_ft"] += max(-25.0, min(25.0, target_alt - a["altitude_ft"]))
    # Explicit ISA density approximation; measured wind aloft is unavailable.
    a["tas_kt"] = a["ias_kt"] * (1 + a["altitude_ft"] / 1000 * 0.02)
    wind = state["weather"]
    speed = wind.get("wind_speed_kt", 0.0) or 0.0
    wind_from = math.radians(wind.get("wind_from_deg_true", 0.0) or 0.0)
    rad = math.radians(a["heading_deg_true"])
    vx = a["tas_kt"] * math.sin(rad) - speed * math.sin(wind_from)
    vy = a["tas_kt"] * math.cos(rad) - speed * math.cos(wind_from)
    a["groundspeed_kt"] = math.hypot(vx, vy)
    a["track_deg_true"] = heading(vx, vy)
    a["x_nm"] += vx / 3600
    a["y_nm"] += vy / 3600
    if a["status"] == "approach" and distance < 0.09 and a["altitude_ft"] <= 13.000001:
        if (
            a["landing_authorized"]
            and state["runway_occupant"] is None
            and a["runway"] not in state["closed_runways"]
        ):
            a["status"] = "taxi"
            a["altitude_ft"] = 13.0
            a["surface_seconds"] = 0
            state["runway_occupant"] = a["id"]
            state["last_runway_use"] = state["clock"]
            event(state, "touchdown_simulated", aircraft_id=a["id"])
        else:
            a["status"] = "go_around"
            a["target_altitude_ft"] = 4000.0
            event(
                state,
                "synthetic_go_around",
                aircraft_id=a["id"],
                reason="Landing authority or runway unavailable",
            )
    if (
        a["status"] in ("go_around", "departure")
        and math.hypot(a["x_nm"], a["y_nm"]) > 25
    ):
        a["status"] = "diverted" if a["status"] == "go_around" else "complete"
        state["metrics"]["diverted" if a["status"] == "diverted" else "completed"] += 1
    for c in state["clearances"]:
        if c["aircraft_id"] == a["id"] and c["status"] == "executing":
            if (
                c["kind"] == "speed"
                and abs(a["ias_kt"] - c["value"]) < 1
                or c["kind"] == "altitude"
                and abs(a["altitude_ft"] - c["value"]) < 25
            ):
                c["status"] = "completed"


def step(state, scenario):
    """Advance exactly one second. Admission data is private to this function."""
    state["clock"] += 1
    state.update(available_context(scenario, state["clock"]))
    if state.get("weather_override"):
        state["weather"] = copy.deepcopy(state["weather_override"])
    entries = scenario["entries"]
    while (
        state["spawn_cursor"] < len(entries)
        and entries[state["spawn_cursor"]]["spawn_time"] <= state["clock"]
    ):
        entry = entries[state["spawn_cursor"]]
        state["spawn_cursor"] += 1
        state["metrics"]["admission_delay_seconds"] += max(
            0,
            entry["spawn_time"]
            - entry.get("original_demand_time", entry["spawn_time"]),
        )
        aircraft = {
            k: copy.deepcopy(entry[k])
            for k in (
                "id",
                "callsign",
                "x_nm",
                "y_nm",
                "altitude_ft",
                "groundspeed_kt",
                "track_deg_true",
                "provenance",
            )
        }
        aircraft["callsign"] = aircraft["callsign"] or aircraft["id"]
        aircraft.update(
            type=entry.get("aircraft_type", "unknown"),
            wake="unknown",
            status="approach"
            if entry.get("operation", "arrival") == "arrival"
            else "pending",
            operation=entry.get("operation", "arrival"),
            runway="28L",
            owner="approach",
            age_seconds=0,
            emergency=False,
            heading_deg_true=aircraft["track_deg_true"],
            ias_kt=aircraft["groundspeed_kt"] / (1 + aircraft["altitude_ft"] / 50000),
            target_ias_kt=210.0,
            target_altitude_ft=aircraft["altitude_ft"],
            landing_authorized=False,
            entry_clock=state["clock"],
            nominal_finish_clock=state["clock"]
            + math.hypot(aircraft["x_nm"], aircraft["y_nm"])
            / max(100.0, aircraft["groundspeed_kt"])
            * 3600
            + 75,
        )
        state["aircraft"].append(aircraft)
        event(
            state,
            "aircraft_entered",
            aircraft_id=aircraft["id"],
            provenance=aircraft["provenance"],
        )
    pilot_responses(state)
    for aircraft in state["aircraft"]:
        move(aircraft, state)
    if state["clock"] >= state["end"]:
        state["status"] = "complete"
        event(state, "run_finished", metrics=state["metrics"])

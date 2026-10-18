"""Versioned, explicitly synthetic demo interventions; never an ATC rule pack."""

import copy
import math

from .data import digest
from .dynamics import event, step
from .verification import verify_motion

VERSION = "kinematic-sandbox-3"
SCENARIO = "early-august-sandbox-v1"


def scenario_from(source):
    value = copy.deepcopy(source)
    value.update(id=SCENARIO, simulator_version=VERSION)
    value["provenance"] = {
        **value["provenance"],
        "sandbox": "interactive-1",
        "source_hash": digest(source),
    }
    return value


def initialize(state):
    state.update(
        sandbox=True,
        initialization_until=state["start"] + 300,
        interventions=[],
        replan_causes=[],
        decision_counter=0,
        admission_requests=[],
        speed=10,
        status="running",
    )


def active(state):
    return state.get("simulator_version") == VERSION


def _revoke(state, runway, cause):
    for a in state["aircraft"]:
        if a["runway"] != runway or a["status"] != "approach":
            continue
        authorized = a["landing_authorized"]
        a["landing_authorized"] = False
        if authorized:
            a.update(status="go_around", target_altitude_ft=max(4000, a["altitude_ft"]))
            event(
                state,
                "synthetic_go_around",
                aircraft_id=a["id"],
                cause_ids=[cause],
                reason="Runway unavailable; synthetic contingency, published missed approach unresolved",
            )
    for c in state["clearances"]:
        if (
            c.get("target") == runway
            and c["kind"] == "landing"
            and c["status"] not in ("cancelled", "expired")
        ):
            c["status"] = "cancelled"
            event(
                state,
                "clearance_cancelled",
                clearance_id=c["id"],
                aircraft_id=c["aircraft_id"],
                cause_ids=[cause],
            )


def intervene(state, command, scenario=None):
    if state.get("initialization_until"):
        raise ValueError("Sandbox is still preparing")
    kind = command.kind
    if kind not in (
        "weather_restriction",
        "pilot_delay",
        "extra_arrival",
        "recover",
        "emergency",
        "runway_closure",
    ):
        return False
    identifier = "i-" + command.idempotency_key
    if any(i["id"] == identifier for i in state["interventions"]):
        return True
    if kind in ("weather_restriction", "pilot_delay") and any(
        i["kind"] == kind and i["status"] == "active" for i in state["interventions"]
    ):
        raise ValueError("This timed intervention is already active")
    entry = dict(
        id=identifier,
        kind=kind,
        clock=state["clock"],
        status="active",
        runway=command.runway,
        aircraft_id=command.aircraft_id,
        before_revision=state.get("command_before_revision"),
        expires_at=state["clock"] + 120
        if kind in ("weather_restriction", "pilot_delay")
        else None,
    )
    if kind == "emergency":
        a = next(
            (
                a
                for a in state["aircraft"]
                if a["id"] == command.aircraft_id
                and a["status"] == "approach"
                and not a["landing_authorized"]
            ),
            None,
        )
        if not a:
            raise ValueError(
                "Choose an approaching aircraft without landing authorization"
            )
        a["emergency"] = True
    elif kind in ("weather_restriction", "runway_closure"):
        state.setdefault("permanent_closed_runways", list(state["closed_runways"]))
        if (
            kind == "runway_closure"
            and command.runway not in state["permanent_closed_runways"]
        ):
            state["permanent_closed_runways"].append(command.runway)
        if command.runway not in state["closed_runways"]:
            state["closed_runways"].append(command.runway)
        _revoke(state, command.runway, identifier)
    elif kind == "pilot_delay":
        entry["previous_delay"] = state["communications_delay"]
        state["communications_delay"] = 15
        for c in state["clearances"]:
            if c["status"] in ("issued", "corrected"):
                c["respond_at"] = max(c["respond_at"], state["clock"] + 15)
    elif kind == "recover":
        target = next(
            (
                i
                for i in state["interventions"]
                if i["id"] == command.intervention_id
                and i["status"] == "active"
                and i["kind"] in ("weather_restriction", "pilot_delay")
            ),
            None,
        )
        if not target:
            raise ValueError("No active timed intervention to recover")
        target["expires_at"] = state["clock"]
        entry["status"] = "completed"
    elif kind == "extra_arrival":
        if len(state["admission_requests"]) >= 3:
            raise ValueError("Three extra arrivals maximum per sandbox")
        if scenario is None:
            raise ValueError("Scenario required for extra demand")
        schedule = state.setdefault(
            "_admission_schedule", copy.deepcopy(scenario["entries"])
        )
        cursor = state["spawn_cursor"]
        while cursor < len(schedule) and schedule[cursor]["id"].startswith("extra-"):
            cursor += 1
        at = max(
            state["clock"] + 1,
            schedule[cursor]["spawn_time"]
            if cursor < len(schedule)
            else state["clock"] + 240,
        )
        donor = copy.deepcopy(scenario["entries"][-1])
        donor.update(
            id="extra-" + identifier,
            callsign=f"DEMO{len(state['admission_requests']) + 1}",
            spawn_time=at,
            original_demand_time=at,
            x_nm=104 * 0.894427,
            y_nm=-104 * 0.447214,
            altitude_ft=30000,
            groundspeed_kt=210,
            track_deg_true=297,
            provenance={
                "kind": "synthetic",
                "generator": "sandbox-extra-1",
                "seed": state["seed"],
                "assumptions": "Supported corridor; subsequent unobserved demand delayed 240 seconds",
            },
        )
        for original in schedule[cursor:]:
            original["spawn_time"] += 240
        schedule.insert(cursor, donor)
        for request in state["admission_requests"]:
            scheduled = next(
                (e for e in schedule if e["id"] == request["aircraft_id"]), None
            )
            if scheduled and request["status"] in ("queued", "deferred"):
                request["scheduled_at"] = scheduled["spawn_time"]
        state["total_demand"] += 1
        entry.update(status="queued", aircraft_id=donor["id"])
        state["admission_requests"].append(
            dict(
                id=identifier,
                aircraft_id=donor["id"],
                status="queued",
                requested_at=state["clock"],
                scheduled_at=at,
            )
        )
    state["interventions"].append(entry)
    state["replan_causes"].append(identifier)
    event(state, "disruption", **command.model_dump(), disruption_id=identifier)
    event(
        state,
        "intervention_changed",
        intervention=entry,
        cause_ids=[identifier],
        reason="Synthetic demo intervention requested",
    )
    return True


def before_step(state, scenario):
    for i in state["interventions"]:
        if i["kind"] in ("emergency", "extra_arrival") and any(
            a["id"] == i["aircraft_id"] and a["status"] in ("complete", "diverted")
            for a in state["aircraft"]
        ):
            i["status"] = "completed"
        if (
            i["status"] != "active"
            or i["expires_at"] is None
            or i["expires_at"] > state["clock"]
        ):
            continue
        i["status"] = "recovered"
        if i["kind"] == "pilot_delay":
            state["communications_delay"] = i["previous_delay"]
        if i["kind"] == "weather_restriction":
            remaining = any(
                j["status"] == "active"
                and j["kind"] == "weather_restriction"
                and j["runway"] == i["runway"]
                for j in state["interventions"]
            )
            if not remaining and i["runway"] not in state.get(
                "permanent_closed_runways", []
            ):
                state["closed_runways"] = [
                    r for r in state["closed_runways"] if r != i["runway"]
                ]
        state["replan_causes"].append(i["id"])
        event(
            state,
            "intervention_recovered",
            intervention_id=i["id"],
            cause_ids=[i["id"]],
            kind=i["kind"],
        )
    schedule = state.get("_admission_schedule")
    if schedule is None:
        return scenario
    effective = {**scenario, "entries": schedule}
    cursor = state["spawn_cursor"]
    if cursor < len(schedule) and schedule[cursor]["spawn_time"] <= state["clock"] + 1:
        req = next(
            (
                r
                for r in state["admission_requests"]
                if r["aircraft_id"] == schedule[cursor]["id"]
                and r["status"] in ("queued", "deferred")
            ),
            None,
        )
        if req:
            trial = copy.deepcopy(state)
            step(trial, effective)
            verdict = verify_motion(state, trial)
            if verdict["status"] != "pass":
                for e in schedule[cursor:]:
                    e["spawn_time"] += 30
                for request in state["admission_requests"]:
                    scheduled = next(
                        (e for e in schedule if e["id"] == request["aircraft_id"]), None
                    )
                    if scheduled and request["status"] in ("queued", "deferred"):
                        request["scheduled_at"] = scheduled["spawn_time"]
                if req["status"] != "deferred":
                    event(
                        state,
                        "arrival_deferred",
                        request_id=req["id"],
                        cause_ids=[req["id"]],
                        verdict=verdict,
                    )
                req["status"] = "deferred"
            else:
                req["status"] = "admitted"
                req["admitted_at"] = state["clock"] + 1
                next(i for i in state["interventions"] if i["id"] == req["id"])[
                    "status"
                ] = "admitted"
                state["replan_causes"].append(req["id"])
                event(
                    state,
                    "arrival_admitted",
                    aircraft_id=req["aircraft_id"],
                    cause_ids=[req["id"]],
                    verdict=verdict,
                )
    return effective


def response(state, proposal, verdict, before_order):
    causes = list(dict.fromkeys(state["replan_causes"]))
    state["replan_causes"] = []
    state["decision_counter"] += 1
    decision_id = f"d{state['decision_counter']}"
    event(
        state,
        "controller_response",
        decision_id=decision_id,
        cause_ids=causes,
        previous_sequence=before_order,
        proposal=proposal.model_dump(),
        verdict=verdict,
        outcome="issued"
        if proposal.clearances and verdict["status"] == "pass"
        else "deferred",
        reason=proposal.explanation,
    )
    state["last_decision"] = {
        "id": decision_id,
        "cause_ids": causes,
        "clock": state["clock"],
    }

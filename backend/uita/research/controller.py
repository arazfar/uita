"""Bounded deterministic scheduler. Independent clearance predicates gate execution."""

import math

from ortools.sat.python import cp_model

from .contracts import Clearance, ControllerProposal
from .verification import verify_clearance


def propose(state, sequence=None):
    if (
        state.get("sandbox")
        and state.get("speed_restore")
        and not any(
            i["kind"] == "weather_restriction" and i["status"] == "active"
            for i in state["interventions"]
        )
    ):
        for a in state["aircraft"]:
            target = state["speed_restore"].get(a["id"])
            pending = any(
                c["aircraft_id"] == a["id"] and c["status"] in ("issued", "corrected")
                for c in state["clearances"]
            )
            if target and not pending and a["status"] == "approach":
                command = Clearance(aircraft_id=a["id"], kind="speed", value=target)
                if verify_clearance(state, command)["status"] == "pass":
                    return ControllerProposal(
                        clearances=[command],
                        sequence=[a["id"]],
                        explanation=f"Restriction recovered: restore {a['callsign']} to its previous {target} knots IAS; independent speed and motion checks still apply.",
                    )
    aircraft = [
        a
        for a in state["aircraft"]
        if a["status"] in ("approach", "pending") and not a["landing_authorized"]
    ]
    pending = {
        c["aircraft_id"]
        for c in state["clearances"]
        if c["status"] in ("issued", "corrected")
    }
    aircraft = [a for a in aircraft if a["id"] not in pending]
    if sequence:
        rank = {identifier: i for i, identifier in enumerate(sequence)}
        aircraft.sort(key=lambda a: (rank.get(a["id"], len(rank)), a["id"]))
    elif state["controller"] == "fcfs":
        aircraft.sort(key=lambda a: (a["entry_clock"], a["id"]))
    else:
        aircraft.sort(
            key=lambda a: (
                not a["emergency"],
                math.hypot(a["x_nm"], a["y_nm"]),
                a["id"],
            )
        )
    aircraft = aircraft[:32]
    if not aircraft:
        return ControllerProposal()
    model = cp_model.CpModel()
    slots = []
    for i, a in enumerate(aircraft):
        eta = int(
            math.hypot(a["x_nm"], a["y_nm"]) / max(100, a["groundspeed_kt"]) * 3600
        )
        slot = model.new_int_var(eta, max(eta, 1800) + 180 * len(aircraft), f"slot{i}")
        if slots:
            model.add(slot >= slots[-1] + 180)
        slots.append(slot)
    model.minimize(sum(slots))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 0.2
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = state["seed"]
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return ControllerProposal(explanation="No bounded scheduler incumbent")
    clearances = []
    for a, slot in zip(aircraft, slots):
        # Synthetic single-corridor traffic cannot safely overtake an earlier approach.
        if state.get("sandbox") and any(
            b["id"] != a["id"]
            and b["status"] == "approach"
            and math.hypot(b["x_nm"], b["y_nm"]) + 8 < math.hypot(a["x_nm"], a["y_nm"])
            for b in state["aircraft"]
            if b["status"] not in ("complete", "diverted")
        ):
            continue
        if solver.value(slot) > 900:
            continue
        for runway in ("28L", "28R"):
            command = Clearance(
                aircraft_id=a["id"],
                kind="landing" if a["operation"] == "arrival" else "takeoff",
                target=runway,
            )
            if verify_clearance(state, command)["status"] == "pass":
                clearances.append(command)
                break
        if clearances:
            break  # one shared runway clearance at a time
    if (
        not clearances
        and state.get("sandbox")
        and any(
            i["kind"] == "weather_restriction" and i["status"] == "active"
            for i in state["interventions"]
        )
    ):
        for a in aircraft:
            if (
                a["status"] == "approach"
                and not a.get("assigned_speed")
                and a["ias_kt"] > 135
                and math.hypot(a["x_nm"], a["y_nm"]) >= 15
            ):
                command = Clearance(aircraft_id=a["id"], kind="speed", value=130)
                if verify_clearance(state, command)["status"] == "pass":
                    clearances.append(command)
                    break
    chosen = next(
        (a for a in aircraft if clearances and a["id"] == clearances[0].aircraft_id),
        None,
    )
    order_basis = (
        "requested sequence"
        if sequence
        else "entry order"
        if state["controller"] == "fcfs"
        else "emergency priority, then distance to SFO"
    )
    explanation = f"Queue ordered by {order_basis}."
    if chosen:
        explanation += (
            f" {chosen['callsign'] or chosen['id']} receives the next {clearances[0].kind} clearance "
            f"for {clearances[0].target}; its estimated scheduler slot is within 15 minutes and "
            "independent runway availability, occupancy and dependent-reservation checks passed. "
            "Other aircraft remain unapproved for landing; pilot acknowledgment is still required."
        )
    else:
        explanation += " No supported runway clearance passes current timing and authorization checks."
        if state.get("sandbox"):
            explanation += " Wait for existing landing commitments and pending pilot acknowledgments; priority cannot bypass the single-corridor order."
    if chosen and clearances[0].kind == "speed":
        explanation = (
            f"Temporary runway restriction: reduce {chosen['callsign']} to 130 knots IAS outside the restricted final segment. "
            "This is a bounded research speed adjustment; no landing authorization is granted."
        )
    return ControllerProposal(
        clearances=clearances,
        sequence=[a["id"] for a in aircraft],
        explanation=explanation,
    )

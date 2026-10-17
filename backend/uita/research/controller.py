"""Bounded deterministic scheduler. Independent clearance predicates gate execution."""

import math

from ortools.sat.python import cp_model

from .contracts import Clearance, ControllerProposal
from .verification import verify_clearance


def propose(state, sequence=None):
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
    return ControllerProposal(
        clearances=clearances,
        sequence=[a["id"] for a in aircraft],
        explanation="Deterministic bounded sequence; dependent runway authority; independent checks required",
    )

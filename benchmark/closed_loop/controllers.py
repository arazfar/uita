"""Three causal arrival schedulers with the same announced state and constraints.

The independent backend verifier decides whether any proposed plan may commit.
These schedulers never inspect historical outcomes or future source queues.
"""
from __future__ import annotations

import math
import time
import uuid

from backend.uita.airport import RULE_VERSION
from backend.uita.simulator import snapshot_hash

SLOT_LIMIT_SECONDS = 20000
APPROACH_SECONDS = 360
RESOURCE_BUFFER_SECONDS = 240
SOLVER_LIMIT_SECONDS = .25


def _duration(aircraft):
    # 90 taxi + 80 approach + 30 reservation + 40 worst-visibility seconds.
    # The same announced occupancy and conservative envelope apply to all methods.
    return math.ceil(aircraft["exit_occupancy"] + RESOURCE_BUFFER_SECONDS)


def _partition(state):
    aircraft = state["aircraft"]
    if len({a["id"] for a in aircraft}) != len(aircraft):
        raise ValueError("Aircraft IDs must be unique")
    fixed, pending = [], []
    for a in aircraft:
        if a["operation"] != "arrival":
            raise ValueError("Closed-loop comparison currently supports arrivals only")
        for key in ("requested", "scheduled", "exit_occupancy"):
            if isinstance(a[key], bool) or not isinstance(a[key], (int, float)) or not math.isfinite(a[key]):
                raise ValueError(f"Aircraft field must be finite: {key}")
        if a["exit_occupancy"] < 0 or not a.get("trajectory"):
            raise ValueError("Known nonnegative occupancy and trajectory binding are required")
        (fixed if a["trajectory"][0]["t"] <= state["time"] else pending).append(a)
    return fixed, pending


def _earliest(state, aircraft):
    return math.ceil(max(aircraft["requested"], state["time"] + APPROACH_SECONDS,
                         state.get("admission_blocked_until", 0) + APPROACH_SECONDS))


def _runway(state, aircraft):
    available = [r for r in ("28L", "28R") if r not in state["closed_runways"]]
    if not available:
        return None
    return aircraft["runway"] if aircraft["runway"] in available else available[0]


def _base_plan(state, controller):
    now = state["time"]
    return {"id": str(uuid.uuid4()), "revision": state["revision"], "rule_version": RULE_VERSION,
            "snapshot_hash": snapshot_hash(state), "snapshot_time": now, "valid_until": now + 30,
            "status": "infeasible", "slots": [], "controller": controller}


def _ordered(state, fixed, pending, order):
    by_id = {a["id"]: a for a in pending}
    if not isinstance(order, list) or not all(isinstance(aid, str) for aid in order):
        raise ValueError("AI order must be a list of pending aircraft IDs")
    if len(order) != len(by_id) or set(order) != set(by_id):
        raise ValueError("AI order must contain every pending aircraft exactly once")
    slots = {a["id"]: {"aircraft_id": a["id"], "runway": a["runway"], "time": a["scheduled"]} for a in fixed}
    cursor = max((a["scheduled"] + _duration(a) for a in fixed), default=0)
    for aid in order:
        a = by_id[aid]
        runway = _runway(state, a)
        slot = max(_earliest(state, a), cursor)
        if runway is None or slot > SLOT_LIMIT_SECONDS:
            return None
        slots[aid] = {"aircraft_id": aid, "runway": runway, "time": slot}
        cursor = slot + _duration(a)
    return [slots[a["id"]] for a in state["aircraft"]]


def _deterministic(state, fixed, pending, horizon):
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()
    times, intervals, incomplete = {}, [], []
    fixed_ids = {a["id"] for a in fixed}
    runways = {}
    aircraft = state["aircraft"]
    for a in aircraft:
        aid = a["id"]
        t = model.NewIntVar(0, SLOT_LIMIT_SECONDS, "slot_" + aid)
        times[aid] = t
        if aid in fixed_ids:
            if a["scheduled"] != int(a["scheduled"]):
                raise ValueError("Committed deterministic slots must use integer seconds")
            model.Add(t == int(a["scheduled"]))
            runways[aid] = a["runway"]
        else:
            model.Add(t >= _earliest(state, a))
            runway = _runway(state, a)
            if runway is None:
                return None, {"status": "INFEASIBLE", "optimal": False, "reason": "all_arrival_runways_closed"}
            runways[aid] = runway
        duration = _duration(a)
        end = model.NewIntVar(0, SLOT_LIMIT_SECONDS + duration, "end_" + aid)
        intervals.append(model.NewIntervalVar(t, duration, end, "resource_" + aid))
        unfinished = model.NewBoolVar("unfinished_" + aid)
        latest_complete = math.floor(horizon - a["exit_occupancy"] - 90)
        model.Add(t > latest_complete).OnlyEnforceIf(unfinished)
        model.Add(t <= latest_complete).OnlyEnforceIf(unfinished.Not())
        incomplete.append(unfinished)
    model.AddNoOverlap(intervals)
    # One fewer unfinished aircraft wins even against the largest possible
    # improvement in sum(slot times). Subtracting requested times is constant.
    primary_weight = len(aircraft) * SLOT_LIMIT_SECONDS + 1
    model.Minimize(primary_weight * sum(incomplete) + sum(times.values()))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVER_LIMIT_SECONDS
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = int(state["seed"])
    status = solver.Solve(model)
    feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    details = {"status": solver.StatusName(status), "optimal": status == cp_model.OPTIMAL,
               "optimal_scope": "Current released aircraft, fixed committed slots and announced synthetic resource constraints only",
               "time_limit_seconds": SOLVER_LIMIT_SECONDS, "workers": 1,
               "objective_order": ["unfinished_aircraft_at_horizon", "sum_landing_delay_seconds"],
               "unfinished_weight": primary_weight, "objective": solver.ObjectiveValue() if feasible else None,
               "best_bound": solver.BestObjectiveBound() if feasible else None}
    if not feasible:
        return None, details
    slots = [{"aircraft_id": a["id"], "runway": runways[a["id"]], "time": solver.Value(times[a["id"]])} for a in aircraft]
    details["unfinished_aircraft"] = sum(solver.Value(value) for value in incomplete)
    details["sum_landing_delay_seconds"] = sum(solver.Value(times[a["id"]]) - a["requested"] for a in aircraft)
    return slots, details


def propose(state, controller, horizon, order=None):
    """Propose a bound plan. No fallback or approval occurs inside this function."""
    if controller not in ("scripted", "deterministic", "ai"):
        raise ValueError("Unknown controller")
    if isinstance(horizon, bool) or not isinstance(horizon, (int, float)) or not math.isfinite(horizon):
        raise ValueError("A finite episode horizon is required")
    started = time.perf_counter()
    fixed, pending = _partition(state)
    result = _base_plan(state, controller)
    if controller == "deterministic":
        if order is not None:
            raise ValueError("Deterministic optimization does not accept an external ordering")
        slots, details = _deterministic(state, fixed, pending, horizon)
    else:
        if controller == "scripted":
            if order is not None:
                raise ValueError("Scripted FCFS ordering cannot be overridden")
            order = [a["id"] for a in sorted(pending, key=lambda a: (a["requested"], a["id"]))]
        slots = _ordered(state, fixed, pending, order)
        details = {"status": "FIXED_ORDER_FEASIBLE" if slots is not None else "INFEASIBLE",
                   "optimal": False, "optimal_scope": None,
                   "order": order, "objective_order": ["earliest_slots_for_the_supplied_order"]}
    result["solver"] = {**details, "wall_seconds": round(time.perf_counter() - started, 6)}
    if slots is not None:
        result.update(status="proposed", slots=slots)
    return result

"""Versioned synthetic route guidance. Observed lateral context is not clearance authority."""

import itertools
import math

from .geometry import geographic, heading, local

VERSION = "kinematic-arrival-flows-4"
SCENARIO = "early-august-arrival-flows-v1"
RECORDING = "arrival-flows-v1"
CATALOG = "sfo-arrival-context-v1"
# FAA AIP KSFO AD 2.12. Snapshot reference, not date-matched approach authorization.
RUNWAYS = {
    "28L": {
        "longitude": -(122 + 21 / 60 + 30.057 / 3600),
        "latitude": 37 + 36 / 60 + 42.163 / 3600,
        "bearing": 298.0,
        "elevation": 12.6,
    },
    "28R": {
        "longitude": -(122 + 21 / 60 + 25.708 / 3600),
        "latitude": 37 + 36 / 60 + 48.721 / 3600,
        "bearing": 298.0,
        "elevation": 13.0,
    },
}


def active(state):
    return state.get("simulator_version") == VERSION


def threshold(runway):
    r = RUNWAYS[runway]
    return local(r["longitude"], r["latitude"])


def final_point(distance, runway="28L"):
    x, y = threshold(runway)
    angle = math.radians(118)
    return [x + distance * math.sin(angle), y + distance * math.cos(angle)]


def cumulative(points):
    ds = [0.0]
    for a, b in itertools.pairwise(points):
        ds.append(ds[-1] + math.dist(a, b))
    return ds


def at(points, ds, distance):
    for i in range(1, len(ds)):
        if ds[i] >= distance:
            f = max(0, min(1, (distance - ds[i - 1]) / (ds[i] - ds[i - 1])))
            return [
                points[i - 1][j] + f * (points[i][j] - points[i - 1][j]) for j in (0, 1)
            ]
    return points[-1][:]


def initialize_aircraft(a, entry):
    if "route" not in entry:
        return
    a["route"] = entry["route"]
    a["route_progress_nm"] = entry.get("route_progress_nm", 0.0)
    a["remaining_route_nm"] = a["route"]["length_nm"] - a["route_progress_nm"]
    a["target_ias_kt"] = 190.0
    a["route_phase"] = "entry"
    a["nominal_finish_clock"] = (
        a["entry_clock"] + a["remaining_route_nm"] / 190 * 3600 + 75
    )


def project(a):
    route = a["route"]
    pts = route["points"]
    ds = route["distances_nm"]
    old = a["route_progress_nm"]
    candidates = []
    for i in range(1, len(pts)):
        if ds[i] < old - 1 or ds[i - 1] > old + 4:
            continue
        u, v = pts[i - 1], pts[i]
        dx, dy = v[0] - u[0], v[1] - u[1]
        f = max(
            0,
            min(
                1,
                ((a["x_nm"] - u[0]) * dx + (a["y_nm"] - u[1]) * dy)
                / (dx * dx + dy * dy),
            ),
        )
        p = [u[0] + dx * f, u[1] + dy * f]
        candidates.append(
            (math.dist(p, [a["x_nm"], a["y_nm"]]), ds[i - 1] + f * (ds[i] - ds[i - 1]))
        )
    error, progress = min(candidates)
    a["route_progress_nm"] = max(old, progress)
    a["remaining_route_nm"] = max(0, route["length_nm"] - a["route_progress_nm"])
    a["route_cross_track_nm"] = error
    return a["remaining_route_nm"]


def profile(remaining):
    # All heights/speeds are authored research profiles, not measured or published restrictions.
    altitude = min(18000, max(13, 13 + 318 * max(0, remaining - 0.15)))
    # A 6,000-ft level segment before descending onto the final approach.
    if 20 <= remaining <= 26:
        altitude = 6000
    speed = 190 if remaining > 25 else 170 if remaining > 12 else 145
    return altitude, speed


def move(a, state):
    from .dynamics import event

    if a["status"] not in ("approach", "go_around", "departure", "holding"):
        return False
    remaining = project(a)
    phase = (
        "entry"
        if remaining > 60
        else "descent"
        if remaining > 25
        else "merge"
        if remaining > 15
        else "final_intercept"
        if remaining > 10
        else "final_approach"
    )
    if phase != a["route_phase"]:
        a["route_phase"] = phase
        event(
            state,
            "route_phase_changed",
            aircraft_id=a["id"],
            route_id=a["route"]["id"],
            phase=phase,
            basis="synthetic",
        )
    lookahead = max(0.6, min(1.5, a["groundspeed_kt"] / 180))
    target = at(
        a["route"]["points"],
        a["route"]["distances_nm"],
        a["route_progress_nm"] + lookahead,
    )
    if remaining < 10:
        # Capture the assigned centerline smoothly; changing runway never moves current position.
        target = final_point(max(-0.3, remaining - lookahead - 0.3), a["runway"])
    dx, dy = target[0] - a["x_nm"], target[1] - a["y_nm"]
    desired = heading(dx, dy)
    wind = state["weather"]
    w = wind.get("wind_speed_kt", 0) or 0
    wr = math.radians(wind.get("wind_from_deg_true", 0) or 0)
    wx, wy = -w * math.sin(wr), -w * math.cos(wr)
    target_alt, target_speed = profile(remaining)
    if a.get("assigned_speed"):
        target_speed = a["target_ias_kt"]
    if a["status"] != "approach":
        desired = 298
        target_alt = max(4000, a["altitude_ft"])
        target_speed = 190
    # Wind correction aims ground track at the route; heading is explicitly true.
    desired = (
        heading(
            math.sin(math.radians(desired)) * a["tas_kt"] - wx,
            math.cos(math.radians(desired)) * a["tas_kt"] - wy,
        )
        if "tas_kt" in a
        else desired
    )
    turn = max(
        -3,
        min(
            3,
            math.degrees(
                9.80665
                * math.tan(math.radians(25))
                / max(70, a.get("tas_kt", 190) * 0.514444)
            ),
        ),
    )
    delta = (desired - a["heading_deg_true"] + 180) % 360 - 180
    a["heading_deg_true"] = (a["heading_deg_true"] + max(-turn, min(turn, delta))) % 360
    a["ias_kt"] += max(-1, min(1, target_speed - a["ias_kt"]))
    a["altitude_ft"] += max(-25, min(25, target_alt - a["altitude_ft"]))
    a["tas_kt"] = a["ias_kt"] * (1 + a["altitude_ft"] / 50000)
    angle = math.radians(a["heading_deg_true"])
    vx = a["tas_kt"] * math.sin(angle) + wx
    vy = a["tas_kt"] * math.cos(angle) + wy
    a["groundspeed_kt"] = math.hypot(vx, vy)
    a["track_deg_true"] = heading(vx, vy)
    a["x_nm"] += vx / 3600
    a["y_nm"] += vy / 3600
    remaining = project(a)
    if a["status"] == "approach" and remaining < 0.12 and a["altitude_ft"] <= 13.001:
        if (
            a["landing_authorized"]
            and state["runway_occupant"] is None
            and a["runway"] not in state["closed_runways"]
        ):
            a.update(status="taxi", surface_seconds=0, route_phase="runway_transition")
            state["runway_occupant"] = a["id"]
            state["last_runway_use"] = state["clock"]
            event(
                state,
                "touchdown_simulated",
                aircraft_id=a["id"],
                cause_ids=a.get("landing_cause_ids", []),
                decision_id=a.get("landing_decision_id"),
            )
        else:
            a.update(status="go_around", target_altitude_ft=4000)
            event(
                state,
                "synthetic_go_around",
                aircraft_id=a["id"],
                reason="Landing authority unavailable; synthetic runway-heading climb, published missed approach unresolved",
            )
    if (
        a["status"] in ("go_around", "departure")
        and math.hypot(a["x_nm"], a["y_nm"]) > 30
    ):
        a["status"] = "diverted"
        state["metrics"]["diverted"] += 1
    return True


def presentation(a, state):
    if "route" not in a or a["status"] in ("go_around", "diverted", "holding"):
        return None
    r = a["route"]
    preview = []
    for index in list(range(0, len(r["points"]), 4)) + [len(r["points"]) - 1]:
        point = r["points"][index]
        remaining = r["length_nm"] - r["distances_nm"][index]
        if a["runway"] != "28L" and remaining < 10:
            point = final_point(remaining - 0.3, a["runway"])
        preview.append(list(geographic(*point)))
    return {
        "id": r["id"],
        "version": CATALOG,
        "name": r["name"],
        "phase": a["route_phase"],
        "remaining_nm": round(a["remaining_route_nm"], 2),
        "progress_nm": round(a["route_progress_nm"], 2),
        "basis": "synthetic",
        "intended_merge_position": (
            state.get("planned_sequence", []).index(a["id"]) + 1
            if a["id"] in state.get("planned_sequence", [])
            else None
        ),
        "preview": preview,
        "merge": list(geographic(*final_point(15))),
    }


def eta(a, merge=False):
    remaining = a.get("remaining_route_nm", math.hypot(a["x_nm"], a["y_nm"]))
    end = 15 if merge else 0
    seconds = 0
    for d in range(math.ceil(end), math.ceil(remaining)):
        alt, speed = profile(d)
        if a.get("assigned_speed"):
            speed = a["target_ias_kt"]
        seconds += 3600 / (speed * (1 + alt / 50000))
    return seconds


def proposal(state):
    from .contracts import Clearance, ControllerProposal
    from .verification import verify_clearance

    # Physical arrival order is protected; a priority flag cannot make an aircraft overtake.
    active_aircraft = sorted(
        [a for a in state["aircraft"] if a["status"] == "approach"],
        key=lambda a: (eta(a), not a["emergency"], a["id"]),
    )
    sequence = [a["id"] for a in active_aircraft]
    pending = {
        c["aircraft_id"]
        for c in state["clearances"]
        if c["status"] in ("issued", "corrected")
    }
    commands = []
    explanation = "Merge order follows remaining route travel time, with existing landing commitments protected."
    weather = any(
        i["kind"] == "weather_restriction" and i["status"] == "active"
        for i in state["interventions"]
    )
    for a in active_aircraft:
        if a["id"] in pending:
            continue
        if (
            a.get("assigned_speed")
            and a["remaining_route_nm"] < 12
            and a["target_ias_kt"] != 145
        ):
            c = Clearance(aircraft_id=a["id"], kind="speed", value=145)
            if verify_clearance(state, c)["status"] == "pass":
                commands = [c]
                explanation = f"{a['callsign']}: reduce to 145 knots IAS for the synthetic stabilized final profile; landing authorization remains separate."
                break
        if (
            a["id"] in state.get("speed_restore", {})
            and not weather
            and a["remaining_route_nm"] > 12
        ):
            _, speed = profile(a["remaining_route_nm"])
            c = Clearance(aircraft_id=a["id"], kind="speed", value=speed)
            if verify_clearance(state, c)["status"] == "pass":
                commands = [c]
                explanation = f"Restriction recovered: {a['callsign']} resumes {speed} knots IAS on {a['route']['name']}; protected merge order retained."
                break
    if not commands and active_aircraft:
        a = active_aircraft[0]
        if a["id"] not in pending and not a["landing_authorized"] and eta(a) < 900:
            # Restrict late changes to already captured runway; no final side-step authority.
            runways = (a["runway"],) if a["remaining_route_nm"] < 15 else ("28L", "28R")
            for runway in runways:
                c = Clearance(aircraft_id=a["id"], kind="landing", target=runway)
                if verify_clearance(state, c)["status"] == "pass":
                    commands = [c]
                    explanation = f"{a['callsign']} is first in the feasible merge order via {a['route']['name']}; issue landing clearance for {runway}. Pilot acknowledgment is required; remaining route {a['remaining_route_nm']:.1f} NM."
                    break
    if not commands:
        for i, a in enumerate(active_aircraft):
            if (
                i == 0
                or a["id"] in pending
                or a["remaining_route_nm"] < 25
                or a.get("assigned_speed")
            ):
                continue
            leader = active_aircraft[i - 1]
            gap = eta(a) - eta(leader)
            if gap < 240 or weather:
                c = Clearance(aircraft_id=a["id"], kind="speed", value=170)
                if verify_clearance(state, c)["status"] == "pass":
                    commands = [c]
                    explanation = f"{a['callsign']}: maintain 170 knots IAS to preserve the merge behind {leader['callsign']} during {'the temporary runway restriction' if weather else 'converging traffic'}. Predicted gap {gap:.0f} seconds; synthetic 240-second scheduling target, independent motion checks required."
                    break
    if not commands:
        priority = next((a for a in active_aircraft if a["emergency"]), None)
        explanation += " " + (
            f"Priority requested for {priority['callsign']}; existing commitments and physical merge order must clear first."
            if priority
            else "Wait for pending acknowledgments or the protected runway commitment; no new landing authority issued."
        )
    return ControllerProposal(
        clearances=commands, sequence=sequence, explanation=explanation
    )


def configure_entry(entry, route):
    entry["route"] = route
    entry["route_progress_nm"] = 0
    entry["x_nm"], entry["y_nm"] = route["points"][0]
    next_point = route["points"][1]
    entry["track_deg_true"] = heading(
        next_point[0] - entry["x_nm"], next_point[1] - entry["y_nm"]
    )
    alt, speed = profile(route["length_nm"])
    entry["altitude_ft"] = alt
    entry["groundspeed_kt"] = speed * (1 + alt / 50000)
    entry["provenance"] = {
        **entry["provenance"],
        "generator": "routed-extra-1",
        "route_catalog": CATALOG,
        "assumptions": "Synthetic entry on observed-context route; reconstructed altitude and speed; subsequent unobserved demand delayed 240 seconds",
    }

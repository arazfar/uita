"""Presentation-only arrival cues. These heuristics grant no ATC authority."""

import math

from .geometry import heading, local


def cue(phase, clock, runway=None, basis="simulated", distance=None):
    return {
        "phase": phase,
        "basis": basis,
        "evidence_time": clock,
        "runway": runway,
        "distance_nm": distance,
    }


def historical_cue(points, index, clock):
    if index < 1:
        return None
    latest = points[index]
    if not 0 <= clock - latest["t"] <= 15 or latest.get("segment_id") is None:
        return None
    altitude, track = latest.get("altitude_ft"), latest.get("track_deg_true")
    if (
        altitude is None
        or track is None
        or not math.isfinite(track)
        or not 200 <= altitude <= 5000
    ):
        return None
    candidates = [
        point for point in points[:index]
        if 10 <= latest["t"] - point["t"] <= 60
        and point.get("segment_id") == latest["segment_id"]
        and point.get("altitude_ft") is not None
        and math.isfinite(point["altitude_ft"])
    ]
    if not candidates:
        return None
    previous = candidates[-1]
    x, y = local(latest["lon"], latest["lat"])
    distance = math.hypot(x, y)
    previous_distance = math.hypot(*local(previous["lon"], previous["lat"]))
    difference = abs((track - heading(-x, -y) + 180) % 360 - 180)
    if (
        distance > 8
        or distance >= previous_distance
        or previous["altitude_ft"] - altitude < 100
        or difference > 30
    ):
        return None
    return cue("approaching", latest["t"], basis="inferred", distance=distance)


def _distance(x, y, runway):
    from .dynamics import THRESHOLDS

    target = THRESHOLDS.get(runway)
    return math.hypot(x - target[0], y - target[1]) if target else None


def _latest_landing(clearances, aircraft_id):
    landings = [
        clearance for clearance in clearances
        if clearance["aircraft_id"] == aircraft_id and clearance["kind"] == "landing"
    ]
    return landings[-1] if landings else None


def _issued(clearance, clock):
    return (
        clearance is not None
        and clearance["status"] in ("issued", "corrected")
        and clearance.get("expires_at", clock) >= clock
    )


def simulation_cue(aircraft, state):
    clock, status = state["clock"], aircraft["status"]
    runway = aircraft.get("runway")
    distance = _distance(aircraft["x_nm"], aircraft["y_nm"], runway)
    if status == "taxi":
        return cue("on_ground", clock, runway)
    if status == "complete" and aircraft.get("surface_seconds", 0) >= 75:
        return cue("arrival_completed", clock, runway)
    if status != "approach":
        return None
    latest = _latest_landing(state.get("clearances", []), aircraft["id"])
    phase = "approaching"
    if runway not in state["closed_runways"]:
        if aircraft.get("landing_authorized") and (
            latest is None
            or latest["status"] in ("acknowledged", "executing", "completed")
        ):
            phase = "landing_authorized"
        elif _issued(latest, clock):
            phase = "clearance_issued"
    return cue(phase, clock, runway, distance=distance)


def recording_frame(original, events):
    """Enrich a copy; proposals alone never establish landing authority."""
    clock = original["clock"]
    visible = sorted(
        (event for event in events if event["clock"] <= clock),
        key=lambda event: event["sequence"],
    )
    clearances, completed = {}, set()
    for event in visible:
        payload, kind = event["payload"], event["kind"]
        clearance_id = payload.get("clearance_id")
        if kind == "clearance_issued":
            clearance = payload["clearance"]
            clearances[clearance["id"]] = dict(clearance)
        elif kind in ("clearance_cancelled", "clearance_expired"):
            if clearance_id in clearances:
                clearances[clearance_id]["status"] = "cancelled"
        elif kind == "pilot_acknowledged" and clearance_id in clearances:
            clearances[clearance_id]["status"] = "acknowledged"
        elif kind == "synthetic_go_around":
            for clearance in clearances.values():
                if clearance["aircraft_id"] == payload.get("aircraft_id"):
                    clearance["status"] = "cancelled"
        elif kind == "arrival_completed":
            completed.add(payload["aircraft_id"])

    aircraft = []
    for item in original["aircraft"]:
        value, runway = None, item.get("runway")
        if item["status"] == "taxi":
            value = cue("on_ground", clock, runway)
        elif item["id"] in completed:
            value = cue("arrival_completed", clock, runway)
        elif item["status"] == "approach":
            phase = "approaching"
            clearance = _latest_landing(clearances.values(), item["id"])
            if (
                clearance
                and clearance.get("target") == runway
                and runway not in original["closed_runways"]
            ):
                if clearance["status"] == "acknowledged":
                    phase = "landing_authorized"
                elif _issued(clearance, clock):
                    phase = "clearance_issued"
            x, y = local(item["longitude"], item["latitude"])
            value = cue(phase, clock, runway, distance=_distance(x, y, runway))
        aircraft.append({**item, "arrival_cue": item.get("arrival_cue") or value})
    return {**original, "aircraft": aircraft}

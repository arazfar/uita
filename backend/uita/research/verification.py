"""Independent predicates. Never imports the scheduler or accepts its feasibility flag."""

import math

from .contracts import VerificationReport
from .geometry import closest
from .standards import VERSION, rule


def check(identifier, status, message, **evidence):
    return {
        "rule": identifier,
        "status": status,
        "message": message,
        "source": rule(identifier)["source"],
        "paragraph": rule(identifier)["paragraph"],
        "classification": rule(identifier)["classification"],
        "evidence": evidence,
    }


def result(checks):
    status = (
        "fail"
        if any(c["status"] == "fail" for c in checks)
        else "unresolved"
        if any(c["status"] == "unresolved" for c in checks)
        else "pass"
    )
    return VerificationReport(
        status=status, checks=checks, rule_version=VERSION
    ).model_dump()


def verify_clearance(state, command):
    aircraft = next(
        (a for a in state["aircraft"] if a["id"] == command.aircraft_id), None
    )
    if aircraft is None or aircraft["status"] in ("complete", "diverted"):
        return result([check("runway", "fail", "Aircraft is not active")])
    a = aircraft
    checks = []
    if state["weather"].get("stale", True):
        checks.append(
            check("separation", "unresolved", "Current weather unavailable or stale")
        )
    if a.get("age_seconds", 999) > 15:
        checks.append(check("separation", "unresolved", "Aircraft observation stale"))
    k, value = command.kind, command.value
    distance = math.hypot(a["x_nm"], a["y_nm"])
    if k == "speed":
        valid = (
            value is not None
            and 130 <= value <= 250
            and value % 5 == 0
            and distance >= 5
            and a["status"] != "holding"
        )
        checks.append(
            check(
                "speed",
                "pass" if valid else "fail",
                "IAS instruction within supported research envelope and outside restricted final segment",
                distance_nm=distance,
                value=value,
            )
        )
    elif k in ("heading", "altitude", "direct", "approach"):
        # No default MVA, procedure authorization or magnetic conversion is invented.
        checks.append(
            check(
                "vectoring",
                "unresolved",
                "Published route / minimum-altitude / jurisdiction coverage not established for this command",
            )
        )
    elif k in ("landing", "takeoff"):
        valid = (
            command.target in ("28L", "28R")
            and command.target not in state["closed_runways"]
        )
        valid = valid and state["runway_occupant"] in (None, a["id"])
        valid = valid and (
            k == "landing"
            and a["status"] == "approach"
            or k == "takeoff"
            and a["status"] == "pending"
        )
        reservations = [
            c
            for c in state["clearances"]
            if c["kind"] in ("landing", "takeoff")
            and c["aircraft_id"] != a["id"]
            and c["status"] not in ("expired", "cancelled")
            and any(
                b["id"] == c["aircraft_id"]
                and b["status"] not in ("complete", "diverted")
                for b in state["aircraft"]
            )
        ]
        valid = (
            valid
            and not reservations
            and state["clock"] - state["last_runway_use"] >= 180
        )
        checks.append(
            check(
                "runway",
                "pass" if valid else "fail",
                "Conservative dependent runway authority and occupancy",
                runway=command.target,
                conflicts=[c["aircraft_id"] for c in reservations],
            )
        )
    elif k in ("hold", "go_around"):
        checks.append(
            check(
                "vectoring",
                "unresolved",
                "Synthetic contingency may be injected by the simulator but is not a published authorized clearance",
            )
        )
    elif k == "handoff":
        valid = (
            command.target in ("approach", "tower", "surface")
            and command.target != a["owner"]
        )
        checks.append(
            check(
                "readback",
                "pass" if valid else "fail",
                "Modeled ownership transfer requires acknowledgment",
                target=command.target,
            )
        )
    return result(checks)


def verify_motion(before, after):
    checks = []
    old = {a["id"]: a for a in before["aircraft"]}
    airborne = lambda a: a["status"] not in ("pending", "complete", "diverted", "taxi")
    # Include the complete landing/departure interval, including transitions to
    # surface or terminal states. Otherwise a touchdown could hide a conflict.
    active = [
        a
        for a in after["aircraft"]
        if airborne(a) or (a["id"] in old and airborne(old[a["id"]]))
    ]
    for a in active:
        p = old.get(a["id"], a)
        if a["status"] == "taxi" and p["status"] != "taxi":
            valid_landing = (
                a.get("landing_authorized")
                and a["runway"] not in after["closed_runways"]
                and before["runway_occupant"] in (None, a["id"])
                and after["runway_occupant"] == a["id"]
            )
            if not valid_landing:
                checks.append(
                    check(
                        "runway",
                        "fail",
                        "Unauthorized runway transition",
                        aircraft=a["id"],
                        runway=a["runway"],
                    )
                )
        valid = (
            all(math.isfinite(a[k]) for k in ("x_nm", "y_nm", "altitude_ft", "ias_kt"))
            and a["altitude_ft"] >= 0
            and 0 <= a["ias_kt"] <= 350
        )
        valid = valid and abs(a["altitude_ft"] - p["altitude_ft"]) <= 25.001
        if not valid:
            checks.append(
                check(
                    "vectoring",
                    "fail",
                    "Research performance envelope exceeded",
                    aircraft=a["id"],
                )
            )
    for i, a in enumerate(active):
        for b in active[i + 1 :]:
            approach = closest(old.get(a["id"], a), a, old.get(b["id"], b), b)
            if approach is None:
                continue
            lateral, vertical, fraction = approach
            if lateral < 5 - 1e-8:
                checks.append(
                    check(
                        "separation",
                        "fail",
                        "Continuous interval conflict; no altitude-floor exemption",
                        aircraft=[a["id"], b["id"]],
                        lateral_nm=lateral,
                        vertical_ft=vertical,
                        clock=before["clock"] + fraction,
                    )
                )
            same_stream = (
                abs((a["track_deg_true"] - b["track_deg_true"] + 180) % 360 - 180) < 15
            )
            if same_stream and lateral < 8 - 1e-8:
                checks.append(
                    check(
                        "wake",
                        "fail",
                        "Conservative unknown-category wake envelope",
                        aircraft=[a["id"], b["id"]],
                        lateral_nm=lateral,
                    )
                )
    if not checks:
        checks.append(
            check(
                "separation",
                "pass",
                "Implemented continuous-motion research checks passed",
                clock=after["clock"],
                aircraft_count=len(active),
            )
        )
    return result(checks)

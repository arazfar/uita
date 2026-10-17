"""Deterministic flight-leg reconstruction; transponders are not flight IDs."""

import copy
import math

from .data import digest
from .geometry import local

VERSION = "flight-leg-2"


def finite(value):
    return value is not None and math.isfinite(value)


def normalize_legs(rows):
    """Input must be ordered by transponder, UTC timestamp, then source hash.

    Gaps, identity changes, impossible jumps and a new airborne segment following
    two minutes on the ground split legs. Ambiguous segments remain inspectable.
    """
    points, prior, identity, ground_since = [], None, None, None
    seen = set()
    for raw in rows:
        identifier = (raw.get("icao24") or "").strip().lower()
        if not identifier or not finite(raw.get("lat")) or not finite(raw.get("lon")):
            continue
        if not (-90 <= raw["lat"] <= 90 and -180 <= raw["lon"] <= 180):
            continue
        if raw["t_utc"].tzinfo is None:
            raise ValueError("Observation timestamp lacks UTC offset")
        timestamp = raw["t_utc"].timestamp()
        x, y = local(raw["lon"], raw["lat"])
        row = {
            "t": timestamp,
            "lat": raw["lat"],
            "lon": raw["lon"],
            "x_nm": x,
            "y_nm": y,
            "altitude_ft": raw.get("alt_baro_ft"),
            "geometric_altitude_ft": raw.get("alt_geom_ft"),
            "groundspeed_kt": raw.get("gs_kt"),
            "track_deg_true": raw.get("track_deg"),
            "on_ground": raw.get("on_ground"),
            "callsign": (raw.get("callsign") or "").strip(),
            "registration": raw.get("registration"),
            "aircraft_type": raw.get("type_code"),
            "source_type": raw.get("source_type"),
            "quality_flags": [
                name
                for name, value in {
                    "stale": raw.get("flag_stale"),
                    "null_pressure_altitude": not finite(raw.get("alt_baro_ft")),
                    "null_motion": not finite(raw.get("gs_kt"))
                    or not finite(raw.get("track_deg")),
                }.items()
                if value
            ],
        }
        if identity != identifier:
            seen = set()
        fingerprint = digest(row)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        reason = None
        if prior is None or identity != identifier:
            reason = "transponder_boundary"
        else:
            dt = timestamp - prior["t"]
            if dt < 0:
                raise ValueError("Source observations are not chronologically ordered")
            distance = math.hypot(x - prior["x_nm"], y - prior["y_nm"])
            if dt > 1200:
                reason = "continuity_gap"
            elif raw.get("flag_new_leg"):
                reason = "source_leg_flag"
            elif any(
                row[k] and prior[k] and row[k] != prior[k]
                for k in ("callsign", "registration")
            ):
                reason = "identity_change"
            elif distance > max(1, dt * 700 / 3600):
                reason = "implausible_position_jump"
            elif (
                row["on_ground"] is False
                and ground_since is not None
                and timestamp - ground_since >= 120
            ):
                reason = "new_departure_after_ground_stop"
        if reason:
            if points:
                yield finish(identity, points)
            points = (
                [copy.deepcopy(prior)]
                if reason == "new_departure_after_ground_stop"
                else []
            )
            ground_since = None
            row["quality_flags"].append(reason)
        points.append(row)
        if row["on_ground"] is True:
            if ground_since is None:
                ground_since = timestamp
        else:
            ground_since = None
        prior, identity = row, identifier
    if points:
        yield finish(identity, points)


def finish(identity, points):
    grounded = [
        i
        for i, p in enumerate(points)
        if p["on_ground"] is True and math.hypot(p["x_nm"], p["y_nm"]) < 1.5
    ]
    airborne = [
        i
        for i, p in enumerate(points)
        if p["on_ground"] is False and math.hypot(p["x_nm"], p["y_nm"]) > 5
    ]
    operation = "unresolved"
    if grounded and airborne:
        if max(grounded) > min(airborne):
            operation = "arrival"
        elif min(grounded) < max(airborne):
            operation = "departure"
    identifier = (
        "late-leg-"
        + digest(
            [
                identity,
                points[0]["t"],
                points[0]["registration"],
                points[0]["lat"],
                points[0]["lon"],
                VERSION,
            ]
        )[:24]
    )
    return {
        "id": identifier,
        "icao24": identity,
        "operation": operation,
        "callsign": next((p["callsign"] for p in points if p["callsign"]), identity),
        "aircraft_type": next(
            (p["aircraft_type"] for p in points if p["aircraft_type"]), "unknown"
        ),
        "start": points[0]["t"],
        "end": points[-1]["t"],
        "points": points,
        "provenance": {
            "kind": "derived",
            "transform": VERSION,
            "source": "atc_sfo_w35.positions",
            "identity_evidence": [
                "transponder",
                "callsign",
                "registration",
                "time_continuity",
                "airport_ground_observations",
            ],
            "field_units": {
                "lat": "WGS84_degrees",
                "lon": "WGS84_degrees",
                "altitude_ft": "pressure_feet",
                "geometric_altitude_ft": "geometric_feet",
                "groundspeed_kt": "knots",
                "track_deg_true": "degrees_true",
                "t": "UTC_seconds",
            },
            "limitation": "Ground-proximity classification is evidence of association, not an operational clearance. Callsign and registration are not unique flight IDs.",
        },
    }

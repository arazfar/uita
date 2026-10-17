"""Immutable scenario artifacts, causal release and provenance-aware imports."""

import copy
import hashlib
import json
import math
from datetime import datetime, timezone

from .database import Artifact
from .geometry import local

TRANSFORM = "research-import-2"


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def save_artifact(db, identifier, kind, payload):
    checksum = digest(payload)
    existing = db.get(Artifact, identifier)
    if existing:
        if existing.checksum != checksum:
            raise ValueError("Immutable artifact already exists with different content")
        return existing
    row = Artifact(id=identifier, kind=kind, checksum=checksum, payload=payload)
    db.add(row)
    return row


def split(day):
    if "2026-08-03" <= day <= "2026-08-06" or day in ("2026-08-24", "2026-08-25"):
        return "train"
    if day in ("2026-08-07", "2026-08-26"):
        return "validation"
    if day in ("2026-08-08", "2026-08-09", "2026-08-29"):
        return "test"
    raise ValueError("Date is outside frozen dataset splits")


def causal_weather(reports, clock):
    eligible = [r for r in reports if r["available_at"] <= clock]
    if not eligible:
        return {"available": False, "stale": True}
    report = copy.deepcopy(max(eligible, key=lambda r: r["available_at"]))
    report["stale"] = clock - report["observed_at"] > 7200
    return report


def causal_forecasts(reports, clock):
    eligible = [
        r for r in reports if r["issued_at"] <= clock and r["valid_until"] > clock
    ]
    if not eligible:
        return []
    latest = max(r["issued_at"] for r in eligible)
    return [copy.deepcopy(r) for r in eligible if r["issued_at"] == latest]


def advisory_status(text):
    text = text.upper()
    for phrase, state in [
        ("CANCEL", "cancelled"),
        ("PROPOSED", "proposed"),
        ("REVISION", "amended"),
        ("AMEND", "amended"),
    ]:
        if phrase in text:
            return state
    return "active"


def clean_positions(rows):
    """Do not impute heights or merge sample data. A new leg follows a 20-minute gap."""
    last = {}
    seen = set()
    for raw in rows:
        row = dict(raw)
        identity = str(row.get("icao24") or "").strip().lower()
        t = (
            row["t_utc"].timestamp()
            if isinstance(row["t_utc"], datetime)
            else float(row["t_utc"])
        )
        coords = [row.get("lat"), row.get("lon")]
        if not identity or any(v is None or not math.isfinite(v) for v in coords):
            continue
        if not -90 <= coords[0] <= 90 or not -180 <= coords[1] <= 180:
            continue
        key = (identity, t, *coords)
        if key in seen:
            continue
        seen.add(key)
        previous = last.get(identity)
        new_leg = (
            previous is None
            or t - previous["t"] > 1200
            or bool(row.get("flag_new_leg"))
        )
        leg_id = digest([identity, t])[:24] if new_leg else previous["leg_id"]
        x, y = local(row["lon"], row["lat"])
        last[identity] = {"t": t, "leg_id": leg_id}
        row.update(
            leg_id=leg_id,
            t_utc=t,
            x_nm=x,
            y_nm=y,
            near_sfo=math.hypot(x, y) <= 3,
            provenance={
                "kind": "observed",
                "transform": TRANSFORM,
                "altitude_reference": "barometric_ft",
                "source": row.get("source_type"),
            },
        )
        yield row


def frozen_fixture():
    """Deterministic offline smoke scenario; never presented as historical data."""
    start = datetime(2026, 8, 6, 22, tzinfo=timezone.utc).timestamp()
    entries = []
    for i in range(8):
        entries.append(
            {
                "id": f"fixture-{i}",
                "callsign": f"UAL{410 + i}",
                "aircraft_type": "A320",
                "spawn_time": start + i * 210,
                "x_nm": 18.0,
                "y_nm": -9.0,
                "altitude_ft": 6000.0,
                "groundspeed_kt": 210.0,
                "track_deg_true": 297.0,
                "operation": "arrival",
                "provenance": {
                    "kind": "synthetic",
                    "generator": "fixture-2",
                    "seed": 42,
                    "assumptions": "Illustrative demand and performance",
                },
            }
        )
    return {
        "id": "fixture-august-v2",
        "dataset_id": "fixture-v2",
        "split": "train",
        "start": start,
        "end": start + 3600,
        "entries": entries,
        "weather": [
            {
                "observed_at": start,
                "available_at": start,
                "visibility_sm": 10.0,
                "ceiling_ft": 6000.0,
                "wind_from_deg_true": 280.0,
                "wind_speed_kt": 8.0,
            }
        ],
        "provenance": {
            "kind": "synthetic",
            "source": "Credential-free research fixture",
        },
        "coverage": {"entries": len(entries), "observed": 0},
    }


def metered_variant(source):
    """Explicit hypothetical admission experiment; never changes recorded evidence.

    Identity and demand order come from a development episode. Initial geometry,
    heights and four-minute metering are authored research assumptions, not
    reconstructed controller actions or calibrated SFO capacity.
    """
    scenario = copy.deepcopy(source)
    scenario["id"] = source["id"] + "-metered"
    previous = source["start"] - 240
    for entry in scenario["entries"]:
        entry["original_demand_time"] = entry["spawn_time"]
        entry["spawn_time"] = max(source["start"], entry["spawn_time"], previous + 240)
        previous = entry["spawn_time"]
        entry.update(
            x_nm=18.0,
            y_nm=-9.0,
            altitude_ft=6000.0,
            groundspeed_kt=210.0,
            track_deg_true=297.0,
        )
        entry["provenance"] = {
            "kind": "synthetic",
            "generator": "metered-terminal-2",
            "source_scenario": source["id"],
            "assumptions": "Authored initial corridor and 240-second admission spacing; identity and demand order retained",
        }
    scenario["end"] = max(source["end"], previous + 1200)
    scenario["coverage"] = {"entries": len(scenario["entries"]), "observed": 0}
    scenario["provenance"] = {
        "kind": "synthetic",
        "source_scenario": source["id"],
        "source_hash": digest(source),
        "limitations": [
            "Not a historical reconstruction",
            "Metering changes admission times; delays are reported",
            "No measured airport capacity claim",
        ],
    }
    return scenario

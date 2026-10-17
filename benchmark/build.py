"""Build disjoint, causal, observed-entry encounters without exposing test dates."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import random

import duckdb

from .core import DATA_DIR, RULES, VERSION, canonical, model_messages, validate_input

ROOT = Path(__file__).resolve().parents[1]
DAYS = {"train": [f"2026-08-{d:02}" for d in range(3, 7)], "validation": ["2026-08-07"]}
CENTER = (-122.3754167, 37.6188056)
QUERY = """
SELECT e.flight_id, e.spawn_time, e.position, e.groundspeed_kt, e.track_deg_true,
       e.altitude_provenance, e.aircraft_type, CAST(e.local_date AS VARCHAR) AS local_date,
       e.split, a.t AS operation_time
FROM entries e JOIN arrivals a ON e.flight_id = a.id
WHERE e.local_date BETWEEN DATE '2026-08-03' AND DATE '2026-08-07'
  AND a.local_date BETWEEN DATE '2026-08-03' AND DATE '2026-08-07'
  AND e.position_provenance = 'observed'
ORDER BY e.local_date, e.spawn_time, e.flight_id
"""
# Simplified categories only. This is not a complete FAA wake classification table.
HEAVY_TYPES = {"A332", "A333", "A338", "A339", "A342", "A343", "A345", "A346", "A359", "A35K",
               "A388", "B744", "B748", "B742", "B743", "B772", "B773", "B77L", "B77W", "B788", "B789", "B78X", "B763", "B764", "MD11"}


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def geometry(position):
    lon1, lat1 = map(math.radians, CENTER)
    lon2, lat2 = map(math.radians, (position["lon"], position["lat"]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    distance = 3440.065 * 2 * math.asin(min(1, math.sqrt(h)))
    # Bearing from airport to last-known observed position.
    bearing = math.degrees(math.atan2(math.sin(dlon) * math.cos(lat2), math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon))) % 360
    return distance, bearing


def create_case(group):
    snapshot = max(r["spawn_time"] for r in group)
    if any(r["operation_time"] <= snapshot for r in group):
        return None, "already_operated_at_snapshot"
    if len({r["operation_time"] for r in group}) != len(group):
        return None, "tied_recorded_operation_time"
    identities = sorted(r["flight_id"] for r in group)
    encounter_hash = sha_bytes(canonical({"version": VERSION, "members": identities}).encode())
    rng = random.Random(int(encounter_hash[:16], 16))
    shuffled = list(group)
    rng.shuffle(shuffled)
    alias_to_source = {f"A{i+1}": r["flight_id"] for i, r in enumerate(shuffled)}
    source_to_alias = {v: k for k, v in alias_to_source.items()}
    aircraft = []
    for r in shuffled:
        distance, bearing = geometry(r["position"])
        age = snapshot - r["spawn_time"]
        aircraft.append({"id": source_to_alias[r["flight_id"]], "distance_nm": round(distance, 5),
                         "bearing_deg_true": round(bearing, 5),
                         "altitude_ft": r["position"]["altitude_ft"] if r["altitude_provenance"] == "beacon_reported" else None,
                         "groundspeed_kt": r["groundspeed_kt"], "track_deg_true": r["track_deg_true"],
                         "wake_category": "heavy" if r["aircraft_type"] in HEAVY_TYPES else "medium",
                         "free_flow_seconds": round(max(0, distance / r["groundspeed_kt"] * 3600 - age), 5),
                         "position_source": "observed_entry", "altitude_source": "beacon_reported" if r["altitude_provenance"] == "beacon_reported" else "unknown", "age_seconds": age})
    rng.shuffle(aircraft)
    state = {"task": "sequence_arrivals_v1", "runway": {"resource": "shared_arrival_runway", "available_in_seconds": 0},
             "rules": dict(RULES), "aircraft": aircraft}
    try:
        validate_input(state)
    except ValueError:
        return None, "feature_bounds"
    case = {"case_id": "seq-" + encounter_hash[:20], "encounter_id": "enc-" + encounter_hash[:20],
            "split": group[0]["split"], "local_date": group[0]["local_date"], "input": state,
            "private": {"historical_order": [source_to_alias[r["flight_id"]] for r in sorted(group, key=lambda r: r["operation_time"])],
                        "alias_to_source": alias_to_source, "source_flight_ids": identities,
                        "source_entry_times": {source_to_alias[r["flight_id"]]: r["spawn_time"] for r in group},
                        "snapshot_time": snapshot, "source_position_stratum": "observed_only"}}
    model_messages(case)
    return case, None


def build(database, output):
    with duckdb.connect(str(database), read_only=True) as connection:
        result = connection.sql(QUERY)
        columns = result.columns
        rows = result.fetchall()
    source = [dict(zip(columns, row)) for row in rows]
    for row in source:
        expected = "train" if row["local_date"] in DAYS["train"] else "validation"
        if row["split"] != expected:
            raise ValueError("Source split disagrees with fixed permitted dates")
    cases = {"train": [], "validation": []}
    counts = Counter()
    # Group only by causal entry availability, never by future recorded order.
    # Pairs maximize independent encounters in this small observed-only source.
    for day in DAYS["train"] + DAYS["validation"]:
        candidates = [r for r in source if r["local_date"] == day]
        i = 0
        while i < len(candidates):
            first = candidates[i]
            if i + 1 == len(candidates) or candidates[i + 1]["spawn_time"] - first["spawn_time"] > 300:
                counts["unpaired_or_stale_entry"] += 1
                i += 1
                continue
            group = candidates[i:i+2]
            i += 2
            case, reason = create_case(group)
            if reason:
                counts[reason] += 1
            else:
                cases[case["split"]].append(case)
    output.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    for split, values in cases.items():
        payload = "".join(canonical(case) + "\n" for case in values).encode()
        (output / f"{split}.jsonl").write_bytes(payload)
        artifacts[f"{split}.jsonl"] = {"sha256": sha_bytes(payload), "bytes": len(payload), "cases": len(values),
                                        "independent_encounters": len(values), "aircraft": sum(len(c["input"]["aircraft"]) for c in values),
                                        "per_day": dict(Counter(c["local_date"] for c in values))}
    manifest = {"benchmark_version": VERSION, "primary_task": "historical_recorded_operation_order_prediction",
                "primary_target_provenance": "recorded_operation_order_not_authentic_ATC_commands",
                "source_database": str(database.relative_to(ROOT)) if database.is_relative_to(ROOT) else str(database),
                "source_query": QUERY.strip(), "source_rows_sha256": sha_bytes(canonical(source).encode()),
                "source_observed_entry_rows": len(source), "split_dates": DAYS,
                "test_policy": "August 8–9 sealed; no scenario/outcome rows queried or evaluated",
                "grouping": "non-overlapping pairs in entry-time order; max entry age 300 seconds; historical completion and tied timestamps screened",
                "aliases": "SHA256-seeded shuffle independent of operation timestamp; candidate list shuffled separately",
                "features": "last-known observed entry positions, not interpolated current positions; only beacon heights retained, all inferred heights null",
                "free_flow": "max(0, great-circle distance/observed groundspeed*3600-observation_age)",
                "excluded": dict(counts), "artifacts": artifacts,
                "frozen_code": {name: sha_bytes((Path(__file__).parent / name).read_bytes()) for name in ("core.py", "build.py")},
                "limits": ["Pairs are a narrow ordering task, not full ATC.", "Aircraft do not repeat between encounters.",
                           "Encounter independence does not create independent traffic days.", "No authentic human controller decisions or measured human safety/delay scores.",
                           "Input snapshots include only first usable observed entry, with age up to 300 seconds.",
                           "Known past arrivals screen inactive members; operation order after snapshot supplies labels only.",
                           "Secondary scheduling metrics use synthetic direct-to-airport dynamics and simplified wake spacing."]}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "pipeline/build/sfo.duckdb")
    parser.add_argument("--output", type=Path, default=DATA_DIR)
    args = parser.parse_args()
    manifest = build(args.database.resolve(), args.output.resolve())
    print(json.dumps({"cases": {k: v["cases"] for k, v in manifest["artifacts"].items()}, "excluded": manifest["excluded"]}, indent=2))


if __name__ == "__main__":
    main()

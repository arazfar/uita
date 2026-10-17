"""Independent, per-example audit of candidate causality and roster-order labels.

This is a mechanical review report, not approval. A separate agent must inspect
this code, all-row findings and samples, then write per-example review decisions.
Only date-filtered source SQL is used; held-out source payloads are not loaded.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from pathlib import Path

from .core import DATA_DIR, model_messages, parse_action
from .training import ALLOWED_DATES, DEFAULT_OUTPUT, PROVENANCE, ROOT, digest, file_digest, read_rows, write_json

CENTER = (-122.3754167, 37.6188056)
HEAVY_TYPES = {"A332", "A333", "A338", "A339", "A342", "A343", "A345", "A346", "A359", "A35K",
               "A388", "B744", "B748", "B742", "B743", "B772", "B773", "B77L", "B77W", "B788",
               "B789", "B78X", "B763", "B764", "MD11"}
SOURCE_QUERY = """
SELECT e.flight_id, e.spawn_time, e.position, e.groundspeed_kt, e.track_deg_true,
       e.position_provenance, e.altitude_provenance, e.motion_provenance,
       a.t AS operation_time, CAST(a.local_date AS VARCHAR) AS local_date, a.split, a.type
FROM entries e JOIN arrivals a ON a.id = e.flight_id
WHERE a.local_date BETWEEN ? AND ? AND e.local_date BETWEEN ? AND ?
  AND a.split IN ('train', 'validation') AND e.split IN ('train', 'validation')
"""


def source_rows(database):
    import duckdb
    connection = duckdb.connect(str(database), read_only=True)
    try:
        cursor = connection.execute(SOURCE_QUERY, ["2026-08-03", "2026-08-07"] * 2)
        names = [description[0] for description in cursor.description]
        result = [dict(zip(names, row)) for row in cursor.fetchall()]
    finally:
        connection.close()
    return {row["flight_id"]: row for row in result}


def distance_bearing(lon, lat):
    lon1, lat1, lon2, lat2 = map(math.radians, (*CENTER, lon, lat))
    half_chord = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    distance = 2 * 3440.065 * math.asin(min(1, math.sqrt(half_chord)))
    bearing = math.degrees(math.atan2(math.sin(lon2 - lon1) * math.cos(lat2),
                                   math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1))) % 360
    return distance, bearing


def close(left, right, tolerance=0.0001):
    return (not isinstance(left, bool) and isinstance(left, (int, float)) and math.isfinite(left)
            and abs(left - right) <= tolerance)


def independent_public_schema(state):
    # An allowlist rejects future fields, dates, source identities and hidden labels.
    if set(state) != {"task", "runway", "rules", "aircraft"} or state["task"] != "sequence_arrivals_v1":
        return False
    if state["runway"] != {"resource": "shared_arrival_runway", "available_in_seconds": 0}:
        return False
    if state["rules"] != {"medium_leader_spacing_seconds": 90, "heavy_leader_spacing_seconds": 150,
                          "completion_horizon_seconds": 3600, "unfinished_penalty_seconds": 3600}:
        return False
    if not isinstance(state["aircraft"], list) or not 2 <= len(state["aircraft"]) <= 6:
        return False
    expected_fields = {"id", "distance_nm", "bearing_deg_true", "altitude_ft", "groundspeed_kt", "track_deg_true",
                       "wake_category", "free_flow_seconds", "position_source", "altitude_source", "age_seconds"}
    expected_ids = {f"A{i+1}" for i in range(len(state["aircraft"]))}
    if {a.get("id") for a in state["aircraft"]} != expected_ids:
        return False
    for aircraft in state["aircraft"]:
        if set(aircraft) != expected_fields or aircraft["position_source"] != "observed_entry":
            return False
        if aircraft["altitude_source"] not in ("beacon_reported", "unknown"):
            return False
        if aircraft["altitude_source"] == "unknown" and aircraft["altitude_ft"] is not None:
            return False
        for key in expected_fields - {"id", "wake_category", "position_source", "altitude_source"}:
            value = aircraft[key]
            if key == "altitude_ft" and aircraft["altitude_source"] == "unknown" and value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                return False
        if aircraft["wake_category"] not in ("medium", "heavy"):
            return False
        if not 0 <= aircraft["age_seconds"] <= 300:
            return False
    return True


def audit_case(row, case, sources):
    state = case["input"]
    private = case["private"]
    checks = {}
    checks["candidate_source_hash"] = row["source_case_sha256"] == digest(case)
    checks["historical_proxy_provenance"] = row["target_provenance"] == PROVENANCE
    checks["allowed_historical_split"] = (row["split"] == case["split"] and row["local_date"] == case["local_date"]
                                            and row["local_date"] in ALLOWED_DATES.get(row["split"], set()))
    checks["public_schema_has_no_outcomes_or_identifiers"] = independent_public_schema(state)
    messages = row["messages"]
    checks["exact_baseline_prompt_and_input"] = (len(messages) == 3 and messages[:2] == model_messages(case)
                                                and messages[2].get("role") == "assistant")
    action = parse_action(messages[2]["content"], state)
    checks["target_is_complete_exact_permutation"] = True
    checks["state_and_target_hashes"] = row["state_sha256"] == digest(state) and row["target_sha256"] == digest(action)
    aliases = private["alias_to_source"]
    snapshot = private["snapshot_time"]
    expected_ids = {a["id"] for a in state["aircraft"]}
    checks["private_alias_mapping_complete"] = set(aliases) == expected_ids and len(set(aliases.values())) == len(aliases)
    matched = {alias: sources.get(source_id) for alias, source_id in aliases.items()}
    checks["source_rows_found_on_allowed_dates"] = all(matched.values())
    if not checks["source_rows_found_on_allowed_dates"]:
        return checks, "Missing permitted source row; cannot validate causal features or target."
    checks["source_split_matches"] = all(source["local_date"] == row["local_date"] and source["split"] == row["split"]
                                        for source in matched.values())
    checks["causal_observed_entries_only"] = all(source["position_provenance"] == "observed"
                                                 and source["spawn_time"] <= snapshot < source["operation_time"]
                                                 and 0 <= snapshot - source["spawn_time"] <= 300
                                                 for source in matched.values())
    checks["snapshot_is_latest_observation"] = close(snapshot, max(source["spawn_time"] for source in matched.values()), 0.001)
    checks["operation_time_labels_unambiguous"] = len({source["operation_time"] for source in matched.values()}) == len(matched)
    source_order = sorted(matched, key=lambda alias: (matched[alias]["operation_time"], aliases[alias]))
    checks["independently_reconstructed_roster_target"] = action["order"] == source_order == private["historical_order"]
    feature_checks = []
    unknown_altitudes = 0
    for aircraft in state["aircraft"]:
        source = matched[aircraft["id"]]
        position = source["position"]
        distance, bearing = distance_bearing(position["lon"], position["lat"])
        age = snapshot - source["spawn_time"]
        free_flow = max(0, distance / source["groundspeed_kt"] * 3600 - age)
        actual_altitude = source["altitude_provenance"] == "beacon_reported"
        altitude_matches = (close(aircraft["altitude_ft"], position["altitude_ft"]) if actual_altitude
                            else aircraft["altitude_ft"] is None)
        altitude_source = "beacon_reported" if actual_altitude else "unknown"
        feature_checks.append(all((close(aircraft["distance_nm"], distance), close(aircraft["bearing_deg_true"], bearing),
                                   close(aircraft["groundspeed_kt"], source["groundspeed_kt"]),
                                   close(aircraft["track_deg_true"], source["track_deg_true"]),
                                   altitude_matches,
                                   close(aircraft["age_seconds"], age), close(aircraft["free_flow_seconds"], free_flow),
                                   aircraft["altitude_source"] == altitude_source,
                                   aircraft["wake_category"] == ("heavy" if source["type"] in HEAVY_TYPES else "medium"))))
        unknown_altitudes += not actual_altitude
    checks["features_recomputed_from_past_observation"] = all(feature_checks)
    checks["private_source_entry_times_match"] = private.get("source_entry_times") == {alias: source["spawn_time"] for alias, source in matched.items()}
    reason = (f"{len(matched)} distinct observed-position aircraft; all observations precede the snapshot; "
              f"roster times independently confirm target {','.join(source_order)}. "
              f"Unknown altitudes are null: {unknown_altitudes}. Recorded order is a proxy, not an ATC command label.")
    return checks, reason


def audit(candidate_path, data_dir, database, output_path):
    # Loading only these two exact files cannot traverse final-test files.
    cases = {}
    for split in ALLOWED_DATES:
        for case in read_rows(data_dir / f"{split}.jsonl"):
            if case["case_id"] in cases:
                raise ValueError("Duplicate case IDs")
            cases[case["case_id"]] = case
    sources = source_rows(database)
    rows = read_rows(candidate_path)
    results = []
    seen_ids, seen_encounters, seen_states, seen_sources = set(), set(), set(), set()
    for row in rows:
        try:
            case = cases[row["case_id"]]
            checks, reason = audit_case(row, case, sources)
            source_ids = set(case["private"]["alias_to_source"].values())
            checks["unique_candidate_id"] = row["example_id"] not in seen_ids
            checks["one_example_per_encounter"] = row["encounter_id"] == case["encounter_id"] and row["encounter_id"] not in seen_encounters
            checks["unique_state"] = row["state_sha256"] not in seen_states
            checks["source_aircraft_disjoint_across_examples"] = not bool(source_ids & seen_sources)
            seen_ids.add(row["example_id"])
            seen_encounters.add(row["encounter_id"])
            seen_states.add(row["state_sha256"])
            seen_sources |= source_ids
            result = {"example_id": row["example_id"], "candidate_sha256": digest(row), "case_id": row["case_id"],
                      "split": row["split"], "checks": checks, "status": "pass" if all(checks.values()) else "fail",
                      "reason": reason, "failed_checks": [name for name, passed in checks.items() if not passed]}
        except (KeyError, ValueError, TypeError, ZeroDivisionError) as error:
            result = {"example_id": row.get("example_id"), "candidate_sha256": digest(row), "checks": {},
                      "status": "fail", "reason": f"Audit exception: {type(error).__name__}: {error}",
                      "failed_checks": ["audit_completeness"]}
        results.append(result)
    report = {
        "schema_version": "historical_order_independent_audit_v1",
        "audit_kind": "mechanical_independent_source_and_causality_check; not reviewer approval",
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "candidate_file_sha256": file_digest(candidate_path),
        "audit_code_sha256": file_digest(Path(__file__)),
        "source_query": SOURCE_QUERY.strip(), "source_query_parameters": ["2026-08-03", "2026-08-07"] * 2,
        "source_case_files_sha256": {split: file_digest(data_dir / f"{split}.jsonl") for split in ALLOWED_DATES},
        "counts": {"examples": len(results), "pass": sum(row["status"] == "pass" for row in results),
                   "fail": sum(row["status"] != "pass" for row in results)},
        "examples": results,
        "limitations": ["No qualified human controller reviewed these labels.",
                        "Review validates observed roster-order provenance; it does not establish optimal control actions.",
                        "Missing observed altitude is null; no synthetic altitude enters model inputs.",
                        "Final test dates are absent from source SQL and input file access."],
    }
    write_json(output_path, report)
    return report["counts"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_OUTPUT / "candidates.jsonl")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--source-database", type=Path, default=ROOT / "pipeline/build/sfo.duckdb")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT / "audit.json")
    args = parser.parse_args()
    print(json.dumps(audit(args.candidates, args.data_dir, args.source_database, args.output), sort_keys=True))


if __name__ == "__main__":
    main()

"""Archive six verified validation artifacts in the existing Railway store.

Usage: python -m benchmark.closed_loop.archive --results <report-directory>
The default prepares and validates bytes locally. Only --execute writes to the
database. Raw decisions, API logs, frozen code and other splits are not uploaded.
"""
from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import hashlib
import json
import math
from pathlib import Path

from .traffic import validate_episode

ROOT = Path(__file__).resolve().parents[2]
DATASET_ID = "sfo-historical-closed-loop-validation-2026-08-07-v1"
CONTROLLERS = {"scripted", "deterministic", "ai"}
SAFETY_COUNTS = ("separation_violation_episodes", "runway_violation_episodes",
                 "surface_violation_episodes", "wake_violations", "performance_violations")
OUTCOME_FIELDS = {"episode_id", "seed", "variant", "spawned", "landed", "completed", "backlog",
                  "added_delay_seconds_sum", "mean_added_delay_seconds_all_demand", "p95_added_delay_seconds_all_demand",
                  "penalized_added_delay_seconds", "delay_metric", "airborne_holding_seconds", "safety", "executed_violations",
                  "controller_failures", "fallback_decisions", "rejected_proposals", "unresolved_decisions", "safety_eligible",
                  "decision_count", "flights", "rank", "controller"}
FLIGHT_FIELDS = {"id", "source_flight_id", "position_provenance", "known_since_seconds", "nominal_landing_seconds",
                 "landing_seconds", "landed", "completed", "nominal_due_before_horizon", "added_delay_seconds",
                 "uncontrolled_feeder_and_queue_scope"}
PLAN_FIELDS = {"version", "split", "episodes", "controllers", "config", "source_hashes", "traffic_sha256",
               "traffic_manifest_sha256", "inference_cap_usd", "model", "final_test", "runtime"}
SUMMARY_FIELDS = {"status", "plan_sha256", "split", "controllers", "paired_reference", "paired",
                  "ai_usage", "source_hashes", "artifacts", "limits"}
SUMMARY_EXECUTION_FIELDS = {"execution", "elapsed_wall_seconds"}


def no_raw_records(value):
    """Reject internal request/response records even inside otherwise valid metadata."""
    if isinstance(value, dict):
        for key, item in value.items():
            require(key.lower() not in {"authorization", "api_key", "access_token", "secret", "messages",
                                        "raw_request", "raw_response", "request", "response"},
                    "Raw API or credential field is outside the archive contract")
            require(key != "decisions" or not isinstance(item, (dict, list)), "Internal decision lists are excluded")
            no_raw_records(item)
    elif isinstance(value, list):
        for item in value:
            no_raw_records(item)


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def encode(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def close(left, right, label):
    require(type(left) in (int, float) and math.isfinite(left) and abs(left - right) <= .002,
            "Outcome metric differs from flight evidence: " + label)


def prepare(results):
    """Read only the validation pack and the selected completed report files."""
    results = Path(results)
    data_dir = Path(__file__).with_name("data")
    traffic_bytes = (data_dir / "validation.json").read_bytes()
    traffic_manifest_bytes = (data_dir / "manifest.json").read_bytes()
    plan_bytes = (results / "plan.json").read_bytes()
    summary_bytes = (results / "summary.json").read_bytes()
    runs_bytes = (results / "runs.json").read_bytes()
    verification_bytes = (results / "verification.json").read_bytes()
    traffic, traffic_manifest = json.loads(traffic_bytes), json.loads(traffic_manifest_bytes)
    plan, summary, runs = json.loads(plan_bytes), json.loads(summary_bytes), json.loads(runs_bytes)
    verification = json.loads(verification_bytes)
    require(set(plan) == PLAN_FIELDS and SUMMARY_FIELDS <= set(summary)
            and set(summary) <= SUMMARY_FIELDS | SUMMARY_EXECUTION_FIELDS,
            "Unknown protocol or summary field")
    require(bool(set(summary) & SUMMARY_EXECUTION_FIELDS), "Missing execution provenance")
    if "execution" in summary:
        execution = summary["execution"]
        require(set(execution) == {"independent_episode_workers", "worker_sha256", "unused_partial_audit_records"}
                and execution["independent_episode_workers"] is True
                and isinstance(execution["worker_sha256"], str) and len(execution["worker_sha256"]) == 64
                and type(execution["unused_partial_audit_records"]) is int and execution["unused_partial_audit_records"] >= 0,
                "Unknown independent-worker execution metadata")
    if "elapsed_wall_seconds" in summary:
        elapsed = summary["elapsed_wall_seconds"]
        require(type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0, "Invalid wall runtime")
    for value in (plan, summary, verification):
        no_raw_records(value)
    require(verification.get("passed") is True, "Report verification must pass before archiving")
    attested = verification.get("artifacts", {})
    require(all(attested.get(name) == digest(payload) for name, payload in (
                ("plan.json", plan_bytes), ("runs.json", runs_bytes), ("summary.json", summary_bytes))),
            "Final report verification must attest exact plan, runs and summary bytes")
    require(plan.get("split") == summary.get("split") == "validation" and summary.get("status") == "completed",
            "Archive requires a completed validation comparison")
    require(set(plan.get("controllers", [])) == CONTROLLERS and len(plan["controllers"]) == 3
            and set(summary.get("controllers", {})) == CONTROLLERS,
            "Archive requires all three distinct controllers")
    require(digest(traffic_bytes) == plan.get("traffic_sha256")
            == traffic_manifest["artifacts"]["validation.json"]["sha256"], "Validation traffic checksum differs")
    require(digest(traffic_manifest_bytes) == plan.get("traffic_manifest_sha256"), "Traffic manifest checksum differs")
    require(digest(plan_bytes) == summary.get("plan_sha256") == summary["artifacts"]["plan.json"],
            "Summary does not bind the supplied protocol")
    require(digest(runs_bytes) == summary["artifacts"]["runs.json"], "Summary does not bind the supplied outcomes")
    require(summary.get("source_hashes") == plan.get("source_hashes") and bool(plan.get("source_hashes")),
            "Summary and protocol source hashes differ")
    config = plan["config"]
    expected_bounds = {"decision_interval_seconds": 300, "approach_seconds": 360,
                       "feeder_speed_min_kt": 140, "feeder_speed_max_kt": 280,
                       "occupancy_min_seconds": 45, "occupancy_max_seconds": 140,
                       "reservation_extra_seconds": 240, "unfinished_penalty_seconds": 3600}
    require(all(config.get(key) == value for key, value in expected_bounds.items()), "Protocol bounds differ from archive version v1")
    require(config.get("seeds") == [17] and config.get("scenario_variants") == ["nominal"],
            "Archive version v1 requires seed 17 and nominal conditions")
    require(plan.get("version") == config.get("version") == "historical-admission-loop-v1",
            "Unknown closed-loop protocol version")
    require(isinstance(config.get("safety_scope"), str) and "upstream" in config["safety_scope"].lower()
            and isinstance(config.get("computation_time"), str), "Missing safety or computation-time scope")
    require(len(traffic) == 6, "Expected six complete August 7 windows")
    episodes = {}
    source_ids = set()
    for episode in traffic:
        validate_episode(episode, "validation")
        require(episode["local_date"] == "2026-08-07" and episode["id"] not in episodes,
                "Unknown date or duplicate validation episode")
        require(episode["start"] - episode["warmup_start"] == 900
                and episode["end"] - episode["start"] == 1800
                and episode["drain_end"] - episode["end"] == 1800,
                "Validation window durations differ from the frozen protocol")
        ids = {entry["flight_id"] for entry in episode["entries"]}
        require(not ids & source_ids, "A historical arrival repeats across validation windows")
        source_ids |= ids
        episodes[episode["id"]] = episode
    require(len(source_ids) == 136 and set(plan["episodes"]) == set(episodes) and len(plan["episodes"]) == 6,
            "Protocol must cover all 136 validation spawns in all six windows")
    require(len(runs) == 18, "Expected eighteen controller/episode outcomes")
    seen = set()
    compact = []
    for row in runs:
        require(set(row) == OUTCOME_FIELDS | {"decisions"}, "Unknown outcome field; raw internal data must not be archived")
        key = (row.get("controller"), row.get("episode_id"))
        require(key[0] in CONTROLLERS and key[1] in episodes and key not in seen,
                "Unknown or duplicate controller/episode outcome")
        seen.add(key)
        episode = episodes[key[1]]
        require(row.get("seed") == 17 and row.get("variant") == "nominal", "Outcome protocol differs")
        require(row.get("airborne_holding_seconds") is None, "Admission waiting must not be relabeled measured airborne holding")
        safety = row.get("safety", {})
        require(set(safety) == set(SAFETY_COUNTS) | {"checked_segment_pairs", "minimum_lateral_nm_when_vertical_under_1000_ft", "findings", "scope"},
                "Unknown executed safety field")
        require(set(safety["findings"]) == {"separation", "runway", "surface", "wake", "performance"},
                "Unknown executed safety finding")
        for name in ("separation", "runway", "surface", "wake"):
            fields = {"aircraft", "gap_seconds" if name == "wake" else "interval"}
            require(all(set(finding) == fields for finding in safety["findings"][name]),
                    "Unexpected internal fields in executed safety findings")
        require(isinstance(row.get("decisions"), list) and row.get("decision_count") == len(row["decisions"]),
                "Outcome decision counts disagree")
        require(row["controller_failures"] == sum(bool(d["controller_failure"]) for d in row["decisions"])
                and row["fallback_decisions"] == sum(bool(d["fallback_used"]) for d in row["decisions"])
                and row["unresolved_decisions"] == sum(d["applied_status"] != "pass" for d in row["decisions"]),
                "Outcome failure/fallback counts disagree with retained local decision evidence")
        entries = {entry["flight_id"]: entry for entry in episode["entries"]}
        flights = row["flights"]
        require(len(flights) == len(entries) == row["spawned"]
                and {flight["source_flight_id"] for flight in flights} == set(entries),
                "Controller did not receive every historical source spawn exactly once")
        require(len({f["id"] for f in flights}) == len(flights), "Repeated local aircraft alias")
        horizon = episode["drain_end"] - episode["warmup_start"]
        for flight in flights:
            require(set(flight) == FLIGHT_FIELDS, "Unknown per-flight outcome field")
            entry = entries[flight["source_flight_id"]]
            require(flight["position_provenance"] == entry["position_provenance"], "Outcome source stratum changed")
            close(flight["known_since_seconds"], entry["spawn_time"] - episode["warmup_start"], "source release")
            require(type(flight["landed"]) is bool and type(flight["completed"]) is bool
                    and (not flight["completed"] or flight["landed"]), "Invalid landed/completed state")
            nominal = flight["nominal_landing_seconds"]
            require(type(nominal) in (int, float) and math.isfinite(nominal) and nominal >= flight["known_since_seconds"],
                    "Nominal arrival precedes source release")
            lon0, lat0 = config["source_center_lon_lat"]
            x = (entry["position"]["lon"] - lon0) * 60 * math.cos(math.radians(lat0))
            y = (entry["position"]["lat"] - lat0) * 60
            px, py = config["synthetic_approach_entry_nm"]
            speed = max(config["feeder_speed_min_kt"], min(config["feeder_speed_max_kt"], entry["groundspeed_kt"]))
            expected_nominal = flight["known_since_seconds"] + math.hypot(x - px, y - py) / speed * 3600 + config["approach_seconds"]
            close(nominal, expected_nominal, "bounded source feeder and fixed approach")
            token = hashlib.sha256(f"17:{entry['flight_id']}".encode()).digest()
            occupancy = config["occupancy_min_seconds"] + int.from_bytes(token[:4], "big") % 96
            require(type(flight["nominal_due_before_horizon"]) is bool
                    and flight["nominal_due_before_horizon"] == (nominal + occupancy + 90 <= horizon)
                    and flight["uncontrolled_feeder_and_queue_scope"] is True,
                    "Nominal due or uncontrolled feeder/queue scope differs")
            if flight["landed"]:
                landing = flight["landing_seconds"]
                require(type(landing) in (int, float) and math.isfinite(landing) and nominal <= landing <= horizon,
                        "Actual landing lies outside causal release or evaluation horizon")
                expected_delay = max(0, landing - nominal)
                require(flight["completed"] == (landing + occupancy + 90 <= horizon),
                        "Completion differs from fixed runway occupancy and taxi bounds")
            else:
                require(flight["landing_seconds"] is None, "Unlanded flight has an actual landing event")
                expected_delay = max(0, horizon - nominal)
            close(flight["added_delay_seconds"], round(expected_delay, 3), "censored admission delay")
        completed, landed = sum(f["completed"] for f in flights), sum(f["landed"] for f in flights)
        require(completed == row["completed"] and landed == row["landed"]
                and len(flights) - completed == row["backlog"], "Completion counts disagree")
        close(row["added_delay_seconds_sum"], round(sum(f["added_delay_seconds"] for f in flights), 3), "episode total")
        close(row["penalized_added_delay_seconds"], round(row["added_delay_seconds_sum"] + row["backlog"] * 3600, 3), "backlog penalty")
        require(sum(row["safety"][name] for name in SAFETY_COUNTS) == row["executed_violations"],
                "Executed safety counts disagree")
        # These are all task outcomes and aggregate counters. The one large
        # decision list contains internal proposals; it stays local with API logs.
        compact.append({key: row[key] for key in sorted(OUTCOME_FIELDS)})
        no_raw_records(compact[-1])
    for controller in CONTROLLERS:
        rows = [row for row in runs if row["controller"] == controller]
        total = summary["controllers"][controller]
        require(len(rows) == total["episodes"] == 6 and total["spawned"] == 136,
                "Aggregate comparison is incomplete")
        for name in ("spawned", "landed", "completed", "backlog", "executed_violations", "controller_failures",
                     "fallback_decisions", "rejected_proposals", "unresolved_decisions"):
            require(sum(row[name] for row in rows) == total[name], "Aggregate counter differs: " + name)
        close(total["added_delay_seconds_sum"], round(sum(row["added_delay_seconds_sum"] for row in rows), 3), "controller total")
    files = {"validation-traffic.json": traffic_bytes, "protocol.json": plan_bytes,
             "results.json": summary_bytes, "outcomes.json": encode(compact), "verification.json": verification_bytes}
    manifest = {"schema_version": 1, "id": DATASET_ID, "kind": "historical_demand_closed_loop_validation",
                "local_date": "2026-08-07", "episodes": 6, "source_spawns_per_controller": 136,
                "controller_episode_outcomes": 18, "controller_flight_outcomes": 408,
                "controllers": plan["controllers"], "model": plan.get("model"),
                "protocol_version": plan["version"], "traffic_sha256": digest(traffic_bytes),
                "original_runs_sha256": digest(runs_bytes), "source_hashes": plan["source_hashes"],
                "protocol_bounds": expected_bounds, "seed": 17, "variant": "nominal",
                "position_strata": dict(Counter(entry["position_provenance"] for e in traffic for entry in e["entries"])),
                "safety_scope": config["safety_scope"], "computation_time": config["computation_time"],
                "held_out": "August 8–9 remain sealed; no final-test artifacts are read or uploaded",
                "excluded": ["development/training payloads", "raw API logs", "internal decision lists", "frozen source files", "final-test payloads"],
                "files": {name: {"sha256": digest(data), "bytes": len(data)} for name, data in sorted(files.items())}}
    files["manifest.json"] = encode(manifest)
    return manifest, files


def upload(manifest, files, results):
    # Lazy imports keep local planning usable without a database driver or key.
    from psycopg.types.json import Jsonb
    from pipeline.uita_data.store import connect

    with connect() as db:
        db.execute("INSERT INTO uita_data.datasets(id,manifest) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                   (DATASET_ID, Jsonb(manifest)))
        stored = db.execute("SELECT manifest FROM uita_data.datasets WHERE id=%s FOR UPDATE", (DATASET_ID,)).fetchone()
        require(stored and stored[0] == manifest, "Frozen Railway dataset already has a different manifest; bump the dataset version")
        for name, payload in files.items():
            db.execute("INSERT INTO uita_data.artifacts(dataset_id,name,sha256,payload) VALUES (%s,%s,%s,%b) ON CONFLICT DO NOTHING",
                       (DATASET_ID, name, digest(payload), payload))
        rows = db.execute("SELECT name,sha256,encode(sha256(payload),'hex'),octet_length(payload) FROM uita_data.artifacts WHERE dataset_id=%s",
                          (DATASET_ID,)).fetchall()
        require(len(rows) == len(files) and {row[0] for row in rows} == set(files), "Railway artifact set differs")
        for name, expected, server_hash, size in rows:
            require(expected == server_hash == digest(files[name]) and size == len(files[name]), "Railway server checksum or size differs: " + name)
    # A new committed read verifies actual download bytes, not just stored hash
    # columns. No DDL or other dataset/table writes occur in either transaction.
    with connect() as db, db.cursor(binary=True) as cursor:
        cursor.execute("SELECT name,sha256,payload FROM uita_data.artifacts WHERE dataset_id=%s", (DATASET_ID,))
        rows = cursor.fetchall()
    require(len(rows) == len(files) and {row[0] for row in rows} == set(files), "Railway round-trip artifact set differs")
    for name, checksum, payload in rows:
        downloaded = bytes(payload)
        require(downloaded == files[name] and digest(downloaded) == checksum, "Railway round-trip bytes differ: " + name)
    report = {"passed": True, "dataset_id": DATASET_ID, "artifacts": len(files),
              "bytes": sum(len(payload) for payload in files.values()), "artifact_names": sorted(files),
              "episodes": 6, "controllers": 3, "source_spawns_per_controller": 136,
              "controller_flight_outcomes": 408, "all_server_checksums_verified": True,
              "all_downloaded_bytes_verified": True, "contains_final_test_data": False,
              "verified_at_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
    (Path(results) / "railway-verification.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    manifest, files = prepare(args.results)
    result = upload(manifest, files, args.results) if args.execute else {
        "status": "plan_only; no database connection or mutation", "dataset_id": DATASET_ID,
        "artifacts": len(files), "bytes": sum(len(payload) for payload in files.values()),
        "artifact_names": sorted(files), "episodes": 6, "controllers": 3, "source_spawns_per_controller": 136,
        "controller_flight_outcomes": 408, "position_strata": manifest["position_strata"]}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

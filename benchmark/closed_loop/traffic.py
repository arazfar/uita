"""Freeze trusted historical spawn queues without reading recorded arrival outcomes.

Only the runner may inspect an entire episode. Pass causally released spawns and
the latest available weather to controllers; never pass a future queue or pack.
The runner reconstructs subsequent motion instead of replaying historical paths.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA_DIR = Path(__file__).resolve().parent / "data"
VERSION = "historical-closed-loop-traffic-v1"
SOURCE_DATASET = "sfo-2026-08-03_09-v1"
DAYS = {"train": [f"2026-08-{n:02}" for n in range(3, 7)], "validation": ["2026-08-07"]}
CUTOFF = datetime.fromisoformat("2026-08-08T00:00:00-07:00").timestamp()
ENTRY_FIELDS = ("flight_id", "callsign", "aircraft_type", "origin", "spawn_time", "position",
                "groundspeed_kt", "track_deg_true", "position_provenance", "altitude_provenance", "motion_provenance")
WEATHER_FIELDS = ("id", "observed_at", "available_at", "availability_assumption", "wind_direction_deg_true",
                  "wind_speed_kt", "wind_gust_kt", "visibility_sm", "altimeter_inhg", "temperature_f",
                  "cloud_layers", "metar", "source")
EPISODE_QUERY = """
SELECT id, split, CAST(local_date AS VARCHAR) AS local_date,
       warmup_start, start, "end", drain_end, flight_ids
FROM episodes
WHERE local_date BETWEEN DATE '2026-08-03' AND DATE '2026-08-07'
  AND split IN ('train', 'validation')
ORDER BY local_date, start, id
"""
ENTRY_QUERY = """
SELECT flight_id, callsign, aircraft_type, origin, spawn_time, position,
       groundspeed_kt, track_deg_true, position_provenance, altitude_provenance,
       motion_provenance
FROM entries
WHERE local_date BETWEEN DATE '2026-08-03' AND DATE '2026-08-07'
  AND split IN ('train', 'validation')
ORDER BY spawn_time, flight_id
"""
WEATHER_QUERY = """
SELECT id, observed_at, available_at, availability_assumption, wind_direction_deg_true,
       wind_speed_kt, wind_gust_kt, visibility_sm, altimeter_inhg, temperature_f,
       cloud_layers, metar, source
FROM weather
WHERE available_at >= ? AND available_at < ? AND observed_at < ?
ORDER BY available_at, id
"""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def _rows(connection, query, params=None):
    result = connection.execute(query, params or [])
    columns = [column[0] for column in result.description]
    return [dict(zip(columns, row)) for row in result.fetchall()]


def _finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Invalid finite numeric field: {label}")


def validate_episode(episode, split):
    expected = {"id", "split", "local_date", "warmup_start", "start", "end", "drain_end", "entries", "weather"}
    if set(episode) != expected or split not in DAYS or episode["split"] != split or episode["local_date"] not in DAYS[split]:
        raise ValueError("Unknown episode fields, split or permitted local date")
    for key in ("warmup_start", "start", "end", "drain_end"):
        _finite(episode[key], key)
    if not episode["warmup_start"] < episode["start"] < episode["end"] < episode["drain_end"] < CUTOFF:
        raise ValueError("Episode clock boundary is invalid or crosses the held-out cutoff")
    seen = set()
    previous_spawn = float("-inf")
    for entry in episode["entries"]:
        if set(entry) != set(ENTRY_FIELDS):
            raise ValueError("Entry contains an outcome, provenance donor or unknown field")
        if entry["flight_id"] in seen:
            raise ValueError("Duplicate source flight within episode")
        seen.add(entry["flight_id"])
        _finite(entry["spawn_time"], "spawn_time")
        if not episode["warmup_start"] <= entry["spawn_time"] < episode["end"] or entry["spawn_time"] < previous_spawn:
            raise ValueError("Spawn is outside the episode queue or not monotonic")
        previous_spawn = entry["spawn_time"]
        if entry["position_provenance"] not in ("observed", "synthetic_training_template"):
            raise ValueError("Unknown observed/synthetic position stratum")
        if set(entry["position"]) != {"lon", "lat", "altitude_ft"}:
            raise ValueError("Unexpected initial-position field")
        for key, value in entry["position"].items():
            _finite(value, key)
        for key in ("groundspeed_kt", "track_deg_true"):
            _finite(entry[key], key)
    previous_available = float("-inf")
    for report in episode["weather"]:
        if set(report) != set(WEATHER_FIELDS):
            raise ValueError("Unexpected weather field")
        for key in ("observed_at", "available_at"):
            _finite(report[key], key)
        if not report["observed_at"] <= report["available_at"] <= episode["drain_end"] or report["available_at"] < previous_available:
            raise ValueError("Weather ordering or availability is invalid")
        previous_available = report["available_at"]
        if report["available_at"] >= CUTOFF or report["observed_at"] >= CUTOFF:
            raise ValueError("Weather crosses final-date cutoff")
    return episode


def available_weather(episode, clock):
    """Return only a report available at this clock, never future episode weather."""
    _finite(clock, "clock")
    reports = [report for report in episode["weather"] if report["available_at"] <= clock]
    return json.loads(canonical(reports[-1])) if reports else None


def build(database=REPO / "pipeline/build/sfo.duckdb", output=DATA_DIR):
    # DuckDB is needed only to build. Frozen JSON loading has no dependencies.
    import duckdb

    database, output = Path(database).resolve(), Path(output).resolve()
    with duckdb.connect(str(database), read_only=True) as connection:
        episodes = _rows(connection, EPISODE_QUERY)
        entries = _rows(connection, ENTRY_QUERY)
        earliest = min(episode["warmup_start"] for episode in episodes)
        # One day of pre-roll ensures a prior causal report without reading
        # final-date observations. Episodes select only their latest prior report.
        weather = _rows(connection, WEATHER_QUERY, [earliest - 86400, CUTOFF, CUTOFF])
    by_id = {entry["flight_id"]: entry for entry in entries}
    if len(by_id) != len(entries):
        raise ValueError("Source entry identifiers are not unique")
    packs = {"train": [], "validation": []}
    seen_flights = set()
    for source in episodes:
        split = source["split"]
        queue = []
        if len(set(source["flight_ids"])) != len(source["flight_ids"]):
            raise ValueError("Source episode has repeated flight IDs")
        for flight_id in source["flight_ids"]:
            if flight_id not in by_id:
                raise ValueError("Episode queue references an entry outside permitted source dates")
            entry = by_id[flight_id]
            if not source["warmup_start"] <= entry["spawn_time"] < source["end"]:
                raise ValueError("Source episode queue contains an out-of-range spawn")
            if flight_id in seen_flights:
                raise ValueError("A source arrival operation repeats across episode windows")
            seen_flights.add(flight_id)
            queue.append(entry)
        queue.sort(key=lambda entry: (entry["spawn_time"], entry["flight_id"]))
        prior = [report for report in weather if report["available_at"] <= source["warmup_start"]]
        during = [report for report in weather if source["warmup_start"] < report["available_at"] <= source["drain_end"]]
        pack = {key: source[key] for key in ("id", "split", "local_date", "warmup_start", "start", "end", "drain_end")}
        pack.update(entries=queue, weather=prior[-1:] + during)
        validate_episode(pack, split)
        packs[split].append(pack)
    if len(packs["train"]) != 24 or len(packs["validation"]) != 6:
        raise ValueError("Expected exactly 24 development and 6 validation windows")
    output.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    for split, pack in packs.items():
        payload = (canonical(pack) + "\n").encode()
        (output / f"{split}.json").write_bytes(payload)
        strata = Counter(entry["position_provenance"] for episode in pack for entry in episode["entries"])
        artifacts[f"{split}.json"] = {"sha256": digest(payload), "bytes": len(payload), "episodes": len(pack),
                                       "source_arrival_operations": sum(len(episode["entries"]) for episode in pack),
                                       "position_strata": dict(strata),
                                       "per_day": dict(Counter(episode["local_date"] for episode in pack))}
    manifest = {"traffic_version": VERSION, "source_dataset_id": SOURCE_DATASET,
                "source_database": str(database.relative_to(REPO)) if database.is_relative_to(REPO) else str(database),
                "split_dates": DAYS, "source_queries": {"episodes": EPISODE_QUERY.strip(), "entries": ENTRY_QUERY.strip(), "weather": WEATHER_QUERY.strip()},
                "weather_query_parameters": [earliest - 86400, CUTOFF, CUTOFF],
                "selected_source_hashes": {"episodes": digest(canonical(episodes).encode()), "entries": digest(canonical(entries).encode()), "weather": digest(canonical(weather).encode())},
                "artifacts": artifacts, "loader_sha256": digest(Path(__file__).read_bytes()),
                "privacy": "Trusted runner only. Entries and weather are future queues; release them causally. Never send whole episode objects to a controller.",
                "outcomes": "No arrivals table or recorded operation times, assigned runways, future paths or template donor identities were read or exported.",
                "held_out": "August 8–9 source scenario files and episode/outcome rows remain unqueried; weather observed/available cutoff is August 8 local midnight exclusive.",
                "motion": "Only initial states seed the runner. Subsequent motion must be reconstructed and controlled; historical paths are not replayed.",
                "strata": "Observed entries and synthetic_training_template entries remain labeled. Synthetic entry timing can derive from historical operation times upstream; do not call them observed.",
                "source_identity": "flight_id identifies a recorded arrival operation, not a unique physical airframe."}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def load_episodes(split, directory=DATA_DIR):
    """Load only a frozen permitted split. This returns runner-private queues."""
    if split not in DAYS:
        raise ValueError("Only train and validation are available; final August 8–9 dates remain sealed")
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest["traffic_version"] != VERSION or manifest["source_dataset_id"] != SOURCE_DATASET or manifest["split_dates"] != DAYS:
        raise ValueError("Frozen traffic manifest version or date bounds changed")
    payload = (directory / f"{split}.json").read_bytes()
    artifact = manifest["artifacts"][f"{split}.json"]
    if digest(payload) != artifact["sha256"]:
        raise ValueError("Frozen traffic artifact checksum mismatch")
    episodes = json.loads(payload)
    if len(episodes) != artifact["episodes"]:
        raise ValueError("Frozen traffic episode count mismatch")
    ids = set()
    for episode in episodes:
        validate_episode(episode, split)
        if episode["id"] in ids:
            raise ValueError("Repeated episode ID")
        ids.add(episode["id"])
    return episodes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=REPO / "pipeline/build/sfo.duckdb")
    parser.add_argument("--output", type=Path, default=DATA_DIR)
    args = parser.parse_args()
    manifest = build(args.database, args.output)
    print(json.dumps({"traffic_version": VERSION, "artifacts": manifest["artifacts"],
                      "manifest_sha256": digest((args.output / "manifest.json").read_bytes())}, indent=2))


if __name__ == "__main__":
    main()

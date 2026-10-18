"""Freeze late-August historical demand; complete queues stay runner-private.

Only date-matched recorded operations provide demand. Missing initial states use
the unchanged August 3–6 training templates, with explicit synthetic provenance.
No August 8–9 operation, scenario or path rows are selected.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import datetime as dt
import hashlib
import io
import json
import math
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from benchmark.closed_loop.traffic import ENTRY_FIELDS, WEATHER_FIELDS, available_weather

REPO = Path(__file__).resolve().parents[2]
DATA_DIR = Path(__file__).resolve().parent / "data"
CACHE = REPO / "pipeline/.cache/sweep-2026-08-24_30"
VERSION = "historical-closed-loop-sweep-traffic-v1"
SOURCE_DATASET = "sfo-historical-demand-2026-08-24_30-v1"
DATES = tuple(f"2026-08-{day:02}" for day in range(24, 31))
DAYS = {"evaluation": list(DATES)}
TZ = ZoneInfo("America/Los_Angeles")
PARQUET = REPO / "pipeline/.cache/sfomuseum-data-flights-2026-08.parquet"
TEMPLATES = REPO / "pipeline/build/templates.json"
DATASF_URL = "https://data.sf.gov/resource/43zc-xw3x.json"
PARQUET_URL = "https://static.sfomuseum.org/parquet/sfomuseum-data-flights-2026-08.parquet"
WEATHER_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
DATASF_QUERY = {
    "$select": "operation_no,flight_date_time,runway_name,aircraft_type,airline,other_port,flight_no,tail_number,airport_code",
    "$group": "operation_no,flight_date_time,runway_name,aircraft_type,airline,other_port,flight_no,tail_number,airport_code",
    "$where": "operation_type='A' AND airport_code='SFO' AND flight_date_time >= '2026-08-24T00:00:00' AND flight_date_time < '2026-08-31T00:00:00'",
    "$order": "flight_date_time,operation_no", "$limit": 50000,
}
WEATHER_QUERY = [
    ("station", "SFO"), ("data", "all"), ("year1", 2026), ("month1", 8), ("day1", 23),
    ("year2", 2026), ("month2", 9), ("day2", 1), ("tz", "Etc/UTC"),
    ("format", "onlycomma"), ("latlon", "yes"), ("elev", "yes"), ("missing", "M"),
    ("trace", "T"), ("direct", "no"), ("report_type", "3"), ("report_type", "4"),
]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def file_info(path):
    payload = Path(path).read_bytes()
    return {"file": str(Path(path).relative_to(REPO)), "sha256": digest(payload), "bytes": len(payload)}


def _fetch(name, url, params):
    import requests
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / name
    if not path.exists():
        response = requests.get(url, params=params, timeout=120,
                                headers={"User-Agent": "UpInTheAir/1.0 historical research"})
        response.raise_for_status()
        temporary = path.with_suffix(".part")
        temporary.write_bytes(response.content)
        temporary.replace(path)
    return path


def _roster():
    path = _fetch("datasf-arrivals.json", DATASF_URL, DATASF_QUERY)
    rows = json.loads(path.read_text())
    if not isinstance(rows, list) or not rows or len(rows) >= DATASF_QUERY["$limit"]:
        raise ValueError("DataSF roster is empty, malformed or potentially truncated")
    flights, dropped = [], Counter()
    for row in rows:
        local = dt.datetime.fromisoformat(row["flight_date_time"]).replace(tzinfo=TZ)
        if local.date().isoformat() not in DATES:
            raise ValueError("DataSF returned a source operation outside requested dates")
        if not re.fullmatch(r"(?:0?1|10|19|28)[LR]", row.get("runway_name", "")):
            dropped["non_named_runway"] += 1
            continue
        flights.append({"id": "a" + row["operation_no"], "operation_id": row["operation_no"],
                        "t": local.timestamp(), "local_date": local.date().isoformat(),
                        "callsign": row.get("flight_no", ""), "type": row.get("aircraft_type", ""),
                        "port": row.get("other_port", ""), "registration": row.get("tail_number", "")})
    flights.sort(key=lambda item: (item["t"], item["id"]))
    if len({flight["id"] for flight in flights}) != len(flights):
        raise ValueError("DataSF operation_no repeats")
    if set(flight["local_date"] for flight in flights) != set(DATES):
        raise ValueError("DataSF demand is missing at least one requested day")
    return flights, rows, {**file_info(path), "url": DATASF_URL, "query": DATASF_QUERY,
                           "rows": len(rows), "eligible_arrivals": len(flights), "dropped": dict(dropped)}


def _observed_entries(flights):
    import pyarrow.parquet as pq
    from pipeline.extract_departures import decode_linestring, nm
    from pipeline.uita_data.build import normalize_track, entry_for

    if not PARQUET.exists():
        raise ValueError(f"Required cached monthly GeoParquet is missing: {PARQUET}")
    # The main records carry flight dates; alternate geometries do not. Select
    # permitted metadata first, then only those IDs' path variants.
    filters = [("flysfo:date", ">=", dt.date(2026, 8, 24)),
               ("flysfo:date", "<=", dt.date(2026, 8, 30)), ("flysfo:event", "=", "A")]
    metadata = pq.read_table(PARQUET, columns=["wof:id", "flysfo:date", "sfomuseum:flight_number", "swim:tail_number"],
                             filters=filters).to_pylist()
    by_id = {row["wof:id"]: row for row in metadata}
    paths = pq.read_table(PARQUET,
                          columns=["wof:id", "geometry", "swim:timestamps", "swim:altitudes", "swim:speeds"],
                          filters=[("wof:id", "in", list(by_id)), ("src:alt_label", "=", "swim-path")]).to_pylist()
    eligible, counts = [], Counter()
    lo = dt.datetime(2026, 8, 24, tzinfo=TZ).timestamp() - 1200
    hi = dt.datetime(2026, 8, 31, tzinfo=TZ).timestamp() + 1200
    for row in paths:
        times, alts, speeds = row["swim:timestamps"], row["swim:altitudes"], row["swim:speeds"]
        points = decode_linestring(row["geometry"])
        if not times or not lo <= times[-1] < hi or points is None or len(points) != len(times) or len(times) != len(alts or []) or len(times) != len(speeds or []):
            counts["malformed_or_out_of_time"] += 1
            continue
        if any(b <= a for a, b in zip(times, times[1:])) or nm(points[-1][1], points[-1][0]) > 5:
            counts["non_arrival_or_nonmonotonic"] += 1
            continue
        retained = [[times[index], round(point[0], 7), round(point[1], 7), alts[index], speeds[index]]
                    for index, point in enumerate(points) if nm(point[1], point[0]) <= 80]
        if len(retained) < 2:
            counts["short_path"] += 1
            continue
        meta = by_id[row["wof:id"]]
        eligible.append({"wof": row["wof:id"], "aliases": set(meta["sfomuseum:flight_number"] or []),
                         "registration": meta["swim:tail_number"], "last_ts": times[-1], "points": retained})
    # Match arrival endpoints, never departure starts. Pairing is one-to-one.
    candidates = []
    for pi, path in enumerate(eligible):
        for fi, flight in enumerate(flights):
            delta = flight["t"] - path["last_ts"]
            if abs(delta) > 1200:
                continue
            both = bool(flight["registration"] and path["registration"])
            if both and flight["registration"] != path["registration"]:
                continue
            callsign = bool(flight["callsign"] and flight["callsign"] in path["aliases"])
            if callsign or both:
                method = "callsign_registration_time" if callsign and both else "callsign_time" if callsign else "registration_time"
                candidates.append((0 if callsign and both else 1 if callsign else 2, abs(delta), fi, pi, method))
    used_flights, used_paths, entries, matches = set(), set(), {}, []
    for _, _, fi, pi, method in sorted(candidates):
        if fi in used_flights or pi in used_paths:
            continue
        used_flights.add(fi)
        used_paths.add(pi)
        flight, path = flights[fi], eligible[pi]
        track = normalize_track({"operation_id": flight["operation_id"], "museum_wof_id": path["wof"],
                                 "match_method": method, "points": path["points"]}, counts)
        entry = entry_for(flight, track)
        if entry:
            entries[flight["id"]] = entry
            matches.append({"source_flight_id": flight["id"], "museum_wof_id": path["wof"], "method": method})
    return entries, {**file_info(PARQUET), "url": PARQUET_URL,
                     "metadata_predicates": [[a, b, str(c)] for a, b, c in filters],
                     "selected_metadata_records": len(metadata), "selected_path_variants": len(paths),
                     "usable_paths": len(eligible), "observed_initial_states": len(entries),
                     "match_sha256": digest(canonical(matches).encode()), "quality_counts": dict(counts)}


def _weather():
    from pipeline.uita_data.references import number
    path = _fetch("ksfo-metar-through-2026-08-31.csv", WEATHER_URL, WEATHER_QUERY)
    text = "\n".join(line for line in path.read_text().splitlines() if not line.startswith("#"))
    reports = []
    for row in csv.DictReader(io.StringIO(text)):
        observed = dt.datetime.fromisoformat(row["valid"]).replace(tzinfo=dt.timezone.utc).timestamp()
        reports.append({"id": f"KSFO-{int(observed)}", "observed_at": observed, "available_at": observed + 300,
                        "availability_assumption": "observation timestamp plus 300 seconds; actual receipt time unavailable",
                        "wind_direction_deg_true": number(row.get("drct")), "wind_speed_kt": number(row.get("sknt")),
                        "wind_gust_kt": number(row.get("gust")), "visibility_sm": number(row.get("vsby")),
                        "altimeter_inhg": number(row.get("alti")), "temperature_f": number(row.get("tmpf")),
                        "cloud_layers": [{"cover": row.get(f"skyc{i}"), "base_ft_agl": number(row.get(f"skyl{i}"))}
                                         for i in range(1, 5) if row.get(f"skyc{i}") not in (None, "M", "")],
                        "metar": row.get("metar"), "source": "IEM KSFO METAR/SPECI"})
    reports.sort(key=lambda item: (item["available_at"], item["id"]))
    if not reports:
        raise ValueError("No historical weather returned")
    return reports, {**file_info(path), "url": WEATHER_URL, "query": WEATHER_QUERY, "reports": len(reports)}


def validate_episode(episode):
    if set(episode) != {"id", "split", "local_date", "warmup_start", "start", "end", "drain_end", "entries", "weather"}:
        raise ValueError("Unexpected episode fields")
    if episode["split"] != "evaluation" or episode["local_date"] not in DATES:
        raise ValueError("Episode outside late-August evaluation dates")
    local = dt.datetime.fromtimestamp(episode["start"], TZ)
    if episode["id"] != f"{local.date()}-{local.hour:02}00" or local.hour not in (6, 9, 12, 15, 18, 21) or local.minute or local.second:
        raise ValueError("Unexpected episode ID or window start")
    if episode["warmup_start"] != episode["start"] - 900 or episode["end"] != episode["start"] + 1800 or episode["drain_end"] != episode["start"] + 3600:
        raise ValueError("Window duration changed")
    previous, seen = float("-inf"), set()
    for entry in episode["entries"]:
        if set(entry) != set(ENTRY_FIELDS) or entry["flight_id"] in seen:
            raise ValueError("Invalid entry fields or repeated source operation")
        seen.add(entry["flight_id"])
        if not episode["warmup_start"] <= entry["spawn_time"] < episode["end"] or entry["spawn_time"] < previous:
            raise ValueError("Source release outside window or not sorted")
        previous = entry["spawn_time"]
        if entry["position_provenance"] not in ("observed", "synthetic_training_template") or set(entry["position"]) != {"lon", "lat", "altitude_ft"}:
            raise ValueError("Initial-state provenance or coordinates invalid")
        for value in [*entry["position"].values(), entry["spawn_time"], entry["groundspeed_kt"], entry["track_deg_true"]]:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("Initial-state numeric field invalid")
    available = float("-inf")
    for report in episode["weather"]:
        if set(report) != set(WEATHER_FIELDS) or not report["observed_at"] <= report["available_at"] <= episode["drain_end"] or report["available_at"] < available:
            raise ValueError("Weather fields or availability invalid")
        available = report["available_at"]
    if not episode["weather"] or episode["weather"][0]["available_at"] > episode["warmup_start"]:
        raise ValueError("No causal weather at episode start")
    return episode


def build(output=DATA_DIR):
    from pipeline.uita_data.build import make_synthetic
    flights, raw_rows, roster_source = _roster()
    observed, paths_source = _observed_entries(flights)
    templates = json.loads(TEMPLATES.read_text())
    if not templates or any(template["entry"]["local_date"] not in ("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06") or template["entry"]["split"] != "train" or not 120 <= template["lead_seconds"] <= 2400 for template in templates):
        raise ValueError("Templates are not frozen August 3–6 development examples")
    weather, weather_source = _weather()
    entries = []
    for flight in flights:
        entry = observed.get(flight["id"]) or make_synthetic(flight, templates)
        entries.append(({key: entry[key] for key in ENTRY_FIELDS}, flight["local_date"]))
    episodes, seen = [], set()
    for day in DATES:
        for hour in (6, 9, 12, 15, 18, 21):
            start = dt.datetime.fromisoformat(day).replace(hour=hour, tzinfo=TZ).timestamp()
            selected = [entry for entry, local_day in entries if local_day == day and start - 900 <= entry["spawn_time"] < start + 1800]
            selected.sort(key=lambda entry: (entry["spawn_time"], entry["flight_id"]))
            for entry in selected:
                if entry["flight_id"] in seen:
                    raise ValueError("Source arrival repeats across selected windows")
                seen.add(entry["flight_id"])
            prior = [report for report in weather if report["available_at"] <= start - 900]
            during = [report for report in weather if start - 900 < report["available_at"] <= start + 3600]
            episode = {"id": f"{day}-{hour:02}00", "split": "evaluation", "local_date": day,
                       "warmup_start": start - 900, "start": start, "end": start + 1800, "drain_end": start + 3600,
                       "entries": selected, "weather": prior[-1:] + during}
            validate_episode(episode)
            episodes.append(episode)
    if len(episodes) != 42 or any(not episode["entries"] for episode in episodes):
        raise ValueError("Expected 42 nonempty historical demand windows")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    payload = (canonical(episodes) + "\n").encode()
    (output / "evaluation.json").write_bytes(payload)
    strata = Counter(entry["position_provenance"] for episode in episodes for entry in episode["entries"])
    per_day = {day: {"episodes": 6, "source_arrival_operations": sum(len(ep["entries"]) for ep in episodes if ep["local_date"] == day)} for day in DATES}
    provenance = {"sources": {"roster": roster_source, "observed_paths": paths_source, "weather": weather_source,
                               "frozen_development_templates": {**file_info(TEMPLATES), "count": len(templates), "fit_dates": ["2026-08-03", "2026-08-06"]}},
                  "selected_roster_sha256": digest(canonical(raw_rows).encode()),
                  "source_arrival_operations_all_day": len(flights),
                  "all_day_roster_counts": dict(sorted(Counter(flight["local_date"] for flight in flights).items())),
                  "all_day_initial_state_strata": {"observed": len(observed), "synthetic_training_template": len(flights) - len(observed)},
                  "timezone_interpretation": "DataSF naive operation times interpreted as America/Los_Angeles, matching the existing benchmark extraction assumption.",
                  "missing_paths": "No late-week swim-path variants exist for selected arrival metadata in the cached monthly GeoParquet. Therefore all initial states are explicitly synthetic August 3–6 templates, shifted by actual late-week recorded operation times.",
                  "synthetic_timing": "Missing-path entry time = actual recorded arrival-operation time minus unchanged development-template lead time. This is historical-demand reconstruction, not a measured historical entry time.",
                  "limits": ["Recorded operation times are not verified touchdown times or human clearances.", "No actual airline delay, human action labels or counterfactual outcomes.", "Observed path matching is one-to-one, callsign/registration plus arrival endpoint within 1200 seconds.", "No recorded assigned runway, target-day future paths or actual operation time is exported into an episode.", "All future episode queues and reports are runner-private; expose only causal releases.", "August 8–9 scenario, operation and path rows are not selected by this builder."]}
    (output / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    manifest = {"traffic_version": VERSION, "source_dataset_id": SOURCE_DATASET, "split_dates": DAYS,
                "loader_sha256": digest(Path(__file__).read_bytes()), "seed": 17, "scenario_variants": ["nominal"],
                "artifacts": {"evaluation.json": {"sha256": digest(payload), "bytes": len(payload), "episodes": 42,
                                                   "source_arrival_operations": len(seen), "position_strata": dict(strata), "per_day": per_day},
                              "provenance.json": {"sha256": digest((output / "provenance.json").read_bytes()), "bytes": (output / "provenance.json").stat().st_size}},
                "privacy": "Trusted runner only; complete future queues never enter model prompts.",
                "held_out": "August 8–9 stay sealed. New evaluation dates are August 24–30.",
                "comparison": "Rerun scripted and deterministic baselines on these same 42 windows. Earlier August 7 scores are historical references, not matched comparators."}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    verification = {"passed": True, "manifest_sha256": digest((output / "manifest.json").read_bytes()),
                    "episodes": len(episodes), "source_arrival_operations": len(seen), "position_strata": dict(strata),
                    "no_repeated_source_operations": True, "all_windows_nonempty": True, "causal_weather_available_every_start": True,
                    "all_templates_fit_only_august_3_to_6": True, "august_8_9_not_selected": True}
    (output / "verification.json").write_text(json.dumps(verification, indent=2) + "\n")
    load_episodes(directory=output)
    return manifest


def load_episodes(split="evaluation", directory=DATA_DIR):
    """Return all 42 validated runner-private queues; never pass these to a model."""
    if split != "evaluation":
        raise ValueError("Only August 24–30 evaluation is available in this frozen pack")
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest["traffic_version"] != VERSION or manifest["source_dataset_id"] != SOURCE_DATASET or manifest["split_dates"] != DAYS:
        raise ValueError("Frozen late-August manifest version or dates changed")
    for name, artifact in manifest["artifacts"].items():
        payload = (directory / name).read_bytes()
        if digest(payload) != artifact["sha256"] or len(payload) != artifact["bytes"]:
            raise ValueError(f"Frozen source artifact checksum mismatch: {name}")
    episodes = json.loads((directory / "evaluation.json").read_bytes())
    expected_ids = {f"{day}-{hour:02}00" for day in DATES for hour in (6, 9, 12, 15, 18, 21)}
    if len(episodes) != 42 or {episode["id"] for episode in episodes} != expected_ids:
        raise ValueError("Expected the complete 42-window matrix")
    seen = set()
    for episode in episodes:
        validate_episode(episode)
        for entry in episode["entries"]:
            if entry["flight_id"] in seen:
                raise ValueError("Repeated source operation across windows")
            seen.add(entry["flight_id"])
    if len(seen) != manifest["artifacts"]["evaluation.json"]["source_arrival_operations"]:
        raise ValueError("Source arrival count differs from manifest")
    return episodes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DATA_DIR)
    args = parser.parse_args()
    manifest = build(args.output)
    print(json.dumps({"traffic_version": VERSION, "artifacts": manifest["artifacts"],
                      "manifest_sha256": digest((args.output / "manifest.json").read_bytes())}, indent=2))


if __name__ == "__main__":
    main()

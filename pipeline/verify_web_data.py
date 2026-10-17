"""Audit the generated replay against the original, full operation roster.

Run after build_web_data.py. This checks delivered data and source provenance;
it does not establish source completeness or certify flight safety.
"""
from collections import Counter
from datetime import datetime
import json
import math
from pathlib import Path
import statistics

HERE = Path(__file__).parent
WEB = HERE.parent / "web/public/data"


def read(path):
    return json.loads(path.read_text())


def main():
    payload, tracks, kpis = (read(WEB / name) for name in ("flights.json", "tracks.json", "kpis.json"))
    flights, week = payload["flights"], payload["week"]
    by_id = {flight["id"]: flight for flight in flights}
    assert len(by_id) == len(flights), "duplicate delivered flight ids"
    sources, raw_tracks = {}, {}
    for kind, folder, operation_key, port in (("arr", "bundle", "arrival_operation_time_utc", "origin"),
            ("dep", "departures-bundle", "departure_operation_time_utc", "destination")):
        for operation in read(HERE / folder / ("arrivals.json" if kind == "arr" else "departures.json")):
            fid = operation["operation_id"]
            assert fid not in sources, "duplicate source operation ids"
            sources[fid] = operation
            delivered = by_id[fid]
            expected = dict(kind=kind, t=int(datetime.fromisoformat(operation[operation_key]).timestamp()),
                callsign=operation["callsign"], reg=operation["registration"], type=operation["aircraft_type"],
                airline=operation["airline_icao"], port=operation[port], runway=operation["runway"])
            assert all(delivered[key] == value for key, value in expected.items()), f"changed roster record: {fid}"
            assert week["start_utc"] <= delivered["t"] < week["end_utc"], "operation outside replay week"
        for raw in read(HERE / folder / "tracks.json")["tracks"]:
            fid = raw["operation_id"]
            assert fid not in raw_tracks, "duplicate source track ids"
            raw_tracks[fid] = raw
    assert set(sources) == set(by_id), "roster members were added or removed"
    assert set(tracks) == {f["id"] for f in flights if f["has_track"]}, "path coverage mismatch"
    counts = Counter()
    for fid, points in tracks.items():
        assert len(points) >= 2, "path cannot animate"
        original = {point[0]: point for point in raw_tracks[fid]["points"]}
        last_time = -math.inf
        for point in points:
            assert len(point) == 5 and all(math.isfinite(value) for value in point[:3]), "invalid track tuple"
            timestamp, lon, lat, height, speed = point
            assert timestamp > last_time and -180 <= lon <= 180 and -90 <= lat <= 90, "invalid track position/time"
            source = original[timestamp]
            assert lon == round(source[1], 5) and lat == round(source[2], 5), "invented position"
            if height is not None:
                assert str(source[3]).endswith("C") and height == int(str(source[3])[:-1]) * 100, "unmeasured altitude"
                counts["beacon_points"] += 1
            if speed is not None:
                assert math.isfinite(speed) and 0 <= speed <= 701, "implausible derived speed"
            counts["gap_intervals_over_120_seconds"] += last_time != -math.inf and timestamp - last_time > 120
            last_time = timestamp
            counts["points"] += 1
    offsets = []
    for flight in flights:
        if "sched" in flight:
            assert flight["kind"] == "arr" and flight["has_track"], "schedule without arrival path"
            assert flight["sched"] == raw_tracks[flight["id"]]["source_scheduled_timestamp"], "changed schedule"
            assert math.isfinite(flight["sched"]) and abs(flight["sched"] - flight["t"]) < 7 * 86400, "invalid source schedule"
            offsets.append((flight["t"] - flight["sched"]) / 60)
    for event in kpis["sep_events"]:
        assert event["a"] != event["b"] and {event["a"], event["b"]} <= set(tracks), "invalid separation pair"
        assert event["t_start"] <= event["t_end"] and 0 <= event["min_nm"] <= 3 and 0 <= event["min_ft"] < 1000
    for event in kpis["go_arounds"]:
        assert event["id"] in tracks and by_id[event["id"]]["kind"] == "arr", "invalid go-around candidate"
    coverage = kpis["coverage"]
    for kind, name in (("arr", "arrivals"), ("dep", "departures")):
        assert coverage[f"roster_{name}"] == sum(f["kind"] == kind for f in flights)
        assert coverage[f"tracked_{name}"] == sum(f["kind"] == kind and f["has_track"] for f in flights)
    assert coverage["beacon_points"] == counts["beacon_points"] and coverage["total_points"] == counts["points"]
    assert all(isinstance(value, int) and value >= 0 for value in coverage.values())
    print(json.dumps(dict(status="pass", roster_operations=len(flights), paths=len(tracks), **counts,
        scheduled_arrivals=len(offsets), median_schedule_offset_minutes=round(statistics.median(offsets), 2)), indent=2))


if __name__ == "__main__":
    main()

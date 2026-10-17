"""Build the local historical replay without turning incomplete paths into full traffic.

The roster supplies operation counts and times. Matched ADSB.lol airborne legs
and Museum fallback paths supply positions. Only reported heights support safety.
"""
from collections import Counter, defaultdict
from datetime import datetime
import json
import gzip
import hashlib
import math
from pathlib import Path
import re

HERE = Path(__file__).parent
WEB = HERE.parent / "web/public/data"
SFO = (37.6213, -122.3790)  # latitude, longitude
MAX_KT = 700
STEP, MAX_GAP, MERGE_GAP = 10, 120, 20  # seconds
SEP_NM, SEP_FT = 3.0, 1000
PAIR_FT, PAIR_NM, PAIR_CROSS_NM, PAIR_HEADING = 3000, 8, 0.5, 20
GA_FT, GA_NM, GA_CLIMB, GA_WINDOW, GA_DESCENT = 1500, 6, 1000, 300, 100
BEACON_ALT = re.compile(r"(\d{1,3})C")
# FAA NASR July 9 / August 6, 2026 landing thresholds; both cycles agree.
THRESHOLDS = {"28L": (-122.35926477, 37.6120965), "28R": (-122.35805769, 37.61391813)}
RUNWAY_HEADING = 298  # true degrees, both parallel runways


def alt_ft(raw):
    """Bare simpleAltitude values are assigned heights, not measured heights."""
    match = BEACON_ALT.fullmatch(str(raw).strip()) if raw is not None else None
    return int(match.group(1)) * 100 if match else None


def dist_nm(a, b):
    """Great-circle distance; point tuples start with (timestamp, lon, lat)."""
    p1, p2 = math.radians(a[2]), math.radians(b[2])
    h = (math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2)
         * math.sin(math.radians(b[1] - a[1]) / 2) ** 2)
    return 3440.065 * 2 * math.asin(min(1, math.sqrt(h)))


def bearing(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, (a[1], a[2], b[1], b[2]))
    return math.degrees(math.atan2(math.sin(lon2 - lon1) * math.cos(lat2),
        math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1))) % 360


def kept_points(points):
    """Screen invalid positions and speed spikes without changing source bundles."""
    kept = []
    for point in points:
        if (len(point) != 5 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in point[:3])
                or not -180 <= point[1] <= 180 or not -90 <= point[2] <= 90):
            continue
        if kept:
            dt = point[0] - kept[-1][0]
            if dt <= 0 or dist_nm(kept[-1], point) / dt * 3600 > MAX_KT:
                continue
        kept.append(point)
    return kept


def clean(points, reported=False):
    kept, out = kept_points(points), []
    for index, point in enumerate(kept):
        previous = kept[index - 1] if index else None
        # Source speed units remain unverified. Use position/time differences instead.
        speed = (round(dist_nm(previous, point) * 3600 / (point[0] - previous[0]))
                 if previous and point[0] - previous[0] <= MAX_GAP else None)
        altitude = point[3] if reported else alt_ft(point[3])
        if altitude is not None and (not isinstance(altitude, (int, float)) or not math.isfinite(altitude)):
            raise ValueError('Invalid reported altitude')
        out.append([point[0], round(point[1], 5), round(point[2], 5), altitude, speed])
    return out


def load(kind, folder):
    ops = json.loads((HERE / folder / ("arrivals.json" if kind == "arr" else "departures.json")).read_text())
    raw_tracks = json.loads((HERE / folder / "tracks.json").read_text())["tracks"]
    tracks = {track["operation_id"]: track for track in raw_tracks}
    assert len(tracks) == len(raw_tracks), "duplicate source track ids"
    return ops, tracks


def usable_interval(a, b):
    return (0 < b[0] - a[0] <= MAX_GAP and a[3] is not None and b[3] is not None
            and dist_nm(a, b) * 3600 / (b[0] - a[0]) <= MAX_KT
            and abs(b[3] - a[3]) * 60 / (b[0] - a[0]) <= 6000)


def sample_grid(points):
    """Only interpolate between two measured heights in the same short interval."""
    for a, b in zip(points, points[1:]):
        if not usable_interval(a, b):
            continue
        heading = bearing(a, b)
        for time in range(math.ceil(a[0] / STEP) * STEP, math.ceil(b[0]), STEP):
            fraction = (time - a[0]) / (b[0] - a[0])
            yield (time, a[1] + fraction * (b[1] - a[1]), a[2] + fraction * (b[2] - a[2]),
                   a[3] + fraction * (b[3] - a[3]), heading)


def in_final_corridor(sample, flight):
    # Pressure-referenced ADS-B height can be slightly negative near sea level.
    if flight["kind"] != "arr" or flight["runway"] not in THRESHOLDS or sample[3] >= PAIR_FT:
        return False
    if abs((sample[4] - RUNWAY_HEADING + 180) % 360 - 180) > PAIR_HEADING:
        return False
    threshold = THRESHOLDS[flight["runway"]]
    east = (sample[1] - threshold[0]) * 60 * math.cos(math.radians(threshold[1]))
    north = (sample[2] - threshold[1]) * 60
    heading = math.radians(RUNWAY_HEADING)
    along = east * math.sin(heading) + north * math.cos(heading)
    cross = east * math.cos(heading) - north * math.sin(heading)
    return -PAIR_NM <= along <= 0 and abs(cross) <= PAIR_CROSS_NM


def paired_approach(p, q, by_id):
    a, b = by_id[p[0]], by_id[q[0]]
    return ({a["runway"], b["runway"]} == {"28L", "28R"}
            and in_final_corridor(p[1:], a) and in_final_corridor(q[1:], b))


def sep_events(flights, tracks):
    """Threshold crossings are candidates, never certified losses of separation."""
    steps, by_id = defaultdict(list), {flight["id"]: flight for flight in flights}
    for fid, points in tracks.items():
        for sample in sample_grid(points):
            # Include time in each point so corridor checks receive the usual tuple.
            steps[sample[0]].append((fid, *sample))
    kx, pairs, excluded = 60 * math.cos(math.radians(SFO[0])), defaultdict(list), 0
    for time, points in steps.items():
        cells = defaultdict(list)
        for point in points:
            cells[(int(point[2] * kx // 4), int(point[3] * 60 // 4))].append(point)
        for (cx, cy), cell in cells.items():
            for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1), (1, -1)):
                other = cells.get((cx + dx, cy + dy))
                if not other:
                    continue
                for index, p in enumerate(cell):
                    for q in (cell[index + 1:] if (dx, dy) == (0, 0) else other):
                        # Two records for one physical aircraft are not a pair.
                        if by_id[p[0]]["reg"] and by_id[p[0]]["reg"] == by_id[q[0]]["reg"]:
                            continue
                        feet = abs(p[4] - q[4])
                        if feet >= SEP_FT:
                            continue
                        nm = dist_nm(p[1:], q[1:])
                        if nm >= SEP_NM:
                            continue
                        if paired_approach(p, q, by_id):
                            excluded += 1
                            continue
                        pairs[tuple(sorted((p[0], q[0])))].append((time, nm, feet))
    events = []
    for (a, b), hits in pairs.items():
        hits.sort()
        run = [hits[0]]
        for hit in hits[1:] + [None]:
            if hit and hit[0] - run[-1][0] <= MERGE_GAP:
                run.append(hit)
                continue
            events.append(dict(t_start=run[0][0], t_end=run[-1][0], a=a, b=b,
                min_nm=round(min(row[1] for row in run), 2), min_ft=round(min(row[2] for row in run))))
            run = [hit]
    return sorted(events, key=lambda event: (event["t_start"], event["a"], event["b"])), excluded


def go_arounds(flights, tracks):
    """Require a measured low approach followed by two measured climb samples.

    Unknown heights and gaps reset the candidate. A lone high terminal point cannot
    create a go-around. Incomplete paths mean this remains a candidate detector.
    """
    events, evaluable = [], 0
    for flight in flights:
        if flight["kind"] != "arr":
            continue
        points = tracks.get(flight["id"], ())
        low, climb, previous, followups, supported = None, [], None, 0, False
        rearm_peak, approach_peak = None, None
        for point in points:
            if previous is None or not usable_interval(previous, point):
                low, climb, followups = None, [], 0
                approach_peak = None
            previous = point
            if point[3] is None:
                continue
            approach_peak = point[3] if approach_peak is None else max(approach_peak, point[3])
            near = dist_nm(point, (0, SFO[1], SFO[0])) < GA_NM
            if rearm_peak is not None:
                rearm_peak = max(rearm_peak, point[3])
                # Re-arm only after a substantial descent into a new approach.
                # Continuing the same climb must not create a second event.
                if near and point[3] < GA_FT and rearm_peak - point[3] >= GA_CLIMB:
                    rearm_peak = None
                else:
                    continue
            if low and point[0] - low[0] > GA_WINDOW:
                low, climb, followups = None, [], 0
            # A nearby-airport departure can be part of an SFO arrival's path.
            # Require measured descent, so its initial climb is not a go-around.
            if near and point[3] < GA_FT and (low is not None or approach_peak - point[3] >= GA_DESCENT):
                if low is None or point[3] < low[3]:
                    low, climb, followups = point, [], 0
            if low and point[0] > low[0]:
                followups += 1
                supported = supported or followups >= 2
                if point[3] >= low[3] + GA_CLIMB:
                    climb.append(point)
                else:
                    climb = []
                if len(climb) >= 2 and climb[-1][0] - climb[0][0] >= STEP:
                    # Count only when the climb evidence exists at replay time.
                    # A later low approach can produce another distinct event.
                    events.append(dict(t=point[0], low_t=low[0], low_ft=low[3],
                                       confirmed_ft=point[3], id=flight["id"]))
                    low, climb, followups = None, [], 0
                    rearm_peak = point[3]
        evaluable += supported
    return sorted(events, key=lambda event: (event["t"], event["id"])), evaluable


def write_json(name, payload):
    (WEB / name).write_text(json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n")


def main():
    flights, tracks, counts = [], {}, Counter()
    supplement_path = HERE / 'adsb-backfill/tracks.json.gz'
    provenance_path = HERE / 'adsb-backfill/provenance.json'
    assert supplement_path.exists() == provenance_path.exists(), 'Incomplete ADS-B supplement installation'
    supplement, provenance = {'tracks': {}, 'source': 'https://github.com/adsblol/globe_history_2026'}, None
    if supplement_path.exists():
        supplement = json.loads(gzip.decompress(supplement_path.read_bytes()))
        provenance = json.loads(provenance_path.read_text())
        assert provenance['archive_scan_complete'] and provenance['supplement_sha256'] == hashlib.sha256(supplement_path.read_bytes()).hexdigest(), 'Unverified ADS-B supplement'
    adsb_tracks = supplement['tracks']
    for kind, folder, time_key, port_key in (("arr", "bundle", "arrival_operation_time_utc", "origin"),
            ("dep", "departures-bundle", "departure_operation_time_utc", "destination")):
        operations, raw_tracks = load(kind, folder)
        for operation in operations:
            oid = operation["operation_id"]
            if oid in raw_tracks:
                raw = raw_tracks[oid]["points"]
                points = clean(raw)
                counts["dropped_points"] += len(raw) - len(points)
                if len(points) >= 2:
                    tracks[oid] = points
                else:
                    counts["dropped_tracks"] += 1
            scheduled = raw_tracks[oid].get("source_scheduled_timestamp") if kind == "arr" and oid in raw_tracks else None
            flight = dict(id=oid, kind=kind, t=int(datetime.fromisoformat(operation[time_key]).timestamp()),
                callsign=operation["callsign"], reg=operation["registration"], type=operation["aircraft_type"],
                airline=operation["airline_icao"], port=operation[port_key], runway=operation["runway"], has_track=oid in tracks)
            if oid in adsb_tracks:
                candidate = adsb_tracks[oid]
                assert candidate['kind'] == kind and candidate['operation_time_utc'] == flight['t'], 'ADS-B operation mismatch'
                assert re.sub(r'[\s-]', '', flight['reg']).upper() == candidate['registration'], 'ADS-B identity mismatch'
                points = clean(candidate['points'], reported=True)
                assert len(points) >= 3, 'ADS-B path has no usable flight leg'
                tracks[oid] = points
                flight.update(has_track=True, track_source='adsb.lol', icao24=candidate['icao24'])
                counts['adsb_paths'] += 1
            elif oid in tracks:
                flight['track_source'] = 'SFO Museum'
                counts['museum_fallback_paths'] += 1
            # Missing source sentinel timestamps must never become enormous delay values.
            if isinstance(scheduled, (int, float)) and math.isfinite(scheduled) and abs(flight["t"] - scheduled) < 7 * 86400:
                flight["sched"] = int(scheduled)
            flights.append(flight)
    flights.sort(key=lambda flight: (flight["t"], flight["id"]))
    ids = [flight["id"] for flight in flights]
    assert len(ids) == len(set(ids)), "duplicate flight ids"
    assert set(adsb_tracks) <= set(ids), 'Unknown ADS-B operation'
    assert set(tracks) == {flight["id"] for flight in flights if flight["has_track"]}
    source_coverage = json.loads((HERE / "departures-bundle/coverage.json").read_text())
    week = dict(start_utc=int(datetime.fromisoformat(source_coverage["week_start_local"]).timestamp()),
        end_utc=int(datetime.fromisoformat(source_coverage["week_end_exclusive_local"]).timestamp()), tz="America/Los_Angeles")
    assert all(week["start_utc"] <= flight["t"] < week["end_utc"] for flight in flights)
    # Track windows can extend beyond the roster week; KPI totals cannot.
    safety_tracks = {fid: [p for p in points if week['start_utc'] <= p[0] < week['end_utc']] for fid, points in tracks.items()}
    separation, excluded = sep_events(flights, safety_tracks)
    go_around, go_evaluable = go_arounds(flights, safety_tracks)
    evaluated_ids = {fid for fid, points in safety_tracks.items() if any(True for _ in sample_grid(points))}
    coverage = dict(roster_arrivals=sum(flight["kind"] == "arr" for flight in flights),
        roster_departures=sum(flight["kind"] == "dep" for flight in flights),
        tracked_arrivals=sum(flight["kind"] == "arr" and flight["has_track"] for flight in flights),
        tracked_departures=sum(flight["kind"] == "dep" and flight["has_track"] for flight in flights),
        separation_evaluable_tracks=len(evaluated_ids),
        separation_evaluable_arrivals=sum(flight["kind"] == "arr" and flight["id"] in evaluated_ids for flight in flights),
        go_around_evaluable_arrivals=go_evaluable,
        measured_altitude_points=sum(point[3] is not None for points in tracks.values() for point in points),
        adsb_paths=counts['adsb_paths'], museum_fallback_paths=counts['museum_fallback_paths'],
        total_points=sum(map(len, tracks.values())))
    methodology = dict(version="sfo-replay-kpis-v3", step_seconds=STEP, max_gap_seconds=MAX_GAP,
        altitude="ADSB.lol barometric heights; Museum explicit beacon heights only", timing="DataSF operation time; exact touchdown/wheels-up time is unverified",
        schedule="DataSF arrival operation minus Museum scheduled arrival; exact gate/touchdown semantics are unverified",
        separation=dict(horizontal_nm=SEP_NM, vertical_ft=SEP_FT, merge_gap_seconds=MERGE_GAP,
            paired_samples_excluded=excluded, pair_zone=dict(max_altitude_ft=PAIR_FT, final_distance_nm=PAIR_NM,
                cross_track_nm=PAIR_CROSS_NM, heading_tolerance_degrees=PAIR_HEADING, runway_heading_true=RUNWAY_HEADING)),
        go_around=dict(low_altitude_ft=GA_FT, airport_distance_nm=GA_NM, climb_ft=GA_CLIMB,
            minimum_approach_descent_ft=GA_DESCENT, max_elapsed_seconds=GA_WINDOW, sustained_samples=2),
        limitations=["Threshold events are track-derived candidates, not certified safety violations.",
            "No inference of actual heights from assigned or interim altitude values.",
            "Missing paths, unknown heights and receiver gaps prevent a complete safety or go-around count.",
            "ADSB.lol paths exclude ground observations and stop at source leg boundaries; Museum paths are fallback only.",
            "Paired-final geometry is a demo exclusion heuristic; actual visual clearances are unknown.",
            "Throughput, runway split and spacing use the full recorded operation roster.",
            "54 arrivals/hour is a user-selected visual-conditions demo reference, not verified capacity for this week."],
        sources=["https://data.sf.gov/d/43zc-xw3x", "https://github.com/sfomuseum-data/sfomuseum-data-flights-2026-08", supplement['source']])
    WEB.mkdir(parents=True, exist_ok=True)
    write_json("flights.json", dict(week=week, flights=flights))
    write_json("tracks.json", tracks)
    write_json("kpis.json", dict(sep_events=separation, go_arounds=go_around, coverage=coverage, methodology=methodology))
    if provenance:
        write_json('adsb-provenance.json', provenance)
        (WEB / 'adsb-backfill.json.gz').write_bytes(supplement_path.read_bytes())
    (WEB / "runways.geojson").write_text((HERE / "runways.geojson").read_text())
    print(json.dumps(dict(coverage=coverage, quality=dict(counts), separation_candidates=len(separation),
        paired_samples_excluded=excluded, go_around_candidates=len(go_around),
        scheduled_arrivals=sum("sched" in flight for flight in flights)), indent=2))


if __name__ == "__main__":
    main()

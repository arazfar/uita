"""Build the SFO departures bundle (Aug 3-9 2026, SFO local), mirroring pipeline/bundle (arrivals).

Inputs:  DataSF SODA (operation_type='D'), SFO Museum monthly GeoParquet (cached in .cache/).
Outputs: pipeline/departures-bundle/{departures,tracks,coverage,quality-notes,provenance}.json
"""
import collections, hashlib, json, math, re, statistics, struct
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow.compute as pc
import pyarrow.parquet as pq
import requests

HERE = Path(__file__).parent
CACHE = HERE / ".cache"
OUT = HERE / "departures-bundle"
PARQUET_URL = "https://static.sfomuseum.org/parquet/sfomuseum-data-flights-2026-08.parquet"
PARQUET = CACHE / "sfomuseum-data-flights-2026-08.parquet"
PARQUET_SIZE = 66135198
DATASF_URL = "https://data.sf.gov/resource/43zc-xw3x.json"
DATASF_QUERY = {
    "$select": "operation_no,flight_date_time,runway_name,aircraft_type,airline,other_port,flight_no,tail_number,airport_code",
    "$group": "operation_no,flight_date_time,runway_name,aircraft_type,airline,other_port,flight_no,tail_number,airport_code",
    "$where": "operation_type='D' AND airport_code='SFO' AND flight_date_time >= '2026-08-01T00:00:00' AND flight_date_time < '2026-08-14T00:00:00'",
    "$order": "flight_date_time,operation_no",
    "$limit": 50000,
}
TZ = ZoneInfo("America/Los_Angeles")
WEEK_START = datetime(2026, 8, 3, tzinfo=TZ)
WEEK_END = datetime(2026, 8, 10, tzinfo=TZ)
RUNWAY_RE = re.compile(r"(?:0?1|10|19|28)[LR]")
CENTER = (37.6213, -122.379)  # lat, lon
START_MAX_NM, POINT_MAX_NM, WINDOW_S, MARGIN_S = 5.0, 80.0, 1200, 1200


def nm(lat, lon):
    p1, p2 = math.radians(CENTER[0]), math.radians(lat)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon - CENTER[1]) / 2) ** 2
    return 3440.065 * 2 * math.asin(math.sqrt(a))


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def fetch_datasf():
    cache = CACHE / "datasf-departures-2026-08-01_13.json"
    if not cache.exists():
        r = requests.get(DATASF_URL, params=DATASF_QUERY, timeout=120)
        r.raise_for_status()
        cache.write_bytes(r.content)
    return cache


def ensure_parquet():
    CACHE.mkdir(exist_ok=True)
    if not PARQUET.exists() or PARQUET.stat().st_size != PARQUET_SIZE:
        raise SystemExit(f"{PARQUET} missing or wrong size (need {PARQUET_SIZE} bytes). Download {PARQUET_URL} into {CACHE}/ "
                         "(server is slow per connection; use curl -r ranged parts in parallel).")


def decode_linestring(b):
    """WKB little-endian 2D LineString -> [(lon, lat)] or None."""
    if not b or b[0] != 1 or struct.unpack_from("<I", b, 1)[0] != 2:
        return None
    n = struct.unpack_from("<I", b, 5)[0]
    if len(b) != 9 + 16 * n:
        return None
    v = struct.unpack_from(f"<{2 * n}d", b, 9)
    return list(zip(v[0::2], v[1::2]))


def load_roster():
    rows = json.loads(fetch_datasf().read_text())
    raw_n = len(rows)
    roster, dropped = [], collections.Counter()
    for r in rows:
        local = datetime.fromisoformat(r["flight_date_time"]).replace(tzinfo=TZ)
        if not (WEEK_START <= local < WEEK_END):
            dropped["outside_week"] += 1
            continue
        rw = r.get("runway_name") or ""
        if not RUNWAY_RE.fullmatch(rw):
            dropped["no_named_runway" if not rw else "non_runway_pad"] += 1
            continue
        roster.append(dict(
            operation_id=r["operation_no"], source=r["flight_date_time"], local=local,
            utc=local.astimezone(timezone.utc), callsign=r.get("flight_no") or None,
            registration=r.get("tail_number") or None, aircraft_type=r.get("aircraft_type") or None,
            airline_icao=r.get("airline") or None, destination=r.get("other_port") or None, runway=rw))
    ids = [r["operation_id"] for r in roster]
    assert len(ids) == len(set(ids)), "operation_no not unique"
    return raw_n, roster, dropped


def load_paths():
    cols = ["wof:id", "src:alt_label", "flysfo:event", "sfomuseum:flight_number", "swim:tail_number",
            "geometry", "swim:timestamps", "swim:altitudes", "swim:speeds"]
    t = pq.read_table(PARQUET, columns=cols)
    ev = t["flysfo:event"]
    meta = t.filter(pc.equal(ev, "D")).select(["wof:id", "sfomuseum:flight_number", "swim:tail_number"]).to_pylist()
    meta = {m["wof:id"]: m for m in meta}
    geo = t.filter(pc.equal(t["src:alt_label"], "swim-path")).to_pylist()
    lo, hi = int((WEEK_START).timestamp()) - MARGIN_S, int(WEEK_END.timestamp()) + MARGIN_S
    chk = collections.Counter()
    paths = []
    for g in geo:
        wid = g["wof:id"]
        if wid not in meta:
            chk["not_departure_metadata"] += 1
            continue
        ts, alts, spds = g["swim:timestamps"], g["swim:altitudes"], g["swim:speeds"]
        if not ts or ts[0] < lo or ts[0] > hi:
            chk["first_ts_outside_window"] += 1
            continue
        chk["path_records_in_time_window"] += 1
        pts = decode_linestring(g["geometry"])
        if pts is None:
            chk["non_linestring"] += 1
            continue
        if not (len(pts) == len(ts) == len(alts or []) == len(spds or [])):
            chk["misaligned_arrays"] += 1
            continue
        if any(b <= a for a, b in zip(ts, ts[1:])):
            chk["non_increasing_timestamps"] += 1
            continue
        if nm(pts[0][1], pts[0][0]) > START_MAX_NM:
            chk["start_more_than_5nm_from_sfo"] += 1
            continue
        keep = [[ts[i], round(pts[i][0], 7), round(pts[i][1], 7), alts[i], spds[i]]
                for i in range(len(ts)) if nm(pts[i][1], pts[i][0]) <= POINT_MAX_NM]
        if len(keep) < 2:
            chk["fewer_than_2_points_within_80nm"] += 1
            continue
        m = meta[wid]
        chk["usable_paths"] += 1
        paths.append(dict(wof=wid, aliases=set(m["sfomuseum:flight_number"] or []), reg=m["swim:tail_number"] or None,
                          first_ts=ts[0], last_ts=ts[-1], points=keep, date=None))
    return paths, chk


def match(roster, paths):
    cands = []
    for pi, p in enumerate(paths):
        for ri, r in enumerate(roster):
            dt = int(r["utc"].timestamp()) - p["first_ts"]
            if abs(dt) > WINDOW_S:
                continue
            reg_both = r["registration"] and p["reg"]
            if reg_both and r["registration"] != p["reg"]:
                continue
            cs = bool(r["callsign"] and r["callsign"] in p["aliases"])
            rg = bool(reg_both)  # equal, since differing were rejected
            if cs and rg: prio, meth = 0, "callsign_registration_time"
            elif cs: prio, meth = 1, "callsign_time"
            elif rg: prio, meth = 2, "registration_time"
            else: continue
            cands.append((prio, abs(dt), ri, pi, dt, meth))
    cands.sort()
    used_r, used_p, out = set(), set(), {}
    for prio, _, ri, pi, dt, meth in cands:
        if ri in used_r or pi in used_p:
            continue
        used_r.add(ri); used_p.add(pi)
        out[ri] = (pi, dt, meth)
    return out


def main():
    ensure_parquet()
    OUT.mkdir(exist_ok=True)
    raw_n, roster, dropped = load_roster()
    paths, chk = load_paths()
    matched = match(roster, paths)

    departures, tracks = [], []
    for ri, r in enumerate(roster):
        d = dict(operation_id=r["operation_id"],
                 departure_operation_time_source=r["source"],
                 departure_operation_time_local=r["local"].isoformat(),
                 departure_operation_time_utc=r["utc"].isoformat(),
                 callsign=r["callsign"], registration=r["registration"], aircraft_type=r["aircraft_type"],
                 airline_icao=r["airline_icao"], destination=r["destination"], runway=r["runway"],
                 source="DataSF 43zc-xw3x", museum_wof_id=None, trajectory_status="no_validated_path_match")
        if ri in matched:
            pi, dt, meth = matched[ri]
            p = paths[pi]
            d["museum_wof_id"] = p["wof"]; d["trajectory_status"] = "matched_observed_path"
            tracks.append(dict(museum_wof_id=p["wof"], source_variant="swim-path",
                               source_flight_aliases=sorted(p["aliases"]), source_registration=p["reg"],
                               source_first_track_timestamp=p["first_ts"], source_last_track_timestamp=p["last_ts"],
                               points=p["points"], operation_id=r["operation_id"], match_method=meth,
                               operation_minus_track_start_seconds=float(dt)))
        departures.append(d)

    def day(r): return r["local"].strftime("%Y-%m-%d")
    meths = collections.Counter(t["match_method"] for t in tracks)
    offs = sorted(t["operation_minus_track_start_seconds"] for t in tracks)
    sign = collections.Counter("op_after_track_start" if o > 0 else "op_before_track_start" if o < 0 else "equal" for o in offs)
    q = lambda f: offs[min(len(offs) - 1, int(f * len(offs)))] if offs else None
    # speed diagnostic on raw points
    over, over_tr, maxkt, short, gap = 0, 0, 0.0, 0, 0
    for t in tracks:
        pts, bad = t["points"], False
        if len(pts) < 5: short += 1
        for a, b in zip(pts, pts[1:]):
            dts = b[0] - a[0]; gap = max(gap, dts)
            kt = nm(b[2], b[1]) if False else 0
            # distance between consecutive points
            p1, p2 = math.radians(a[2]), math.radians(b[2])
            h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
            kt = 3440.065 * 2 * math.asin(math.sqrt(h)) / dts * 3600
            maxkt = max(maxkt, kt)
            if kt > 700: over += 1; bad = True
        over_tr += bad
    n = len(roster)
    coverage = dict(
        week_start_local=WEEK_START.isoformat(), week_end_exclusive_local=WEEK_END.isoformat(),
        roster_count=n, unique_operation_ids=len({r["operation_id"] for r in roster}),
        observed_path_matches=len(tracks), roster_without_validated_path=n - len(tracks),
        terminal_points=sum(len(t["points"]) for t in tracks), match_methods=dict(meths),
        path_checks=dict(chk),
        daily_roster=dict(sorted(collections.Counter(day(r) for r in roster).items())),
        daily_matched=dict(sorted(collections.Counter(day(roster[ri]) for ri in matched).items())),
        runways=dict(collections.Counter(r["runway"] for r in roster)))
    quality = dict(
        status="Raw observations; not normalized or physically cleaned",
        diagnostic_speed_threshold_knots=700, adjacent_pairs_above_diagnostic_threshold=over,
        tracks_with_pairs_above_diagnostic_threshold=over_tr, maximum_implied_groundspeed_knots=round(maxkt, 1),
        maximum_adjacent_sample_gap_seconds=gap, tracks_with_fewer_than_five_retained_points=short,
        operation_minus_track_start_seconds=dict(minimum=offs[0], p05=q(.05), median=statistics.median(offs), p95=q(.95), maximum=offs[-1]),
        operation_minus_track_start_sign=dict(sign),
        note="Departure paths are anchored on the FIRST point (near SFO); the DataSF time is the recorded departure-operation time, not wheels-up. Threshold is a diagnostic, not an ATC rule.")
    prov = json.loads((HERE / "bundle/provenance.json").read_text())
    prov.update(
        dataset="SFO runway departures, 2026-08-03 through 2026-08-09",
        source_inputs=[
            dict(name=PARQUET.name, url=PARQUET_URL, size_bytes=PARQUET.stat().st_size, sha256=sha256(PARQUET), included_in_bundle=False),
            dict(name=fetch_datasf().name, url=DATASF_URL, size_bytes=fetch_datasf().stat().st_size, sha256=sha256(fetch_datasf()), included_in_bundle=False)],
        datasf_query=DATASF_QUERY, datasf_grouped_rows_retrieved=raw_n,
        roster_rows_dropped=dict(dropped), retrieved_and_extracted_date_utc=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        path_start_maximum_distance_nm=START_MAX_NM,
        notes=["Derived extraction; counts are our audit results, not publisher-certified completeness.",
               "Each operation and each matched Museum ID appear at most once.",
               "Paths anchored on first timestamp/point (departures); metadata joined on wof:id with flysfo:event='D'; geometry rows have null metadata.",
               "swim-takeoff and swim-approach alternates excluded.",
               "Read README.md for transformations, matching details, limits, attribution and source licenses."])
    prov.pop("path_end_maximum_distance_nm", None)
    prov["match_basis"] = "DataSF operation time vs first path timestamp"
    tr_doc = dict(point_columns=["timestamp_unix_utc", "longitude", "latitude", "altitude_raw", "speed_raw"],
                  radius_nm=80, center=dict(latitude=CENTER[0], longitude=CENTER[1]),
                  altitude_note="Raw FAA SWIM simpleAltitude values retained; codes may describe assigned, beacon, or interim altitude. Validate and normalize before simulation.",
                  speed_note="Raw swim:speeds values retained; verify units before simulation.", tracks=tracks)
    dump = lambda name, obj, **k: (OUT / name).write_text(json.dumps(obj, **k) + "\n")
    dump("departures.json", departures, indent=2)
    dump("tracks.json", tr_doc, separators=(",", ":"))
    dump("coverage.json", coverage, indent=2); dump("quality-notes.json", quality, indent=2); dump("provenance.json", prov, indent=2)
    for f in ("SFO-Museum-LICENSE.txt", "datasf-source-metadata.json"):
        (OUT / f).write_bytes((HERE / "bundle" / f).read_bytes())

    print(f"DataSF grouped D rows: {raw_n}; roster in week w/ named runway: {n}; dropped: {dict(dropped)}")
    print(f"path checks: {dict(chk)}")
    print(f"matched: {len(tracks)} ({100*len(tracks)/n:.1f}%) methods: {dict(meths)}")
    print(f"per-day roster/matched: {coverage['daily_roster']} / {coverage['daily_matched']}")
    print(f"offset (op - path first ts) s: {quality['operation_minus_track_start_seconds']} sign: {dict(sign)}")
    if len(tracks) < 0.25 * n:
        raise SystemExit("matching below 25% - stop and review")


if __name__ == "__main__":
    main()

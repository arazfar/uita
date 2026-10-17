"""Emit web-ready flights.json + tracks.json from the arrivals and departures bundles."""
import json, math, re
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
WEB = HERE.parent / "web/public/data"
MAX_KT = 700
ALT_RE = re.compile(r"(\d{1,4})[A-Za-z]?")  # FAA simpleAltitude: hundreds of ft, optional trailing letter (e.g. '110C')


def alt_ft(raw):
    m = ALT_RE.fullmatch(str(raw).strip()) if raw is not None else None
    return int(m.group(1)) * 100 if m else None


def dist_nm(a, b):
    p1, p2 = math.radians(a[2]), math.radians(b[2])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 3440.065 * 2 * math.asin(math.sqrt(h))


def kept_points(points):
    """Drop points implying > MAX_KT from the previous kept point (raw values untouched)."""
    kept = []
    for p in points:
        if kept:
            dt = p[0] - kept[-1][0]
            if dt <= 0 or dist_nm(kept[-1], p) / dt * 3600 > MAX_KT:
                continue
        kept.append(p)
    return kept


def clean(points):
    return [[p[0], round(p[1], 5), round(p[2], 5), alt_ft(p[3]), int(p[4]) if isinstance(p[4], (int, float)) else None]
            for p in kept_points(points)]


def load(kind, folder):
    ops = json.loads((HERE / folder / ("arrivals.json" if kind == "arr" else "departures.json")).read_text())
    trk = {t["operation_id"]: t for t in json.loads((HERE / folder / "tracks.json").read_text())["tracks"]}
    return ops, trk


def main():
    flights, tracks, dropped_pts, dropped_tracks = [], {}, 0, 0
    for kind, folder, tkey, pkey in (("arr", "bundle", "arrival_operation_time_utc", "origin"),
                                     ("dep", "departures-bundle", "departure_operation_time_utc", "destination")):
        ops, trk = load(kind, folder)
        for o in ops:
            oid = o["operation_id"]
            if oid in trk:
                raw = trk[oid]["points"]
                pts = clean(raw)
                dropped_pts += len(raw) - len(pts)
                if len(pts) >= 2:
                    tracks[oid] = pts
                else:
                    dropped_tracks += 1
            flights.append(dict(id=oid, kind=kind, t=int(datetime.fromisoformat(o[tkey]).timestamp()),
                                callsign=o["callsign"], reg=o["registration"], type=o["aircraft_type"],
                                airline=o["airline_icao"], port=o[pkey], runway=o["runway"], has_track=oid in tracks))
    flights.sort(key=lambda f: (f["t"], f["id"]))
    ids = [f["id"] for f in flights]
    assert len(ids) == len(set(ids)), "duplicate flight ids"
    assert set(tracks) <= {f["id"] for f in flights if f["has_track"]}
    cov = json.loads((HERE / "departures-bundle/coverage.json").read_text())
    week = dict(start_utc=int(datetime.fromisoformat(cov["week_start_local"]).timestamp()),
                end_utc=int(datetime.fromisoformat(cov["week_end_exclusive_local"]).timestamp()), tz="America/Los_Angeles")
    WEB.mkdir(parents=True, exist_ok=True)
    (WEB / "flights.json").write_text(json.dumps(dict(week=week, flights=flights), separators=(",", ":")) + "\n")
    (WEB / "tracks.json").write_text(json.dumps(tracks, separators=(",", ":")) + "\n")
    (WEB / "runways.geojson").write_text((HERE / "runways.geojson").read_text())
    n = lambda k: sum(f["kind"] == k for f in flights)
    h = lambda k: sum(f["kind"] == k and f["has_track"] for f in flights)
    print(f"flights: {n('arr')} arr ({h('arr')} tracked) + {n('dep')} dep ({h('dep')} tracked); unique ids OK")
    print(f"tracks: {len(tracks)}; speed-outlier points dropped: {dropped_pts}; tracks dropped (<2 pts): {dropped_tracks}")
    print(f"alt unparsed points: {sum(1 for v in tracks.values() for p in v if p[3] is None)} / {sum(len(v) for v in tracks.values())}")


if __name__ == "__main__":
    main()

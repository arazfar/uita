"""Load flights + track_points + dataset_meta into Supabase (idempotent truncate-reload).

Usage: uv run load_supabase.py [--dry-run]
Creds (env or repo-root .env.local): SUPABASE_DB_URL (preferred, psql \\copy)
  or SUPABASE_SECRET_KEY + NEXT_PUBLIC_SUPABASE_URL (REST upsert, batched).
Apply supabase/migrations/*_flight_week.sql first. --dry-run only builds the CSVs in .cache/load/.
"""
import csv, json, os, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

import requests

from build_web_data import alt_ft, kept_points, load

HERE = Path(__file__).parent
OUT = HERE / ".cache/load"
BATCH = 5000
FLIGHT_COLS = ["operation_id", "kind", "op_time", "op_time_source", "callsign", "registration", "aircraft_type",
               "airline_icao", "other_port", "runway", "museum_wof_id", "trajectory_status", "match_method", "source"]
POINT_COLS = ["operation_id", "seq", "ts", "lon", "lat", "altitude_raw", "speed_raw", "alt_ft", "spd_kt"]


def env():
    e = dict(os.environ)
    f = HERE.parent / ".env.local"
    if f.exists():
        for line in f.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                e.setdefault(k.strip(), v.strip().strip("'\""))
    return e


def iso(unix): return datetime.fromtimestamp(unix, timezone.utc).isoformat()


def build():
    flights, points = [], []
    for kind, folder, tkey, pkey, src in (("arr", "bundle", "arrival_operation_time_utc", "origin", "arrival_operation_time_source"),
                                          ("dep", "departures-bundle", "departure_operation_time_utc", "destination", "departure_operation_time_source")):
        ops, trk = load(kind, folder)
        for o in ops:
            t = trk.get(o["operation_id"])
            flights.append(dict(operation_id=o["operation_id"], kind=kind, op_time=o[tkey], op_time_source=o[src],
                                callsign=o["callsign"], registration=o["registration"], aircraft_type=o["aircraft_type"],
                                airline_icao=o["airline_icao"], other_port=o[pkey], runway=o["runway"],
                                museum_wof_id=o["museum_wof_id"], trajectory_status=o["trajectory_status"],
                                match_method=t["match_method"] if t else None, source=o["source"]))
            if t:
                for i, p in enumerate(kept_points(t["points"])):
                    points.append(dict(operation_id=o["operation_id"], seq=i, ts=iso(p[0]), lon=round(p[1], 7), lat=round(p[2], 7),
                                       altitude_raw=p[3], speed_raw=p[4], alt_ft=alt_ft(p[3]),
                                       spd_kt=int(p[4]) if isinstance(p[4], (int, float)) else None))
    meta = {}
    for name, folder in (("arrivals", "bundle"), ("departures", "departures-bundle")):
        for part in ("coverage", "provenance", "quality-notes"):
            meta[f"{name}_{part}"] = json.loads((HERE / folder / f"{part}.json").read_text())
    return flights, points, meta


def write_csv(name, cols, rows):
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{name}.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow(["" if r[c] is None else r[c] for c in cols])  # psql csv: empty unquoted -> NULL
    return p


def via_psql(url, flights, points, meta):
    fc, pc_ = write_csv("flights", FLIGHT_COLS, flights), write_csv("track_points", POINT_COLS, points)
    mc = write_csv("dataset_meta", ["key", "value"], [dict(key=k, value=json.dumps(v)) for k, v in meta.items()])
    script = f"""\\set ON_ERROR_STOP on
begin;
truncate public.track_points, public.flights, public.dataset_meta;
\\copy public.flights ({",".join(FLIGHT_COLS)}) from '{fc}' csv header
\\copy public.track_points ({",".join(POINT_COLS)}) from '{pc_}' csv header
\\copy public.dataset_meta (key, value) from '{mc}' csv header
commit;
"""
    subprocess.run(["psql", url, "-v", "ON_ERROR_STOP=1", "-c", "select 1"], check=True, capture_output=True)
    subprocess.run(["psql", url], input=script, text=True, check=True)


def via_rest(base, key, flights, points, meta):
    h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
         "Prefer": "resolution=merge-duplicates,return=minimal"}

    def up(table, rows, conflict):
        for i in range(0, len(rows), BATCH):
            r = requests.post(f"{base}/rest/v1/{table}?on_conflict={conflict}", headers=h, data=json.dumps(rows[i:i + BATCH]), timeout=120)
            if not r.ok:
                raise SystemExit(f"REST upsert into {table} failed: {r.status_code} {r.text[:500]}")
    up("flights", flights, "operation_id")
    up("track_points", points, "operation_id,seq")
    up("dataset_meta", [dict(key=k, value=v) for k, v in meta.items()], "key")


def main():
    flights, points, meta = build()
    print(f"built {len(flights)} flights, {len(points)} track points, {len(meta)} meta keys")
    if "--dry-run" in sys.argv:
        for n, c, r in (("flights", FLIGHT_COLS, flights), ("track_points", POINT_COLS, points)):
            print("wrote", write_csv(n, c, r))
        return
    e = env()
    if e.get("SUPABASE_DB_URL"):
        via_psql(e["SUPABASE_DB_URL"], flights, points, meta)
    elif e.get("SUPABASE_SECRET_KEY") and e.get("NEXT_PUBLIC_SUPABASE_URL"):
        via_rest(e["NEXT_PUBLIC_SUPABASE_URL"].rstrip("/"), e["SUPABASE_SECRET_KEY"], flights, points, meta)
    else:
        raise SystemExit("Missing Supabase credentials: set SUPABASE_DB_URL, or SUPABASE_SECRET_KEY + NEXT_PUBLIC_SUPABASE_URL "
                         "(env or repo-root .env.local). Nothing was loaded.")
    print("loaded OK")


if __name__ == "__main__":
    main()

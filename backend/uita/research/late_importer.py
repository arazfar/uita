"""Freeze a distinct late-August development/validation extract, read-only at source.

Ten-second buckets reduce transport volume. Raw rows remain in the source schema;
the exact extracted observations, counts and checksums are frozen as artifacts.
Sealed August 29 payloads cannot be read by this interactive importer.
"""

import argparse
import json
import os
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from .context import normalize_advisory, normalize_forecast, normalize_metar
from .data import digest, metered_variant, save_artifact, split
from .database import Database
from .legs import VERSION, finite, normalize_legs


def ingest(source_url, target, day, hours=24):
    if day not in ("2026-08-24", "2026-08-25", "2026-08-26") or not 1 <= hours <= 24:
        raise ValueError(
            "Only bounded late-August development/validation partitions are permitted"
        )
    start = datetime.combine(date.fromisoformat(day), datetime.min.time(), timezone.utc)
    end = start + timedelta(hours=hours)
    with psycopg.connect(
        source_url,
        connect_timeout=15,
        row_factory=dict_row,
        options="-c default_transaction_read_only=on -c statement_timeout=120000",
    ) as source:
        source.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        snapshot = source.execute(
            "SELECT transaction_timestamp() AS at, pg_current_snapshot()::text AS snapshot"
        ).fetchone()
        counts = source.execute(
            """SELECT count(*) AS rows, min(t_utc) AS first, max(t_utc) AS last,
            count(*) FILTER (WHERE alt_baro_ft IS NULL) AS null_altitude,
            count(*) FILTER (WHERE flag_stale) AS stale
            FROM atc_sfo_w35.positions WHERE t_utc >= %s AND t_utc < %s AND utc_date = %s""",
            (start, end, day),
        ).fetchone()
        if not counts["rows"]:
            raise ValueError("Source partition has no observations")
        # Candidate screening is only an optimization. Flight-leg evidence below
        # independently excludes overflights and nearby-airport traffic.
        rows = source.execute(
            """
            WITH candidates AS (
                SELECT DISTINCT icao24 FROM atc_sfo_w35.positions
                WHERE utc_date=%s AND t_utc >= %s AND t_utc < %s AND on_ground
                  AND lat BETWEEN 37.594 AND 37.644 AND lon BETWEEN -122.407 AND -122.343
            ), sampled AS (
                SELECT DISTINCT ON (p.icao24, floor(extract(epoch FROM p.t_utc)/10)) p.*
                FROM atc_sfo_w35.positions p JOIN candidates c USING (icao24)
                WHERE p.utc_date=%s AND p.t_utc >= %s AND p.t_utc < %s
                ORDER BY p.icao24, floor(extract(epoch FROM p.t_utc)/10), p.t_utc, md5(row_to_json(p)::text)
            ) SELECT * FROM sampled ORDER BY icao24, t_utc
        """,
            (day, start, end, day, start, end),
        ).fetchall()
        metars = source.execute(
            "SELECT * FROM atc_sfo_w35.metar WHERE t_utc >= %s AND t_utc < %s ORDER BY t_utc",
            (start - timedelta(hours=3), end),
        ).fetchall()
        forecasts = source.execute(
            "SELECT * FROM atc_sfo_w35.taf WHERE utc_taf_issue >= %s AND utc_taf_issue < %s ORDER BY utc_taf_issue, utc_valid, product_id, raw",
            (start - timedelta(days=1), end),
        ).fetchall()
        advisories = source.execute(
            "SELECT * FROM atc_sfo_w35.advisories WHERE start_utc >= %s AND start_utc < %s ORDER BY date, advzy, text",
            (start, end),
        ).fetchall()
    raw = json.loads(json.dumps(rows, default=str, allow_nan=False))
    raw_checksum = digest(raw)
    legs = list(normalize_legs(rows))
    weather = [normalize_metar(r) for r in metars]
    forecast_data = [normalize_forecast(r) for r in forecasts]
    advisory_data = [normalize_advisory(r) for r in advisories]
    content_checksum = digest(
        {
            "positions": raw_checksum,
            "weather": weather,
            "forecasts": forecast_data,
            "advisories": advisory_data,
            "transform": VERSION,
        }
    )
    dataset_id = f"late-{day}-{hours}h-{content_checksum[:12]}"
    entries = []
    rejected = Counter()
    for leg in legs:
        if leg["operation"] != "arrival":
            rejected[leg["operation"]] += 1
            continue
        initial = next(
            (
                p
                for p in leg["points"]
                if p["on_ground"] is False
                and "stale" not in p["quality_flags"]
                and all(
                    finite(p.get(k))
                    for k in ("altitude_ft", "groundspeed_kt", "track_deg_true")
                )
                and 1000 <= p["altitude_ft"] <= 18000
                and 5 <= (p["x_nm"] ** 2 + p["y_nm"] ** 2) ** 0.5 <= 60
            ),
            None,
        )
        if initial is None:
            rejected["no_valid_initial_state"] += 1
            continue
        entries.append(
            {
                "id": dataset_id + ":" + leg["id"],
                "callsign": leg["callsign"],
                "aircraft_type": leg["aircraft_type"],
                "spawn_time": initial["t"],
                **{
                    k: initial[k]
                    for k in (
                        "x_nm",
                        "y_nm",
                        "altitude_ft",
                        "groundspeed_kt",
                        "track_deg_true",
                    )
                },
                "operation": "arrival",
                "provenance": {
                    "kind": "derived",
                    "position": "observed",
                    "motion": "observed",
                    "altitude_reference": "pressure_feet",
                    "transform": VERSION,
                    "source_leg": leg["id"],
                    "source_checksum": raw_checksum,
                    "limitation": "SFO association established using later ground evidence; initial approach state is a research assumption",
                },
            }
        )
    scenarios = []
    for hour in range(hours):
        a = start.timestamp() + hour * 3600
        demand = sorted(
            [e for e in entries if a <= e["spawn_time"] < a + 3600],
            key=lambda e: (e["spawn_time"], e["id"]),
        )
        if not demand:
            continue
        scenarios.append(
            {
                "id": dataset_id + f"-{hour:02d}",
                "dataset_id": dataset_id,
                "split": split(day),
                "start": a,
                "end": a + 5400,
                "entries": demand,
                "weather": weather,
                "forecasts": forecast_data,
                "advisories": advisory_data,
                "coverage": {
                    "entries": len(demand),
                    "observed": len(demand),
                    "sampling_seconds": 10,
                },
                "provenance": {
                    "kind": "derived",
                    "source": "Separate late-August extract",
                    "source_checksum": raw_checksum,
                    "limitations": [
                        "Ten-second sampling; not all raw positions",
                        "Future ground evidence used for airport association, never exposed to controller",
                        "Arrival-only reconstructed demand; departures and unresolved legs excluded",
                        "Source publication times incomplete; advisory content withheld from controller",
                    ],
                },
            }
        )
    manifest = {
        "id": dataset_id,
        "source": "atc_sfo_w35.positions",
        "split": split(day),
        "checksum": raw_checksum,
        "snapshot": snapshot,
        "source_counts": counts,
        "status": "complete_extract",
        "coverage": {
            "requested_start": start,
            "requested_end": end,
            "source_first": counts["first"],
            "source_last": counts["last"],
            "whole_day_requested": hours == 24,
            "sampled_rows": len(rows),
            "legs": len(legs),
            "sfo_arrivals": len(entries),
            "excluded": dict(rejected),
            "sampling_seconds": 10,
            "sample_table_used": False,
        },
        "transform": VERSION,
    }
    manifest = json.loads(json.dumps(manifest, default=str))
    with target.transaction() as db:
        # Content-derived names also preserve extracts when source collection changes.
        save_artifact(
            db,
            dataset_id + ":raw",
            "raw_extract",
            {"rows": raw, "checksum": raw_checksum},
        )
        for leg in legs:
            save_artifact(db, dataset_id + ":" + leg["id"], "flight_leg", leg)
            save_artifact(
                db,
                "replay:" + dataset_id + ":" + leg["id"],
                "replay",
                {"points": leg["points"], "source": dataset_id},
            )
        for scenario in scenarios:
            save_artifact(db, scenario["id"], "scenario", scenario)
            if scenario["split"] == "train":
                variant = metered_variant(scenario)
                save_artifact(db, variant["id"], "scenario", variant)
        # Snapshot metadata is mutable across repeated extractions, so version it
        # separately from deterministic content IDs.
        save_artifact(
            db, dataset_id + ":manifest:" + digest(manifest)[:12], "manifest", manifest
        )
    return {"dataset_id": dataset_id, "scenarios": len(scenarios), "manifest": manifest}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", required=True)
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--report", default="output/research-late-import.json")
    args = parser.parse_args()
    database = Database()
    try:
        report = ingest(
            os.environ["SOURCE_DATABASE_URL"], database, args.day, args.hours
        )
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({k: v for k, v in report.items() if k != "manifest"}))
    finally:
        database.close()


if __name__ == "__main__":
    main()

"""Read-only Railway source extraction into new immutable research artifacts.

Run with SOURCE_DATABASE_URL and a separate DATABASE_URL target. This importer
does not write source schemas or load sealed-test payloads into interactive data.
"""

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from .data import TRANSFORM, digest, metered_variant, save_artifact
from .database import Database
from .geometry import local
from .procedures import parse


def artifact(source, dataset, name):
    row = source.execute(
        "SELECT sha256,payload FROM uita_data.artifacts WHERE dataset_id=%s AND name=%s",
        (dataset, name),
    ).fetchone()
    if row is None:
        raise ValueError("Source artifact missing: " + name)
    payload = bytes(row["payload"])
    if hashlib.sha256(payload).hexdigest() != row["sha256"]:
        raise ValueError("Source checksum mismatch")
    return json.loads(payload), row["sha256"]


def normalize_pack(pack, episode, checksums):
    ids = set(episode["flight_ids"])
    entries = []
    for e in pack["entries"]:
        if e["flight_id"] not in ids:
            continue
        x, y = local(e["position"]["lon"], e["position"]["lat"])
        entries.append(
            {
                "id": e["flight_id"],
                "callsign": e["callsign"],
                "aircraft_type": e["aircraft_type"],
                "spawn_time": e["spawn_time"],
                "x_nm": x,
                "y_nm": y,
                "altitude_ft": e["position"]["altitude_ft"],
                "groundspeed_kt": e["groundspeed_kt"],
                "track_deg_true": e["track_deg_true"],
                "operation": "arrival",
                "provenance": {
                    "kind": "observed"
                    if e["position_provenance"] == "observed"
                    else "synthetic",
                    "position": e["position_provenance"],
                    "altitude": e["altitude_provenance"],
                    "motion": e["motion_provenance"],
                    "transform": TRANSFORM,
                },
            }
        )
    reports = []
    for w in pack["weather"]:
        layers = [
            l["base_ft_agl"]
            for l in w.get("cloud_layers", [])
            if l.get("cover") in ("BKN", "OVC", "VV")
            and l.get("base_ft_agl") is not None
        ]
        reports.append(
            {
                **w,
                "wind_from_deg_true": w.get("wind_direction_deg_true"),
                "ceiling_ft": min(layers) if layers else None,
            }
        )
    return {
        "id": episode["id"] + "-research-v2",
        "dataset_id": pack["dataset_id"],
        "split": episode["split"],
        "start": episode["warmup_start"],
        "end": episode["drain_end"],
        "entries": sorted(entries, key=lambda e: (e["spawn_time"], e["id"])),
        "weather": reports,
        "coverage": {
            "entries": len(entries),
            "observed": sum(e["provenance"]["kind"] == "observed" for e in entries),
        },
        "provenance": {
            "kind": "mixed",
            "source": "Frozen Railway arrival pack",
            "source_checksums": checksums,
            "transform": TRANSFORM,
            "limitations": [
                "Some entry times reconstructed from later operation timestamps",
                "Motion after initialization is a research simulation",
                "Published procedure assignments are not known",
            ],
        },
    }


def ingest(source_url, target):
    inventory = {}
    checksums = {}
    scenarios = []
    replays = []
    with psycopg.connect(
        source_url,
        connect_timeout=15,
        options="-c default_transaction_read_only=on -c statement_timeout=120000",
        row_factory=dict_row,
    ) as source:
        source.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        dataset = "sfo-2026-08-03_09-v1"
        episodes = source.execute(
            "SELECT payload FROM uita_data.episodes WHERE dataset_id=%s AND split != 'test' ORDER BY episode_id",
            (dataset,),
        ).fetchall()
        packs = {}
        for row in episodes:
            episode = row["payload"]
            name = episode["scenario_file"]
            if name not in packs:
                packs[name], checksums[name] = artifact(source, dataset, name)
            scenarios.append(
                normalize_pack(packs[name], episode, {name: checksums[name]})
            )
        observations = [
            r["payload"]
            for r in source.execute(
                "SELECT t.payload FROM uita_data.tracks t JOIN uita_data.arrivals a ON a.dataset_id=t.dataset_id AND a.flight_id=t.flight_id WHERE t.dataset_id=%s AND a.split != 'test' ORDER BY t.flight_id",
                (dataset,),
            ).fetchall()
        ]
        checksums["development-validation-observations"] = digest(observations)
        train_ids = set(e["id"] for s in scenarios for e in s["entries"])
        for track in observations:
            if track["flight_id"] not in train_ids:
                continue
            # Raw replay remains separate from simulator state and control observations.
            replays.append({"id": "replay:" + track["flight_id"], "payload": track})
        inventory["positions"] = source.execute(
            "SELECT utc_date,count(*) AS count,min(t_utc) AS first,max(t_utc) AS last FROM atc_sfo_w35.positions GROUP BY utc_date ORDER BY utc_date"
        ).fetchall()
        procedures = parse(
            source.execute("SELECT * FROM atc_sfo_w35.sfo_procedures").fetchall()
        )
        inventory["procedures"] = {
            "rows": sum(len(p["legs"]) for p in procedures),
            "routes": len(procedures),
            "supported_geometry": sum(p["supported"] for p in procedures),
        }
        inventory["counts"] = {
            table: source.execute(
                f"SELECT count(*) AS n FROM atc_sfo_w35.{table}"
            ).fetchone()["n"]
            for table in (
                "metar",
                "taf",
                "advisories",
                "asos1min",
                "weather_hourly",
                "sfo_runways",
            )
        }
        inventory["snapshot_at"] = datetime.now(timezone.utc).isoformat()
        inventory["expected_late_days"] = [
            "2026-08-24",
            "2026-08-25",
            "2026-08-26",
            "2026-08-29",
        ]
        present = {str(r["utc_date"]) for r in inventory["positions"]}
        inventory["missing_late_days"] = sorted(
            set(inventory["expected_late_days"]) - present
        )
        inventory["source_checksums"] = checksums
    inventory = json.loads(json.dumps(inventory, default=str))
    snapshot_id = "inventory-" + digest(inventory)[:16]
    with target.transaction() as db:
        for scenario in scenarios:
            save_artifact(db, scenario["id"], "scenario", scenario)
            if scenario["split"] == "train":
                variant = metered_variant(scenario)
                save_artifact(db, variant["id"], "scenario", variant)
        for replay in replays:
            save_artifact(db, replay["id"], "replay", replay["payload"])
        for procedure in procedures:
            save_artifact(db, "procedure:" + procedure["id"], "procedure", procedure)
        save_artifact(
            db,
            snapshot_id,
            "manifest",
            {
                "id": snapshot_id,
                "source": "Railway consistent read-only snapshot",
                "inventory": inventory,
            },
        )
    return {
        "snapshot_id": snapshot_id,
        "scenarios": len(scenarios),
        "replay_tracks": len(replays),
        "procedures": len(procedures),
        "inventory": inventory,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="output/research-import.json")
    args = parser.parse_args()
    from pathlib import Path

    result = ingest(os.environ["SOURCE_DATABASE_URL"], Database())
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "inventory"}))


if __name__ == "__main__":
    main()

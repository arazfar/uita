"""Capture the single preregistered demo episode; never retry or select winners.
Run with UITA_RECORD_PAID=1, DATABASE_URL pointing to the existing validation
ledger, and CRUSOE_API_KEY in the environment. Output includes all failures.
"""

import copy
import gzip
import json
import os
import time
from pathlib import Path

from sqlalchemy import select
from uita.provider import MODEL
from uita.research.contracts import Control, Disruption, RunCreate
from uita.research.data import digest
from uita.research.database import Checkpoint, Database, Event, Reservation, Run
from uita.research.dynamics import initial_state, public_state
from uita.research.presentation import frame, install_recording
from uita.research.service import (
    advance_one,
    apply_disruption,
    create_run,
    identifier,
    mutate,
    scenario_for,
)
from uita.research.worker import Worker

ID = "nemotron-aug06-closure-v1"
SCENARIO = "2026-08-06-1500-research-v2-metered"
TEAM = "research"


def main():
    if os.getenv("UITA_RECORD_PAID") != "1":
        raise SystemExit(
            "Set UITA_RECORD_PAID=1; capture uses the existing shared ledger"
        )
    database = Database()
    worker = Worker(database)
    with database.transaction() as db:
        run = create_run(
            db,
            TEAM,
            RunCreate(
                scenario_id=SCENARIO,
                seed=42,
                controller="crusoe",
                spend_cap_usd=0.5,
                idempotency_key=ID,
            ),
        )
        if run["revision"] != 1:
            raise SystemExit("Capture already started; inspect it instead of rerunning")
        scenario = copy.deepcopy(scenario_for(db, SCENARIO))
        r = db.get(Run, run["id"])
        if r.revision != 1:
            raise SystemExit("Capture already exists; retain its original outcome")
        r.owner, r.lease_until = worker.id, time.time() + 45
        mutate(
            db,
            TEAM,
            r.id,
            "control",
            Control(
                action="speed",
                speed=30,
                expected_revision=r.revision,
                idempotency_key=identifier(),
            ),
        )
        mutate(
            db,
            TEAM,
            r.id,
            "control",
            Control(
                action="play",
                expected_revision=r.revision,
                idempotency_key=identifier(),
            ),
        )
    run_id = run["id"]
    print(json.dumps({"capture_started": run_id}), flush=True)
    closure = False
    try:
        for _ in range(40):
            with database.transaction() as db:
                r = db.get(Run, run_id)
                if r.status != "running":
                    break
                r.next_tick = 0
            worker.tick()
            # Recording uses the real worker/response lifecycle, with presentation
            # time held between batches while the external response is captured.
            deadline = time.monotonic() + 30
            while worker.pending and time.monotonic() < deadline:
                time.sleep(0.1)
                worker.collect_inference()
            with database.transaction() as db:
                r = db.get(Run, run_id)
                elapsed = r.state["clock"] - r.state["start"]
                if elapsed >= 90 and not closure:
                    mutate(
                        db,
                        TEAM,
                        run_id,
                        "disruption",
                        Disruption(
                            kind="runway_closure",
                            runway="28R",
                            expected_revision=r.revision,
                            idempotency_key=identifier(),
                        ),
                    )
                    closure = True
                r.lease_until = time.time() + 45
            print(json.dumps({"seconds": elapsed}), flush=True)
    finally:
        worker.close()
        with database.transaction() as db:
            r = db.get(Run, run_id)
            if r.status == "running":
                mutate(
                    db,
                    TEAM,
                    run_id,
                    "control",
                    Control(
                        action="pause",
                        expected_revision=r.revision,
                        idempotency_key=identifier(),
                    ),
                )
    with database.sessions() as db:
        r = db.get(Run, run_id)
        checkpoints = list(
            db.scalars(
                select(Checkpoint)
                .where(Checkpoint.run_id == run_id)
                .order_by(Checkpoint.revision)
            )
        )
        frames = [
            frame(
                c.state, run_id, c.revision, c.state["event_sequence"], "recording"
            ).model_dump()
            for c in checkpoints
        ]
        events = [
            {
                "sequence": e.sequence,
                "kind": e.kind,
                "clock": e.clock,
                "payload": e.payload,
            }
            for e in db.scalars(
                select(Event).where(Event.run_id == run_id).order_by(Event.sequence)
            )
        ]
        reservations = list(
            db.scalars(select(Reservation).where(Reservation.run_id == run_id))
        )
        responses = [
            {
                "reservation_id": x.id,
                "reserved_usd": x.amount,
                "actual_usd": x.actual,
                **x.metadata_json,
            }
            for x in reservations
        ]
        candidate = {
            "controller": r.state["policy_version"],
            "metrics": public_state(r.state)["metrics"],
            "status": r.status,
            "clock": r.state["clock"],
            "state_hash": digest(r.state),
        }
        end = r.state["clock"]
    tape = [e for e in events if e["kind"] == "disruption"]
    baseline = initial_state(scenario, 42, "static")
    baseline["status"] = "running"
    baseline_frames = [frame(baseline, "baseline", 1, mode="recording").model_dump()]
    cursor = 0
    for tick in range(int(end - baseline["start"])):
        while cursor < len(tape) and tape[cursor]["clock"] <= baseline["clock"]:
            apply_disruption(baseline, Disruption(**tape[cursor]["payload"]))
            cursor += 1
        advance_one(baseline, scenario)
        if tick % 5 == 4 or baseline["status"] != "running":
            baseline_frames.append(
                frame(baseline, "baseline", tick + 2, mode="recording").model_dump()
            )
        if baseline["status"] != "running":
            break
    baseline_frames.append(
        frame(baseline, "baseline", tick + 3, mode="recording").model_dump()
    )
    comparison = {
        "scenario_id": SCENARIO,
        "scenario_hash": digest(scenario),
        "seed": 42,
        "event_tape": tape,
        "results": [
            {
                "controller": "static-2",
                "metrics": public_state(baseline)["metrics"],
                "status": baseline["status"],
                "clock": baseline["clock"],
                "state_hash": digest(baseline),
            },
            candidate,
        ],
        "limitations": [
            "Completed-only delay; report alongside backlog",
            "Synthetic metered demand and research dynamics",
            "Recorded computation pauses; not a real-time controller deadline test",
        ],
    }
    payload = {
        "frames": frames,
        "baseline_frames": baseline_frames,
        "events": events,
        "comparison": comparison,
        "responses": responses,
    }
    payload["manifest"] = {
        "id": ID,
        "title": "August 6 · Nemotron and a 28R closure",
        "scenario_id": SCENARIO,
        "scenario_checksum": digest(scenario),
        "simulator_version": frames[0]["simulator_version"],
        "rule_version": frames[0]["rule_version"],
        "policy_version": "crusoe-2",
        "model": MODEL,
        "start": scenario["start"],
        "end": end,
        "seed": 42,
        "outcome": candidate["status"],
        "model_responses": sum(e["kind"] == "model_response" for e in events),
        "fallback_count": sum(e["kind"] == "controller_fallback" for e in events),
        "event_tape": tape,
        "checksums": {k: digest(v) for k, v in payload.items()},
        "limitations": comparison["limitations"],
    }
    with database.transaction() as db:
        install_recording(db, payload)
    out = Path("backend/uita/research/assets/showcase_recording.json.gz")
    out.write_bytes(
        gzip.compress(
            json.dumps(payload, separators=(",", ":"), allow_nan=False).encode(),
            mtime=0,
        )
    )
    print(
        json.dumps(
            {
                "recording": str(out),
                "model_responses": payload["manifest"]["model_responses"],
                "known_cost": sum(x.actual or 0 for x in reservations),
                "reserved": sum(x.amount for x in reservations),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()

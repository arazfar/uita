"""One opt-in paid end-to-end validation; shared reservations enforce all caps."""

import json
import os
import time
from pathlib import Path

from sqlalchemy import select
from uita.research.contracts import Control, RunCreate
from uita.research.database import Database, Event, Reservation, Run
from uita.research.service import create_run, identifier, mutate
from uita.research.worker import Worker


def main():
    if os.getenv("UITA_VALIDATE_PAID") != "1":
        raise SystemExit("Set UITA_VALIDATE_PAID=1 to authorize one bounded live probe")
    database = Database()
    with database.transaction() as db:
        run = create_run(
            db,
            "validation",
            RunCreate(
                scenario_id="fixture-august-v2",
                controller="crusoe",
                idempotency_key=identifier(),
            ),
        )
        mutate(
            db,
            "validation",
            run["id"],
            "control",
            Control(action="play", expected_revision=1, idempotency_key=identifier()),
        )
    worker = Worker(database)
    deadline = time.monotonic() + 28
    try:
        while time.monotonic() < deadline:
            worker.tick()
            with database.sessions() as db:
                events = list(
                    db.scalars(
                        select(Event)
                        .where(Event.run_id == run["id"])
                        .order_by(Event.sequence)
                    )
                )
            if any(
                e.kind
                in ("model_response", "controller_fallback", "model_response_discarded")
                for e in events
            ):
                break
            time.sleep(0.1)
    finally:
        worker.close()
        with database.transaction() as db:
            row = db.get(Run, run["id"])
            if row.status == "running":
                mutate(
                    db,
                    "validation",
                    row.id,
                    "control",
                    Control(
                        action="pause",
                        expected_revision=row.revision,
                        idempotency_key=identifier(),
                    ),
                )
        with database.sessions() as db:
            events = list(
                db.scalars(
                    select(Event)
                    .where(Event.run_id == run["id"])
                    .order_by(Event.sequence)
                )
            )
            ledger = list(db.scalars(select(Reservation)))
            report = {
                "run_id": run["id"],
                "passed": any(e.kind == "model_response" for e in events)
                and any(
                    e.kind == "proposal_verified"
                    and e.payload["verdict"]["status"] == "pass"
                    for e in events
                ),
                "events": [
                    {"kind": e.kind, "clock": e.clock, "payload": e.payload}
                    for e in events
                    if e.kind
                    in (
                        "model_response",
                        "proposal_verified",
                        "controller_fallback",
                        "model_response_discarded",
                    )
                ],
                "aggregate_actual_usd": sum(r.actual or 0 for r in ledger),
                "aggregate_reserved_usd": sum(r.amount for r in ledger),
                "limitations": [
                    "Single fixture probe; not evidence of policy improvement"
                ],
            }
        Path("output/research-live-async.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
        print(json.dumps({k: v for k, v in report.items() if k != "events"}))
        database.close()
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

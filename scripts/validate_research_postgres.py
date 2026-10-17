"""Validate in a disposable, uniquely named schema; never mutate source tables."""

import concurrent.futures
import copy
import json
import os
import uuid
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import select
from uita.research.budget import reserve
from uita.research.contracts import Control, RunCreate
from uita.research.data import frozen_fixture, save_artifact
from uita.research.database import Budget, Checkpoint, Database, Run
from uita.research.service import create_run, mutate
from uita.research.worker import Worker


def main():
    original = os.environ["DATABASE_URL"]
    schema = "uita_validation_" + uuid.uuid4().hex[:12]
    parsed = urlsplit(original)
    query = dict(parse_qsl(parsed.query))
    query["options"] = "-csearch_path=" + schema
    target = urlunsplit(parsed._replace(query=urlencode(query)))
    source_url = original.replace("postgresql+psycopg://", "postgresql://")
    report = {"schema": schema, "checks": []}
    with psycopg.connect(source_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    database = None
    try:
        os.environ["DATABASE_URL"] = target
        command.upgrade(Config("alembic.ini"), "head")
        report["checks"].append("migration")
        database = Database(target)
        with database.transaction() as db:
            s = frozen_fixture()
            save_artifact(db, s["id"], "scenario", s)
            db.add(Budget(id="validation-v2", cap=5.0, reserved=0.0))
        cmd = RunCreate(scenario_id=s["id"], idempotency_key="parallel-create")

        def create():
            with database.transaction() as db:
                return create_run(db, "test", cmd)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda _: create(), range(4)))
        assert len({r["id"] for r in responses}) == 1
        report["checks"].append("concurrent_idempotency")
        run = responses[0]
        with database.transaction() as db:
            mutate(
                db,
                "test",
                run["id"],
                "control",
                Control(
                    expected_revision=1, idempotency_key="start-run", action="play"
                ),
            )
        first = Worker(database)
        second = Worker(database)
        assert first.tick()
        assert not second.tick()
        with database.transaction() as db:
            row = db.get(Run, run["id"])
            old_fence = row.fence
            row.lease_until = 0
            row.next_tick = 0
        assert second.tick()
        with database.sessions() as db:
            row = db.get(Run, run["id"])
            assert row.fence > old_fence and row.owner == second.id
            checkpoints = list(
                db.scalars(select(Checkpoint).where(Checkpoint.run_id == row.id))
            )
            assert checkpoints[-1].state == row.state
            saved = copy.deepcopy(row.state)
        report["checks"].append("lease_takeover_and_checkpoint_recovery")

        def spend():
            try:
                with database.transaction() as db:
                    reserve(db, "test", run["id"], 0.3)
                return True
            except ValueError:
                return False

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            paid = list(pool.map(lambda _: spend(), range(4)))
        assert sum(paid) == 1
        report["checks"].append("concurrent_budget_cap")
        # Restore serialized state into a separate run and verify a round trip.
        serialized = json.loads(json.dumps(saved))
        with database.transaction() as db:
            db.add(
                Run(
                    id=str(uuid.uuid4()),
                    team="restore",
                    revision=1,
                    state=serialized,
                    status="paused",
                )
            )
        with database.sessions() as db:
            assert db.scalar(select(Run).where(Run.team == "restore")).state == saved
        report["checks"].append("logical_checkpoint_restore")
        report["passed"] = True
    finally:
        if database:
            database.close()
        os.environ["DATABASE_URL"] = original
        with psycopg.connect(source_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )
        report["temporary_schema_removed"] = True
        Path("output").mkdir(exist_ok=True)
        Path("output/research-postgres.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
    print(json.dumps(report))


if __name__ == "__main__":
    main()

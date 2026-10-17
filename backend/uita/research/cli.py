"""Explicit administrative operations; runtime startup never migrates or creates users."""

import argparse
import getpass
import json
from pathlib import Path

from .data import digest, frozen_fixture, save_artifact
from .database import Budget, Database
from .security import add_user


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("bootstrap")
    user = sub.add_parser("user")
    user.add_argument("username")
    user.add_argument("--team", default="research")
    user.add_argument(
        "--role", choices=["viewer", "operator", "administrator"], default="operator"
    )
    args = parser.parse_args()
    database = Database()
    with database.transaction() as db:
        if args.command == "bootstrap":
            scenario = frozen_fixture()
            save_artifact(db, scenario["id"], "scenario", scenario)
            bundle = json.loads(
                (Path(__file__).parent / "assets" / "demo_bundle.json").read_text()
            )
            for artifact in bundle["artifacts"]:
                if digest(artifact["payload"]) != artifact["checksum"]:
                    raise ValueError("Bundled demo checksum mismatch")
                save_artifact(db, artifact["id"], artifact["kind"], artifact["payload"])
            if db.get(Budget, "validation-v2") is None:
                db.add(Budget(id="validation-v2", cap=5.0, reserved=0.0))
        elif args.command == "user":
            add_user(
                db,
                args.username,
                getpass.getpass("Password (12+ characters): "),
                args.team,
                args.role,
            )
    database.close()


if __name__ == "__main__":
    main()

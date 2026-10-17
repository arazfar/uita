"""Reproducible research validation; never consumes the sealed test split."""

import copy
import json
import platform
import time
from pathlib import Path

from sqlalchemy import select
from uita.research.data import digest, frozen_fixture
from uita.research.database import Artifact, Database
from uita.research.dynamics import initial_state, public_state
from uita.research.service import advance_one
from uita.research.verification import verify_motion


def evaluate(scenario, controller, seconds=1800):
    state = initial_state(scenario, 42, controller)
    state["status"] = "running"
    started = time.perf_counter()
    for _ in range(seconds):
        advance_one(state, scenario)
        if state["status"] in ("failed", "complete"):
            break
        state["_events"] = []
    return {
        "scenario_id": scenario["id"],
        "controller": controller,
        "status": state["status"],
        "simulated_seconds": state["clock"] - state["start"],
        "metrics": public_state(state)["metrics"],
        "state_hash": digest(state),
        "wall_seconds": time.perf_counter() - started,
        "last_events": state["_events"],
    }


def main():
    fixture = frozen_fixture()
    results = [evaluate(fixture, c) for c in ("fcfs", "static")]
    database = Database()
    with database.sessions() as db:
        historical = db.scalar(
            select(Artifact).where(Artifact.id == "2026-08-06-1500-research-v2")
        )
        if historical:
            results.append(evaluate(historical.payload, "static"))
    # Dense-scene check cost is measured independently from actual valid traffic capacity.
    state = initial_state(fixture, 42, "static")
    advance_one(state, fixture)
    first = state["aircraft"][0]
    state["aircraft"] = [
        {
            **copy.deepcopy(first),
            "id": str(i),
            "x_nm": (i % 20) * 10,
            "y_nm": (i // 20) * 10,
        }
        for i in range(200)
    ]
    timings = []
    for _ in range(20):
        started = time.perf_counter()
        verify_motion(state, state)
        timings.append((time.perf_counter() - started) * 1000)
    report = {
        "machine": platform.platform(),
        "results": results,
        "motion_check_200_aircraft_p95_ms": sorted(timings)[18],
        "limitations": [
            "Microbenchmark is not four concurrent hosted runs",
            "Historical scenario failures are retained, not filtered",
            "No sealed-test evaluation",
        ],
    }
    path = Path("output/research-evaluation.json")
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                **report,
                "results": [
                    {k: v for k, v in r.items() if k != "last_events"} for r in results
                ],
            }
        )
    )


if __name__ == "__main__":
    main()

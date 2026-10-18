"""Record a labeled deterministic controller demonstration with all verifier evidence."""

import gzip
import json
from pathlib import Path

from uita.research.contracts import Disruption
from uita.research.data import digest
from uita.research.dynamics import initial_state, public_state
from uita.research.presentation import frame, validate_recording
from uita.research.service import advance_one, apply_disruption

root = Path("backend/uita/research/assets")
scenario = next(
    a["payload"]
    for a in json.loads((root / "demo_bundle.json").read_text())["artifacts"]
    if a["id"] == "2026-08-06-1500-research-v2-metered"
)
state = initial_state(scenario, 42, "static")
state["status"] = "running"
frames = []
events = []
for tick in range(1501):
    if tick == 390:
        apply_disruption(
            state,
            Disruption(
                kind="runway_closure",
                runway="28R",
                expected_revision=1,
                idempotency_key="guided-closure",
            ),
        )
    for e in state["_events"]:
        events.append({**e, "sequence": len(events) + 1})
    state["_events"] = []
    if tick % 5 == 0 or state["status"] != "running":
        frames.append(
            frame(state, "guided-demo-v1", tick + 1, mode="recording").model_dump()
        )
    if state["status"] != "running" or tick == 1500:
        break
    advance_one(state, scenario)
if state["status"] == "failed" or state["metrics"]["violations"]:
    raise SystemExit(
        "Guided scenario did not pass; retain diagnostics and repair the scenario, not the verifier"
    )
baseline = [{**f, "source_id": "baseline"} for f in frames]
result = {
    "controller": "static-2",
    "metrics": public_state(state)["metrics"],
    "status": state["status"],
    "clock": state["clock"],
    "state_hash": digest(state),
}
comparison = {
    "scenario_id": scenario["id"],
    "scenario_hash": digest(scenario),
    "seed": 42,
    "results": [result, {**result, "controller": "scripted-demo (static-2)"}],
    "limitations": [
        "Scripted deterministic controller; not Nemotron output",
        "Identical baseline: no improvement claimed",
        "Passing satisfies implemented research checks, not operational ATC certification",
    ],
}
payload = {
    "frames": frames,
    "baseline_frames": baseline,
    "events": events,
    "responses": [],
    "comparison": comparison,
}
payload["manifest"] = {
    "id": "guided-demo-v1",
    "title": "San Francisco · guided runway closure",
    "scenario_id": scenario["id"],
    "scenario_checksum": digest(scenario),
    "simulator_version": state["simulator_version"],
    "rule_version": state["rule_version"],
    "policy_version": "static-2",
    "model": "Scripted deterministic controller · no model inference",
    "start": scenario["start"],
    "end": state["clock"],
    "recommended_start": scenario["start"] + 300,
    "sample_seconds": 5,
    "provenance": "fixture",
    "seed": 42,
    "outcome": "recording_complete",
    "model_responses": 0,
    "fallback_count": 0,
    "event_tape": [e for e in events if e["kind"] == "disruption"],
    "checksums": {k: digest(v) for k, v in payload.items()},
    "coverage": {
        "max_active_aircraft": max(len(f["aircraft"]) for f in frames),
        "duration_seconds": 1500,
    },
    "limitations": comparison["limitations"],
}
validate_recording(payload)
(root / "recordings").mkdir(exist_ok=True)
(root / "recordings/guided-demo-v1.json.gz").write_bytes(
    gzip.compress(json.dumps(payload, separators=(",", ":")).encode(), mtime=0)
)
print(
    json.dumps(
        {
            "outcome": state["status"],
            "metrics": result["metrics"],
            "events": len(events),
        }
    )
)

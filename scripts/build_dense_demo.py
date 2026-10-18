"""Record a labeled deterministic controller demonstration with all verifier evidence."""

import gzip
import json
import copy
import math
import statistics
from bisect import bisect_right
from pathlib import Path

from uita.research.contracts import Disruption
from uita.research.geometry import local
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
scenario = copy.deepcopy(scenario)
source_id = scenario["id"]
scenario["id"] = "early-august-dense-demo-v1"
assumptions = "Synthetic 104 NM approach corridor; seven staggered initial arrivals; 240-second replenishment; no measured controller behavior"
for i, entry in enumerate(scenario["entries"]):
    distance = 8 + 16 * i if i < 7 else 104
    entry.update(
        spawn_time=scenario["start"] + (0 if i < 7 else (i - 6) * 240),
        x_nm=distance * 0.894427,
        y_nm=-distance * 0.447214,
        altitude_ft=min(30000, distance * 318),
        groundspeed_kt=210,
        track_deg_true=297,
    )
    entry["provenance"] = {
        "kind": "synthetic",
        "generator": "dense-terminal-1",
        "source_scenario": source_id,
        "assumptions": assumptions,
    }
scenario["end"] = scenario["start"] + 1800
scenario["entries"] = [
    e for e in scenario["entries"] if e["spawn_time"] < scenario["end"]
]
scenario["provenance"] = {
    "kind": "synthetic",
    "source_scenario": source_id,
    "assumptions": assumptions,
}
scenario["coverage"] = {"entries": len(scenario["entries"]), "observed": 0}
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
            frame(state, "dense-demo-v1", tick + 1, mode="recording").model_dump()
        )
    if state["status"] != "running" or tick == 1500:
        break
    advance_one(state, scenario)
if state["status"] == "failed" or state["metrics"]["violations"]:
    raise SystemExit(
        "Guided scenario did not pass; retain diagnostics and repair the scenario, not the verifier"
    )
# Independently execute the same policy, seed and disruption tape.
baseline_state = initial_state(scenario, 42, "static")
baseline_state["status"] = "running"
baseline = []
for tick in range(1501):
    if tick == 390:
        apply_disruption(
            baseline_state,
            Disruption(
                kind="runway_closure",
                runway="28R",
                expected_revision=1,
                idempotency_key="guided-closure",
            ),
        )
    baseline_state["_events"] = []
    if tick % 5 == 0:
        baseline.append(
            frame(baseline_state, "baseline", tick + 1, mode="recording").model_dump()
        )
    if tick < 1500:
        advance_one(baseline_state, scenario)
assert digest(state) == digest(baseline_state), "Deterministic replay diverged"
counts = [
    sum(
        a["status"] in ("approach", "holding", "go_around")
        and a["altitude_ft"] is not None
        and math.hypot(*local(a["longitude"], a["latitude"])) <= 110
        for a in f["aircraft"]
    )
    for f in frames
    if f["clock"] >= scenario["start"] + 300
]
coverage = {
    "airborne_min": min(counts),
    "airborne_median": statistics.median(counts),
    "airborne_peak": max(counts),
    "fraction_6_to_10": sum(6 <= c <= 10 for c in counts) / len(counts),
    "region": "Within 110 NM of SFO",
    "presentation_seconds": 1200,
}
assert coverage["fraction_6_to_10"] >= 0.8, coverage
# Same geographic extent and 60-second observation freshness as historical playback.
histories = json.loads(gzip.decompress((root / "showcase_data.json.gz").read_bytes()))
coverage["historical"] = []
for artifact in histories["artifacts"]:
    if artifact["kind"] != "history_window":
        continue
    history = artifact["payload"]
    tracks = [(t["points"], [p["t"] for p in t["points"]]) for t in history["tracks"]]
    observed = []
    for tick in range(history["start"], history["end"], 5):
        count = 0
        for points, times in tracks:
            i = bisect_right(times, tick) - 1
            if i < 0:
                continue
            p = points[i]
            if (
                tick - p["t"] <= 60
                and p.get("altitude_ft") is not None
                and p["altitude_ft"] > 0
                and math.hypot(*local(p["lon"], p["lat"])) <= 110
            ):
                count += 1
        observed.append(count)
    coverage["historical"].append(
        {
            "id": history["id"],
            "min": min(observed),
            "median": statistics.median(observed),
            "peak": max(observed),
        }
    )
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
    "id": "dense-demo-v1",
    "title": "San Francisco · busy arrivals · synthetic",
    "scenario_id": scenario["id"],
    "scenario_checksum": digest(scenario),
    "simulator_version": state["simulator_version"],
    "rule_version": state["rule_version"],
    "policy_version": "static-2",
    "model": "Deterministic demo controller · no model inference",
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
        **coverage,
    },
    "limitations": comparison["limitations"],
}
validate_recording(payload)
(root / "recordings").mkdir(exist_ok=True)
(root / "recordings/dense-demo-v1.json.gz").write_bytes(
    gzip.compress(json.dumps(payload, separators=(",", ":")).encode(), mtime=0)
)
artifact = {
    "id": scenario["id"],
    "kind": "scenario",
    "payload": scenario,
    "checksum": digest(scenario),
}
pack = {
    "version": "dense-demo-v1",
    "artifacts": [artifact],
    "checksum": digest([artifact]),
}
(root / "dense_demo.json.gz").write_bytes(
    gzip.compress(json.dumps(pack, separators=(",", ":")).encode(), mtime=0)
)
print(json.dumps(coverage))
print(
    json.dumps(
        {
            "outcome": state["status"],
            "metrics": result["metrics"],
            "events": len(events),
        }
    )
)

"""Deterministic 0-1 reward against the CP-SAT closed-loop reference."""
from __future__ import annotations

import json
import math
from pathlib import Path

from . import ENV_ID  # noqa: F401  (ensures sys.path is set up)

REFERENCE_DIR = Path(__file__).resolve().parent / "references"
REFERENCE_LABEL = ("CP-SAT closed-loop reference, per-decision optimisation; "
                   "not a proven global optimum")
REWARD_FORMULA = ("0.0 if executed safety violations > 0; "
                  "0.2 * accepted_decisions / total_decisions if any submitted plan was rejected/invalid (fallback used); "
                  "else 0.2 + 0.8 * exp(-max(gap, 0) / 0.5), capped at 1.0, "
                  "gap = (agent_penalized - ref_penalized) / max(ref_penalized, 600)")
GAP_SCALE = 0.5
GAP_FLOOR_SECONDS = 600.0

_cache: dict[str, dict] = {}


def reference_record(outcome: dict) -> dict:
    return {
        "penalized_added_delay_seconds": outcome["penalized_added_delay_seconds"],
        "backlog": outcome["backlog"],
        "completed": outcome["completed"],
        "spawned": outcome["spawned"],
        "executed_violations": outcome["executed_violations"],
        "landing_seconds": {f["id"]: f["landing_seconds"] for f in outcome["flights"]},
    }


def compute_reference(episode: dict) -> dict:
    from benchmark.closed_loop.engine import simulate
    return reference_record(simulate(episode, "deterministic"))


def load_references(split: str) -> dict:
    if split not in _cache:
        path = REFERENCE_DIR / f"{split}.json"
        _cache[split] = json.loads(path.read_text())["references"] if path.exists() else {}
    return _cache[split]


def get_reference(split: str, episode: dict) -> dict:
    refs = load_references(split)
    if episode["id"] not in refs:
        refs[episode["id"]] = compute_reference(episode)  # fall back to computing
    return refs[episode["id"]]


def grade(outcome: dict, reference: dict) -> dict:
    decisions = outcome["decisions"]
    total = len(decisions)
    accepted = sum(1 for d in decisions if d["proposal_status"] == "pass" and not d["controller_failure"])
    rejected = total - accepted
    agent = outcome["penalized_added_delay_seconds"]
    ref = reference["penalized_added_delay_seconds"]
    gap = (agent - ref) / max(ref, GAP_FLOOR_SECONDS)
    violations = outcome["executed_violations"]
    beat = False
    if violations > 0:
        reward, reason = 0.0, "executed_safety_violation"
    elif rejected > 0:
        reward, reason = 0.2 * accepted / total, "fallback_used"
    else:
        reward = min(1.0, 0.2 + 0.8 * math.exp(-max(gap, 0.0) / GAP_SCALE))
        beat = agent < ref
        reason = "scored_against_reference"
    return {
        "reward": round(reward, 6), "reason": reason,
        "executed_violations": violations, "safety_eligible": bool(outcome["safety_eligible"]),
        "rejected_plans": rejected, "accepted_decisions": accepted, "total_decisions": total,
        "penalized_added_delay_seconds": agent, "reference_penalized_added_delay_seconds": ref,
        "gap": round(gap, 6), "beat_reference": beat,
        "backlog": outcome["backlog"], "reference_backlog": reference["backlog"],
        "completed": outcome["completed"], "reference_completed": reference["completed"],
        "spawned": outcome["spawned"],
        "reference": REFERENCE_LABEL, "reward_formula": REWARD_FORMULA,
    }

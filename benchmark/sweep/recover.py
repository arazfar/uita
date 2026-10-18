"""Resume audited transport-interrupted jobs without repeating paid requests.

The frozen controller already persists an ambiguous result in ``finally`` when
http.client.IncompleteRead escapes. This wrapper converts that particular saved
failure to the existing None/fallback contract. Prior fallback commitments can
be reconstructed from the next already-recorded causal public state; they are
never replaced by another optimizer result.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import http.client
import json
import os
from pathlib import Path
import time

from benchmark.closed_loop import controllers, engine
from benchmark.provider import ProviderError, canonical, digest
from .models import SweepController
from .run import ROOT, read, row_path, sha, write
from .traffic import load_episodes

VERSION = "historical-admission-incomplete-read-recovery-v1"


class NeedsDispatch(RuntimeError):
    pass


class InterruptedResponseController(SweepController):
    """Preserve frozen payload/audit logic and handle one missing transport case."""
    def __init__(self, *args, execute=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.execute = execute
        self.recovery_reused = 0
        self.recovery_incomplete_reads = []
        self.recovery_new_decisions = 0

    def choose(self, view, request_id):
        identifier = self.config_id + ":" + request_id
        cached = identifier in self._cache
        if not cached and not self.execute:
            raise NeedsDispatch("Recovery reached its first uncached decision; no request was dispatched")
        if cached:
            self.recovery_reused += 1
        else:
            self.recovery_new_decisions += 1
        try:
            return super().choose(view, request_id)
        except http.client.IncompleteRead:
            # The original finally block must have durably recorded the failed
            # dispatch before it is safe to treat it as the normal fallback.
            record = self._cache.get(identifier)
            if (not isinstance(record, dict) or record.get("status") != "ambiguous_failure"
                    or record.get("dispatched") is not True or record.get("payload_sha256") is None
                    or record.get("cost_usd") is not None):
                raise ProviderError("Incomplete-read recovery lacks the frozen ambiguous dispatch audit") from None
            persisted = self.ledger.lookup(identifier)
            if persisted != record:
                raise ProviderError("Incomplete-read recovery audit differs from its durable reservation")
            self.recovery_incomplete_reads.append({"request_id": identifier,
                                                   "payload_sha256": record["payload_sha256"],
                                                   "exception": "http.client.IncompleteRead",
                                                   "treatment": "Original ambiguous failure retained; no retry; ordinary checked fallback"})
            return None


def _audit_records(path):
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if len({call["request_id"] for call in records}) != len(records):
        raise ValueError("Recovery source contains repeated request IDs")
    return records


def _commit_slots(state, next_call):
    public = json.loads(next_call["request"]["messages"][1]["content"])
    engine_ai = __import__("benchmark.closed_loop.ai", fromlist=["validate_view"])
    engine_ai.validate_view(public)
    if public["clock_seconds"] <= state["time"]:
        raise ValueError("Recovered commitment evidence must come from a later recorded state")
    pending = {a["id"]: a for a in public["pending"]}
    active = {a["id"]: a for a in public["active_commitments"]}
    if state["closed_runways"] or any(a["runway"] != "28L" for a in state["aircraft"]):
        raise ValueError("Pending commitment runway cannot be uniquely reconstructed")
    slots = []
    for aircraft in state["aircraft"]:
        aid = aircraft["id"]
        if aid in active:
            value, runway = active[aid]["landing_seconds"], active[aid]["runway"]
        elif aid in pending and pending[aid]["current_slot_seconds"] is not None:
            value, runway = pending[aid]["current_slot_seconds"], aircraft["runway"]
        else:
            raise ValueError("Later causal view does not reveal every prior committed aircraft")
        slots.append({"aircraft_id": aid, "runway": runway, "time": value})
    return slots


def _recovered_proposal(state, horizon, next_call):
    slots = _commit_slots(state, next_call)
    by_id = {slot["aircraft_id"]: slot for slot in slots}
    unfinished = sum(by_id[a["id"]]["time"] + a["exit_occupancy"] + 90 > horizon for a in state["aircraft"])
    delay = sum(by_id[a["id"]]["time"] - a["requested"] for a in state["aircraft"])
    weight = len(state["aircraft"]) * controllers.SLOT_LIMIT_SECONDS + 1
    result = controllers._base_plan(state, "deterministic")
    result.update(status="proposed", slots=slots, solver={
        "status": "RECOVERED_FEASIBLE", "optimal": False,
        "objective_order": ["unfinished_aircraft_at_horizon", "sum_landing_delay_seconds"],
        "unfinished_weight": weight, "unfinished_aircraft": unfinished,
        "sum_landing_delay_seconds": delay,
        "objective": weight * unfinished + sum(slot["time"] for slot in slots),
        "original_solver_status": None, "original_solver_best_bound": None,
        "original_solver_wall_seconds": None,
        "recovery_source_request_id": next_call["request_id"],
        "recovery_source_payload_sha256": next_call["payload_sha256"],
        "recovery_scope": "Exact prior applied commitment reconstructed from the next recorded causal public state; original solver status, bound and elapsed time were not serialized",
    })
    return result


def recover_job(run, config_id, episode_id, *, execute=False):
    run = Path(run)
    plan = read(run / "plan.json")
    configuration = next(c for c in plan["configurations"] if c["id"] == config_id)
    episode = next(e for e in load_episodes("evaluation") if e["id"] == episode_id)
    for name, expected in plan["source_hashes"].items():
        if sha(ROOT / name) != expected:
            raise ValueError("Frozen source differs before recovery: " + name)
    target = row_path(run, config_id, episode_id)
    if target.exists():
        return {"status": "already_complete", "config_id": config_id, "episode_id": episode_id}
    directory = run / "configs" / config_id / "episodes" / episode_id
    if not (directory / "calls.jsonl").exists():
        raise ValueError("Recovery requires existing paid-call audit evidence")
    lock = directory / ".recovery.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError("Another recovery owns this incomplete job; inspect its lock") from None
    os.write(descriptor, str(os.getpid()).encode())
    os.close(descriptor)
    recovery_dir = directory / "recovery"
    recovery_dir.mkdir(exist_ok=True)
    original_audit = recovery_dir / "original-calls.jsonl"
    original_progress = recovery_dir / "original-progress.jsonl"
    if not original_audit.exists():
        original_audit.write_bytes((directory / "calls.jsonl").read_bytes())
        original_progress.write_bytes((directory / "progress.jsonl").read_bytes())
    prior_calls = _audit_records(original_audit)
    if not prior_calls or prior_calls[-1].get("status") != "ambiguous_failure":
        lock.unlink()
        raise ValueError("Recovery source does not end in an audited ambiguous transport failure")
    progress = [json.loads(line) for line in original_progress.read_text().splitlines() if line.strip()]
    progressed = {record["time"]: record for record in progress}
    recovered = {}
    for index, call in enumerate(prior_calls[:-1]):
        public = json.loads(call["request"]["messages"][1]["content"])
        now = public["clock_seconds"]
        if call["status"] != "completed":
            applied = progressed.get(now)
            if not applied or applied.get("applied_status") != "pass" or applied.get("fallback") is not True:
                lock.unlink()
                raise ValueError("Prior failed action lacks a successfully applied fallback observation")
            recovered[now] = prior_calls[index + 1]
    source_hash = sha(Path(__file__))
    source_copy = run / "recovery_sources" / (source_hash + ".py")
    source_copy.parent.mkdir(exist_ok=True)
    if not source_copy.exists():
        source_copy.write_bytes(Path(__file__).read_bytes())
    manifest_path = run / "recoveries" / config_id / (episode_id + ".json")
    manifest = {"version": VERSION, "configuration": config_id, "episode_id": episode_id,
                "status": "running" if execute else "dry_run", "execute": execute,
                "source_sha256": source_hash, "source_snapshot": str(source_copy.relative_to(run)),
                "original_calls_sha256": sha(original_audit), "original_progress_sha256": sha(original_progress),
                "original_calls": len(prior_calls), "reconstructed_fallback_clock_seconds": sorted(recovered),
                "original_source_hashes_unchanged": True, "started_at_epoch": time.time(),
                "paid_retry_policy": "No repeated POST. Reuse every prior audit with an identical payload; only genuinely new decision IDs may dispatch.",
                "change": "Catch http.client.IncompleteRead only after durable ambiguous audit; preserve unknown cost and use existing checked fallback policy"}
    write(manifest_path, manifest)
    original_propose = engine.propose
    ai = None
    try:
        ai = InterruptedResponseController(directory, configuration, ledger_path=run / "budget.sqlite3",
                                           budget_id=plan["budget"]["id"], cap_usd=plan["budget"]["cap_usd"], execute=execute)
        replayed = set()

        def propose(state, controller, horizon, order=None):
            if controller == "deterministic" and state["time"] in recovered:
                if state["time"] in replayed:
                    raise ValueError("Recovered fallback was applied more than once")
                replayed.add(state["time"])
                return _recovered_proposal(state, horizon, recovered[state["time"]])
            return original_propose(state, controller, horizon, order=order)

        def emit(record):
            with (recovery_dir / "progress.jsonl").open("a") as stream:
                stream.write(canonical(record) + "\n")

        engine.propose = propose
        row = engine.simulate(episode, "ai", ai=ai, emit=emit)
        if replayed != set(recovered):
            raise ValueError("Some prior observed fallback commitments were not reconstructed")
        row.update(controller=config_id, engine_controller="ai")
        if not execute:
            raise ValueError("Dry-run unexpectedly completed a previously incomplete window")
        for name, expected in plan["source_hashes"].items():
            if sha(ROOT / name) != expected:
                raise ValueError("Frozen source changed during recovery: " + name)
        write(directory / "usage.json", ai.summary())
        write(target, row)
        manifest.update(status="completed", result_sha256=sha(target), result=str(target.relative_to(run)),
                        completed=row["completed"], spawned=row["spawned"], fallback_decisions=row["fallback_decisions"])
    except NeedsDispatch:
        manifest.update(status="dry_run_passed_to_first_new_decision")
    except Exception as error:
        manifest.update(status="incomplete", error_type=type(error).__name__)
        raise
    finally:
        engine.propose = original_propose
        if ai:
            manifest.update(reused_cached_decisions=ai.recovery_reused, new_decision_attempts=ai.recovery_new_decisions,
                            new_incomplete_reads=ai.recovery_incomplete_reads,
                            final_audit_sha256=sha(directory / "calls.jsonl"))
        manifest["finished_at_epoch"] = time.time()
        write(manifest_path, manifest)
        lock.unlink(missing_ok=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--episode", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    print(json.dumps(recover_job(args.run, args.config, args.episode, execute=args.execute)), flush=True)


if __name__ == "__main__":
    main()

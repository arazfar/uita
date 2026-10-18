"""Durable leased run clock and comparison worker; one owner per run."""

import copy
import logging
import signal
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from .contracts import Disruption
from .controller import propose
from .data import digest
from .database import Database, Job, Run
from .dynamics import SIMULATOR_VERSION, event, initial_state, public_state
from .inference import generate
from .service import (
    advance_one,
    apply_disruption,
    apply_proposal,
    persist,
    scenario_for,
)
from .standards import VERSION

log = logging.getLogger(__name__)


class Worker:
    def __init__(self, database, capture_campaign=None):
        self.capture_campaign = capture_campaign
        self.database = database
        self.id = str(uuid.uuid4())
        self.stopped = False
        self.inference_pool = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="uita-inference"
        )
        self.pending = {}
        self.job_pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="uita-comparison"
        )
        self.pending_job = None

    def tick(self):
        self.collect_inference()
        now = time.time()
        with self.database.transaction() as db:
            run = db.scalar(
                select(Run)
                .where(
                    Run.status == "running",
                    Run.next_tick <= now,
                    (Run.lease_until < now) | (Run.owner == self.id),
                )
                .order_by(Run.next_tick, Run.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if run is None:
                return False
            if run.owner != self.id:
                run.fence += 1
            run.owner = self.id
            run.lease_until = now + 45
            state = copy.deepcopy(run.state)
            scenario = scenario_for(db, state["scenario_id"])
            compatible = (
                state["simulator_version"] == SIMULATOR_VERSION
                and state["rule_version"] == VERSION
            )
            if not compatible:
                state["status"] = "paused"
                event(
                    state,
                    "runtime_incompatible",
                    simulator_version=state["simulator_version"],
                    rule_version=state["rule_version"],
                )
            for _ in range(state["speed"] if compatible else 0):
                advance_one(state, scenario)
                if state["status"] != "running":
                    break
            request_model = (
                state["controller"] == "crusoe"
                and state["status"] == "running"
                and any(
                    a["status"] in ("approach", "runway", "holding")
                    for a in state["aircraft"]
                )
                and state["clock"] - state["last_model_clock"] >= 30
                and run.id not in self.pending
                and len(self.pending) < 4
            )
            if request_model:
                state["last_model_clock"] = state["clock"]
            persist(db, run, state)
            run.next_tick = now + 1
            run_id, team, fence, revision = run.id, run.team, run.fence, run.revision
        if request_model:
            future = self.inference_pool.submit(
                generate, self.database, run_id, team, state, self.capture_campaign
            )
            self.pending[run_id] = (
                future,
                fence,
                revision,
                state["clock"],
                state.get("command_epoch", 0),
            )
        return True

    def collect_inference(self):
        for run_id, pending in list(self.pending.items()):
            future, fence, revision, clock, epoch = pending
            if not future.done():
                continue
            del self.pending[run_id]
            try:
                proposal, metadata = future.result()
                failure = None
            except Exception as exc:
                proposal, metadata, failure = (
                    None,
                    {},
                    getattr(exc, "reason", "inference_internal_error"),
                )
            with self.database.transaction() as db:
                run = db.scalar(select(Run).where(Run.id == run_id).with_for_update())
                if (
                    run is None
                    or run.owner != self.id
                    or run.fence != fence
                    or run.lease_until < time.time()
                ):
                    continue
                current = copy.deepcopy(run.state)
                if failure:
                    current["controller"] = "static"
                    current["fallback_reason"] = failure
                    event(
                        current,
                        "controller_fallback",
                        reason=failure,
                        policy_version=current["policy_version"],
                    )
                elif (
                    run.status != "running"
                    or current.get("command_epoch", 0) != epoch
                    or current["clock"] - clock > 15
                ):
                    event(
                        current,
                        "model_response_discarded",
                        reason="Observation expired or user intervened",
                        metadata=metadata,
                        proposal=proposal.model_dump(),
                    )
                else:
                    # An asynchronous suggestion becomes a NEW proposal against current
                    # state, with a fresh independent prediction before atomic commit.
                    event(
                        current,
                        "model_response",
                        metadata=metadata,
                        proposal=proposal.model_dump(),
                        input_revision=revision,
                        input_clock=clock,
                        verified_revision=run.revision,
                    )
                    if proposal.sequence and not proposal.clearances:
                        proposal = propose(current, proposal.sequence)
                    verdict = apply_proposal(current, proposal)
                    if verdict["status"] != "pass":
                        fallback = propose(current)
                        event(current, "proposal_fallback", reason=verdict["status"])
                        if fallback.clearances:
                            apply_proposal(current, fallback)
                persist(db, run, current)

    def job(self):
        now = time.time()
        with self.database.transaction() as db:
            job = db.scalar(
                select(Job)
                .where(
                    (Job.status == "queued")
                    | ((Job.status == "running") & (Job.lease_until < now))
                )
                .order_by(Job.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                return False
            job.status = "running"
            job.owner = self.id
            job.fence += 1
            job.lease_until = now + 45
            job_id, fence, payload = job.id, job.fence, copy.deepcopy(job.payload)
            scenario = copy.deepcopy(scenario_for(db, payload["scenario_id"]))
        try:
            self.execute_job(job_id, fence, payload, scenario)
        except Exception as exc:
            with self.database.transaction() as db:
                job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
                if (
                    job.owner == self.id
                    and job.fence == fence
                    and job.lease_until >= time.time()
                ):
                    job.status = "failed"
                    job.result = {
                        "reason": "comparison_failed",
                        "error_type": type(exc).__name__,
                    }
            log.error(
                "Comparison failed",
                extra={"job_id": job_id, "error_type": type(exc).__name__},
            )
        return True

    def execute_job(self, job_id, fence, payload, scenario):
        results = []
        for controller in payload["controllers"]:
            state = initial_state(scenario, payload["seed"], controller)
            state["status"] = "running"
            evidence = []
            tape = copy.deepcopy(payload.get("event_tape", []))
            cursor = 0
            for tick in range(payload["seconds"]):
                if self.stopped:
                    return  # Lease expires; another worker recomputes the same job.
                while cursor < len(tape) and tape[cursor]["clock"] <= state["clock"]:
                    apply_disruption(state, Disruption(**tape[cursor]["payload"]))
                    cursor += 1
                advance_one(state, scenario)
                evidence.extend(state.pop("_events", []))
                state["_events"] = []
                if tick % 20 == 0:
                    with self.database.transaction() as db:
                        job = db.scalar(
                            select(Job).where(Job.id == job_id).with_for_update()
                        )
                        if (
                            job.owner != self.id
                            or job.fence != fence
                            or job.lease_until < time.time()
                        ):
                            return
                        job.lease_until = time.time() + 45
                if state["status"] != "running":
                    break
            results.append(
                {
                    "controller": controller,
                    "status": state["status"],
                    "clock": state["clock"],
                    "metrics": public_state(state)["metrics"],
                    "state_hash": digest(state),
                    "events": evidence,
                }
            )
        candidate = payload.get("candidate")
        if candidate:
            results.append(candidate)
        with self.database.transaction() as db:
            job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
            if (
                job.owner == self.id
                and job.fence == fence
                and job.lease_until >= time.time()
            ):
                job.status = "complete"
                job.result = {
                    "scenario_id": scenario["id"],
                    "scenario_hash": digest(scenario),
                    "seed": payload["seed"],
                    "simulator_version": SIMULATOR_VERSION,
                    "rule_version": VERSION,
                    "source_run_id": payload.get("source_run_id"),
                    "source_revision": payload.get("source_revision"),
                    "event_tape": payload.get("event_tape", []),
                    "results": results,
                    "limitations": [
                        "Fixed simulation horizon; unfinished traffic counts as backlog",
                        "Research checks and synthetic aircraft performance",
                        "Candidate is a frozen executed run; baseline replays the same timed disruptions without inference",
                    ],
                }

    def dispatch_job(self):
        if self.pending_job is not None:
            if not self.pending_job.done():
                return
            self.pending_job.result()
        self.pending_job = self.job_pool.submit(self.job)

    def close(self):
        self.stopped = True
        self.inference_pool.shutdown(wait=True, cancel_futures=True)
        self.job_pool.shutdown(wait=True, cancel_futures=True)

    def run(self):
        while not self.stopped:
            try:
                worked = self.tick()
                self.dispatch_job()
                if not worked:
                    time.sleep(0.2)
            except Exception:
                log.exception("Worker iteration failed")
                time.sleep(1)


def main():
    logging.basicConfig(level=logging.INFO)
    database = Database()
    worker = Worker(database)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: setattr(worker, "stopped", True))
    try:
        worker.run()
    finally:
        worker.close()
        database.close()


if __name__ == "__main__":
    main()

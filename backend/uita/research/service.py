"""Transactional run commands. All externally visible mutations are journaled."""

import copy
import time
import uuid

from sqlalchemy import select, text

from .contracts import ControllerProposal
from .controller import propose
from .data import digest
from .database import Artifact, Checkpoint, Command, Event, Run
from .dynamics import event, initial_state, issue, public_state, step
from .verification import check, result, verify_clearance, verify_motion


def identifier():
    return str(uuid.uuid4())


def get_run(db, run_id, team, lock=False):
    query = select(Run).where(Run.id == run_id, Run.team == team)
    if lock:
        query = query.with_for_update()
    run = db.scalar(query)
    if run is None:
        raise LookupError("Run not found")
    return run


def scenario_for(db, identifier):
    artifact = db.get(Artifact, identifier)
    if artifact is None or artifact.kind != "scenario":
        raise LookupError("Scenario not found")
    if artifact.checksum != digest(artifact.payload):
        raise ValueError("Scenario integrity check failed")
    if artifact.payload["split"] == "test":
        raise PermissionError("Sealed test scenario unavailable to interactive runs")
    return artifact.payload


def view(run):
    return {
        "id": run.id,
        "revision": run.revision,
        "status": run.status,
        "state": public_state(run.state),
    }


def previous(db, key, payload):
    if db.bind.dialect.name == "postgresql":
        lock_id = int(digest(key)[:16], 16)
        if lock_id >= 2**63:
            lock_id -= 2**64
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})
    prior = db.get(Command, key)
    if prior:
        if prior.fingerprint != digest(payload):
            raise ValueError("Idempotency key reused with different command")
        return prior.response


def record(db, key, payload, response):
    db.add(Command(key=key, fingerprint=digest(payload), response=response))


def persist(db, run, state, checkpoint=True):
    state = copy.deepcopy(state)
    for item in state.pop("_events", []):
        state["event_sequence"] += 1
        db.add(
            Event(
                id=identifier(), run_id=run.id, sequence=state["event_sequence"], **item
            )
        )
    state["_events"] = []
    run.revision += 1
    run.state = state
    run.status = state["status"]
    if checkpoint:
        db.add(
            Checkpoint(
                id=identifier(), run_id=run.id, revision=run.revision, state=state
            )
        )


def create_run(db, team, command):
    key = team + ":create:" + command.idempotency_key
    prior = previous(db, key, command.model_dump())
    if prior:
        return prior
    scenario = scenario_for(db, command.scenario_id)
    state = initial_state(scenario, command.seed, command.controller)
    state["spend_cap_usd"] = command.spend_cap_usd
    state["fixture_fault"] = command.fixture_fault
    run = Run(id=identifier(), team=team, revision=0, state={}, status="paused")
    db.add(run)
    event(
        state,
        "run_created",
        scenario_hash=state["scenario_hash"],
        seed=command.seed,
        controller=command.controller,
    )
    persist(db, run, state)
    response = view(run)
    record(db, key, command.model_dump(), response)
    return response


def apply_proposal(state, proposal, execute=True):
    trial = copy.deepcopy(state)
    checks = []
    active_ids = {
        a["id"]
        for a in state["aircraft"]
        if a["status"] not in ("complete", "diverted")
    }
    if (
        len(proposal.sequence) != len(set(proposal.sequence))
        or not set(proposal.sequence) <= active_ids
    ):
        raise ValueError("Sequence contains duplicate or unknown aircraft")
    for command in proposal.clearances:
        verdict = verify_clearance(trial, command)
        checks.extend(verdict["checks"])
        if verdict["status"] == "pass":
            issue(trial, command.model_dump())
    if checks and result(checks)["status"] == "pass":
        prediction = copy.deepcopy(trial)
        # Predict only currently observed traffic. Never read the private future queue.
        prediction_scenario = {
            "entries": [],
            "weather": [copy.deepcopy(trial["weather"])],
        }
        for _ in range(30):
            before = copy.deepcopy(prediction)
            step(prediction, prediction_scenario)
            motion = verify_motion(before, prediction)
            if motion["status"] != "pass":
                checks.extend(motion["checks"])
                break
            prediction["_events"] = []
        else:
            checks.append(
                check(
                    "separation",
                    "pass",
                    "Current-traffic prediction passed",
                    horizon_seconds=30,
                    future_traffic_included=False,
                )
            )
    verdict = result(checks)
    if verdict["status"] == "pass" and execute:
        state.clear()
        state.update(trial)
    event(state, "proposal_verified", proposal=proposal.model_dump(), verdict=verdict)
    if verdict["status"] != "pass":
        state["metrics"][
            "unresolved" if verdict["status"] == "unresolved" else "rejected"
        ] += 1
    return verdict


def advance_one(state, scenario):
    before = copy.deepcopy(state)
    step(state, scenario)
    verdict = verify_motion(before, state)
    if verdict["status"] != "pass":
        state["metrics"]["violations"] += len(
            [c for c in verdict["checks"] if c["status"] == "fail"]
        )
        state["status"] = "failed"
        event(state, "motion_failed", verdict=verdict)
        return
    if (
        state["controller"] not in ("crusoe", "fixture")
        and int(state["clock"] - state["start"]) % 5 == 0
    ):
        proposal = propose(state)
        if proposal.clearances:
            apply_proposal(state, proposal)
    if (
        state["controller"] == "fixture"
        and state["clock"] - state["last_model_clock"] >= 30
    ):
        from .inference import InferenceFailure, fixture_proposal

        state["last_model_clock"] = state["clock"]
        try:
            proposal = fixture_proposal(state)
            event(
                state,
                "model_response",
                proposal=proposal.model_dump(),
                metadata={
                    "mode": "fixture",
                    "policy": "fixture-runway-preference-1",
                    "cost_usd": 0,
                },
            )
            verdict = apply_proposal(state, proposal)
            if verdict["status"] != "pass":
                event(state, "proposal_fallback", reason=verdict["status"])
                fallback = propose(state)
                if fallback.clearances:
                    apply_proposal(state, fallback)
        except InferenceFailure as exc:
            state["controller"] = "static"
            state["fallback_reason"] = exc.reason
            event(
                state,
                "controller_fallback",
                reason=exc.reason,
                mode="fixture_fault_injection",
                cost_usd=0,
            )


def mutate(db, team, run_id, operation, command):
    run = get_run(db, run_id, team, lock=True)
    payload = {"operation": operation, **command.model_dump()}
    key = team + ":" + run_id + ":" + command.idempotency_key
    prior = previous(db, key, payload)
    if prior:
        return prior
    if run.revision != command.expected_revision:
        raise ValueError("Stale revision; refresh the run")
    state = copy.deepcopy(run.state)
    if state["status"] in ("failed", "complete"):
        raise ValueError(
            "Finished or failed runs are immutable; fork a prior checkpoint"
        )
    state["command_epoch"] = state.get("command_epoch", 0) + 1
    if operation == "control":
        if command.action == "play":
            state["status"] = "running"
            run.next_tick = time.time()
        elif command.action == "pause":
            state["status"] = "paused"
        elif command.action == "speed":
            state["speed"] = command.speed
        else:
            state["status"] = "paused"
            scenario = scenario_for(db, state["scenario_id"])
            for _ in range(command.seconds):
                advance_one(state, scenario)
                if state["status"] in ("failed", "complete"):
                    break
        event(state, "control", action=command.action)
    elif operation == "disruption":
        apply_disruption(state, command)
    elif operation == "propose":
        proposal = command.proposal
        verdict = apply_proposal(state, proposal, execute=False)
        state["pending_proposal"] = {
            "id": identifier(),
            "proposal": proposal.model_dump(),
            "verdict": verdict,
            "state_hash": digest(run.state),
            "revision": run.revision + 1,
            "clock": state["clock"],
        }
    elif operation == "commit":
        pending = state.get("pending_proposal")
        if (
            not pending
            or pending["id"] != command.proposal_id
            or pending["revision"] != run.revision
            or pending["clock"] != state["clock"]
        ):
            raise ValueError("Proposal expired or does not match this revision")
        apply_proposal(state, ControllerProposal(**pending["proposal"]))
        state.pop("pending_proposal", None)
    else:
        raise ValueError("Unsupported operation")
    persist(db, run, state)
    response = view(run)
    record(db, key, payload, response)
    return response


def fork(db, team, run_id, command):
    parent = get_run(db, run_id, team, lock=True)
    key = team + ":" + run_id + ":fork:" + command.idempotency_key
    prior = previous(db, key, command.model_dump())
    if prior:
        return prior
    if parent.revision != command.expected_revision:
        raise ValueError("Stale revision")
    checkpoint = db.scalar(
        select(Checkpoint).where(
            Checkpoint.run_id == run_id,
            Checkpoint.revision == command.checkpoint_revision,
        )
    )
    if checkpoint is None:
        raise LookupError("Checkpoint not found")
    state = copy.deepcopy(checkpoint.state)
    state.update(
        status="paused",
        event_sequence=0,
        parent_run=run_id,
        parent_revision=checkpoint.revision,
        _events=[],
    )
    state.pop("pending_proposal", None)
    run = Run(id=identifier(), team=team, revision=0, state={}, status="paused")
    db.add(run)
    event(state, "run_forked", parent_run=run_id, parent_revision=checkpoint.revision)
    persist(db, run, state)
    response = view(run)
    record(db, key, command.model_dump(), response)
    return response


def apply_disruption(state, command):
    if state["status"] in ("failed", "complete"):
        raise ValueError("Finished run cannot be changed")
    if command.kind == "runway_closure":
        affected = []
        if command.runway not in state["closed_runways"]:
            state["closed_runways"].append(command.runway)
        for a in state["aircraft"]:
            if a["runway"] == command.runway and a["status"] == "approach":
                a["landing_authorized"] = False
                a["status"] = "go_around"
                a["target_altitude_ft"] = max(4000, a["altitude_ft"])
                affected.append(a["id"])
        for c in state["clearances"]:
            if c.get("target") == command.runway and c["status"] in (
                "issued",
                "corrected",
                "executing",
                "completed",
            ):
                c["status"] = "cancelled"
        event(
            state,
            "runway_closure_response",
            runway=command.runway,
            aircraft=affected,
            decision="Cancel landing authority on the closed runway; existing airborne motion continues on the synthetic go-around contingency.",
            limitation="Contingency is a research assumption; published missed-approach and MVA authority remain unresolved.",
        )
    elif command.kind == "weather":
        state["weather_override"] = {
            **state["weather"],
            "visibility_sm": command.value,
            "available": True,
            "stale": False,
            "observed_at": state["clock"],
            "available_at": state["clock"],
            "provenance": "synthetic intervention",
        }
    elif command.kind == "readback_error":
        state["readback_error"] = True
    elif command.kind == "communications":
        state["communications_delay"] = command.value
    elif command.kind == "emergency":
        a = next((a for a in state["aircraft"] if a["id"] == command.aircraft_id), None)
        if a is None:
            raise ValueError("Select an active aircraft")
        a["emergency"] = True
    event(state, "disruption", **command.model_dump())

"""SFOArrivalEnv-v1: stepped version of benchmark.closed_loop.engine.simulate.

The agent is the controller at each 300 s decision point. Everything else (spawn
release, weather, verifier, scripted fallback, outcome audit) is the trusted loop.
"""
from __future__ import annotations

import hashlib

from . import ENV_ID
from benchmark.closed_loop.controllers import propose
from benchmark.closed_loop.engine import (CONFIG, add_aircraft, canonical, commit, initial_state, outcome,
                                          view_for)
from benchmark.closed_loop.traffic import available_weather, load_episodes
from backend.uita.airport import RULE_VERSION
from backend.uita.verifier import verify

from .grader import REFERENCE_LABEL, REWARD_FORMULA, get_reference, grade

SEED = 17
DEFAULT_CHECKS = 3
INSTRUCTIONS = (
    "You are the arrival controller for one shared SFO runway resource. Each decision point lists aircraft "
    "already announced (pending). Plan format: {\"order\": [every pending id exactly once]}. A trusted decoder "
    "assigns each aircraft in that order its earliest feasible slot (>= earliest_landing_seconds, >= clock+360, "
    "and after the previous reservation of exit_occupancy_seconds+240). An independent verifier must approve the plan; "
    "a rejected or invalid submit is replaced by scripted FCFS and costs reward. check_plan is limited per decision "
    "and does not commit; submit_plan commits and advances the clock. Objective: zero safety violations, then fewer "
    "unfinished aircraft at horizon_seconds, then lower total added delay. Reward is 0-1 against a CP-SAT closed-loop reference."
)


class SFOArrivalEnv:
    env_id = ENV_ID

    def __init__(self, splits=("train", "validation"), checks_per_decision=DEFAULT_CHECKS, seed=SEED):
        self.checks_per_decision = checks_per_decision
        self.seed = seed
        self._episodes = {}  # task_id -> (split, episode)
        for split in splits:
            for ep in load_episodes(split):  # only frozen train/validation; sealed test is unreachable
                self._episodes[ep["id"]] = (split, ep)
        self.task_id = None

    # ---- tasks -------------------------------------------------------------
    def list_tasks(self):
        return [{"task_id": tid, "split": s, "local_date": ep["local_date"], "source_arrivals": len(ep["entries"])}
                for tid, (s, ep) in self._episodes.items()]

    def reset(self, task_id):
        if task_id not in self._episodes:
            return {"error": f"unknown task_id {task_id!r}", "known_task_ids": list(self._episodes)}
        self.split, self.episode = self._episodes[task_id]
        self.task_id = task_id
        ep = self.episode
        self.epoch = ep["warmup_start"]
        self.horizon = ep["drain_end"] - self.epoch
        self.state = initial_state(ep, self.seed)
        self.state["rule_version"] = RULE_VERSION
        interval = CONFIG["decision_interval_seconds"]
        ticks = set(float(t) for t in range(0, int(self.horizon) + 1, interval))
        ticks.update(e["spawn_time"] - self.epoch for e in ep["entries"])
        ticks.add(self.horizon)
        self._ticks = sorted(ticks)
        self._tick_i = 0
        self._cursor = 0
        self.decisions = []
        self.steps = []
        self._cur = None
        self._cpsat = None
        self.checks_used = 0
        self.checks_left = self.checks_per_decision
        self.done = False
        self.grade_ = None
        self.outcome_ = None
        self._advance()
        return self.get_situation()

    # ---- trusted loop ------------------------------------------------------
    def _advance(self):
        """Run the trusted loop until the next decision point or the end."""
        interval = CONFIG["decision_interval_seconds"]
        entries = self.episode["entries"]
        state = self.state
        while self._tick_i < len(self._ticks):
            now = self._ticks[self._tick_i]
            self._tick_i += 1
            state["time"] = now
            while self._cursor < len(entries) and entries[self._cursor]["spawn_time"] - self.epoch <= now:
                add_aircraft(state, entries[self._cursor], self.epoch, self._cursor + 1)
                self._cursor += 1
            report = available_weather(self.episode, self.epoch + now)
            if report is not None and report["visibility_sm"] is not None:
                state["weather"]["visibility"] = report["visibility_sm"]
            if now == self.horizon or now % interval or not view_for(state, self.horizon)["pending"]:
                continue
            self._public = view_for(state, self.horizon)
            self._cpsat = None
            self.checks_left = self.checks_per_decision
            self._cur = {"clock_seconds": now, "pending": [p["id"] for p in self._public["pending"]],
                         "tool_calls": []}
            return
        # end of episode
        if self._cursor != len(entries):
            raise ValueError("Historical episode did not admit every scheduled source spawn")
        self.outcome_ = outcome(state, self.episode, self.decisions, self.horizon)
        self.reference_ = get_reference(self.split, self.episode)
        self.grade_ = grade(self.outcome_, self.reference_)
        self.done = True
        self._cur = None

    # ---- helpers -----------------------------------------------------------
    def _pending_ids(self):
        return self._cur["pending"]

    def _validate(self, plan):
        if not isinstance(plan, dict) or "order" not in plan:
            return None, 'plan must be an object like {"order": [ids...]}'
        order = plan["order"]
        if not isinstance(order, list) or not all(isinstance(x, str) for x in order):
            return None, "order must be a list of aircraft id strings"
        pending = self._pending_ids()
        if len(set(order)) != len(order):
            return None, "order contains duplicate ids"
        unknown = sorted(set(order) - set(pending))
        if unknown:
            return None, f"unknown or non-pending ids: {unknown}"
        missing = sorted(set(pending) - set(order))
        if missing:
            return None, f"order is missing pending ids: {missing}"
        return order, None

    def _decode(self, order):
        proposal = propose(self.state, "ai", self.horizon, order=order)
        if proposal.get("status") == "infeasible":
            return proposal, {"status": "infeasible", "checks": []}
        return proposal, verify(self.state, proposal)

    def _pending_delay(self, slots):
        req = {a["id"]: a["requested"] for a in self.state["aircraft"]}
        pending = set(self._pending_ids())
        return round(sum(s["time"] - req[s["aircraft_id"]] for s in slots if s["aircraft_id"] in pending), 3)

    def _pending_slots(self, slots):
        pending = set(self._pending_ids())
        return [dict(s) for s in slots if s["aircraft_id"] in pending]

    def cpsat_proposal(self):
        """Privileged oracle: the CP-SAT proposal at this decision (cached)."""
        if self._cpsat is None:
            self._cpsat = propose(self.state, "deterministic", self.horizon)
        return self._cpsat

    def cpsat_order(self):
        p = self.cpsat_proposal()
        pending = set(self._pending_ids())
        slots = sorted((s for s in p.get("slots", []) if s["aircraft_id"] in pending),
                       key=lambda s: (s["time"], s["aircraft_id"]))
        return [s["aircraft_id"] for s in slots]

    # ---- tools -------------------------------------------------------------
    def get_situation(self):
        if self.task_id is None:
            return {"error": "call reset(task_id) first"}
        if self.done:
            return {"task_id": self.task_id, "split": self.split, "done": True,
                    "decision_index": len(self.decisions), "checks_remaining": 0, "grade": self.grade_}
        return {**self._public, "task_id": self.task_id, "split": self.split,
                "decision_index": len(self.decisions), "checks_remaining": self.checks_left,
                "done": False, "instructions": INSTRUCTIONS, "reward_formula": REWARD_FORMULA}

    def check_plan(self, plan):
        if self.task_id is None or self.done:
            return {"status": "error", "error": "no active decision point; call reset(task_id)" if self.task_id is None
                    else "episode is done"}
        order, reason = self._validate(plan)
        raw_order = plan.get("order") if isinstance(plan, dict) else None
        if reason:
            self._cur["tool_calls"].append({"tool": "check_plan", "order": raw_order if isinstance(raw_order, list) else [],
                                            "status": "invalid"})
            return {"status": "invalid", "reason": reason, "checks_remaining": self.checks_left}
        if self.checks_left <= 0:
            return {"status": "error", "error": "check budget exhausted for this decision; call submit_plan",
                    "checks_remaining": 0}
        self.checks_left -= 1
        self.checks_used += 1
        proposal, verdict = self._decode(order)
        status = "pass" if verdict["status"] == "pass" else "rejected"
        self._cur["tool_calls"].append({"tool": "check_plan", "order": order, "status": status})
        return {"status": status,
                "reason": None if status == "pass" else f"verifier status {verdict['status']}",
                "failed_checks": [c["id"] for c in verdict["checks"] if c["status"] != "pass"],
                "slots": self._pending_slots(proposal.get("slots", [])),
                "added_delay_seconds": self._pending_delay(proposal["slots"]) if proposal.get("slots") else None,
                "checks_remaining": self.checks_left}

    def submit_plan(self, plan):
        if self.task_id is None or self.done:
            return {"status": "error", "error": "no active decision point; call reset(task_id)" if self.task_id is None
                    else "episode is done"}
        order, reason = self._validate(plan)
        state, horizon, now = self.state, self.horizon, self.state["time"]
        public = self._public
        proposal, verdict, proposed_solver, proposed_slots = None, None, None, []
        if reason:
            verdict = {"status": "invalid", "checks": []}
            status = "invalid"
        else:
            proposal, verdict = self._decode(order)
            proposed_solver, proposed_slots = proposal.get("solver"), proposal.get("slots", [])
            status = "pass" if verdict["status"] == "pass" else "rejected"
        fallback = verdict["status"] != "pass"
        applied, applied_controller = verdict, "ai_agent"
        if fallback:
            proposal = propose(state, "scripted", horizon)
            applied_controller = "scripted_fallback"
            applied = verify(state, proposal) if proposal.get("status") != "infeasible" else {"status": "infeasible", "checks": []}
        if applied["status"] == "pass":
            applied = commit(state, proposal)
        record = {"time_seconds": now, "public_view_sha256": hashlib.sha256(canonical(public).encode()).hexdigest(),
                  "controller_failure": False, "fallback_used": fallback,
                  "proposal_status": verdict["status"], "applied_status": applied["status"],
                  "applied_controller": applied_controller, "proposed_solver": proposed_solver,
                  "proposed_slots": proposed_slots,
                  "proposal_failed_checks": [c["id"] for c in verdict["checks"] if c["status"] != "pass"],
                  "solver": proposal.get("solver"), "slots": proposal["slots"] if applied["status"] == "pass" else []}
        self.decisions.append(record)
        cur = self._cur
        cur["tool_calls"].append({"tool": "submit_plan", "order": order if order is not None else [], "status": status})
        cur.update(submitted_order=order if order is not None else [], status=status, fallback=fallback,
                   invalid_reason=reason, slots=self._pending_slots(record["slots"]))
        self.steps.append(cur)
        self._advance()
        result = {"submitted": status, "reason": reason, "fallback_used": fallback,
                  "failed_checks": record["proposal_failed_checks"]}
        return {**result, "situation": self.get_situation()} if not self.done else {**result, "done": True, "grade": self.grade_}

    # ---- export ------------------------------------------------------------
    def tool_summary(self):
        return {"checks_used": self.checks_used, "decisions": len(self.decisions)}

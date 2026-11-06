"""Built-in agents. Each agent is `choose(env, situation) -> {"order": [...]}` and may call env.check_plan."""
from __future__ import annotations

import json
import os
import random
import urllib.request

SEED = 17


class ScriptedAgent:
    name, label, kind = "scripted", "Scripted FCFS", "scripted"

    def choose(self, env, sit):
        pend = sorted(sit["pending"], key=lambda p: (p["earliest_landing_seconds"], p["id"]))
        return {"order": [p["id"] for p in pend]}


class RandomAgent:
    name, label, kind = "random", "Random order", "baseline"

    def __init__(self):
        self.rng = random.Random(SEED)

    def reset(self):
        self.rng = random.Random(SEED)

    def choose(self, env, sit):
        order = [p["id"] for p in sit["pending"]]
        self.rng.shuffle(order)
        return {"order": order}


class CpsatAgent:
    name, label, kind = "cpsat", "CP-SAT order (oracle)", "reference"

    def choose(self, env, sit):
        return {"order": env.cpsat_order()}  # privileged: reads the CP-SAT proposal for this decision


class HeavyLastAgent:
    """Earliest-first, but a heavy never directly precedes a medium when the swap costs <= 60 s of earliest-time lag.

    The swapped order is only used if check_plan says it passes and does not add delay vs FCFS.
    """
    name, label, kind = "heavy_last", "Heavy-last heuristic", "heuristic"
    SWAP_LIMIT_SECONDS = 60

    def choose(self, env, sit):
        pend = sorted(sit["pending"], key=lambda p: (p["earliest_landing_seconds"], p["id"]))
        fcfs = [p["id"] for p in pend]
        order = list(pend)
        for i in range(len(order) - 1):
            a, b = order[i], order[i + 1]
            if a["wake"] == "heavy" and b["wake"] == "medium" and \
                    b["earliest_landing_seconds"] - a["earliest_landing_seconds"] <= self.SWAP_LIMIT_SECONDS:
                order[i], order[i + 1] = b, a
        cand = [p["id"] for p in order]
        if cand == fcfs:
            return {"order": fcfs}
        base, alt = env.check_plan({"order": fcfs}), env.check_plan({"order": cand})
        if alt.get("status") == "pass" and (base.get("status") != "pass" or
                                            alt["added_delay_seconds"] <= base["added_delay_seconds"]):
            return {"order": cand}
        return {"order": fcfs}


class NemotronAgent:
    """Optional paid OpenAI-compatible chat agent (tool-calling loop). NOT run by tests or smoke.

    Env: CRUSOE_API_KEY (required), ATC_LLM_BASE_URL (default Crusoe), ATC_LLM_MODEL (default Nemotron).
    """
    name, label, kind = "nemotron", "Nemotron (LLM)", "llm"
    MAX_TURNS = 6
    TOOLS = [{"type": "function", "function": {"name": n, "description": d, "parameters": {
        "type": "object", "properties": {"order": {"type": "array", "items": {"type": "string"}}},
        "required": ["order"]}}} for n, d in (
            ("check_plan", "Dry-run a pending-aircraft order through the verifier (limited per decision)."),
            ("submit_plan", "Commit the order and advance to the next decision point."))]

    def __init__(self):
        self.key = os.environ.get("CRUSOE_API_KEY")
        if not self.key:
            raise RuntimeError("CRUSOE_API_KEY is required for the nemotron agent")
        self.base = os.environ.get("ATC_LLM_BASE_URL", "https://api.inference.crusoecloud.com/v1").rstrip("/")
        self.model = os.environ.get("ATC_LLM_MODEL", "nvidia/NVIDIA-Nemotron-3.5-Super-VL")

    def _chat(self, messages):
        body = json.dumps({"model": self.model, "messages": messages, "tools": self.TOOLS,
                           "temperature": 0.2, "max_tokens": 2048}).encode()
        req = urllib.request.Request(f"{self.base}/chat/completions", data=body, headers={
            "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())["choices"][0]["message"]

    def choose(self, env, sit):
        messages = [{"role": "system", "content": sit["instructions"]},
                    {"role": "user", "content": json.dumps({k: sit[k] for k in ("clock_seconds", "horizon_seconds", "pending",
                                                                                 "active_commitments", "minimum_spacing")})}]
        last = {"order": [p["id"] for p in sit["pending"]]}
        for _ in range(self.MAX_TURNS):
            try:
                msg = self._chat(messages)
            except Exception as exc:  # network/API failure: fall through to submit last order
                print(f"nemotron request failed: {type(exc).__name__}", flush=True)
                break
            messages.append(msg)
            calls = msg.get("tool_calls") or []
            if not calls:
                break
            for call in calls:
                try:
                    args = json.loads(call["function"]["arguments"])
                except Exception:
                    args = {}
                if "order" in args:
                    last = {"order": args["order"]}
                if call["function"]["name"] == "submit_plan":
                    return last
                result = env.check_plan(last) if call["function"]["name"] == "check_plan" else {"error": "unknown tool"}
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)})
        return last


AGENTS = {"scripted": ScriptedAgent, "random": RandomAgent, "cpsat": CpsatAgent,
          "heavy_last": HeavyLastAgent, "nemotron": NemotronAgent}


def run_episode(env, agent, task_id):
    """Drive one task to completion; return the final grade."""
    if hasattr(agent, "reset"):
        agent.reset()
    sit = env.reset(task_id)
    while not sit.get("done"):
        out = env.submit_plan(agent.choose(env, sit))
        sit = out["situation"] if "situation" in out else out
    return sit["grade"]

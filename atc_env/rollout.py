"""Run agents over a split and write viewer JSON.

python -m atc_env.rollout --split validation --agents scripted,random,heavy_last,cpsat [--tasks N] [--out DIR]
python -m atc_env.rollout --smoke
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path

from . import ENV_ID
from .agents import AGENTS, run_episode
from .env import SFOArrivalEnv
from .grader import REFERENCE_LABEL, REWARD_FORMULA

DEFAULT_OUT = "showcase/candidates/data/arena"


def safe(name):
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def rollout_record(env, agent, grade):
    ep, out, ref = env.episode, env.outcome_, env.reference_
    meta = {a["id"]: a for a in env.state["aircraft"]}
    aircraft = []
    for f in out["flights"]:
        a = meta[f["id"]]
        aircraft.append({"id": f["id"], "type": a["type"], "wake": a["wake"],
                         "known_since_seconds": f["known_since_seconds"],
                         "nominal_landing_seconds": f["nominal_landing_seconds"],
                         "landing_seconds": f["landing_seconds"],
                         "reference_landing_seconds": ref["landing_seconds"].get(f["id"]),
                         "completed": f["completed"], "added_delay_seconds": f["added_delay_seconds"],
                         "position_provenance": f["position_provenance"]})
    return {"environment": ENV_ID, "task_id": env.task_id, "agent": agent.name, "label": agent.label,
            "reward": grade["reward"], "grade": grade, "horizon_seconds": env.horizon,
            "window": {"warmup_start_epoch": ep["warmup_start"], "start_epoch": ep["start"], "end_epoch": ep["end"],
                       "drain_end_epoch": ep["drain_end"], "local_date": ep["local_date"]},
            "aircraft": aircraft,
            "steps": [{"clock_seconds": s["clock_seconds"], "pending": s["pending"], "tool_calls": s["tool_calls"],
                       "submitted_order": s["submitted_order"], "status": s["status"], "fallback": s["fallback"],
                       "slots": s["slots"]} for s in env.steps]}


def task_row(env, grade):
    return {"task_id": env.task_id, "local_date": env.episode["local_date"], "reward": grade["reward"],
            "safety_eligible": grade["safety_eligible"], "completed": grade["completed"], "backlog": grade["backlog"],
            "spawned": grade["spawned"], "penalized_added_delay_seconds": grade["penalized_added_delay_seconds"],
            "reference_penalized_added_delay_seconds": grade["reference_penalized_added_delay_seconds"],
            "gap": grade["gap"], "rejected_plans": grade["rejected_plans"], "decisions": grade["total_decisions"],
            "checks_used": env.checks_used}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--split", default="validation", choices=["train", "validation"])
    p.add_argument("--agents", default="scripted,random,heavy_last,cpsat")
    p.add_argument("--tasks", type=int, default=None, help="only the first N tasks of the split")
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--smoke", action="store_true", help="scripted agent on one validation task; no keys needed")
    p.add_argument("--allow-paid", action="store_true", help="required to run the nemotron LLM agent (paid, needs CRUSOE_API_KEY)")
    a = p.parse_args(argv)

    if a.smoke:
        env = SFOArrivalEnv(splits=("validation",))
        tid = env.list_tasks()[0]["task_id"]
        grade = run_episode(env, AGENTS["scripted"](), tid)
        print(json.dumps({"task_id": tid, **{k: grade[k] for k in (
            "reward", "reason", "gap", "penalized_added_delay_seconds",
            "reference_penalized_added_delay_seconds", "rejected_plans", "total_decisions")}}, indent=1))
        return 0

    names = [n.strip() for n in a.agents.split(",") if n.strip()]
    for n in names:
        if n not in AGENTS:
            p.error(f"unknown agent {n!r}; choose from {sorted(AGENTS)}")
    if "nemotron" in names and not a.allow_paid:
        p.error("the nemotron agent makes paid API calls; pass --allow-paid (and set CRUSOE_API_KEY)")

    env = SFOArrivalEnv(splits=(a.split,))
    tasks = [t["task_id"] for t in env.list_tasks()][: a.tasks]
    out = Path(a.out)
    rows = []
    for n in names:
        agent = AGENTS[n]()
        task_rows = []
        for tid in tasks:
            grade = run_episode(env, agent, tid)
            rec = rollout_record(env, agent, grade)
            path = out / "rollouts" / agent.name / f"{safe(tid)}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(rec, separators=(",", ":")) + "\n")
            task_rows.append(task_row(env, grade))
            print(f"{n:11s} {tid} reward={grade['reward']:.3f} gap={grade['gap']:+.3f} rejected={grade['rejected_plans']}", flush=True)
        rows.append({"agent": agent.name, "label": agent.label, "kind": agent.kind,
                     "mean_reward": round(sum(t["reward"] for t in task_rows) / len(task_rows), 6),
                     "safety_eligible_tasks": sum(t["safety_eligible"] for t in task_rows), "tasks": task_rows})
    rows.sort(key=lambda r: -r["mean_reward"])
    board = {"environment": ENV_ID, "split": a.split, "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
             "reference": REFERENCE_LABEL, "reward_formula": REWARD_FORMULA, "agents": rows}
    (out / "leaderboard.json").parent.mkdir(parents=True, exist_ok=True)
    (out / "leaderboard.json").write_text(json.dumps(board, indent=1) + "\n")
    for r in rows:
        print(f"{r['agent']:11s} mean_reward={r['mean_reward']:.4f} safety_eligible={r['safety_eligible_tasks']}/{len(r['tasks'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

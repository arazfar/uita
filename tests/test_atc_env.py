"""E2E tests for SFOArrivalEnv-v1 against the real closed-loop engine (no mocks)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atc_env.agents import AGENTS, run_episode  # noqa: E402
from atc_env.env import SFOArrivalEnv  # noqa: E402
from benchmark.closed_loop.engine import simulate  # noqa: E402
from benchmark.closed_loop.traffic import load_episodes  # noqa: E402

PY = sys.executable


@pytest.fixture(scope="module")
def env():
    return SFOArrivalEnv(splits=("validation",))


@pytest.fixture(scope="module")
def tasks(env):
    return [t["task_id"] for t in env.list_tasks()]


def test_scripted_fidelity_to_engine(env, tasks):
    episodes = {e["id"]: e for e in load_episodes("validation")}
    for tid in tasks[:3]:
        run_episode(env, AGENTS["scripted"](), tid)
        ref = simulate(episodes[tid], "scripted")
        for key in ("penalized_added_delay_seconds", "backlog", "completed"):
            assert env.outcome_[key] == ref[key], (tid, key)
        assert [f["landing_seconds"] for f in env.outcome_["flights"]] == [f["landing_seconds"] for f in ref["flights"]]


def test_deterministic_replay(env, tasks):
    a = run_episode(env, AGENTS["random"](), tasks[1])
    b = run_episode(env, AGENTS["random"](), tasks[1])
    assert a == b


def test_malformed_plan_falls_back(env, tasks):
    sit = env.reset(tasks[0])
    ids = [p["id"] for p in sit["pending"]]
    for bad in (None, "x", {"order": "A001"}, {"order": ids + ids}, {"order": ["nope"] + ids[1:]}, {"order": ids[:-1]}):
        assert env.check_plan(bad)["status"] == "invalid"
    out = env.submit_plan({"order": ["bogus"]})
    assert out["fallback_used"] is True and out["submitted"] == "invalid"
    while not env.done:
        sit = env.get_situation()
        env.submit_plan({"order": sorted(p["id"] for p in sit["pending"])})
    assert env.grade_["rejected_plans"] >= 1
    assert env.grade_["reward"] <= 0.2


def test_check_budget_enforced(env, tasks):
    sit = env.reset(tasks[0])
    plan = {"order": [p["id"] for p in sit["pending"]]}
    for i in range(3):
        r = env.check_plan(plan)
        assert r["status"] in ("pass", "rejected") and r["checks_remaining"] == 2 - i
    over = env.check_plan(plan)
    assert over["status"] == "error"
    assert env.get_situation()["decision_index"] == 0  # no state change
    env.submit_plan(plan)
    assert env.get_situation().get("checks_remaining") in (3, 0)  # budget resets per decision


def test_cpsat_not_worse_than_scripted(env, tasks):
    tid = tasks[1]
    s = run_episode(env, AGENTS["scripted"](), tid)
    c = run_episode(env, AGENTS["cpsat"](), tid)
    # CP-SAT stops at a 0.25 s wall-clock limit, so its plans vary slightly with
    # machine load; per-decision optimisation is also not guaranteed to beat FCFS.
    assert c["rejected_plans"] == 0 and c["executed_violations"] == 0
    assert c["reward"] >= s["reward"] - 0.02


def test_mcp_round_trip():
    proc = subprocess.Popen([PY, "-m", "atc_env.mcp_server", "--split", "validation"], cwd=ROOT,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    n = 0

    def rpc(method, params=None):
        nonlocal n
        n += 1
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": n, "method": method, "params": params or {}}) + "\n")
        proc.stdin.flush()
        return json.loads(proc.stdout.readline())

    def tool(name, **args):
        res = rpc("tools/call", {"name": name, "arguments": args})["result"]
        return json.loads(res["content"][0]["text"])

    try:
        assert rpc("initialize", {"protocolVersion": "2024-11-05"})["result"]["serverInfo"]["name"] == "SFOArrivalEnv-v1"
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        names = {t["name"] for t in rpc("tools/list")["result"]["tools"]}
        assert names == {"list_tasks", "reset", "get_situation", "check_plan", "submit_plan"}
        tid = tool("list_tasks")[0]["task_id"]
        sit = tool("reset", task_id=tid)
        assert tool("get_situation")["decision_index"] == 0
        while not sit.get("done"):
            order = sorted(p["id"] for p in sit["pending"])
            order.sort(key=lambda i: next(p["earliest_landing_seconds"] for p in sit["pending"] if p["id"] == i))
            out = tool("submit_plan", order=order)
            sit = out.get("situation", out)
        assert 0.0 <= sit["grade"]["reward"] <= 1.0
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)

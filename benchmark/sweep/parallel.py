"""Finish distant, unstarted windows under the frozen sweep and shared API cap.

This is an explicit orchestration amendment, not a new model experiment. The
original forward runner later reuses these completed rows. Final verification
must prove that reuse, unique paid identities and complete causal replay.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import threading
import time

from .run import DEFAULT_OUT, ROOT, read, row_path, run_job, sha, utc_now, write
from .traffic import load_episodes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    plan = read(args.out / "plan.json")
    for name, expected in plan["source_hashes"].items():
        if sha(ROOT / name) != expected:
            raise ValueError("A frozen sweep source changed")
    episodes = [e for e in reversed(load_episodes()) if e["local_date"] >= "2026-08-28"]
    jobs = [(episode, config) for episode in episodes for config in plan["configurations"]]
    if len(jobs) != 180:
        raise ValueError("The amendment covers exactly the last three days and ten configurations")
    path = args.out / "orchestration-amendment.json"
    if path.exists():
        raise ValueError("An orchestration amendment already exists; investigate rather than redispatch")
    for episode, config in jobs:
        if row_path(args.out, config["id"], episode["id"]).exists() or (
            args.out / "configs" / config["id"] / "episodes" / episode["id"] / "ai-plan.json").exists():
            raise ValueError("A future window is already owned; no concurrent takeover is allowed")
    amendment = {
        "kind": "execution_concurrency_only", "created_at_utc": utc_now(),
        "reason": "Slow bounded reasoning calls prevent six workers per model from reaching the unchanged dispatch ceiling",
        "plan_sha256": sha(args.out / "plan.json"), "helper_sha256": sha(__file__),
        "original_workers": 30, "original_workers_per_model": 6,
        "additional_workers": 90, "additional_workers_per_model": 18,
        "maximum_combined_workers_per_model": 24,
        "minimum_per_model_dispatch_seconds": 2.2, "spending_cap_usd": plan["budget"]["cap_usd"],
        "unchanged": ["model checkpoints", "reasoning controls", "task prompt", "output/token/deadline bounds",
                      "traffic", "simulator", "safety gate", "decoder", "fallbacks", "objective", "request pacing", "spending cap"],
        "jobs": [{"controller": config["id"], "episode_id": episode["id"]} for episode, config in jobs],
        "required_final_proof": "Every corresponding original-runner future returned reused=true; unique raw IDs and no orphan reservations; all 504 rows pass replay",
    }
    if not args.execute:
        print({"status": "plan_only", "additional_jobs": len(jobs), "additional_workers": 90}, flush=True)
        return
    write(path, amendment)
    frozen = args.out / "frozen_source" / "benchmark/sweep/parallel.py"
    frozen.parent.mkdir(parents=True, exist_ok=True)
    frozen.write_bytes(Path(__file__).read_bytes())
    gates = {model: threading.Semaphore(18) for model in {c["model"] for c in plan["configurations"]}}
    completed, started = [], time.monotonic()
    with ThreadPoolExecutor(max_workers=90) as pool:
        futures = {pool.submit(run_job, args.out, episode, config["id"], config, plan["budget"], gates[config["model"]]):
                   (episode, config) for episode, config in jobs}
        for future in as_completed(futures):
            episode, config = futures[future]
            row, reused = future.result()
            if reused:
                raise ValueError("The forward runner unexpectedly owned an amendment window; preserve evidence")
            completed.append({"controller": config["id"], "episode_id": episode["id"]})
            print({"helper_finished": len(completed), "expected": len(jobs), "controller": config["id"],
                   "episode": episode["id"], "completed": row["completed"], "fallbacks": row["fallback_decisions"],
                   "elapsed_seconds": round(time.monotonic() - started, 1)}, flush=True)
    if sorted((j["controller"], j["episode_id"]) for j in completed) != sorted((j["controller"], j["episode_id"]) for j in amendment["jobs"]):
        raise ValueError("The amendment result set is incomplete")
    write(args.out / "orchestration-worker-completion.json", {
        "completed": True, "helper_sha256": sha(__file__), "amendment_sha256": sha(path),
        "jobs": completed, "elapsed_seconds": time.monotonic() - started,
    })
    print({"status": "helper_completed", "jobs": len(completed)}, flush=True)


if __name__ == "__main__":
    main()

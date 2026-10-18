"""Run an immutable five-model reasoning sweep on August 24–30 historical demand.

The simulator and both reference controllers are imported without modification.
Every model/window is an independently resumable job. A shared token ledger and
per-model dispatch schedule bound spending and concurrency across all jobs.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import datetime as dt
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import statistics
import threading
import time

from benchmark.closed_loop.engine import CONFIG, percentile, simulate
from benchmark.closed_loop.run import SOURCES as ENGINE_SOURCES, aggregate

ROOT = Path(__file__).resolve().parents[2]
VERSION = "historical-admission-model-sweep-v1"
DEFAULT_OUT = ROOT / "benchmark/results/late-august-sweep-20261017"
DEFAULT_REPORT = ROOT / "benchmark/sweep/reports/2026-08-24_30"
BUDGET_ID = "uita-late-august-model-sweep-20261017-v1"
SOURCES = ENGINE_SOURCES + ["benchmark/sweep/traffic.py", "benchmark/sweep/models.py",
                            "benchmark/sweep/run.py"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, allow_nan=False) + "\n"
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(payload)
    temporary.replace(path)


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def prepare(out, cap_usd, workers, per_model_workers):
    from .models import configuration_matrix
    from .traffic import DATA_DIR, load_episodes

    episodes = load_episodes("evaluation")
    if len(episodes) != 42:
        raise ValueError("The sweep requires all forty-two late-August windows")
    out.mkdir(parents=True, exist_ok=True)
    existing = out / "plan.json"
    # Resumes reuse discovery metadata, rather than refreshing timestamps or
    # resolving aliases after the experiment has already started.
    preflight_configurations = out / "preflight-configurations.json"
    configurations = (read(existing)["configurations"] if existing.exists()
                      else read(preflight_configurations) if preflight_configurations.exists()
                      else configuration_matrix())
    if len(configurations) != 10 or len({c["model"] for c in configurations}) < 5:
        raise ValueError("Exactly ten configurations and at least five distinct models are required")
    if len({c["id"] for c in configurations}) != 10:
        raise ValueError("Configuration identities must be unique")
    for model in {c["model"] for c in configurations}:
        if {c["reasoning"] for c in configurations if c["model"] == model} != {"on", "off"}:
            raise ValueError("Each base model needs a documented ON/OFF pair")
    plan = {
        "version": VERSION, "date_range": ["2026-08-24", "2026-08-30"], "timezone": "America/Los_Angeles",
        "episodes": [e["id"] for e in episodes], "configurations": configurations,
        "references": ["scripted", "deterministic"], "engine_config": CONFIG,
        "source_hashes": {name: sha(ROOT / name) for name in SOURCES},
        "traffic_sha256": sha(DATA_DIR / "evaluation.json"),
        "traffic_manifest_sha256": sha(DATA_DIR / "manifest.json"),
        "runtime": {"python": platform.python_version(), "ortools": importlib.metadata.version("ortools")},
        "budget": {"id": BUDGET_ID, "cap_usd": cap_usd, "automatic_paid_retries": 0},
        "concurrency": {"workers": workers, "per_model_workers": per_model_workers},
        "final_test": "Original August 8–9 remain sealed; no selection or evaluation reads them",
        "selection": "Ten configurations frozen before late-August evaluation; no outcome-based tuning",
    }
    references = out / "reference-source-hashes.json"
    if references.exists() and read(references) != {name: plan["source_hashes"][name] for name in ENGINE_SOURCES}:
        raise ValueError("Reference runs used a different frozen engine")
    if existing.exists() and read(existing) != plan:
        raise ValueError("Existing immutable sweep plan differs from current sources, settings or runtime")
    write(existing, plan)
    for name in SOURCES:
        target = out / "frozen_source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and sha(target) != plan["source_hashes"][name]:
            raise ValueError("Frozen execution source changed: " + name)
        if not target.exists():
            shutil.copyfile(ROOT / name, target)
    return plan, episodes


def row_path(out, controller, episode):
    return out / "episodes" / controller / (episode + ".json")


def run_job(out, episode, controller, configuration, budget, semaphore):
    target = row_path(out, controller, episode["id"])
    if target.exists():
        row = read(target)
        if row["controller"] != controller or row["episode_id"] != episode["id"]:
            raise ValueError("Cached episode identity differs")
        return row, True
    with semaphore:
        job_dir = out / "configs" / controller / "episodes" / episode["id"]
        job_dir.mkdir(parents=True, exist_ok=True)
        engine_controller = "ai" if configuration else controller
        ai = None
        if configuration:
            from .models import SweepController
            ai = SweepController(job_dir, configuration, ledger_path=out / "budget.sqlite3",
                                 budget_id=budget["id"], cap_usd=budget["cap_usd"])

        def emit(record):
            with (job_dir / "progress.jsonl").open("a") as stream:
                stream.write(json.dumps(record, separators=(",", ":")) + "\n")

        row = simulate(episode, engine_controller, ai=ai, emit=emit)
        row.update(controller=controller, engine_controller=engine_controller)
        if ai:
            write(job_dir / "usage.json", ai.summary())
        write(target, row)
        return row, False


def usage_for(out, controller, episodes):
    records = []
    for episode in episodes:
        path = out / "configs" / controller / "episodes" / episode["id"] / "calls.jsonl"
        if path.exists():
            records.extend(json.loads(line) for line in path.read_text().splitlines() if line.strip())
    # Recovered copies never become additional model decisions or charges.
    unique = {}
    for record in records:
        identifier = record["request_id"]
        if identifier in unique and unique[identifier].get("payload_sha256") != record.get("payload_sha256"):
            raise ValueError("Repeated request identity has different payloads")
        unique[identifier] = record
    records = list(unique.values())
    latencies = [r["latency_seconds"] for r in records if r.get("dispatched")]
    return {
        "calls": len(records), "successful_calls": sum(r["status"] == "completed" for r in records),
        "dispatched_calls": sum(bool(r.get("dispatched")) for r in records),
        "statuses": dict(Counter(r["status"] for r in records)),
        "failure_categories": dict(Counter(r.get("failure", "none") for r in records if r["status"] != "completed")),
        "finish_reasons": dict(Counter(str(r.get("finish_reason")) for r in records)),
        "reported_cost_usd": sum(r.get("cost_usd") or 0 for r in records),
        "unknown_cost_requests": sum(r.get("cost_usd") is None for r in records),
        "reserved_usd": sum(r.get("reserved_usd", 0) for r in records), "paid_retries": 0,
        "latency_seconds_mean": statistics.mean(latencies) if latencies else None,
        "latency_seconds_p95": percentile(latencies, .95),
    }


def document(out, plan, episodes):
    from .traffic import DATA_DIR

    configurations = {c["id"]: c for c in plan["configurations"]}
    verification_path = out / "verification.json"
    verification = read(verification_path) if verification_path.exists() else {}
    verified = verification.get("passed") is True and all(
        (out / name).exists() and sha(out / name) == verification.get("artifacts", {}).get(name)
        for name in ("plan.json", "runs.json", "summary.json"))
    manifest = read(DATA_DIR / "manifest.json")
    entries = []
    all_rows = []
    for index, controller in enumerate(plan["references"] + list(configurations)):
        rows = [read(row_path(out, controller, e["id"])) for e in episodes
                if row_path(out, controller, e["id"]).exists()]
        all_rows.extend(rows)
        config = configurations.get(controller)
        complete = len(rows) == len(episodes)
        metrics = aggregate(rows) if rows else {}
        entries.append({
            "id": controller, "model": config["model"] if config else controller,
            "provider": "Crusoe" if config else "Local", "reasoning": config["reasoning"] if config else "n/a",
            "kind": "model" if config else "reference", "status": "completed" if complete else "running" if rows else "pending",
            "experiment_index": index - 1 if config else None, "metrics": metrics,
            "usage": usage_for(out, controller, episodes) if config else {"calls": 0, "reported_cost_usd": 0},
            "episodes_completed": len(rows), "episodes_expected": len(episodes),
            "verification": {"passed": complete and verified},
            "date": "2026-10-17", "audit_url": "verification.json",
            "episode_results": [{key: value for key, value in row.items() if key not in ("decisions", "flights")} for row in rows],
        })
    return {
        "schema_version": 1, "title": "SFO arrival admission model leaderboard",
        "date_range": plan["date_range"], "generated_at": utc_now(), "harness_version": CONFIG["version"],
        "coverage": {"days": 7, "episodes": len(episodes), "arrivals": sum(len(e["entries"]) for e in episodes),
                     "source_label": "Historical arrival demand; all 1,029 initial states use synthetic development templates; fixed simulated approaches",
                     "provenance_note": "Historical demand uses actual August 24–30 operation times. All 1,029 initial states use synthetic August 3–6 templates; they are not recorded August 24–30 flight paths.",
                     "provenance": manifest.get("counts", manifest.get("artifacts", {}))},
        "entries": entries, "verification": verification,
        "baseline_context": {"period": "2026-08-07", "not_ranked": True,
                             "report": "../../../closed_loop/reports/2026-10-17/comparison.md"},
        "limits": ["Historical demand; the feeder and upstream waiting queue are outside the safety model.",
                   "Added delay is modeled admission waiting, right-censored at a fixed horizon.",
                   "Common independent safety checks and explicitly counted fallbacks apply to every model.",
                   "Logical simulation time pauses during inference; API latency is separate.",
                   "No authentic human ATC commands or human-controller quality score exists.",
                   "August 8–9 remain held out. All ten configurations were fixed before this evaluation."],
    }, all_rows


def refresh(out, report_dir, plan, episodes):
    doc, rows = document(out, plan, episodes)
    write(out / "leaderboard.json", doc)
    if report_dir:
        report_dir.mkdir(parents=True, exist_ok=True)
        for name in ("plan.json", "verification.json"):
            if (out / name).exists():
                shutil.copyfile(out / name, report_dir / name)
        from .report import write_report
        write_report(doc, report_dir)
    return doc, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--cap-usd", type=float, default=30.)
    parser.add_argument("--workers", type=int, default=30)
    parser.add_argument("--per-model-workers", type=int, default=6)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if not 0 < args.cap_usd <= 30 or not 1 <= args.workers <= 30 or not 1 <= args.per_model_workers <= 6:
        parser.error("Cap must be at most $30, workers at most 30 and concurrent workers per base model at most six")
    plan, episodes = prepare(args.out, args.cap_usd, args.workers, args.per_model_workers)
    expected = len(episodes) * (len(plan["configurations"]) + len(plan["references"]))
    if not args.execute and not args.finalize:
        print(json.dumps({"status": "plan_only", "models": 5, "configurations": 10, "episodes": len(episodes),
                          "controller_episode_runs": expected, "source_spawns": sum(len(e["entries"]) for e in episodes),
                          "cap_usd": args.cap_usd, "paid_calls": 0}), flush=True)
        return
    if args.execute:
        semaphores = {model: threading.Semaphore(args.per_model_workers) for model in {c["model"] for c in plan["configurations"]}}
        reference_semaphore = threading.Semaphore(4)
        failures = []
        finished = 0
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {}
            # References run on exactly the same late-August requests. August 7
            # totals remain context only; comparing their absolute scores here
            # would confound model changes with different traffic demand.
            for episode in episodes:
                for reference in plan["references"]:
                    future = pool.submit(run_job, args.out, episode, reference, None, plan["budget"], reference_semaphore)
                    futures[future] = (reference, episode["id"])
            # Interleave configurations instead of exhausting one model first.
            # Independent episode jobs pause logical time while API work waits.
            for episode in episodes:
                for config in plan["configurations"]:
                    future = pool.submit(run_job, args.out, episode, config["id"], config, plan["budget"], semaphores[config["model"]])
                    futures[future] = (config["id"], episode["id"])
            for future in as_completed(futures):
                controller, episode_id = futures[future]
                try:
                    row, reused = future.result()
                    finished += 1
                    print(json.dumps({"finished": finished, "expected": expected, "controller": controller,
                                      "episode": episode_id, "completed": row["completed"], "spawned": row["spawned"],
                                      "violations": row["executed_violations"], "fallbacks": row["fallback_decisions"],
                                      "reused": reused, "elapsed_seconds": round(time.monotonic() - started, 1)}), flush=True)
                except Exception as error:
                    failures.append({"controller": controller, "episode_id": episode_id, "error_type": type(error).__name__,
                                     "message": "Episode incomplete; inspect its local audit. It is excluded from ranking."})
                    write(args.out / "failures.json", failures)
                    print(json.dumps({"failed": controller, "episode": episode_id, "error_type": type(error).__name__}), flush=True)
                if finished % 10 == 0:
                    refresh(args.out, args.report, plan, episodes)
        refresh(args.out, args.report, plan, episodes)
        if failures:
            raise RuntimeError("Some sweep windows are incomplete; resume under the same immutable plan")
    for name, expected_hash in plan["source_hashes"].items():
        if sha(ROOT / name) != expected_hash:
            raise ValueError("Frozen source changed during execution: " + name)
    doc, rows = document(args.out, plan, episodes)
    if len(rows) != expected:
        raise ValueError("Finalization requires all 504 matched controller/window outcomes")
    write(args.out / "runs.json", rows)
    summary = {"status": "completed", "version": VERSION, "plan_sha256": sha(args.out / "plan.json"),
               "controllers": {entry["id"]: entry["metrics"] for entry in doc["entries"]},
               "ai_usage": {entry["id"]: entry["usage"] for entry in doc["entries"] if entry["kind"] == "model"},
               "source_hashes": plan["source_hashes"],
               "artifacts": {name: sha(args.out / name) for name in ("plan.json", "runs.json")},
               "date_range": plan["date_range"], "limits": doc["limits"]}
    write(args.out / "summary.json", summary)
    from .verify import verify_run
    verify_run(args.out, args.out / "verification.json")
    doc, rows = refresh(args.out, args.report, plan, episodes)
    if args.report:
        shutil.copyfile(args.out / "summary.json", args.report / "summary.json")
    print(json.dumps({"status": "completed", "controller_episode_runs": len(rows), "report": str(args.report)}), flush=True)


if __name__ == "__main__":
    main()

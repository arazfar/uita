"""Run the historical-order proxy with frozen prompts and an explicit paid gate.

Usage: python3 -m benchmark.run_baseline --out benchmark/results/<run> --execute
Without --execute this performs read-only provider discovery and writes a plan.
Final test cases cannot be selected by this runner.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import time

from . import core
from .provider import DEFAULT_MODEL, ProviderError, ReservationLedger, canonical, digest, discover, generate, request_plan


LIMITATIONS = [
    "Historical-order agreement is a prediction proxy. It does not measure human controller decision quality.",
    "The source lacks authentic ATC commands and full operating context. No AI-versus-human performance gap can be estimated.",
    "Surrogate schedules enforce spacing mechanically. Zero constructed schedule violations do not establish ATC safety.",
    "This is a causal observed-entry snapshot task, not a closed-loop heading/altitude/speed controller benchmark.",
    "Validation is used for model selection. Final August 8–9 cases remain sealed and unexecuted.",
]


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def append_jsonl(path, value):
    with Path(path).open("a") as stream:
        stream.write(canonical(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def aggregate(rows):
    n = len(rows)
    good = [r for r in rows if r["valid_action"]]
    pairs = sum(r["metrics"]["pairwise_total"] for r in rows)
    correct = sum(r["metrics"]["pairwise_correct"] for r in rows)
    return {
        "cases": n, "valid_actions": len(good), "invalid_actions": n - len(good),
        "next_arrival_accuracy": sum(r["metrics"]["next_arrival_correct"] for r in rows) / n if n else None,
        "exact_sequence_accuracy": sum(r["metrics"]["exact_sequence_correct"] for r in rows) / n if n else None,
        "mean_case_pairwise_agreement": statistics.mean(r["metrics"]["pairwise_agreement"] for r in rows) if n else None,
        "pooled_pairwise_agreement": correct / pairs if pairs else None,
        "pairwise_correct": correct, "pairwise_total": pairs,
        "surrogate_completed": sum(r["metrics"]["completed"] for r in rows),
        "surrogate_backlog": sum(r["metrics"]["backlog"] for r in rows),
        "surrogate_penalized_delay_seconds": sum(r["metrics"]["penalized_delay_seconds"] for r in rows),
        "failure_types": dict(Counter(r.get("failure", "none") for r in rows if not r["valid_action"])),
    }


def token_usage(call, name):
    response = call.get("response")
    usage = response.get("usage") if isinstance(response, dict) else None
    value = usage.get(name) if isinstance(usage, dict) else None
    return value if type(value) is int and value >= 0 else 0


def score(case, action, *, method, failure=None):
    valid = action is not None
    metrics = core.evaluate_action(case, action) if valid else core.failed_metrics(case)
    return {"case_id": case["case_id"], "split": case["split"], "method": method,
            "action": action, "valid_action": valid, "failure": failure, "metrics": metrics}


def references(case):
    state = case["input"]
    return {
        "always_A1": {"order": sorted(a["id"] for a in state["aircraft"])},
        "list_first": {"order": [a["id"] for a in state["aircraft"]]},
        "free_flow_heuristic": core.scripted_action(state),
        "distance_heuristic": {"order": [a["id"] for a in sorted(state["aircraft"], key=lambda a: (a["distance_nm"], a["id"]))]},
        "synthetic_min_delay_oracle": core.teacher_action(state),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--split", choices=("train", "validation"), default="validation")
    parser.add_argument("--max-cases", type=int, default=512)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--cap-usd", type=float, default=1)
    parser.add_argument("--budget-id", default="uita-historical-baseline-20261017")
    parser.add_argument("--controller-name", default="untuned_nemotron")
    parser.add_argument("--min-request-interval-seconds", type=float, default=2.2)
    parser.add_argument("--ledger", type=Path, default=Path("benchmark/results/inference-budget.sqlite3"))
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.max_cases <= 512 or not 1 <= args.max_tokens <= 2048:
        parser.error("Case limit must be 1–512 and output limit 1–2048")
    if not 0 < args.cap_usd <= 1:
        parser.error("This runner's approved inference cap is at most $1")
    if not 2.2 <= args.min_request_interval_seconds <= 60:
        parser.error("Per-model dispatch spacing must be between 2.2 and 60 seconds")
    cases = core.load_cases(args.split)
    if len(cases) > args.max_cases:
        parser.error(f"The frozen split contains {len(cases)} cases, exceeding the declared cap; select no partial split")
    if not cases:
        parser.error("The frozen split is empty")
    model = discover(args.model)
    reservations = [request_plan(core.model_messages(case), model=model, max_tokens=args.max_tokens,
                                 seed=args.seed)["reserved_usd"] for case in cases]
    if sum(reservations) > args.cap_usd:
        parser.error("The complete frozen split exceeds the approved worst-case inference cap")
    plan = {
        "benchmark_version": core.VERSION, "model": model, "split": args.split, "controller_name": args.controller_name,
        "case_count": len(cases), "case_ids": [case["case_id"] for case in cases],
        "case_file_sha256": sha_file(core.DATA_DIR / (args.split + ".jsonl")),
        "core_sha256": sha_file(core.__file__), "provider_sha256": sha_file(Path(__file__).with_name("provider.py")),
        "runner_sha256": sha_file(__file__), "prompt_sha256": digest(core.SYSTEM_PROMPT),
        "prompt_inputs_sha256": digest([core.model_messages(case) for case in cases]),
        "generation": {"temperature": 0, "top_p": 1, "seed": args.seed, "max_tokens": args.max_tokens,
                       "response_format": {"type": "json_object"}, **model["generation_overrides"], "paid_retries": 0},
        "pacing": {"minimum_start_interval_seconds": args.min_request_interval_seconds,
                   "scope": "per-model across processes sharing the persistent inference ledger"},
        "budget": {"id": args.budget_id, "cap_usd": args.cap_usd, "worst_case_total_reserved_usd": sum(reservations)},
        "limitations": LIMITATIONS,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    plan_path = args.out / "plan.json"
    if plan_path.exists():
        existing = json.loads(plan_path.read_text())
        # The initial discovery timestamp is evidence. A later GET must otherwise
        # return exactly the same pinned model and rates before resuming.
        model["discovered_at_epoch"] = existing["model"]["discovered_at_epoch"]
        plan["model"] = model
        if existing != plan:
            raise ProviderError("The frozen run plan differs from current code, cases, model, rates or settings")
    else:
        write_json(plan_path, plan)
    if not args.execute:
        print(canonical({"status": "plan_only_no_paid_calls", "plan": str(plan_path),
                         "case_count": len(cases), "model": model["id"],
                         "worst_case_total_reserved_usd": sum(reservations)}))
        return
    if (args.out / "summary.json").exists():
        raise ProviderError("This completed run is frozen; use a new output path for an independent run")
    ledger = ReservationLedger(args.ledger, args.budget_id, args.cap_usd)
    source_dir = args.out / "frozen_source"
    source_dir.mkdir(exist_ok=True)
    for source, expected in [(Path(core.__file__), plan["core_sha256"]),
                             (Path(__file__).with_name("provider.py"), plan["provider_sha256"]),
                             (Path(__file__), plan["runner_sha256"])]:
        target = source_dir / source.name
        if sha_file(source) != expected or target.exists() and sha_file(target) != expected:
            raise ProviderError("A frozen benchmark source snapshot has changed")
        if not target.exists():
            shutil.copy2(source, target)
    # Persist exact prompts before any generation. Private historical outcomes are
    # absent; only the trusted scorer reads them after each action is returned.
    prompts_path = args.out / "prompts.jsonl"
    prompts = [{"case_id": case["case_id"], "messages": core.model_messages(case)} for case in cases]
    expected_prompts = "".join(canonical(row) + "\n" for row in prompts)
    if prompts_path.exists() and prompts_path.read_text() != expected_prompts:
        raise ProviderError("The frozen prompt file has changed")
    prompts_path.write_text(expected_prompts)
    audits_path = args.out / "calls.jsonl"
    audits = [json.loads(line) for line in audits_path.read_text().splitlines()] if audits_path.exists() else []
    by_request = {row["request_id"]: row for row in audits}
    if len(by_request) != len(audits):
        raise ProviderError("Duplicate paid request audit records")
    all_scores = []
    for case in cases:
        for method, action in references(case).items():
            all_scores.append(score(case, action, method=method))
        request_id = args.out.name + ":" + case["case_id"]
        audit = by_request.get(request_id) or ledger.lookup(request_id)
        if audit is None:
            ledger.pace_model(model["id"], args.min_request_interval_seconds)
            audit = generate(core.model_messages(case), model=model, ledger=ledger,
                             request_id=request_id, max_tokens=args.max_tokens, seed=args.seed)
        if request_id not in by_request:
            append_jsonl(audits_path, audit)
            by_request[request_id] = audit
        action, failure = None, audit.get("failure")
        if audit["status"] == "completed":
            try:
                # Preserve raw parsing so duplicate keys or extra text cannot be
                # erased by the provider's preliminary JSON-object check.
                action = core.parse_action(audit["response"]["choices"][0]["message"]["content"], case["input"])
            except ValueError as exc:
                failure = "action_contract: " + str(exc)
        all_scores.append(score(case, action, method=args.controller_name,
                                failure=(failure or audit["status"]) if action is None else None))
        print(canonical({"case_id": case["case_id"], "status": audit["status"], "valid_action": action is not None,
                         "latency_seconds": round(audit["latency_seconds"], 3), "cost_usd": audit["cost_usd"]}), flush=True)
    scores_path = args.out / "scores.jsonl"
    scores_path.write_text("".join(canonical(row) + "\n" for row in all_scores))
    methods = sorted({row["method"] for row in all_scores})
    aggregates = {method: aggregate([row for row in all_scores if row["method"] == method]) for method in methods}
    calls = [by_request[args.out.name + ":" + case["case_id"]] for case in cases]
    latencies = [call["latency_seconds"] for call in calls]
    total_usage = {key: sum(token_usage(call, key) for call in calls)
                   for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
    summary = {"status": "completed", "completed_at_epoch": time.time(), "plan_sha256": sha_file(plan_path),
               "split": args.split, "model": model["id"], "aggregates": aggregates,
               "usage": total_usage, "budget": ledger.summary(),
               "run_cost": {"reported_cost_usd": sum(call["cost_usd"] or 0 for call in calls),
                            "unknown_cost_requests": sum(call["cost_usd"] is None for call in calls),
                            "reserved_usd": sum(call["reserved_usd"] for call in calls)},
               "mean_latency_seconds": statistics.mean(latencies), "max_latency_seconds": max(latencies),
               "case_paired_difference_model_minus_free_flow": {
                   metric: aggregates[args.controller_name][metric] - aggregates["free_flow_heuristic"][metric]
                   for metric in ("next_arrival_accuracy", "exact_sequence_accuracy", "mean_case_pairwise_agreement")},
               "artifacts": {path.name: sha_file(path) for path in (plan_path, prompts_path, audits_path, scores_path)},
               "limitations": LIMITATIONS}
    write_json(args.out / "summary.json", summary)
    print(canonical(summary))


if __name__ == "__main__":
    main()

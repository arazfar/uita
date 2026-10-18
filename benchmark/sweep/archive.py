"""Archive six minimal, verified sweep artifacts in the existing Railway store.

The default validates local bytes only. Only --execute connects to PostgreSQL.
Raw requests, responses, decisions, source code and other dates stay local.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit

from benchmark.closed_loop.engine import CONFIG
from .traffic import DATA_DIR, DATES, load_episodes

DATASET_ID = "sfo-arrival-admission-model-sweep-2026-08-24_30-v1"
VERSION = "historical-admission-model-sweep-v1"
PLAN_FIELDS = {"version", "date_range", "timezone", "episodes", "configurations", "references", "engine_config",
               "source_hashes", "traffic_sha256", "traffic_manifest_sha256", "runtime", "budget", "concurrency",
               "final_test", "selection"}
CONFIG_FIELDS = {"id", "model", "display_name", "family", "reasoning", "reasoning_label", "generation", "discovery",
                 "guidance_source", "reasoning_control_evidence", "catalog_source", "discovered_at_epoch", "timeout_seconds",
                 "minimum_per_model_dispatch_seconds", "sampling_policy"}
DISCOVERY_FIELDS = {"id", "context_length", "quantization", "supported_parameters", "input_usd_per_million_tokens",
                    "output_usd_per_million_tokens", "pricing_source"}
SUMMARY_FIELDS = {"status", "version", "plan_sha256", "controllers", "ai_usage", "source_hashes", "artifacts", "date_range", "limits"}
SAFETY_COUNTS = {"separation_violation_episodes", "runway_violation_episodes", "surface_violation_episodes",
                 "wake_violations", "performance_violations"}
METRIC_FIELDS = {"episodes", "spawned", "landed", "completed", "backlog", "nominal_due_arrivals", "not_nominally_due_arrivals",
                 "executed_violations", "safe_episodes", "executed_safety_counts", "minimum_lateral_nm_when_vertical_under_1000_ft",
                 "safety_eligible", "added_delay_seconds_sum", "mean_added_delay_seconds_all_demand",
                 "p95_added_delay_seconds_all_demand", "mean_added_delay_seconds_completed_only", "penalized_added_delay_seconds",
                 "controller_failures", "fallback_decisions", "rejected_proposals", "unresolved_decisions", "decisions",
                 "solver_status_counts", "source_strata"}
USAGE_FIELDS = {"calls", "successful_calls", "dispatched_calls", "statuses", "failure_categories", "finish_reasons",
                "reported_cost_usd", "unknown_cost_requests", "reserved_usd", "paid_retries",
                "latency_seconds_mean", "latency_seconds_p95"}
VERIFICATION_FIELDS = {"passed", "verification_kind", "verifier_sha256", "artifacts", "counts",
                       "ai_usage_independently_recomputed", "source_verification", "budget_verification",
                       "unscored_development_preflight_verification", "orchestration_verification", "recovery_verification",
                       "checks", "negative_qa", "limits"}
LEADERBOARD_FIELDS = {"schema_version", "title", "date_range", "generated_at", "harness_version", "coverage", "entries",
                      "verification", "baseline_context", "limits", "best_history", "ranked_configurations", "matched_references",
                      "comparison_verdict"}
ENTRY_FIELDS = {"id", "model", "display_name", "provider", "reasoning", "kind", "status", "experiment_index", "metrics", "usage",
                "episodes_completed", "episodes_expected", "verification", "date", "audit_url", "episode_results",
                "harness_version", "verified", "rankable", "eligible", "completion_percent", "fallback_percent",
                "usable_response_percent", "rank"}
COUNT_FIELDS = {"episodes", "controller_episode_results", "source_arrival_operations_per_controller", "base_models",
                "model_configurations", "replayed_decisions", "selected_ai_decisions", "raw_audit_records", "unique_audit_request_ids"}
SOURCE_VERIFICATION_FIELDS = {"historical_roster_operations", "selected_source_operations", "all_initial_states_synthetic",
                              "template_donors_development_only", "source_weather_receipt_seconds", "whole_month_path_archive_opened"}
BUDGET_VERIFICATION_FIELDS = {"budget_id", "cap_usd", "dispatched_requests", "reserved_usd", "known_cost_usd",
                              "unknown_reserved_exposure_usd", "settled_cost_plus_unknown_exposure_usd",
                              "unscored_development_preflight_calls", "unknown_cost_requests", "unresolved_reservations", "paid_retries"}
ORCHESTRATION_FIELDS = {"amended", "kind", "plan_sha256", "helper_sha256", "amendment_sha256", "completion_sha256",
                        "main_execution_log_sha256", "helper_execution_log_sha256", "helper_owned_windows",
                        "original_runner_reused_windows", "original_runner_finished_windows", "original_runner_recovered_failed_windows",
                        "total_acknowledged_windows", "minimum_per_model_dispatch_seconds",
                        "maximum_combined_workers_per_model", "spending_cap_usd", "semantic_settings_unchanged", "all_helper_jobs_owned_once"}
RECOVERY_FIELDS = {"recovered_jobs", "reconstructed_fallback_decisions", "jobs", "execution_amendment_sha256",
                   "maximum_combined_workers_per_base_model", "maximum_recovery_workers_per_base_model",
                   "minimum_shared_per_model_dispatch_seconds", "spending_cap_usd", "payload_and_scoring_unchanged",
                   "original_paid_requests_preserved", "paid_retries", "unknown_original_fallback_producer_decisions",
                   "original_solver_status_and_bound_recovered", "limits"}
RECOVERY_JOB_FIELDS = {"configuration", "episode_id", "manifest_sha256", "result_sha256", "source_sha256",
                       "original_calls", "reconstructed_fallback_decisions", "original_calls_preserved", "paid_retries"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def encode(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _fields(value, expected, label):
    require(isinstance(value, dict) and set(value) == expected, "Unknown or missing archive fields: " + label)


def _safe(value):
    """Reject raw inference and credential containers before compact projection."""
    if isinstance(value, dict):
        for key, item in value.items():
            require(isinstance(key, str) and key.lower() not in {
                "authorization", "api_key", "access_token", "secret", "password", "messages",
                "raw_request", "raw_response", "request", "response", "reasoning_content",
            }, "Raw inference or credential fields are outside the archive contract")
            require(key not in ("decisions", "flights") or not isinstance(item, (list, dict)),
                    "Decision and flight lists must stay local")
            _safe(item)
    elif isinstance(value, list):
        for item in value:
            _safe(item)
    elif isinstance(value, float):
        require(math.isfinite(value), "Archive contains a non-finite number")
    else:
        require(value is None or isinstance(value, (str, int, bool)), "Unsupported archive data type")


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _counter(value, label):
    require(isinstance(value, dict) and all(isinstance(key, str) and type(count) is int and count >= 0
                                           for key, count in value.items()), "Invalid aggregate counter: " + label)


def _close(left, right, label):
    require(type(left) in (int, float) and math.isfinite(left) and abs(left - right) <= .002,
            "Aggregate measurement differs: " + label)


def _metrics(value):
    _fields(value, METRIC_FIELDS, "controller metrics")
    require(value["episodes"] == 42 and value["spawned"] == 1029, "Every controller must cover all 42 windows and 1,029 arrivals")
    for key in ("episodes", "spawned", "landed", "completed", "backlog", "nominal_due_arrivals", "not_nominally_due_arrivals",
                "executed_violations", "safe_episodes", "controller_failures", "fallback_decisions", "rejected_proposals",
                "unresolved_decisions", "decisions"):
        require(type(value[key]) is int and value[key] >= 0, "Invalid controller count: " + key)
    require(value["completed"] <= value["landed"] <= 1029 and value["completed"] + value["backlog"] == 1029,
            "Completion counts do not cover demand")
    require(value["nominal_due_arrivals"] + value["not_nominally_due_arrivals"] == 1029,
            "Nominal due counts do not cover demand")
    require(value["safe_episodes"] <= 42 and value["safety_eligible"] is (value["executed_violations"] == value["unresolved_decisions"] == 0),
            "Safety eligibility differs from measured events")
    _fields(value["executed_safety_counts"], SAFETY_COUNTS, "executed safety counts")
    _counter(value["executed_safety_counts"], "executed safety counts")
    require(sum(value["executed_safety_counts"].values()) == value["executed_violations"], "Executed safety totals differ")
    for key in ("controller_failures", "fallback_decisions", "rejected_proposals", "unresolved_decisions"):
        require(value[key] <= value["decisions"], "Failure counter exceeds decisions")
    _close(value["penalized_added_delay_seconds"], value["added_delay_seconds_sum"] + 3600 * value["backlog"], "penalized delay")
    _close(value["mean_added_delay_seconds_all_demand"], value["added_delay_seconds_sum"] / 1029, "all-demand mean")
    require(value["added_delay_seconds_sum"] >= 0 and value["p95_added_delay_seconds_all_demand"] >= 0,
            "Delay measurements cannot be negative")
    _counter(value["solver_status_counts"], "solver status counts")
    _fields(value["source_strata"], {"synthetic_training_template"}, "source strata")
    stratum = value["source_strata"]["synthetic_training_template"]
    _fields(stratum, {"spawned", "completed", "mean_added_delay_seconds_all_demand"}, "synthetic source measurements")
    require(stratum["spawned"] == 1029 and stratum["completed"] == value["completed"], "Source stratum counts differ")
    _close(stratum["mean_added_delay_seconds_all_demand"], value["mean_added_delay_seconds_all_demand"], "source stratum mean")


def _usage(value):
    _fields(value, USAGE_FIELDS, "model usage")
    for key in ("calls", "successful_calls", "dispatched_calls", "unknown_cost_requests", "paid_retries"):
        require(type(value[key]) is int and value[key] >= 0, "Invalid usage count: " + key)
    require(value["paid_retries"] == 0 and value["successful_calls"] <= value["calls"]
            and value["dispatched_calls"] <= value["calls"] and value["unknown_cost_requests"] <= value["calls"],
            "Usage counts or retry policy differ")
    for key in ("statuses", "failure_categories", "finish_reasons"):
        _counter(value[key], key)
    require(sum(value["statuses"].values()) == value["calls"]
            and value["statuses"].get("completed", 0) == value["successful_calls"]
            and sum(value["failure_categories"].values()) == value["calls"] - value["successful_calls"],
            "Inference status totals differ")


def prepare(results):
    """Validate published aggregates against a complete replay attestation."""
    from .models import validate_configuration

    results = Path(results)
    payloads = {name: (results / name).read_bytes() for name in ("plan.json", "summary.json", "verification.json", "leaderboard.json")}
    plan, summary, verification, leaderboard = [json.loads(payloads[name]) for name in payloads]
    for value in (plan, summary, verification, leaderboard):
        _safe(value)
    _fields(plan, PLAN_FIELDS, "protocol")
    _fields(summary, SUMMARY_FIELDS, "summary")
    _fields(verification, VERIFICATION_FIELDS, "verification")
    _fields(leaderboard, LEADERBOARD_FIELDS | ({"failure_analysis_url"} if "failure_analysis_url" in leaderboard else set()), "leaderboard")
    if "failure_analysis_url" in leaderboard:
        link = leaderboard["failure_analysis_url"]
        require(isinstance(link, str) and link, "Failure analysis link must name an existing report file")
        parsed = urlsplit(link)
        target = (results / parsed.path).resolve()
        require(not parsed.scheme and not parsed.netloc and not parsed.query
                and target.is_relative_to(results.resolve()) and target.is_file(),
                "Failure analysis link must stay within the existing local report")
    require(plan["version"] == summary["version"] == VERSION and summary["status"] == "completed", "Archive requires a completed sweep")
    require(plan["date_range"] == summary["date_range"] == leaderboard["date_range"] == [DATES[0], DATES[-1]]
            and plan["timezone"] == "America/Los_Angeles", "Evaluation dates or timezone changed")
    require(plan["engine_config"] == CONFIG and leaderboard["harness_version"] == CONFIG["version"], "Frozen engine configuration changed")
    _fields(plan["runtime"], {"python", "ortools"}, "runtime")
    _fields(plan["budget"], {"id", "cap_usd", "automatic_paid_retries"}, "budget")
    require(plan["budget"]["automatic_paid_retries"] == 0 and 0 < plan["budget"]["cap_usd"] <= 30, "Budget or retry contract differs")
    _fields(plan["concurrency"], {"workers", "per_model_workers"}, "concurrency")
    require(1 <= plan["concurrency"]["workers"] <= 30 and 1 <= plan["concurrency"]["per_model_workers"] <= 6,
            "Concurrency contract differs")
    configurations = plan["configurations"]
    require(isinstance(configurations, list) and len(configurations) == 10, "Expected ten configurations")
    for config in configurations:
        _fields(config, CONFIG_FIELDS, "model configuration")
        _fields(config["discovery"], DISCOVERY_FIELDS, "model discovery")
        validate_configuration(config)
    by_id = {config["id"]: config for config in configurations}
    require(len(by_id) == 10 and len({config["model"] for config in configurations}) == 5,
            "Expected ten unique configurations and five distinct models")
    for model in {config["model"] for config in configurations}:
        require({config["reasoning"] for config in configurations if config["model"] == model} == {"on", "off"},
                "Each model requires true reasoning ON and OFF")
    require(plan["references"] == ["scripted", "deterministic"], "Matching reference controllers changed")
    controllers = [*plan["references"], *by_id]
    require(set(summary["controllers"]) == set(controllers) and set(summary["ai_usage"]) == set(by_id), "Incomplete controller aggregates")
    require(bool(plan["source_hashes"]) and all(_hash(value) for value in plan["source_hashes"].values())
            and summary["source_hashes"] == plan["source_hashes"], "Protocol and summary source hashes differ")
    _fields(verification["artifacts"], {"plan.json", "runs.json", "summary.json"}, "verification artifacts")
    _fields(summary["artifacts"], {"plan.json", "runs.json"}, "summary artifacts")
    require(verification["passed"] is True and verification["verification_kind"] == "independent_complete_matrix_causal_replay",
            "Independent complete-matrix verification must pass")
    require(_hash(verification["verifier_sha256"]), "Verifier source hash is missing")
    require(verification["artifacts"]["plan.json"] == digest(payloads["plan.json"])
            == summary["plan_sha256"] == summary["artifacts"]["plan.json"], "Verification does not bind the exact supplied plan")
    require(verification["artifacts"]["summary.json"] == digest(payloads["summary.json"]), "Verification does not bind the exact supplied summary")
    require(_hash(verification["artifacts"]["runs.json"])
            and verification["artifacts"]["runs.json"] == summary["artifacts"]["runs.json"], "Original run attestation differs")
    # Published reports omit full runs. The replay attestation binds their hash;
    # compact episode evidence below independently checks matrix membership.
    if (results / "runs.json").exists():
        require(digest((results / "runs.json").read_bytes()) == verification["artifacts"]["runs.json"], "Local full-run bytes differ from verification")
    _fields(verification["counts"], COUNT_FIELDS, "verification counts")
    counts = verification["counts"]
    require(all(counts.get(key) == expected for key, expected in {
        "episodes": 42, "controller_episode_results": 504, "source_arrival_operations_per_controller": 1029,
        "base_models": 5, "model_configurations": 10}.items()), "Verification does not cover the complete expected matrix")
    _fields(verification["source_verification"], SOURCE_VERIFICATION_FIELDS, "source verification")
    source = verification["source_verification"]
    require(source["selected_source_operations"] == 1029 and source["all_initial_states_synthetic"] is True
            and source["template_donors_development_only"] is True and source["source_weather_receipt_seconds"] == 300
            and source["whole_month_path_archive_opened"] is False, "Source reconstruction verification differs")
    _fields(verification["budget_verification"], BUDGET_VERIFICATION_FIELDS, "budget verification")
    budget = verification["budget_verification"]
    require(budget["budget_id"] == plan["budget"]["id"] and budget["cap_usd"] == plan["budget"]["cap_usd"]
            and budget["paid_retries"] == budget["unresolved_reservations"] == 0
            and budget["unscored_development_preflight_calls"] == 10, "Spending verification differs")
    _close(budget["settled_cost_plus_unknown_exposure_usd"], budget["known_cost_usd"] + budget["unknown_reserved_exposure_usd"], "known plus unknown cost")
    require(budget["settled_cost_plus_unknown_exposure_usd"] <= budget["cap_usd"] + 1e-9, "Spending cap was exceeded")
    orchestration = verification["orchestration_verification"]
    _fields(orchestration, ORCHESTRATION_FIELDS, "concurrency amendment verification")
    require(orchestration["amended"] is True and orchestration["kind"] == "execution_concurrency_only",
            "This dataset version requires the actual concurrency amendment proof")
    require(all(_hash(orchestration[key]) for key in ("plan_sha256", "helper_sha256", "amendment_sha256", "completion_sha256",
                                                     "main_execution_log_sha256", "helper_execution_log_sha256"))
            and orchestration["plan_sha256"] == digest(payloads["plan.json"]),
            "Concurrency amendment is not bound to the unchanged original plan and execution evidence")
    require(orchestration["helper_owned_windows"] == orchestration["original_runner_reused_windows"] == 180
            and orchestration["original_runner_finished_windows"] == 502
            and orchestration["original_runner_recovered_failed_windows"] == 2
            and orchestration["total_acknowledged_windows"] == 504,
            "Original runner did not verify every helper-owned outcome through the full matrix")
    require(plan["concurrency"] == {"workers": 30, "per_model_workers": 6}
            and orchestration["minimum_per_model_dispatch_seconds"] == 2.2
            and orchestration["maximum_combined_workers_per_model"] == 24
            and orchestration["spending_cap_usd"] == plan["budget"]["cap_usd"]
            and orchestration["semantic_settings_unchanged"] is True
            and orchestration["all_helper_jobs_owned_once"] is True,
            "Concurrency amendment changed pacing, spending, semantics or exclusive ownership")
    recovery = verification["recovery_verification"]
    _fields(recovery, RECOVERY_FIELDS, "interrupted-window recovery verification")
    require(recovery["recovered_jobs"] == 2 and recovery["reconstructed_fallback_decisions"] == 4
            and recovery["unknown_original_fallback_producer_decisions"] == 4
            and recovery["original_solver_status_and_bound_recovered"] is False,
            "Recovered slots must retain the unknown original fallback-producer and optimizer limits")
    require(_hash(recovery["execution_amendment_sha256"])
            and recovery["maximum_combined_workers_per_base_model"] == 25
            and recovery["maximum_recovery_workers_per_base_model"] == 1
            and recovery["minimum_shared_per_model_dispatch_seconds"] == 2.2
            and recovery["spending_cap_usd"] == plan["budget"]["cap_usd"]
            and recovery["payload_and_scoring_unchanged"] is True
            and recovery["original_paid_requests_preserved"] is True and recovery["paid_retries"] == 0,
            "Recovery changed ownership, pacing, spending, model payloads, scoring or paid-retry policy")
    require(isinstance(recovery["limits"], list) and len(recovery["limits"]) == 2
            and all(isinstance(limit, str) and limit for limit in recovery["limits"]), "Missing recovery evidence limits")
    jobs = recovery["jobs"]
    expected_recoveries = {("nemotron-3.5-super-vl-off", "2026-08-25-1500"): (2, 0),
                           ("nemotron-3.5-lightning-on", "2026-08-24-1200"): (5, 4)}
    require(isinstance(jobs, list) and len(jobs) == 2, "Both explicit interrupted-window recoveries are required")
    recovered_keys = set()
    for job in jobs:
        _fields(job, RECOVERY_JOB_FIELDS, "recovered window")
        key = job["configuration"], job["episode_id"]
        require(key in expected_recoveries and key not in recovered_keys, "Unknown or duplicate recovered window")
        recovered_keys.add(key)
        original_calls, reconstructed = expected_recoveries[key]
        require(job["original_calls"] == original_calls and job["reconstructed_fallback_decisions"] == reconstructed
                and job["original_calls_preserved"] is True and job["paid_retries"] == 0
                and all(_hash(job[name]) for name in ("manifest_sha256", "result_sha256", "source_sha256")),
                "Recovery manifest, exact-result evidence or preserved-request counts differ")
    require(recovered_keys == set(expected_recoveries) and len({job["source_sha256"] for job in jobs}) == 1,
            "Recovery jobs do not share the attested recovery implementation")
    require(set(verification["unscored_development_preflight_verification"]) == set(by_id), "Missing development reasoning-control checks")
    for identifier, check in verification["unscored_development_preflight_verification"].items():
        _fields(check, {"status", "reasoning_content_characters", "cost_usd", "scored"}, "development preflight")
        require(check["status"] == "completed" and check["scored"] is False
                and type(check["reasoning_content_characters"]) is int
                and (check["reasoning_content_characters"] > 0 if by_id[identifier]["reasoning"] == "on" else check["reasoning_content_characters"] == 0),
                "Actual reasoning ON/OFF preflight evidence differs")
    require(set(verification["ai_usage_independently_recomputed"]) == set(by_id), "Missing independently recomputed inference usage")
    for identifier in controllers:
        _metrics(summary["controllers"][identifier])
        if identifier in by_id:
            usage = summary["ai_usage"][identifier]
            _usage(usage)
            require(usage["calls"] == summary["controllers"][identifier]["decisions"], "Inference calls do not cover model decisions")
            recomputed = verification["ai_usage_independently_recomputed"][identifier]
            _fields(recomputed, {"calls", "statuses", "successful_calls", "reported_cost_usd", "unknown_cost_requests", "reserved_usd"}, "independent usage")
            for key in recomputed:
                if key in ("reported_cost_usd", "reserved_usd"):
                    require(math.isclose(recomputed[key], usage[key], abs_tol=1e-9), "Independently verified inference costs differ")
                else:
                    require(recomputed[key] == usage[key], "Independently verified usage differs")
    require(counts["replayed_decisions"] == sum(total["decisions"] for total in summary["controllers"].values())
            and counts["selected_ai_decisions"] == sum(usage["calls"] for usage in summary["ai_usage"].values())
            == counts["raw_audit_records"] == counts["unique_audit_request_ids"], "Verified decision/audit totals differ")
    episodes = load_episodes()
    traffic_bytes, manifest_bytes = (DATA_DIR / "evaluation.json").read_bytes(), (DATA_DIR / "manifest.json").read_bytes()
    require(digest(traffic_bytes) == plan["traffic_sha256"] and digest(manifest_bytes) == plan["traffic_manifest_sha256"], "Frozen evaluation traffic differs")
    episode_ids = [episode["id"] for episode in episodes]
    require(plan["episodes"] == episode_ids, "Protocol episode matrix differs")
    require(len({entry["flight_id"] for episode in episodes for entry in episode["entries"]}) == 1029,
            "Source demand is incomplete or repeats")
    require(leaderboard["verification"] == verification and leaderboard["ranked_configurations"] <= 10
            and leaderboard["matched_references"] == 2, "Leaderboard verification or reference counts differ")
    require(leaderboard["coverage"].get("episodes") == 42 and leaderboard["coverage"].get("arrivals") == 1029
            and leaderboard["coverage"].get("days") == 7, "Leaderboard coverage differs")
    entries = leaderboard["entries"]
    require(isinstance(entries, list) and len(entries) == 12 and {entry["id"] for entry in entries} == set(controllers), "Leaderboard matrix is incomplete")
    ordered = sorted((identifier for identifier in by_id if summary["controllers"][identifier]["safety_eligible"]),
                     key=lambda identifier: (summary["controllers"][identifier]["backlog"],
                                             summary["controllers"][identifier]["penalized_added_delay_seconds"], identifier))
    ranks, previous, previous_rank = {}, None, None
    for number, identifier in enumerate(ordered, 1):
        score = tuple(summary["controllers"][identifier][key] for key in ("backlog", "penalized_added_delay_seconds"))
        ranks[identifier] = previous_rank if score == previous else number
        previous, previous_rank = score, ranks[identifier]
    require(leaderboard["ranked_configurations"] == len(ordered), "Ranked configuration count differs from safety eligibility")
    compact_entries = []
    from .report import comparison_verdict, display_name
    for entry in entries:
        _fields(entry, ENTRY_FIELDS, "leaderboard entry")
        identifier = entry["id"]
        model = by_id.get(identifier)
        require(entry["model"] == (model["model"] if model else identifier)
                and entry["reasoning"] == (model["reasoning"] if model else "n/a")
                and entry["kind"] == ("model" if model else "reference"), "Leaderboard model identity differs")
        allowed_labels = {display_name(entry["model"])} | ({model["display_name"]} if model else set())
        require(entry["display_name"] in allowed_labels, "Leaderboard display name obscures the recorded model identity")
        require(entry["status"] == "completed" and entry["episodes_completed"] == entry["episodes_expected"] == 42
                and entry["verified"] is True and entry["rankable"] is True and entry["verification"] == {"passed": True},
                "Leaderboard entry is incomplete or unverified")
        require(entry["metrics"] == summary["controllers"][identifier], "Leaderboard measurements differ from verified summary")
        require(entry["harness_version"] == CONFIG["version"] and entry["eligible"] is entry["metrics"]["safety_eligible"]
                and entry["rank"] == ranks.get(identifier), "Leaderboard eligibility or objective ranking differs")
        _close(entry["completion_percent"], 100 * entry["metrics"]["completed"] / 1029, "completion percentage")
        if model:
            require(entry["usage"] == summary["ai_usage"][identifier], "Leaderboard inference measurements differ from verified summary")
        else:
            _fields(entry["usage"], {"calls", "reported_cost_usd", "successful_calls", "unknown_cost_requests",
                                     "latency_seconds_mean", "latency_seconds_p95"}, "local reference usage")
            require(entry["usage"]["calls"] == entry["usage"]["reported_cost_usd"] == 0,
                    "Local references cannot have inference charges")
        rows = entry["episode_results"]
        require(isinstance(rows, list) and len(rows) == 42 and {row["episode_id"] for row in rows} == set(episode_ids), "Leaderboard lacks the complete per-controller window matrix")
        for row in rows:
            require(row["controller"] == identifier and row["seed"] == 17 and row["variant"] == "nominal",
                    "Compact window evidence uses a different controller or protocol")
            expected = next(episode for episode in episodes if episode["id"] == row["episode_id"])
            require(row["spawned"] == len(expected["entries"]), "A controller received different historical demand")
        for key in ("spawned", "landed", "completed", "backlog", "executed_violations", "controller_failures", "fallback_decisions", "rejected_proposals", "unresolved_decisions"):
            require(sum(row[key] for row in rows) == entry["metrics"][key], "Window evidence differs from aggregate: " + key)
        require(sum(row["decision_count"] for row in rows) == entry["metrics"]["decisions"], "Window decision total differs")
        _close(sum(row["added_delay_seconds_sum"] for row in rows), entry["metrics"]["added_delay_seconds_sum"], "window delay total")
        # Per-window safety findings and traces stay local. Retain only verified
        # aggregate fields needed to recreate the leaderboard and its charts.
        compact_entries.append({key: entry[key] for key in sorted(ENTRY_FIELDS - {"episode_results", "verification"})})
    require(leaderboard["comparison_verdict"] == comparison_verdict(entries),
            "Model-to-reference verdict differs from the verified objective")
    compact = {"schema_version": "uita-compact-sweep-leaderboard-v1", "title": leaderboard["title"],
               "date_range": plan["date_range"], "harness_version": CONFIG["version"],
               "coverage": {"days": 7, "episodes": 42, "arrivals": 1029, "all_initial_states_synthetic": True},
               "entries": compact_entries, "audit_artifact": "verification.json",
               "comparison_verdict": leaderboard["comparison_verdict"],
               "limits": [*summary["limits"], *recovery["limits"]]}
    files = {"evaluation-traffic.json": traffic_bytes, "protocol.json": payloads["plan.json"],
             "aggregate-results.json": payloads["summary.json"], "leaderboard.json": encode(compact),
             "verification.json": payloads["verification.json"]}
    for payload in files.values():
        _safe(json.loads(payload))
    manifest = {"schema_version": 1, "id": DATASET_ID, "kind": "historical_arrival_admission_model_sweep",
                "date_range": plan["date_range"], "timezone": plan["timezone"], "episodes": 42,
                "source_spawns_per_controller": 1029, "controller_episode_outcomes": 504, "base_models": 5,
                "model_configurations": 10, "references": plan["references"], "configuration_ids": list(by_id),
                "seed": 17, "variant": "nominal", "position_strata": {"synthetic_training_template": 1029},
                "traffic_manifest_sha256": digest(manifest_bytes), "original_runs_sha256": verification["artifacts"]["runs.json"],
                "original_leaderboard_sha256": digest(payloads["leaderboard.json"]), "source_hashes": plan["source_hashes"],
                "safety_scope": CONFIG["safety_scope"], "computation_time": CONFIG["computation_time"],
                "held_out": "August 8–9 are excluded from construction, model inputs and evaluation.",
                "excluded": ["raw API logs", "reasoning text", "internal decisions", "per-flight outcomes", "per-window safety traces",
                             "development training payloads", "source code", "other dates and held-out data"],
                "files": {name: {"sha256": digest(payload), "bytes": len(payload)} for name, payload in sorted(files.items())}}
    files["manifest.json"] = encode(manifest)
    return manifest, files


def upload(manifest, files, results):
    """Write only this immutable dataset; verify server hashes and downloaded bytes."""
    from psycopg.types.json import Jsonb
    from pipeline.uita_data.store import connect

    with connect() as database:
        database.execute("INSERT INTO uita_data.datasets(id,manifest) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                         (DATASET_ID, Jsonb(manifest)))
        stored = database.execute("SELECT manifest FROM uita_data.datasets WHERE id=%s FOR UPDATE", (DATASET_ID,)).fetchone()
        require(stored and stored[0] == manifest, "Railway already has a different immutable dataset; use a new version")
        for name, payload in files.items():
            database.execute("INSERT INTO uita_data.artifacts(dataset_id,name,sha256,payload) VALUES (%s,%s,%s,%b) ON CONFLICT DO NOTHING",
                             (DATASET_ID, name, digest(payload), payload))
        rows = database.execute("SELECT name,sha256,encode(sha256(payload),'hex'),octet_length(payload) FROM uita_data.artifacts WHERE dataset_id=%s",
                                (DATASET_ID,)).fetchall()
        require(len(rows) == len(files) and {row[0] for row in rows} == set(files), "Railway artifact membership differs")
        for name, expected, actual, size in rows:
            require(expected == actual == digest(files[name]) and size == len(files[name]), "Railway server checksum or size differs: " + name)
    # This second connection sees committed data. Binary reads compare actual
    # downloaded payloads rather than trusting stored checksum columns alone.
    with connect() as database, database.cursor(binary=True) as cursor:
        cursor.execute("SELECT name,sha256,payload FROM uita_data.artifacts WHERE dataset_id=%s", (DATASET_ID,))
        rows = cursor.fetchall()
    require(len(rows) == len(files) and {row[0] for row in rows} == set(files), "Railway downloaded artifact membership differs")
    for name, expected, payload in rows:
        downloaded = bytes(payload)
        require(downloaded == files[name] and digest(downloaded) == expected, "Railway downloaded bytes differ: " + name)
    report = {"passed": True, "dataset_id": DATASET_ID, "artifacts": len(files), "bytes": sum(map(len, files.values())),
              "artifact_names": sorted(files), "episodes": 42, "controllers": 12, "base_models": 5, "model_configurations": 10,
              "source_spawns_per_controller": 1029, "all_server_checksums_verified": True, "all_downloaded_bytes_verified": True,
              "contains_final_test_data": False, "verified_at_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
    (Path(results) / "railway-verification.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    manifest, files = prepare(args.results)
    if args.execute:
        try:
            result = upload(manifest, files, args.results)
        except ValueError:
            raise
        except Exception:
            raise RuntimeError("Railway archive connection or write failed; credentials are not logged") from None
    else:
        result = {"status": "plan_only; no database connection or mutation", "dataset_id": DATASET_ID,
                  "artifacts": len(files), "bytes": sum(map(len, files.values())), "artifact_names": sorted(files),
                  "episodes": 42, "controllers": 12, "base_models": 5, "model_configurations": 10,
                  "source_spawns_per_controller": 1029, "position_strata": manifest["position_strata"]}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

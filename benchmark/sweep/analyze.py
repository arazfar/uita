"""Explain recorded model, API and token-budget failures without inference.

This reader never retries requests, changes policy, or calls a model. It reports
all recorded attempts separately from decisions selected by completed windows.
Example text contains final answers only; reasoning text is counted, not copied.
"""
from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import statistics

from benchmark.closed_loop.ai import SYSTEM_PROMPT, parse_action, validate_view
from benchmark.closed_loop.engine import percentile
from benchmark.provider import digest

VERSION = "historical-admission-failure-analysis-v1"
EXAMPLE_CONTENT_CHARACTERS = 400


def read(path):
    return json.loads(Path(path).read_text())


def _safe_text(text, limit=EXAMPLE_CONTENT_CHARACTERS):
    if not isinstance(text, str):
        return None
    text = re.sub(r"(?is)<think>.*?(?:</think>|$)", "[reasoning block omitted]", text)
    text = re.sub(r"(?is)<\|channel>(?:thought|analysis).*?(?:<channel\|>|$)", "[reasoning block omitted]", text)
    text = re.sub(r"(?i)bearer\s+[^\s\"']+", "Bearer [redacted]", text)
    text = re.sub(r"(?i)postgres(?:ql)?://[^\s\"']+", "[database URL redacted]", text)
    text = re.sub(r"\b(?:sk-|sk_|crusoe_)[A-Za-z0-9_-]{16,}", "[credential-shaped text redacted]", text)
    return text[:limit]


def _message(call):
    response = call.get("response")
    if not isinstance(response, dict):
        return None, None
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None, None
    message = choices[0].get("message")
    return choices[0], message if isinstance(message, dict) else None


def _public(call):
    try:
        public = json.loads(call["request"]["messages"][1]["content"])
        validate_view(public)
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    return public


def _contract_detail(content, public):
    if not isinstance(content, str):
        return "missing_final_text", {}
    if content.lstrip().startswith("```"):
        return "markdown_wrapped_json", {}
    try:
        action = json.loads(content)
    except (ValueError, TypeError):
        return "invalid_json", {}
    if not isinstance(action, dict):
        return "non_object_json", {}
    if set(action) != {"order"}:
        return "extra_or_missing_action_fields", {}
    order = action["order"]
    if not isinstance(order, list):
        return "invalid_order_type", {}
    if not all(isinstance(item, str) for item in order):
        return "invalid_order_elements", {}
    if public is None:
        return "unavailable_public_state", {}
    expected = {item["id"] for item in public["pending"]}
    returned = set(order)
    unknown = sorted(returned - expected)
    missing = sorted(expected - returned)
    details = {"returned_count": len(order), "expected_count": len(expected),
               "unknown_ids": [_safe_text(item, 32) for item in unknown[:10]], "missing_ids": missing[:10]}
    if len(order) != len(returned):
        return "duplicate_aircraft_ids", details
    if unknown:
        return "unknown_aircraft_ids", details
    if missing:
        return "missing_aircraft_ids", details
    # The strict parser also rejects duplicate keys and non-finite constants.
    return "strict_json_contract", details


def classify(call):
    """Attribute only errors supported by the preserved transport and final text."""
    status = call.get("status")
    choice, message = _message(call)
    finish = choice.get("finish_reason") if choice else call.get("finish_reason")
    public = _public(call)
    content = message.get("content") if message else None
    if status == "completed":
        try:
            action = parse_action(content, public)
        except (ValueError, TypeError, KeyError):
            return "audit_inconsistency", "completed_action_fails_reparse", {}
        if call.get("action") != action:
            return "audit_inconsistency", "saved_action_differs_from_response", {}
        return "usable_action", "strict_complete_permutation", {}
    if status == "ambiguous_failure":
        return "api_transport_failure", "response_not_received_no_retry", {}
    if status == "http_failure":
        code = call.get("http_status")
        detail = "rate_limit_429" if code == 429 else "provider_capacity_503" if code == 503 else "provider_http_5xx" if type(code) is int and code >= 500 else "request_or_api_http_error"
        return "api_http_failure", detail, {}
    if status in ("budget_or_dispatch_blocked", "unresolved_reservation") or not call.get("dispatched"):
        return "orchestration_block", str(call.get("failure", status)), {}
    if finish == "length":
        return "bounded_generation_failure", "output_token_limit", {}
    if finish not in (None, "stop"):
        return "bounded_generation_failure", "non_stop_finish_" + str(finish), {}
    if choice is None or message is None:
        return "provider_response_failure", "missing_response_structure", {}
    if finish != "stop":
        return "provider_response_failure", "missing_finish_reason", {}
    if not isinstance(content, str):
        return "provider_response_failure", "missing_final_text", {}
    if public is None:
        return "audit_inconsistency", "public_view_unavailable", {}
    try:
        parse_action(content, public)
    except (ValueError, TypeError, KeyError):
        detail, evidence = _contract_detail(content, public)
        return "model_contract_failure", detail, evidence
    return "audit_inconsistency", "usable_action_recorded_as_failure", {}


def _load_calls(path, warnings):
    result = []
    lines = path.read_text().splitlines()
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            call = json.loads(line)
        except ValueError:
            # A concurrent append can expose an unfinished last line. It cannot
            # be silently discarded from a completed analysis.
            warnings.append({"path": str(path), "line": index + 1, "issue": "unparsed_audit_line"})
            continue
        if not isinstance(call, dict) or not isinstance(call.get("request_id"), str):
            warnings.append({"path": str(path), "line": index + 1, "issue": "invalid_audit_record"})
            continue
        result.append(call)
    return result


def _unique(calls):
    result = {}
    for call in calls:
        identity = call["request_id"]
        if identity in result and result[identity].get("payload_sha256") != call.get("payload_sha256"):
            raise ValueError("Repeated request identity has changed payload")
        result[identity] = call
    return result


def _reasoning_characters(call):
    _, message = _message(call)
    if message is None:
        return None
    reasoning = message.get("reasoning_content", message.get("reasoning"))
    return len(reasoning) if isinstance(reasoning, str) else 0


def summarize(calls, mode):
    classified = [classify(call) for call in calls]
    groups = Counter(group for group, _, _ in classified)
    details = Counter(detail for _, detail, _ in classified)
    latencies = [call["latency_seconds"] for call in calls if call.get("dispatched")
                 and type(call.get("latency_seconds")) in (int, float)
                 and math.isfinite(call["latency_seconds"]) and call["latency_seconds"] >= 0]
    known_costs = [call["cost_usd"] for call in calls if type(call.get("cost_usd")) in (int, float)]
    observed = [_reasoning_characters(call) for call in calls]
    present = [count for count in observed if count is not None]
    return {
        "calls": len(calls), "dispatched": sum(bool(call.get("dispatched")) for call in calls),
        "groups": dict(groups), "details": dict(details),
        "usable_response_percent": 100 * groups["usable_action"] / len(calls) if calls else None,
        "known_cost_usd": sum(known_costs), "unknown_cost_calls": sum(call.get("cost_usd") is None for call in calls),
        "unknown_cost_reserved_usd": sum(call.get("reserved_usd", 0) for call in calls if call.get("cost_usd") is None),
        "latency_seconds": {"mean": statistics.mean(latencies) if latencies else None,
                            "p50": percentile(latencies, .5), "p95": percentile(latencies, .95)},
        "reasoning_observability": {"requested_mode": mode, "responses_with_message": len(present),
                                    "nonempty_returned_reasoning": sum(count > 0 for count in present),
                                    "empty_or_missing_returned_reasoning": sum(count == 0 for count in present),
                                    "responses_without_message": sum(count is None for count in observed),
                                    "unexpected_nonempty_when_off": sum(count > 0 for count in present) if mode == "off" else 0},
    }


def _example(call, configuration):
    group, detail, extra = classify(call)
    public = _public(call)
    _, message = _message(call)
    response = call.get("response")
    usage = response.get("usage") if isinstance(response, dict) else None
    return {
        "config_id": configuration["id"], "model": configuration["model"], "reasoning": configuration["reasoning"],
        "request_id": call["request_id"], "group": group, "detail": detail,
        "http_status": call.get("http_status"), "finish_reason": call.get("finish_reason"),
        "latency_seconds": call.get("latency_seconds"), "known_cost_usd": call.get("cost_usd"),
        "clock_seconds": public.get("clock_seconds") if public else None,
        "episode_id": public.get("episode_id") if public else None,
        "source_episode_id": (re.search(r":(2026-\d{2}-\d{2}-\d{4}):", call["request_id"]).group(1)
                              if re.search(r":(2026-\d{2}-\d{2}-\d{4}):", call["request_id"]) else None),
        "pending_count": len(public["pending"]) if public else None,
        "pending_ids_first_twenty": [item["id"] for item in public["pending"][:20]] if public else [],
        "final_answer_excerpt": _safe_text(message.get("content")) if message else None,
        "completion_tokens": usage.get("completion_tokens") if isinstance(usage, dict) else None,
        "contract_details": extra,
        "interpretation": {
            "model_contract_failure": "A complete final response violated the exact pending-ID action contract. This is a model response mistake.",
            "api_transport_failure": "The client did not receive a complete response. This does not establish a scheduling or reasoning mistake.",
            "api_http_failure": "The API returned an HTTP error. Provider or request handling failed before a usable model action; HTTP status alone cannot establish model quality.",
            "bounded_generation_failure": "The configured generation boundary prevented a completed action. This measures reliability under the frozen budget, not unrestricted reasoning ability.",
            "provider_response_failure": "The response lacked the fields needed to judge the final action. Attribution to model competence is uncertain.",
            "orchestration_block": "The local spending or dispatch boundary stopped this job. It must remain incomplete and cannot receive a competitive score.",
            "audit_inconsistency": "The preserved response and audit status disagree. Investigate this evidence before publishing a score.",
        }.get(group, "A valid action passed the strict output contract. Scheduling quality requires the separate closed-loop outcomes."),
    }


def analyze(run):
    run = Path(run)
    plan = read(run / "plan.json")
    configurations = plan["configurations"]
    expected_episodes = set(plan["episodes"])
    warnings, entries, all_calls, preflight_calls = [], [], [], []
    complete_windows = 0
    config_by_id = {c["id"]: c for c in configurations}
    for configuration in configurations:
        config_id = configuration["id"]
        calls = _unique([call for path in sorted((run / "configs" / config_id / "episodes").glob("*/calls.jsonl"))
                         for call in _load_calls(path, warnings)])
        for call in calls.values():
            if call.get("config_id") != config_id or not call["request_id"].startswith(config_id + ":"):
                raise ValueError("Audit identity differs from its configuration directory")
        selected_ids, completed_episodes = set(), set()
        for path in sorted((run / "episodes" / config_id).glob("*.json")):
            row = read(path)
            if row.get("episode_id") not in expected_episodes or row.get("controller") != config_id:
                raise ValueError("Completed outcome is outside its frozen configuration or episode set")
            episode_id = row["episode_id"]
            completed_episodes.add(episode_id)
            for decision in row["decisions"]:
                engine_id = f"cl-{digest(SYSTEM_PROMPT)[:12]}:{episode_id}:17:{int(decision['time_seconds'])}"
                selected_ids.add(config_id + ":" + engine_id)
        missing = sorted(selected_ids - calls.keys())
        if missing:
            warnings.append({"config_id": config_id, "issue": "completed_decisions_missing_audits", "count": len(missing)})
        selected = [calls[identifier] for identifier in sorted(selected_ids & calls.keys())]
        raw = [calls[identifier] for identifier in sorted(calls)]
        preflight_path = run / "preflight" / config_id / "calls.jsonl"
        preflight = list(_unique(_load_calls(preflight_path, warnings)).values()) if preflight_path.exists() else []
        complete_windows += len(completed_episodes)
        entries.append({"config_id": config_id, "model": configuration["model"], "reasoning": configuration["reasoning"],
                        "completed_windows": len(completed_episodes), "expected_windows": len(expected_episodes),
                        "all_recorded_attempts": summarize(raw, configuration["reasoning"]),
                        "selected_completed_window_decisions": summarize(selected, configuration["reasoning"]),
                        "not_yet_selected_attempts": len(calls.keys() - selected_ids),
                        "preflight": summarize(preflight, configuration["reasoning"])})
        all_calls.extend(raw)
        preflight_calls.extend(preflight)
    verification = read(run / "verification.json") if (run / "verification.json").exists() else {}
    bound_verified = verification.get("passed") is True and all(
        (run / name).exists() and hashlib.sha256((run / name).read_bytes()).hexdigest() == verification.get("artifacts", {}).get(name)
        for name in ("plan.json", "runs.json", "summary.json"))
    expected_windows = len(expected_episodes) * len(configurations)
    complete = complete_windows == expected_windows and not warnings and bound_verified
    failures = sorted((call for call in all_calls if classify(call)[0] != "usable_action"), key=lambda call: call["request_id"])
    # Choose the first lexical request in each observed failure kind, regardless
    # of its controller score. No examples are fabricated for absent failures.
    examples, seen = [], set()
    for call in failures:
        group, detail, _ = classify(call)
        key = (group, detail, call.get("http_status") if group == "api_http_failure" else None)
        if key in seen:
            continue
        seen.add(key)
        examples.append(_example(call, config_by_id[call["config_id"]]))
        if len(examples) == 10:
            break
    return {
        "version": VERSION, "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": "complete_verified" if complete else "incomplete_or_unverified",
        "date_range": plan["date_range"], "completed_model_windows": complete_windows,
        "expected_model_windows": expected_windows, "independent_replay_bound_to_current_artifacts": bound_verified,
        "plan_sha256": hashlib.sha256((run / "plan.json").read_bytes()).hexdigest(), "warnings": warnings,
        "scope": "Failure attribution for recorded calls only; scheduling quality remains measured by the closed-loop leaderboard.",
        "denominators": "All recorded attempts include unfinished jobs. Selected decisions include completed model-window outcomes only. Preflights are separate and unscored.",
        "failure_definitions": {
            "model_contract_failure": "A stopped text response fails the exact JSON pending-ID permutation contract.",
            "api_transport_failure": "No complete API response reached the client; no paid retry occurred.",
            "api_http_failure": "An HTTP error reached the client; 429, 503, other 5xx and request/API errors remain distinct.",
            "bounded_generation_failure": "The configured output limit or another non-stop finish prevented a complete answer.",
            "provider_response_failure": "Missing response structure or final text prevents reliable model attribution.",
            "orchestration_block": "A local budget, dispatch, or unresolved-reservation boundary stopped an incomplete job.",
            "audit_inconsistency": "Response, stored action and audit classification disagree; publish no unsupported attribution.",
        },
        "limitations": ["A valid action is not evidence of an optimal schedule.",
                        "Timeouts do not establish whether the provider generated an answer or incurred a charge.",
                        "Token-limit failures measure this output budget and cannot prove unrestricted model inability.",
                        "Returned reasoning is an observation, not proof of every internal computation. Missing reasoning fields alone cannot prove OFF.",
                        "Examples contain at most 400 final-answer characters and never copy reasoning bodies or HTTP error bodies.",
                        "All compared model actions use the same checked decoder and counted fallback policy. August 8–9 remain held out."],
        "configurations": entries, "all_recorded_attempts": summarize(all_calls, "mixed"),
        "preflight_attempts": summarize(preflight_calls, "mixed"),
        "example_selection": "First request by lexical ID for each observed failure group/detail/HTTP status, at most ten; no invented examples.",
        "examples": examples,
    }


def markdown(document):
    lines = ["# Model and API failure analysis", "",
             f"Status: **{document['status']}**. Completed model windows: {document['completed_model_windows']}/{document['expected_model_windows']}.",
             "", document["scope"], "", document["denominators"], "",
             "A model response mistake requires a complete final response that violates the action contract. Transport and HTTP failures are separate. "
             "Truncation measures reliability under the frozen output budget. A valid action does not establish a good schedule.", "",
             "The table includes all recorded attempts, including unfinished jobs. It cannot rank model performance.", "",
             "| Configuration | Calls | Usable | Model contract | API transport | API HTTP | Token/finish boundary | Other | Known $ | Unknown cost | P95 latency |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for entry in document["configurations"]:
        summary = entry["all_recorded_attempts"]
        groups = summary["groups"]
        other = sum(value for key, value in groups.items() if key not in {
            "usable_action", "model_contract_failure", "api_transport_failure", "api_http_failure", "bounded_generation_failure"})
        p95 = summary["latency_seconds"]["p95"]
        p95_text = f"{p95:.2f}s" if p95 is not None else "—"
        lines.append(f"| {entry['config_id']} | {summary['calls']} | {groups.get('usable_action', 0)} | {groups.get('model_contract_failure', 0)} | "
                     f"{groups.get('api_transport_failure', 0)} | {groups.get('api_http_failure', 0)} | {groups.get('bounded_generation_failure', 0)} | "
                     f"{other} | {summary['known_cost_usd']:.5f} | {summary['unknown_cost_calls']} | {p95_text} |")
    lines.extend(["", "Known charges exclude unknown charges. Unknown requests retain their full reservation in the shared spending cap.", "",
                  "## Reasoning controls", "",
                  "| Configuration | Evaluation responses with reasoning | Evaluation responses with empty/missing reasoning | Preflight with reasoning | Unexpected OFF reasoning |",
                  "|---|---:|---:|---:|---:|"])
    for entry in document["configurations"]:
        observed = entry["all_recorded_attempts"]["reasoning_observability"]
        preflight = entry["preflight"]["reasoning_observability"]
        lines.append(f"| {entry['config_id']} | {observed['nonempty_returned_reasoning']} | {observed['empty_or_missing_returned_reasoning']} | "
                     f"{preflight['nonempty_returned_reasoning']} | {observed['unexpected_nonempty_when_off']} |")
    lines.extend(["", "Counts describe returned API fields. Missing reasoning fields alone cannot prove that internal reasoning was disabled.", "",
                  "## Example cases", "", document["example_selection"], ""])
    if not document["examples"]:
        lines.extend(["No failures were observed in the available audit records.", ""])
    for example in document["examples"]:
        lines.extend([f"### {example['config_id']}: {example['detail']}", "",
                      f"Episode `{example['source_episode_id'] or example['episode_id']}`, clock {example['clock_seconds']}s. Pending aircraft: "
                      + ", ".join(example["pending_ids_first_twenty"]) + f" ({example['pending_count']} total).", "",
                      f"HTTP {example['http_status']}; finish reason `{example['finish_reason']}`; latency {example['latency_seconds']:.2f}s.", "",
                      example["interpretation"], ""])
        details = example["contract_details"]
        if details.get("missing_ids"):
            lines.extend(["Missing pending IDs: " + ", ".join(details["missing_ids"]) + ".", ""])
        if details.get("unknown_ids"):
            lines.extend(["Unexpected IDs: " + json.dumps(details["unknown_ids"]) + ".", ""])
        if example["completion_tokens"] is not None:
            lines.extend([f"Reported output tokens: {example['completion_tokens']}.", ""])
        if example["final_answer_excerpt"] is not None:
            lines.extend(["Final-answer excerpt (maximum 400 characters; JSON escaping preserves literal text):", "",
                          "```json", json.dumps(example["final_answer_excerpt"], ensure_ascii=False), "```", ""])
        else:
            lines.extend(["No final-answer text was available to inspect.", ""])
    lines.extend(["## Limits", ""] + ["- " + limit for limit in document["limitations"]] + [""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    document = analyze(args.run)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "failure-analysis.json").write_text(json.dumps(document, indent=2, allow_nan=False) + "\n")
    (args.out / "failure-analysis.md").write_text(markdown(document))
    print(json.dumps({"status": document["status"], "model_windows": document["completed_model_windows"],
                      "calls": document["all_recorded_attempts"]["calls"], "examples": len(document["examples"]),
                      "warnings": len(document["warnings"])}))


if __name__ == "__main__":
    main()

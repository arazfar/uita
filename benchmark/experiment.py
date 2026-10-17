"""Review, price, submit and collect one bounded historical-order SFT job.

prepare is read-only against Crusoe. upload and start require explicit execute
flags. Each paid job consumes one experiment directory permanently, including
ambiguous failures. Final-test files are never opened by this module.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import time

from .core import canonical as core_canonical, load_cases, model_messages, parse_action
from .crusoe import Client, CrusoeError, Experiment, TERMINAL, canonical, scrub, sha256

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path(__file__).with_name("experiment-config.json")
DEFAULT_RUN = ROOT / "output/crusoe-sft-2026-10-17"
ALLOWED_DATES = {"train": {f"2026-08-{day:02d}" for day in range(3, 7)}, "validation": {"2026-08-07"}}


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scrub(value), indent=2, allow_nan=False) + "\n")


def config_path(config: dict, key: str) -> Path:
    value = Path(config[key])
    return value if value.is_absolute() else ROOT / value


def preflight(config: dict) -> dict:
    """Reconstruct every uploaded message and label from approved source cases."""
    source = config_path(config, "source_data_directory")
    exports = config_path(config, "reviewed_export_directory")
    manifest_path = exports / "export-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema_version") != "historical_order_reviewed_export_v1" or not manifest.get("reviewer"):
        raise CrusoeError("An independently reviewed export manifest is required")
    if manifest.get("target_provenance") != "historical_arrival_operation_order_proxy":
        raise CrusoeError("Unsupported target provenance")
    if not isinstance(manifest.get("review_scope"), str) or len(manifest["review_scope"]) < 40:
        raise CrusoeError("Reviewer scope must describe independent review")
    if config.get("dates", {}).get("train") != sorted(ALLOWED_DATES["train"]) or config.get("dates", {}).get("validation") != ["2026-08-07"]:
        raise CrusoeError("Experiment split dates differ from the frozen boundary")
    source_manifest = json.loads((source / "manifest.json").read_text())
    if source_manifest.get("split_dates") != {k: sorted(v) for k, v in ALLOWED_DATES.items()}:
        raise CrusoeError("Source manifest split boundary differs")
    lineage = manifest.get("lineage", [])
    identifiers = [row["example_id"] for row in lineage]
    encounters = [row["encounter_id"] for row in lineage]
    if len(set(identifiers)) != len(identifiers) or len(set(encounters)) != len(encounters):
        raise CrusoeError("Reviewed export contains duplicate examples or encounters")
    if any(row.get("split") not in ALLOWED_DATES or row.get("local_date") not in ALLOWED_DATES[row["split"]] for row in lineage):
        raise CrusoeError("Reviewed export contains an unknown or held-out date")
    artifacts = {}
    used_aircraft = set()
    total_bytes = 0
    total_samples = 0
    for split in ("train", "validation"):
        path = exports / f"{split}.jsonl"
        payload = path.read_bytes()
        digest = sha256(payload)
        if digest != manifest.get(split + "_file_sha256"):
            raise CrusoeError(f"Reviewed {split} content hash changed")
        if sha256((source / f"{split}.jsonl").read_bytes()) != source_manifest["artifacts"][f"{split}.jsonl"]["sha256"]:
            raise CrusoeError(f"Frozen {split} source content hash changed")
        cases = {case["case_id"]: case for case in load_cases(split, source)}
        rows = [json.loads(line) for line in payload.splitlines() if line.strip()]
        provenance = [row for row in lineage if row["split"] == split]
        if len(rows) != len(provenance) or len(rows) != manifest["accepted_counts"][split]:
            raise CrusoeError(f"Reviewed {split} row counts disagree")
        if len(rows) < (100 if split == "train" else 20):
            raise CrusoeError("Small experiment requires at least 100 train and 20 explicit validation examples")
        seen_states = set()
        max_bytes = 0
        for row, trace in zip(rows, provenance):
            if set(row) != {"messages"}:
                raise CrusoeError("Uploaded rows may contain only messages")
            case = cases.get(trace["case_id"])
            if not case or case["local_date"] != trace["local_date"] or case["encounter_id"] != trace["encounter_id"]:
                raise CrusoeError("Reviewed lineage does not match a permitted source encounter")
            source_ids = set(case["private"]["source_flight_ids"])
            if source_ids & used_aircraft:
                raise CrusoeError("An aircraft repeats across reviewed train or validation examples")
            used_aircraft |= source_ids
            messages = row["messages"]
            if len(messages) != 3 or messages[:2] != model_messages(case) or set(messages[2]) != {"role", "content"} or messages[2]["role"] != "assistant":
                raise CrusoeError("Training and baseline prompts differ or contain unexpected fields")
            action = parse_action(messages[2]["content"], case["input"])
            if action["order"] != case["private"]["historical_order"]:
                raise CrusoeError("Training target differs from the reviewed historical operation-order label")
            state_sha = sha256(core_canonical(case["input"]).encode())
            if state_sha != trace["state_sha256"] or state_sha in seen_states:
                raise CrusoeError("Reviewed state changed or repeats")
            if sha256(core_canonical(action).encode()) != trace["target_sha256"]:
                raise CrusoeError("Reviewed target changed")
            seen_states.add(state_sha)
            row_bytes = len(canonical(row))
            max_bytes = max(max_bytes, row_bytes)
            if row_bytes > 65536:
                raise CrusoeError("A reviewed sample exceeds the frozen 64 KiB bound")
        artifacts[split] = {"path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                            "sha256": digest, "bytes": len(payload), "examples": len(rows),
                            "maximum_row_bytes": max_bytes,
                            "dates": dict(Counter(trace["local_date"] for trace in provenance))}
        if split == "train":
            total_bytes, total_samples = len(payload), len(rows)
    epochs = config["hyperparameters"].get("n_epochs")
    rate, cap = config["training_usd_per_million_tokens"], config["training_reservation_cap_usd"]
    if type(epochs) is not int or not 1 <= epochs <= 2:
        raise CrusoeError("Only one or two explicitly bounded training epochs are permitted")
    if any(not isinstance(x, (int, float)) or not math.isfinite(x) or x <= 0 for x in (rate, cap)):
        raise CrusoeError("Training price and reservation must be finite and positive")
    # Without the private base tokenizer, reserve two tokens per UTF-8 byte plus
    # 1,024 framing/special tokens per example. This is conservative accounting,
    # not a provider quote or a platform-enforced dollar limit.
    tokens = (2 * total_bytes + 1024 * total_samples) * epochs
    cost = tokens * rate / 1_000_000
    if cost > cap:
        raise CrusoeError(f"Conservative training reservation ${cost:.4f} exceeds cap ${cap:.2f}")
    immutable = {"config_sha256": sha256(canonical(config)), "export_manifest_sha256": sha256(manifest_path.read_bytes()),
                 "artifacts": artifacts, "training_token_reservation": tokens,
                 "training_cost_reservation_usd": cost, "target_provenance": manifest["target_provenance"],
                 "reviewer": manifest["reviewer"], "held_out_test": "August 8–9 unopened; train and explicit validation only"}
    immutable["approval_fingerprint"] = sha256(canonical(immutable))
    return immutable


def job_payload(config: dict, plan: dict, state: dict) -> dict:
    for split in ("train", "validation"):
        uploaded, reviewed = state.get("files", {}).get(split, {}), plan["artifacts"][split]
        if uploaded.get("sha256") != reviewed["sha256"] or uploaded.get("bytes") != reviewed["bytes"] or not uploaded.get("id"):
            raise CrusoeError("Stored uploaded file does not match the exact reviewed corpus")
    return {"model": config["training_model"], "training_file": state["files"]["train"]["id"],
            "validation_file": state["files"]["validation"]["id"],
            "suffix": "uita-hist-" + plan["approval_fingerprint"][:20], "seed": config["seed"],
            "method": {"type": "supervised", "supervised": {"hyperparameters": config["hyperparameters"]}},
            "metadata": {"experiment": config["experiment"], "review_sha256": plan["export_manifest_sha256"],
                         "plan_sha256": plan["approval_fingerprint"], "target": plan["target_provenance"]}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("discover", "prepare", "upload", "estimate", "start", "status", "watch", "cancel", "download"))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--run-directory", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--execute-reviewed", action="store_true")
    parser.add_argument("--approved-fingerprint")
    parser.add_argument("--checkpoint")
    parser.add_argument("--max-wait-seconds", type=int, default=3600)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if args.command in {"upload", "start"} and config.get("fine_tuning_authorized") is not True:
        raise CrusoeError("Fine-tuning is deferred by the user; uploads and job submission are disabled")
    client = Client()
    if args.command == "discover":
        model = next((m for m in client.models() if m["id"] == config["training_model"]), None)
        result = {"model": model, "existing_job_count": len(client.jobs()),
                  "existing_file_count": len(client.files()), "collected_at_epoch": time.time()}
        write_json(args.run_directory / "discovery.json", result)
    elif args.command in {"prepare", "upload", "estimate", "start"}:
        plan = preflight(config)
        model = next((m for m in client.models() if m["id"] == config["training_model"]), None)
        if not model or not model.get("fine_tuning_available") or model.get("model_name") != config["training_model_name"]:
            raise CrusoeError("Authenticated training model differs from the reviewed configuration")
        write_json(args.run_directory / "plan.json", plan | {"model_discovery": model})
        result = plan
        if args.command != "prepare":
            if args.command in {"upload", "start"} and (not args.execute_reviewed or args.approved_fingerprint != plan["approval_fingerprint"]):
                raise CrusoeError("Mutation requires --execute-reviewed and the exact reviewed plan fingerprint")
            experiment = Experiment(args.run_directory, client=client)
            if args.command == "upload":
                exports = config_path(config, "reviewed_export_directory")
                result = {split: experiment.upload(exports / f"{split}.jsonl", split,
                                                   expected_sha256=plan["artifacts"][split]["sha256"])
                          for split in ("train", "validation")}
            else:
                state = json.loads(experiment.path.read_text())
                payload = job_payload(config, plan, state)
                if args.command == "estimate":
                    result = experiment.estimate(payload)
                else:
                    estimate = state.get("price_estimate", {})
                    if estimate.get("request_sha256") != sha256(canonical(payload)):
                        raise CrusoeError("A price estimate for this exact payload is required before starting")
                    quote = estimate["result"]
                    if quote.get("currency") != "usd" or not 0 < float(quote["estimated_price"]) <= plan["training_cost_reservation_usd"]:
                        raise CrusoeError("Provider price estimate exceeds reservation or is not a positive USD amount")
                    result = experiment.start(payload, cost_reservation_usd=plan["training_cost_reservation_usd"],
                                              max_runtime_seconds=config["max_runtime_seconds"])
    else:
        experiment = Experiment(args.run_directory, client=client)
        if args.command == "cancel":
            result = experiment.cancel()
        elif args.command == "download":
            if not args.checkpoint:
                raise CrusoeError("--checkpoint must name a result of this experiment")
            result = experiment.download(args.checkpoint)
        elif args.command == "status":
            result = experiment.status(cancel_overdue=True)
        else:
            if not 1 <= args.max_wait_seconds <= 7200:
                raise CrusoeError("Watch duration must be between 1 and 7,200 seconds")
            deadline = time.monotonic() + args.max_wait_seconds
            previous = None
            while True:
                result = experiment.status(cancel_overdue=True)
                current = result["status"]
                if current != previous:
                    print(json.dumps({"status": current, "job_id": result["id"]}), flush=True)
                    previous = current
                if current in TERMINAL:
                    break
                if time.monotonic() >= deadline:
                    result = experiment.cancel()
                    break
                time.sleep(min(30, max(1, deadline - time.monotonic())))
    print(json.dumps(scrub(result), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()

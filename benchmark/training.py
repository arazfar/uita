"""Build historical-order candidates, then export only independently approved rows.

Candidates are labels from the operation roster, not authentic controller commands.
Generation never grants review approval. Export requires a separate audit and an
independent reviewer's decisions, bound to the exact candidate bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from .core import DATA_DIR, VERSION, canonical, load_cases, model_messages, parse_action

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "benchmark/artifacts/training"
PROVENANCE = "historical_arrival_operation_order_proxy"
ALLOWED_DATES = {
    "train": {f"2026-08-{day:02d}" for day in range(3, 7)},
    "validation": {"2026-08-07"},
}


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def write_rows(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(canonical(row) + "\n" for row in rows))


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def candidates(data_dir, output_dir):
    """Produce one candidate per disjoint encounter; no alias augmentation."""
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    encounters = set()
    states = set()
    all_source_ids = set()
    source_files = {}
    for split in ("train", "validation"):
        source_files[split] = file_digest(data_dir / f"{split}.jsonl")
        for case in load_cases(split, data_dir):
            if case["local_date"] not in ALLOWED_DATES[split]:
                raise ValueError("Refusing dates outside the frozen training/validation boundary")
            if case["encounter_id"] in encounters:
                raise ValueError("An encounter cannot produce multiple training candidates")
            encounters.add(case["encounter_id"])
            state_hash = digest(case["input"])
            if state_hash in states:
                raise ValueError("Duplicate model state")
            states.add(state_hash)
            source_ids = set(case["private"]["alias_to_source"].values())
            if all_source_ids & source_ids:
                raise ValueError("Aircraft reused across encounters or splits")
            all_source_ids |= source_ids
            action = parse_action(canonical({"order": case["private"]["historical_order"]}), case["input"])
            messages = model_messages(case) + [{"role": "assistant", "content": canonical(action)}]
            row = {
                "schema_version": "historical_order_candidates_v1",
                "benchmark_version": VERSION,
                "case_id": case["case_id"],
                "encounter_id": case["encounter_id"],
                "local_date": case["local_date"],
                "split": split,
                "target_provenance": PROVENANCE,
                "source_case_sha256": digest(case),
                "state_sha256": state_hash,
                "target_sha256": digest(action),
                "messages": messages,
            }
            row["example_id"] = "example-" + digest(row)[:24]
            rows.append(row)
    if not all(any(row["split"] == split for row in rows) for split in ALLOWED_DATES):
        raise ValueError("Both train and validation require candidates")
    candidate_path = output_dir / "candidates.jsonl"
    write_rows(candidate_path, rows)
    manifest = {
        "schema_version": "historical_order_training_manifest_v1",
        "status": "candidates_only; independent audit and reviewer decisions required",
        "target_provenance": PROVENANCE,
        "counts": dict(Counter(row["split"] for row in rows)),
        "unique_encounters": len(encounters),
        "unique_aircraft": len(all_source_ids),
        "augmentation": "none",
        "source_files_sha256": source_files,
        "candidate_file_sha256": file_digest(candidate_path),
        "code_sha256": file_digest(Path(__file__)),
        "limits": [
            "Roster order is an observational proxy, not a human command or optimal action label.",
            "No expert ATC review is implied by program audit or agent review.",
            "August 8–9 payloads and labels are neither loaded nor exported.",
            "Historical mismatch does not establish inferior safety or control quality.",
        ],
    }
    write_json(output_dir / "candidate-manifest.json", manifest)
    return manifest


def export(candidate_path, audit_path, decisions_path, data_dir, output_dir):
    """Bind separate per-row mechanical audit and agent decisions before export."""
    rows = read_rows(candidate_path)
    audit = json.loads(audit_path.read_text())
    decisions = json.loads(decisions_path.read_text())
    candidate_hash = file_digest(candidate_path)
    if audit.get("candidate_file_sha256") != candidate_hash:
        raise ValueError("Audit does not cover these exact candidate bytes")
    if decisions.get("candidate_file_sha256") != candidate_hash:
        raise ValueError("Reviewer decisions do not cover these exact candidate bytes")
    if decisions.get("audit_file_sha256") != file_digest(audit_path):
        raise ValueError("Reviewer decisions are not bound to the supplied audit")
    if not decisions.get("reviewer") or decisions.get("reviewer_role") != "independent_agent_review":
        raise ValueError("A separate independent agent reviewer must identify itself")
    if not isinstance(decisions.get("review_scope"), str) or len(decisions["review_scope"].strip()) < 40:
        raise ValueError("Reviewer must state code, all-row audit and sampled-example review scope")
    checks = {row["example_id"]: row for row in audit.get("examples", [])}
    reviews = {row["example_id"]: row for row in decisions.get("decisions", [])}
    ids = {row["example_id"] for row in rows}
    if len(ids) != len(rows) or set(checks) != ids or set(reviews) != ids:
        raise ValueError("Every unique candidate needs exactly one audit and reviewer decision")
    if len(checks) != len(audit.get("examples", [])) or len(reviews) != len(decisions.get("decisions", [])):
        raise ValueError("Duplicate per-example audit or review decisions")
    current_cases = {}
    for split in ALLOWED_DATES:
        for case in load_cases(split, data_dir):
            current_cases[case["case_id"]] = case
    exported = {"train": [], "validation": []}
    lineage = []
    accepted = Counter()
    rejected = Counter()
    for row in rows:
        example_id = row["example_id"]
        check = checks[example_id]
        review = reviews[example_id]
        if check.get("candidate_sha256") != digest(row) or review.get("candidate_sha256") != digest(row):
            raise ValueError("Per-example audit and decision must bind the exact candidate")
        if not isinstance(review.get("reason"), str) or len(review["reason"].strip()) < 20:
            raise ValueError("Every reviewer decision requires a specific reason")
        if review.get("decision") not in ("approve", "reject"):
            raise ValueError("Reviewer decision must be approve or reject")
        if review["decision"] == "reject":
            rejected[row["split"]] += 1
            continue
        if check.get("status") != "pass" or not check.get("checks") or not all(check["checks"].values()):
            raise ValueError("Reviewer cannot approve a failed or incomplete independent audit")
        case = current_cases.get(row["case_id"])
        if case is None or digest(case) != row["source_case_sha256"]:
            raise ValueError("Source case changed since candidate generation")
        if row["local_date"] not in ALLOWED_DATES.get(row["split"], set()):
            raise ValueError("Export refused a held-out or unknown date")
        if row["target_provenance"] != PROVENANCE:
            raise ValueError("Target provenance differs from this historical-order experiment")
        action = parse_action(row["messages"][2]["content"], case["input"])
        expected = model_messages(case) + [{"role": "assistant", "content": canonical(action)}]
        if row["messages"] != expected or action["order"] != case["private"]["historical_order"]:
            raise ValueError("Export requires exact baseline messages and source historical target")
        exported[row["split"]].append({"messages": row["messages"]})
        accepted[row["split"]] += 1
        lineage.append({key: row[key] for key in ("example_id", "case_id", "encounter_id", "split", "local_date",
                                                 "state_sha256", "target_sha256", "target_provenance")}
                       | {"audit_reason": check["reason"], "reviewer": decisions["reviewer"],
                          "review_reason": review["reason"], "candidate_sha256": digest(row)})
    if not all(exported.values()):
        raise ValueError("Approved training and explicit validation examples are both required")
    output_dir.mkdir(parents=True, exist_ok=True)
    for split, items in exported.items():
        write_rows(output_dir / f"{split}.jsonl", items)
    manifest = {
        "schema_version": "historical_order_reviewed_export_v1",
        "status": "independently audited and agent-reviewed; no upload or training submitted by exporter",
        "target_provenance": PROVENANCE,
        "accepted_counts": dict(accepted), "rejected_counts": dict(rejected),
        "unique_encounters": len({row["encounter_id"] for row in lineage}),
        "candidate_file_sha256": candidate_hash,
        "audit_file_sha256": file_digest(audit_path),
        "decisions_file_sha256": file_digest(decisions_path),
        "train_file_sha256": file_digest(output_dir / "train.jsonl"),
        "validation_file_sha256": file_digest(output_dir / "validation.jsonl"),
        "reviewer": decisions["reviewer"], "review_scope": decisions["review_scope"],
        "code_sha256": file_digest(Path(__file__)),
        "lineage": lineage,
        "limits": "Recorded order proxy only. Program and agent review do not imply qualified human ATC review.",
    }
    write_json(output_dir / "export-manifest.json", manifest)
    return {key: value for key, value in manifest.items() if key != "lineage"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build_parser = sub.add_parser("candidates")
    build_parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    build_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    export_parser = sub.add_parser("export")
    export_parser.add_argument("--candidates", type=Path, default=DEFAULT_OUTPUT / "candidates.jsonl")
    export_parser.add_argument("--audit", type=Path, default=DEFAULT_OUTPUT / "audit.json")
    export_parser.add_argument("--decisions", type=Path, required=True)
    export_parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    export_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT / "export")
    args = parser.parse_args()
    if args.command == "candidates":
        result = candidates(args.data_dir, args.output_dir)
    else:
        result = export(args.candidates, args.audit, args.decisions, args.data_dir, args.output_dir)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

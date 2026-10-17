"""Audit the actual frozen artifacts and execute every case through fixed checkers."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .core import DATA_DIR, canonical, check_schedule, evaluate_action, load_cases, model_messages, parse_action, schedule_action, scripted_action, teacher_action


def verify(directory=DATA_DIR):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    seen_sources = set()
    seen_inputs = set()
    report = {}
    for name, expected_hash in manifest["frozen_code"].items():
        actual = hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
        if actual != expected_hash:
            raise ValueError(f"Frozen code changed: {name}")
    for split in ("train", "validation"):
        artifact = manifest["artifacts"][f"{split}.jsonl"]
        payload = (directory / f"{split}.jsonl").read_bytes()
        if hashlib.sha256(payload).hexdigest() != artifact["sha256"]:
            raise ValueError(f"Frozen artifact changed: {split}")
        cases = load_cases(split, directory)
        if len(cases) != artifact["cases"]:
            raise ValueError("Manifest case count mismatch")
        metrics = []
        for case in cases:
            if case["local_date"] not in manifest["split_dates"][split]:
                raise ValueError("Unexpected date exposure")
            sources = case["private"]["source_flight_ids"]
            if len(set(sources)) != len(sources) or seen_sources.intersection(sources):
                raise ValueError("Source aircraft reused across encounters")
            seen_sources.update(sources)
            messages = model_messages(case)
            serialized = canonical(messages)
            fingerprint = hashlib.sha256(serialized.encode()).hexdigest()
            if fingerprint in seen_inputs:
                raise ValueError("Repeated model input")
            seen_inputs.add(fingerprint)
            for source in sources:
                if source in serialized:
                    raise ValueError("Source identity leaked into prompt")
            if json.loads(messages[1]["content"]) != case["input"]:
                raise ValueError("Prompt does not match public input")
            scripted = scripted_action(case["input"])
            oracle = teacher_action(case["input"])
            scripted_metrics = evaluate_action(case, scripted)
            oracle_metrics = evaluate_action(case, oracle)
            for action in (scripted, oracle, {"order": case["private"]["historical_order"]}):
                parse_action(canonical(action), case["input"])
                check_schedule(case["input"], schedule_action(case["input"], action))
            if (oracle_metrics["backlog"], oracle_metrics["delay_seconds_sum"], oracle_metrics["max_delay_seconds"]) > (scripted_metrics["backlog"], scripted_metrics["delay_seconds_sum"], scripted_metrics["max_delay_seconds"]):
                raise ValueError("Oracle is worse than scripted order")
            metrics.append(scripted_metrics)
        report[split] = {"cases": len(cases), "aircraft": sum(len(c["input"]["aircraft"]) for c in cases),
                         "scripted_historical_pairwise_agreement": sum(m["pairwise_agreement"] for m in metrics) / len(metrics),
                         "scripted_modeled_delay_seconds_sum": round(sum(m["delay_seconds_sum"] for m in metrics), 3),
                         "scripted_backlog": sum(m["backlog"] for m in metrics)}
    return {"status": "passed", "checks": ["artifact/code hashes", "date boundaries", "source disjointness", "unique public prompts", "source identity exclusion", "all-case scripted/oracle/historical schedules"], "splits": report}


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))

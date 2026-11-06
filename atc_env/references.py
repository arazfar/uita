"""Precompute CP-SAT closed-loop references: python -m atc_env.references"""
from __future__ import annotations

import json

from benchmark.closed_loop.traffic import load_episodes

from .grader import REFERENCE_DIR, REFERENCE_LABEL, compute_reference


def main():
    REFERENCE_DIR.mkdir(exist_ok=True)
    for split in ("train", "validation"):
        refs = {ep["id"]: compute_reference(ep) for ep in load_episodes(split)}
        payload = {"environment": "SFOArrivalEnv-v1", "split": split, "reference": REFERENCE_LABEL,
                   "source": "benchmark.closed_loop.engine.simulate(episode, 'deterministic', seed=17)",
                   "references": refs}
        (REFERENCE_DIR / f"{split}.json").write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")
        print(f"{split}: {len(refs)} references")


if __name__ == "__main__":
    main()

"""Freeze existing development observations into an offline-capable demo pack.
Usage: PYTHONPATH=backend python scripts/build_showcase_pack.py --database sqlite:///...
Never reads sealed-test observations or imputes altitude.
"""

import argparse
import gzip
import json
from collections import Counter
from pathlib import Path

from sqlalchemy import select
from uita.research.data import digest
from uita.research.database import Artifact, Database


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--database", required=True)
    args = p.parse_args()
    database = Database(args.database)
    root = Path("backend/uita/research/assets")
    bundle = json.loads((root / "demo_bundle.json").read_text())
    ids = {e["id"] for a in bundle["artifacts"] for e in a["payload"]["entries"]}
    tracks = []
    with database.sessions() as db:
        for row in db.scalars(
            select(Artifact).where(Artifact.kind == "replay").order_by(Artifact.id)
        ):
            d = row.payload
            pts = [p for p in d.get("points", []) if 1785736800 <= p["t"] < 1786082400]
            if pts:
                tracks.append((row.id, {**d, "points": pts}))
    hours = Counter()
    for _, t in tracks:
        for p in t["points"]:
            if p.get("altitude_ft") is not None:
                hours[int(p["t"] // 3600) * 3600] += 1
    if not hours:
        raise ValueError("No measured development altitude available")
    start = min(hours, key=lambda x: (-hours[x], x))
    selected = []
    artifacts = []
    for id, t in tracks:
        if id.removeprefix("replay:") in ids:
            artifacts.append(
                {"id": id, "kind": "replay", "payload": t, "checksum": digest(t)}
            )
        pts = [p for p in t["points"] if start - 60 <= p["t"] <= start + 3660]
        if pts:
            selected.append({**t, "id": id.removeprefix("replay:"), "points": pts})
    points = [
        p for t in selected for p in t["points"] if start <= p["t"] < start + 3600
    ]
    measured = [p for p in points if p.get("altitude_ft") is not None]
    payload = {
        "id": "early-august-history-v1",
        "start": start,
        "end": start + 3600,
        "recommended_start": min(p["t"] for p in measured),
        "tracks": selected,
        "coverage": {
            "tracks": len(selected),
            "points": len(points),
            "measured_altitude_points": len(measured),
        },
        "provenance": {
            "kind": "observed",
            "source": "Frozen early-August development observations",
            "selection": "Hour with most measured altitude samples; earliest hour breaks ties",
            "limitations": [
                "Sparse measured altitude: unknown heights remain unplotted in 3D",
                "Not a human-controller counterfactual",
            ],
        },
    }
    artifacts.append(
        {
            "id": payload["id"],
            "kind": "history_window",
            "payload": payload,
            "checksum": digest(payload),
        }
    )
    pack = {"version": "immersive-demo-v1", "artifacts": artifacts}
    pack["checksum"] = digest(artifacts)
    (root / "showcase_data.json.gz").write_bytes(
        gzip.compress(json.dumps(pack, separators=(",", ":")).encode(), mtime=0)
    )
    print(
        json.dumps(
            {
                "artifacts": len(artifacts),
                "history": payload["coverage"],
                "start": start,
            }
        )
    )


if __name__ == "__main__":
    main()

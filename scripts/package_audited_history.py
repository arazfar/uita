"""Package the strongest hour from the already source-audited early-August replay.

Run pipeline/verify_web_data.py first. This does not collect or infer observations.
Existing v1 artifacts remain untouched; v2 is an additive immutable artifact.
"""

import gzip
import json
import math
from collections import Counter
from pathlib import Path

from uita.research.data import digest

root = Path(__file__).resolve().parents[1]
roster = json.loads((root / "web/public/data/flights.json").read_text())
raw = json.loads((root / "web/public/data/tracks.json").read_text())
flights = {f["id"]: f for f in roster["flights"]}
start = roster["week"]["start_utc"]
end = start + 4 * 86400
hours = Counter(
    int(p[0] // 3600) * 3600
    for points in raw.values()
    for p in points
    if start <= p[0] < end and p[3] is not None
)
hour = min(hours, key=lambda t: (-hours[t], t))
tracks = []
for fid, points in sorted(raw.items()):
    pts = [p for p in points if hour - 60 <= p[0] <= hour + 3660]
    if not pts:
        continue
    out = []
    segment = 0
    previous = None
    for t, lon, lat, alt, speed in pts:
        heading = None
        if previous:
            dt = t - previous[0]
            if dt > 60 or math.hypot(lon - previous[1], lat - previous[2]) > 0.3:
                segment += 1
            else:
                p1, p2 = math.radians(previous[2]), math.radians(lat)
                dlon = math.radians(lon - previous[1])
                heading = (
                    math.degrees(
                        math.atan2(
                            math.sin(dlon) * math.cos(p2),
                            math.cos(p1) * math.sin(p2)
                            - math.sin(p1) * math.cos(p2) * math.cos(dlon),
                        )
                    )
                    % 360
                )
        out.append(
            dict(
                t=t,
                lon=lon,
                lat=lat,
                altitude_ft=alt,
                altitude_reference="reported_pressure"
                if alt is not None
                else "unknown",
                track_deg_true=heading,
                segment_id=f"{fid}:{segment}",
                quality_flags=["unknown_altitude"] if alt is None else [],
                source=flights[fid].get("track_source", "SFO Museum"),
            )
        )
        previous = (t, lon, lat)
    tracks.append(dict(id=fid, callsign=flights[fid]["callsign"], points=out))
points = [p for t in tracks for p in t["points"] if hour <= p["t"] < hour + 3600]
measured = [p for p in points if p["altitude_ft"] is not None]
payload = dict(
    id="early-august-history-v2",
    start=hour,
    end=hour + 3600,
    recommended_start=min(p["t"] for p in measured),
    tracks=tracks,
    coverage=dict(
        tracks=len(tracks), points=len(points), measured_altitude_points=len(measured)
    ),
    provenance=dict(
        kind="observed",
        source="Source-audited frozen early-August Museum replay",
        source_checksum=digest(raw),
        selection="Development hour with most measured altitude samples; earliest tie",
        limitations=[
            "Unknown heights remain unknown; map dots are position-only",
            "Observed tracks are context, not a human-controller counterfactual",
            "Heading is derived from adjacent positions, not observed heading",
        ],
    ),
)
path = root / "backend/uita/research/assets/showcase_data.json.gz"
pack = json.loads(gzip.decompress(path.read_bytes()))
existing = next((a for a in pack["artifacts"] if a["id"] == payload["id"]), None)
artifact = dict(
    id=payload["id"], kind="history_window", payload=payload, checksum=digest(payload)
)
if existing and existing != artifact:
    raise ValueError("Refusing to replace immutable historical artifact")
if not existing:
    pack["artifacts"].append(artifact)
pack["checksum"] = digest(pack["artifacts"])
path.write_bytes(
    gzip.compress(json.dumps(pack, separators=(",", ":")).encode(), mtime=0)
)
print(
    json.dumps(
        dict(start=hour, coverage=payload["coverage"], checksum=artifact["checksum"])
    )
)

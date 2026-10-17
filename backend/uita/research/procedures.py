"""Parse leg semantics without inventing missing geometry or facility authority."""

import hashlib
import json

SUPPORTED = {"IF", "TF", "DF"}
KNOWN = SUPPORTED | {"CF", "CA", "VA", "VI", "FM", "VM", "RF", "HM"}


def parse(rows):
    groups = {}
    for row in rows:
        key = (
            row["airac"],
            row["procedure"],
            row.get("route_type"),
            row.get("transition"),
        )
        groups.setdefault(key, []).append(row)
    results = []
    for key, legs in sorted(groups.items(), key=lambda p: str(p[0])):
        legs = sorted(legs, key=lambda r: r["seq"])
        unsupported = sorted(
            {r["path_term"] for r in legs if r["path_term"] not in SUPPORTED}
        )
        missing = any(
            r.get("lat") is None or r.get("lon") is None
            for r in legs
            if r["path_term"] in SUPPORTED
        )
        results.append(
            {
                "id": ":".join(str(k or "") for k in key),
                "legs": legs,
                "supported": not unsupported and not missing,
                "unsupported_legs": unsupported,
                "missing_geometry": missing,
                "autonomous_authorized": False,
                "reason": "Chart validation, aircraft capability and date applicability still required",
                "checksum": hashlib.sha256(
                    json.dumps(legs, sort_keys=True, default=str).encode()
                ).hexdigest(),
            }
        )
    return results

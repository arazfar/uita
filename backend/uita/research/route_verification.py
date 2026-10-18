"""Independent route predicates; no planner feasibility flags are accepted."""

import copy
import math

from .geometry import local
from .verification import check, result


def motion(before, after):
    checks = []
    old = {a["id"]: a for a in before["aircraft"]}
    for a in after["aircraft"]:
        if "route" not in a:
            checks.append(
                check(
                    "vectoring",
                    "unresolved",
                    "Synthetic route evidence missing",
                    aircraft=a["id"],
                )
            )
            continue
        if a["id"] not in old:
            continue
        p = old[a["id"]]
        if p["status"] not in ("approach", "go_around"):
            continue
        delta = math.dist((p["x_nm"], p["y_nm"]), (a["x_nm"], a["y_nm"]))
        if delta > a["groundspeed_kt"] / 3600 + 0.00001:
            checks.append(
                check(
                    "vectoring",
                    "fail",
                    "Route position discontinuity",
                    aircraft=a["id"],
                    distance_nm=delta,
                )
            )
        turn = abs((a["heading_deg_true"] - p["heading_deg_true"] + 180) % 360 - 180)
        bound = min(
            3,
            math.degrees(
                9.80665
                * math.tan(math.radians(25))
                / max(70, p.get("tas_kt", 190) * 0.514444)
            ),
        )
        if turn > bound + 0.001:
            checks.append(
                check(
                    "vectoring",
                    "fail",
                    "Synthetic 25-degree bank turn envelope exceeded",
                    aircraft=a["id"],
                    turn_deg=turn,
                    limit_deg=bound,
                )
            )
        if a["status"] == "approach":
            if a.get("route_cross_track_nm", 0) > 2:
                checks.append(
                    check(
                        "vectoring",
                        "fail",
                        "Outside synthetic route corridor",
                        aircraft=a["id"],
                        cross_track_nm=a["route_cross_track_nm"],
                    )
                )
            if (
                a["remaining_route_nm"] < 3
                and abs((a["track_deg_true"] - 298 + 180) % 360 - 180) > 10
            ):
                checks.append(
                    check(
                        "runway",
                        "fail",
                        "Final ground track is not aligned",
                        aircraft=a["id"],
                        track_deg_true=a["track_deg_true"],
                    )
                )
        if a["status"] == "taxi" and p["status"] == "approach":
            # Independently reconstruct published threshold coordinates and runway-axis projection.
            coords = {
                "28L": (-(122 + 21 / 60 + 30.057 / 3600), 37 + 36 / 60 + 42.163 / 3600),
                "28R": (-(122 + 21 / 60 + 25.708 / 3600), 37 + 36 / 60 + 48.721 / 3600),
            }
            tx, ty = local(*coords[a["runway"]])
            dx, dy = a["x_nm"] - tx, a["y_nm"] - ty
            rad = math.radians(298)
            along = dx * math.sin(rad) + dy * math.cos(rad)
            cross = abs(dx * math.cos(rad) - dy * math.sin(rad))
            if not (
                -0.02 <= along <= 0.5 and cross <= 0.025 and a["altitude_ft"] <= 15
            ):
                checks.append(
                    check(
                        "runway",
                        "fail",
                        "Touchdown outside runway geometry",
                        aircraft=a["id"],
                        along_nm=along,
                        cross_nm=cross,
                        altitude_ft=a["altitude_ft"],
                    )
                )
    return checks


def predict_merge(state, horizon=900):
    """One-second current-traffic projection through the merge; no future demand is exposed.
    Aircraft leave this check at 10 NM remaining. Runway/final checks remain separate.
    No future clearance is fabricated to make a projection pass.
    """
    from .dynamics import move, pilot_responses
    from .verification import verify_motion

    immutable = {id(a["route"]): a["route"] for a in state["aircraft"] if "route" in a}
    projection = copy.deepcopy(state, dict(immutable))
    projection["_events"] = []
    projection["aircraft"] = [
        a
        for a in projection["aircraft"]
        if a["status"] == "approach" and a.get("remaining_route_nm", 0) > 10
    ]
    ids = {a["id"] for a in projection["aircraft"]}
    projection["clearances"] = [
        c for c in projection["clearances"] if c["aircraft_id"] in ids
    ]
    for _ in range(horizon):
        if len(projection["aircraft"]) < 2:
            break
        before = copy.deepcopy(projection, dict(immutable))
        projection["clock"] += 1
        pilot_responses(projection)
        for a in projection["aircraft"]:
            move(a, projection)
        verdict = verify_motion(before, projection)
        if verdict["status"] != "pass":
            return verdict
        removed = {
            a["id"]
            for a in projection["aircraft"]
            if a["remaining_route_nm"] <= 10 or a["status"] != "approach"
        }
        projection["aircraft"] = [
            a for a in projection["aircraft"] if a["id"] not in removed
        ]
        projection["clearances"] = [
            c for c in projection["clearances"] if c["aircraft_id"] not in removed
        ]
        projection["_events"] = []
    return result(
        [
            check(
                "separation",
                "pass",
                "Current-traffic synthetic merge projection passed",
                horizon_seconds=horizon,
                final_excluded_below_remaining_nm=10,
                future_demand_included=False,
            )
        ]
    )

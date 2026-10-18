"""Build independently versioned, evidence-grounded synthetic routes and episode.
No network, provider calls, held-out observations, or mutation of old artifacts.
"""

import copy
import gzip
import itertools
import json
import math
import statistics
from pathlib import Path

from uita.research import arrival_routes as routes
from uita.research import sandbox
from uita.research.contracts import Disruption
from uita.research.data import digest
from uita.research.dynamics import initial_state, public_state
from uita.research.geometry import heading, local
from uita.research.presentation import frame, validate_recording
from uita.research.service import advance_one, apply_disruption

ROOT = Path("backend/uita/research/assets")


def read(name):
    return json.loads(gzip.decompress((ROOT / name).read_bytes()))


def write(name, value):
    (ROOT / name).write_bytes(
        gzip.compress(json.dumps(value, separators=(",", ":")).encode(), mtime=0)
    )


def simplify(points, tolerance=1.5):
    if len(points) < 3:
        return points
    a, b = points[0], points[-1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    errors = []
    for p in points[1:-1]:
        f = max(
            0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy))
        )
        errors.append(math.dist(p, [a[0] + f * dx, a[1] + f * dy]))
    m = max(errors)
    if m <= tolerance:
        return [a, b]
    k = errors.index(m) + 1
    return simplify(points[: k + 1]) + simplify(points[k:])[1:]


def catalog():
    pack = read("showcase_data.json.gz")
    accepted = {}
    rejected = []
    for artifact in pack["artifacts"]:
        if artifact["kind"] != "replay":
            continue
        data = artifact["payload"]
        ps = data["points"]
        xy = [list(local(p["lon"], p["lat"])) for p in ps]
        valid = len(ps) >= 10 and math.hypot(*xy[-1]) < 3
        for a, b, u, v in zip(ps, ps[1:], xy, xy[1:]):
            dt = b["t"] - a["t"]
            valid = (
                valid
                and 0 < dt <= 120
                and a.get("segment_id") == b.get("segment_id")
                and math.dist(u, v) * 3600 / max(1, dt) <= 600
            )
        family = (
            "east"
            if xy[0][0] > 60 and abs(xy[0][1]) < 10
            else "south"
            if xy[0][1] < -60 and xy[0][0] > 10
            else None
        )
        if not valid or not family:
            rejected.append(
                {
                    "id": artifact["id"],
                    "reason": "insufficient/unsupported family, discontinuity, or implausible speed",
                }
            )
            continue
        accepted.setdefault(family, []).append((artifact, xy))
    representatives = {"east": "replay:a45896926", "south": "replay:a45897305"}
    result = []
    for family, identifier in representatives.items():
        a, xy = next(v for v in accepted[family] if v[0]["id"] == identifier)
        # Retain observed lateral shape outside final, reconstruct a common stable final.
        points = simplify([p for p in xy if math.hypot(*p) > 20])
        dx, dy = points[0][0] - points[1][0], points[0][1] - points[1][1]
        n = math.hypot(dx, dy)
        points.insert(0, [points[0][0] + 35 * dx / n, points[0][1] + 35 * dy / n])
        points += [
            routes.final_point(15),
            routes.final_point(10),
            routes.final_point(0),
            routes.final_point(-0.3),
        ]
        # Chaikin corner rounding (synthetic reconstruction), preserving final centerline.
        for _ in range(3):
            smooth = [points[0]]
            for u, v in itertools.pairwise(points):
                smooth += [
                    [0.75 * u[j] + 0.25 * v[j] for j in (0, 1)],
                    [0.25 * u[j] + 0.75 * v[j] for j in (0, 1)],
                ]
            points = smooth + [points[-1]]
        ds = routes.cumulative(points)
        deviations = []
        for point in points:
            if not 20 <= math.hypot(*point) <= 70:
                continue
            distances = []
            for u, v in itertools.pairwise(xy):
                dx, dy = v[0] - u[0], v[1] - u[1]
                f = max(
                    0,
                    min(
                        1,
                        ((point[0] - u[0]) * dx + (point[1] - u[1]) * dy)
                        / (dx * dx + dy * dy),
                    ),
                )
                distances.append(math.dist(point, [u[0] + f * dx, u[1] + f * dy]))
            deviations.append(min(distances))
        lateral_context = {
            "comparison": "Template to representative observed polyline, radial extent 20–70 NM only; excludes final and upstream extension",
            "sample_count": len(deviations),
            "mean_deviation_nm": statistics.mean(deviations),
            "max_deviation_nm": max(deviations),
        }
        result.append(
            {
                "id": family,
                "name": {
                    "east": "Eastern descent / Bay merge",
                    "south": "Southern descent / Bay merge",
                }[family],
                "points": points,
                "distances_nm": ds,
                "length_nm": ds[-1],
                "source_ids": [x["id"] for x, _ in accepted[family]],
                "source_checksums": [digest(x["payload"]) for x, _ in accepted[family]],
                "representative": identifier,
                "lateral_context": lateral_context,
                "assumptions": [
                    "35 NM synthetic upstream extension",
                    "Rounded lateral context; synthetic final connection",
                    "All altitude and speed profiles synthetic; no clearance/procedure authority inferred",
                ],
            }
        )
    return {
        "id": routes.CATALOG,
        "routes": result,
        "rejected": rejected,
        "runways": routes.RUNWAYS,
        "references": [
            "https://noise.flysfo.com/about/flight-patterns-operations/",
            "https://www.faa.gov/air_traffic/publications/atpubs/aip_html/part3_ad_2.0_california.html",
        ],
        "reference_review_date": "2026-10-18",
        "reference_limitations": "Runway geometry contextual snapshot, not date-matched procedural authorization",
        "source_pack_checksum": digest(pack),
    }


def scenario(catalog):
    base = copy.deepcopy(read("dense_demo.json.gz")["artifacts"][0]["payload"])
    base["id"] = routes.SCENARIO
    base["simulator_version"] = routes.VERSION
    base["route_catalog"] = catalog
    base["provenance"] = {
        "kind": "synthetic",
        "generator": "arrival-flows-1",
        "source_catalog": routes.CATALOG,
        "catalog_checksum": digest(catalog),
        "assumptions": "Observed lateral context; synthetic profiles, extension, initialization and admission timing",
    }
    base["end"] = base["start"] + 2100
    for i, e in enumerate(base["entries"]):
        r = catalog["routes"][i % 2]
        remaining = 10 + 15 * i if i < 7 else r["length_nm"]
        progress = max(0, r["length_nm"] - remaining)
        pos = routes.at(r["points"], r["distances_nm"], progress)
        target = routes.at(r["points"], r["distances_nm"], progress + 1)
        alt, ias = routes.profile(remaining)
        e.update(
            spawn_time=base["start"] + (0 if i < 7 else (i - 6) * 240),
            x_nm=pos[0],
            y_nm=pos[1],
            altitude_ft=alt,
            groundspeed_kt=ias * (1 + alt / 50000),
            track_deg_true=heading(target[0] - pos[0], target[1] - pos[1]),
            route=r,
            route_progress_nm=progress,
            provenance=base["provenance"],
        )
    return base


def episode(s, disruptions=True):
    state = initial_state(s, 42, "static")
    sandbox.initialize(state)
    state["policy_version"] = "static-arrival-flows-1"
    state["initialization_until"] = None
    frames = []
    events = []
    telemetry = {
        "max_turn_deg_per_second": 0,
        "max_descent_ft_per_minute": 0,
        "min_airborne_ias_kt": 999,
        "max_airborne_ias_kt": 0,
        "max_final_alignment_error_deg": 0,
    }
    for tick in range(1501):
        if tick == 390 and disruptions:
            apply_disruption(
                state,
                Disruption(
                    kind="runway_closure",
                    runway="28R",
                    expected_revision=1,
                    idempotency_key="flow-closure",
                ),
                s,
            )
        for e in state["_events"]:
            events.append({**e, "sequence": len(events) + 1})
        state["_events"] = []
        if tick % 5 == 0 or state["status"] != "running":
            frames.append(
                frame(state, routes.RECORDING, tick + 1, mode="recording").model_dump()
            )
        if tick == 1500 or state["status"] != "running":
            break
        previous = {
            a["id"]: (a["heading_deg_true"], a["altitude_ft"])
            for a in state["aircraft"]
        }
        advance_one(state, s)
        for a in state["aircraft"]:
            if a["status"] != "approach":
                continue
            telemetry["min_airborne_ias_kt"] = min(
                telemetry["min_airborne_ias_kt"], a["ias_kt"]
            )
            telemetry["max_airborne_ias_kt"] = max(
                telemetry["max_airborne_ias_kt"], a["ias_kt"]
            )
            if a["id"] in previous:
                h, z = previous[a["id"]]
                telemetry["max_turn_deg_per_second"] = max(
                    telemetry["max_turn_deg_per_second"],
                    abs((a["heading_deg_true"] - h + 180) % 360 - 180),
                )
                telemetry["max_descent_ft_per_minute"] = max(
                    telemetry["max_descent_ft_per_minute"], (z - a["altitude_ft"]) * 60
                )
            if a["remaining_route_nm"] < 3:
                telemetry["max_final_alignment_error_deg"] = max(
                    telemetry["max_final_alignment_error_deg"],
                    abs((a["track_deg_true"] - 298 + 180) % 360 - 180),
                )
    state["realism_measurements"] = telemetry
    return state, frames, events


def main():
    c = catalog()
    s = scenario(c)
    state, frames, events = episode(s)
    Path("output").mkdir(exist_ok=True)
    diagnostic = {
        "status": state["status"],
        "clock": state["clock"] - state["start"],
        "metrics": state["metrics"],
        "failures": [e for e in events if e["kind"] == "motion_failed"],
        "route_lengths": [r["length_nm"] for r in c["routes"]],
    }
    attempts = Path("output/arrival-flow-attempts")
    attempts.mkdir(exist_ok=True)
    (attempts / (digest(diagnostic) + ".json")).write_text(
        json.dumps(
            {
                **diagnostic,
                "scenario_checksum": digest(s),
                "events": events if state["status"] == "failed" else [],
            },
            indent=2,
        )
    )
    Path("output/arrival-flows-diagnostic.json").write_text(
        json.dumps(diagnostic, indent=2)
    )
    print(json.dumps(diagnostic))
    if state["status"] == "failed":
        return
    baseline, bframes, _ = episode(s)
    assert digest(state) == digest(baseline)
    counts = [
        sum(
            a["status"] in ("approach", "holding", "go_around")
            and a["altitude_ft"] is not None
            and math.hypot(*local(a["longitude"], a["latitude"])) <= 125
            for a in f["aircraft"]
        )
        for f in frames
        if f["clock"] >= s["start"] + 300
    ]
    coverage = dict(
        airborne_min=min(counts),
        airborne_median=statistics.median(counts),
        airborne_peak=max(counts),
        fraction_6_to_10=sum(6 <= n <= 10 for n in counts) / len(counts),
        region="Within 125 NM of SFO",
        presentation_seconds=1200,
        synthetic_altitude_fraction=1.0,
        route_families=[
            {"id": r["id"], "source_tracks": len(r["source_ids"])} for r in c["routes"]
        ],
        **state["realism_measurements"],
    )
    print(json.dumps(coverage))
    Path("output/arrival-flows-coverage.json").write_text(
        json.dumps(coverage, indent=2)
    )
    if coverage["fraction_6_to_10"] < 0.8:
        raise SystemExit("Density gate failed; do not replace default")
    result = {
        "controller": state["policy_version"],
        "metrics": public_state(state)["metrics"],
        "status": state["status"],
        "clock": state["clock"],
        "state_hash": digest(state),
    }
    comparison = {
        "scenario_id": s["id"],
        "scenario_hash": digest(s),
        "seed": 42,
        "results": [result, copy.deepcopy(result)],
        "limitations": [
            "Both branches use the same deterministic policy; no improvement claimed",
            "Synthetic routes and profiles informed by historical lateral context; not professional validation",
        ],
    }
    payload = {
        "frames": frames,
        "baseline_frames": bframes,
        "events": events,
        "responses": [],
        "comparison": comparison,
    }
    payload["manifest"] = {
        "id": routes.RECORDING,
        "title": "San Francisco · converging arrivals · synthetic",
        "scenario_id": s["id"],
        "scenario_checksum": digest(s),
        "simulator_version": routes.VERSION,
        "rule_version": state["rule_version"],
        "policy_version": state["policy_version"],
        "model": "Deterministic demo controller · no model inference",
        "start": s["start"],
        "end": state["clock"],
        "recommended_start": s["start"] + 300,
        "sample_seconds": 5,
        "provenance": "fixture",
        "seed": 42,
        "outcome": "recording_complete",
        "model_responses": 0,
        "fallback_count": 0,
        "event_tape": [e for e in events if e["kind"] == "disruption"],
        "checksums": {k: digest(v) for k, v in payload.items()},
        "coverage": {
            **coverage,
            "duration_seconds": 1500,
            "max_active_aircraft": max(len(f["aircraft"]) for f in frames),
        },
        "limitations": comparison["limitations"],
    }
    validate_recording(payload)
    artifacts = [
        {"id": v["id"], "kind": kind, "payload": v, "checksum": digest(v)}
        for v, kind in ((c, "route_catalog"), (s, "scenario"))
    ]
    write(
        "arrival_flows.json.gz",
        {
            "version": "arrival-flows-1",
            "artifacts": artifacts,
            "checksum": digest(artifacts),
        },
    )
    write("recordings/arrival-flows-v1.json.gz", payload)


if __name__ == "__main__":
    main()

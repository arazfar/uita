"""Read-only geographic presentation and integrity-checked demo recordings."""

import math
import os
from pathlib import Path

import httpx
from fastapi import HTTPException, Query, Request
from sqlalchemy import select

from . import service
from .arrival_cues import historical_cue, simulation_cue, recording_frame
from .contracts import (
    ControllerProposal,
    PresentationAircraft,
    PresentationFrame,
    RecordingManifest,
    RecordingWindow,
)
from .data import digest, save_artifact
from .database import Artifact, Checkpoint, Event, Reservation
from .dynamics import public_state
from .geometry import geographic


def frame(state, source_id, revision, cursor=0, mode="simulation"):
    aircraft = []
    for a in state["aircraft"]:
        lon, lat = geographic(a["x_nm"], a["y_nm"])
        aircraft.append(
            PresentationAircraft(
                arrival_cue=simulation_cue(a, state),
                id=a["id"],
                callsign=a["callsign"],
                longitude=lon,
                latitude=lat,
                altitude_ft=a.get("altitude_ft"),
                track_deg_true=a.get("track_deg_true"),
                groundspeed_kt=a.get("groundspeed_kt"),
                status=a["status"],
                aircraft_type=a.get("type", "UNKNOWN"),
                runway=a.get("runway"),
                source_time=state["clock"],
                provenance=a.get("provenance", {"kind": "synthetic"}),
            )
        )
    return PresentationFrame(
        interventions=state.get("interventions", []),
        admission_requests=state.get("admission_requests", []),
        initialization_until=state.get("initialization_until"),
        last_decision=state.get("last_decision"),
        source_id=source_id,
        mode=mode,
        clock=state["clock"],
        revision=revision,
        status=state["status"],
        event_cursor=cursor,
        aircraft=aircraft,
        metrics=public_state(state)["metrics"],
        closed_runways=state["closed_runways"],
        controller=state["policy_version"],
        simulator_version=state["simulator_version"],
        rule_version=state["rule_version"],
        provenance={"kind": "simulated", "scenario_id": state["scenario_id"]},
    )


def validate_recording(payload):
    manifest = RecordingManifest.model_validate(payload["manifest"])
    for key in ("frames", "events", "comparison", "responses", "baseline_frames"):
        if digest(payload[key]) != manifest.checksums[key]:
            raise ValueError("Recording checksum mismatch: " + key)
    if not payload["frames"]:
        raise ValueError("Recording requires motion frames")
    if manifest.provenance == "fixture" and manifest.model_responses:
        raise ValueError("Fixture cannot claim model responses")
    observed_responses = [e for e in payload["events"] if e["kind"] == "model_response"]
    if len(observed_responses) != manifest.model_responses:
        raise ValueError("Model response count does not match journal")
    reservations = {r["reservation_id"]: r for r in payload["responses"]}
    for event in observed_responses:
        metadata = event["payload"]["metadata"]
        response = reservations.get(metadata["reservation_id"])
        if response is None or response.get("model") != manifest.model:
            raise ValueError("Model response provenance is missing")
        parsed = ControllerProposal.model_validate_json(
            response["response"]["message"]["content"]
        )
        if parsed.model_dump() != event["payload"]["proposal"]:
            raise ValueError("Model response differs from recorded proposal")
    last = -math.inf
    for raw in payload["frames"] + payload["baseline_frames"]:
        f = PresentationFrame.model_validate(raw)
        if (
            f.simulator_version != manifest.simulator_version
            or f.rule_version != manifest.rule_version
        ):
            raise ValueError("Incompatible recording frame")
    for raw in payload["frames"]:
        if raw["clock"] < last:
            raise ValueError("Unordered recording")
        last = raw["clock"]
    return manifest


def install_recording(db, payload):
    manifest = validate_recording(payload)
    scenario = db.get(Artifact, manifest.scenario_id)
    if scenario is None or scenario.checksum != manifest.scenario_checksum:
        raise ValueError(
            "Recording scenario checksum does not match installed artifact"
        )
    save_artifact(db, manifest.id, "demo_recording", payload)


def routes(app, database):
    validated = {}

    @app.get("/api/v2/history/catalog")
    def history_catalog():
        with database.sessions() as db:
            return [
                {k: v for k, v in a.payload.items() if k != "tracks"}
                for a in db.scalars(
                    select(Artifact).where(Artifact.kind == "history_window")
                )
            ]

    @app.get("/api/v2/history/{dataset_id}/window", response_model=RecordingWindow)
    def history_window(
        dataset_id: str, clock: float, seconds: int = Query(120, ge=1, le=120)
    ):
        from bisect import bisect_right

        with database.sessions() as db:
            row = db.get(Artifact, dataset_id)
            if row is None or row.kind != "history_window":
                raise HTTPException(404, "History dataset not found")
            data = row.payload
        if not math.isfinite(clock) or not data["start"] <= clock <= data["end"]:
            raise HTTPException(422, "Clock outside historical coverage")
        frames = []
        tracks = [(t, [p["t"] for p in t["points"]]) for t in data["tracks"]]
        for tick in range(int(clock), min(int(clock) + seconds + 2, data["end"] + 1)):
            aircraft = []
            for t, times in tracks:
                i = bisect_right(times, tick) - 1
                if i < 0 or tick - times[i] > 60:
                    continue
                p = t["points"][i]
                position = dict(p)
                interpolated = False
                if i + 1 < len(times):
                    q = t["points"][i + 1]
                    gap = q["t"] - p["t"]
                    if (
                        0 < gap <= 60
                        and p.get("altitude_ft") is not None
                        and q.get("altitude_ft") is not None
                        and p.get("segment_id") == q.get("segment_id")
                        and math.hypot(q["lat"] - p["lat"], q["lon"] - p["lon"]) <= 0.3
                    ):
                        fraction = (tick - p["t"]) / gap
                        for key in ("lat", "lon", "altitude_ft"):
                            position[key] = p[key] + (q[key] - p[key]) * fraction
                        if (
                            p.get("track_deg_true") is not None
                            and q.get("track_deg_true") is not None
                        ):
                            position["track_deg_true"] = (
                                p["track_deg_true"]
                                + (
                                    (q["track_deg_true"] - p["track_deg_true"] + 180)
                                    % 360
                                    - 180
                                )
                                * fraction
                            ) % 360
                        interpolated = fraction > 0
                aircraft.append(
                    PresentationAircraft(
                        arrival_cue=historical_cue(t["points"], i, tick),
                        id=t["id"],
                        callsign=t.get("callsign") or t["id"],
                        longitude=position["lon"],
                        latitude=position["lat"],
                        altitude_ft=position.get("altitude_ft"),
                        altitude_reference=p.get("altitude_reference", "unknown"),
                        track_deg_true=position.get("track_deg_true"),
                        status="observed",
                        source_time=p["t"],
                        age_seconds=tick - p["t"],
                        provenance={
                            "kind": "observed",
                            "segment_id": p.get("segment_id"),
                            "quality_flags": p.get("quality_flags", []),
                            "presentation_interpolation": interpolated,
                        },
                    )
                )
            frames.append(
                PresentationFrame(
                    source_id=dataset_id,
                    mode="historical",
                    clock=tick,
                    revision=0,
                    status="recorded",
                    event_cursor=0,
                    aircraft=aircraft,
                    metrics={},
                    closed_runways=[],
                    controller="Historical observations",
                    simulator_version="observed",
                    rule_version="not-applicable",
                    provenance=data["provenance"],
                )
            )
        return {"frames": frames, "baseline_frames": [], "events": []}

    @app.get("/api/v2/runs/{run_id}/motion", response_model=RecordingWindow)
    def motion(run_id: str, request: Request):
        with database.sessions() as db:
            service.get_run(db, run_id, request.state.user["team"])
            rows = list(
                db.scalars(
                    select(Checkpoint)
                    .where(Checkpoint.run_id == run_id)
                    .order_by(Checkpoint.revision.desc())
                    .limit(8)
                )
            )
            frames = [
                frame(c.state, run_id, c.revision, c.state["event_sequence"])
                for c in reversed(rows)
            ]
            return {"frames": frames, "baseline_frames": [], "events": []}

    @app.get("/api/v2/runs/{run_id}/presentation", response_model=PresentationFrame)
    def live_frame(run_id: str, request: Request):
        with database.sessions() as db:
            run = service.get_run(db, run_id, request.state.user["team"])
            events = list(
                db.scalars(
                    select(Event)
                    .where(Event.run_id == run_id)
                    .order_by(Event.sequence.desc())
                    .limit(1)
                )
            )
            result = frame(
                run.state, run.id, run.revision, events[0].sequence if events else 0
            )
            reservations = list(
                db.scalars(select(Reservation).where(Reservation.run_id == run_id))
            )
            result.runtime = {
                "lease_expires_at": run.lease_until,
                "next_tick_due_at": run.next_tick,
            }
            result.spend = {
                "reserved_usd": sum(r.amount for r in reservations),
                "known_actual_usd": sum(r.actual or 0 for r in reservations),
                "uncertain_calls": sum(r.actual is None for r in reservations),
                "cap_usd": run.state["spend_cap_usd"],
            }
            return result

    @app.get("/api/v2/recordings", response_model=list[RecordingManifest])
    def recordings():
        with database.sessions() as db:
            return [
                RecordingManifest.model_validate(recording(db, a.id)["manifest"])
                for a in db.scalars(
                    select(Artifact).where(Artifact.kind == "demo_recording")
                )
            ]

    def recording(db, recording_id):
        checksum = db.scalar(
            select(Artifact.checksum).where(
                Artifact.id == recording_id, Artifact.kind == "demo_recording"
            )
        )
        if checksum is None:
            raise LookupError("Recording not found")
        key = (recording_id, checksum)
        if key in validated:
            return validated[key]
        row = db.get(Artifact, recording_id)
        if digest(row.payload) != checksum:
            raise ValueError("Recording integrity check failed")
        validate_recording(row.payload)
        if len(validated) >= 4:
            validated.pop(next(iter(validated)))
        validated[key] = row.payload
        return row.payload

    @app.get("/api/v2/recordings/{recording_id}/window", response_model=RecordingWindow)
    def window(recording_id: str, clock: float, seconds: int = Query(30, ge=1, le=120)):
        if not math.isfinite(clock):
            raise HTTPException(422, "Invalid clock")
        with database.sessions() as db:
            payload = recording(db, recording_id)
            manifest = payload["manifest"]
            if not manifest["start"] <= clock <= manifest["end"]:
                raise HTTPException(422, "Clock outside recording")

            def frames(key):
                prior = [f for f in payload[key] if f["clock"] <= clock]
                future = [
                    f for f in payload[key] if clock < f["clock"] <= clock + seconds
                ]
                return [
                    recording_frame(f, payload["events"] if key == "frames" else [])
                    for f in prior[-1:] + future
                ]

            # Seeks retain bounded prior decision/clearance evidence for the
            # displayed aircraft, without exposing events after the playhead.
            context_sequences = {
                e["sequence"]
                for e in [
                    e
                    for e in payload["events"]
                    if e["clock"] <= clock
                    and e["kind"] in ("proposal_verified", "clearance_issued")
                ][-128:]
            }
            return {
                "frames": frames("frames"),
                "baseline_frames": frames("baseline_frames"),
                "events": [
                    e
                    for e in payload["events"]
                    if clock - seconds <= e["clock"] <= clock + seconds
                    or e["sequence"] in context_sequences
                    or (
                        e["clock"] <= clock
                        and e["kind"]
                        in (
                            "controller_fallback",
                            "model_response",
                            "disruption",
                            "scenario_failed",
                        )
                    )
                ],
            }

    @app.get("/api/v2/recordings/{recording_id}/export")
    def export(recording_id: str):
        with database.sessions() as db:
            return recording(db, recording_id)

    @app.get("/api/v2/recordings/{recording_id}/comparison")
    def comparison(recording_id: str):
        with database.sessions() as db:
            payload = recording(db, recording_id)
            responses = payload["responses"]
            return {
                **payload["comparison"],
                "recording_inference": {
                    "model_responses": payload["manifest"]["model_responses"],
                    "fallback_count": payload["manifest"]["fallback_count"],
                    "requests": len(responses),
                    "known_actual_usd": sum(
                        r.get("actual_usd") or 0 for r in responses
                    ),
                    "reserved_usd": sum(r["reserved_usd"] for r in responses),
                    "uncertain_charges": sum(
                        r.get("actual_usd") is None for r in responses
                    ),
                    "latency_seconds": [r.get("latency_seconds") for r in responses],
                },
            }

    @app.get("/api/v2/published-benchmark")
    def benchmark():
        path = (
            Path(__file__).parents[3]
            / "benchmark/closed_loop/reports/2026-10-17/comparison.md"
        )
        return {
            "title": "Separate August 7 admission benchmark",
            "text": path.read_text()
            if path.exists()
            else "Published benchmark unavailable in this build.",
        }

    @app.get("/api/maps-key")
    def maps_key():
        return {"key": os.getenv("GOOGLE_MAPS_API_KEY", "")}

    @app.get("/uita/api/history/{endpoint}")
    async def history(endpoint: str, start: int | None = None):
        if endpoint not in ("catalog", "window"):
            raise HTTPException(404, "Unknown history endpoint")
        if endpoint == "window" and (
            start is None or not 1787554800 <= start < 1788159600
        ):
            raise HTTPException(422, "Window outside late-August archive")
        base = os.getenv("UITA_HISTORY_SERVER_URL")
        if not base:
            raise HTTPException(503, "Late-August history service is not configured")
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
                response = await client.get(
                    base.rstrip("/") + "/api/history/" + endpoint,
                    params={"start": start} if endpoint == "window" else {},
                )
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError):
            raise HTTPException(
                503, "Historical source unavailable; retry later"
            ) from None

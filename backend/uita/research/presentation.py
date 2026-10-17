"""Read-only geographic presentation and integrity-checked demo recordings."""

import math
import os
from pathlib import Path

import httpx
from fastapi import HTTPException, Query, Request
from sqlalchemy import select

from . import service
from .contracts import (
    ControllerProposal,
    PresentationAircraft,
    PresentationFrame,
    RecordingManifest,
    RecordingWindow,
)
from .data import digest, save_artifact
from .database import Artifact, Event, Reservation
from .dynamics import public_state
from .geometry import geographic


def frame(state, source_id, revision, cursor=0, mode="simulation"):
    aircraft = []
    for a in state["aircraft"]:
        lon, lat = geographic(a["x_nm"], a["y_nm"])
        aircraft.append(
            PresentationAircraft(
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
    if (
        not payload["frames"]
        or not payload["responses"]
        or manifest.model_responses < 1
    ):
        raise ValueError("Recording requires authentic model responses")
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
                validate_recording(a.payload)
                for a in db.scalars(
                    select(Artifact).where(Artifact.kind == "demo_recording")
                )
            ]

    def recording(db, recording_id):
        row = db.get(Artifact, recording_id)
        if row is None or row.kind != "demo_recording":
            raise LookupError("Recording not found")
        if digest(row.payload) != row.checksum:
            raise ValueError("Recording integrity check failed")
        validate_recording(row.payload)
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
                return prior[-1:] + future

            return {
                "frames": frames("frames"),
                "baseline_frames": frames("baseline_frames"),
                "events": [
                    e
                    for e in payload["events"]
                    if clock - seconds <= e["clock"] <= clock + seconds
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

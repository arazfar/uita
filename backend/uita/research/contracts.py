"""Strict, versioned wire contracts; UTC seconds, NM, feet and knots are explicit."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Mutation(Contract):
    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=128)


class RunCreate(Contract):
    scenario_id: str = Field(max_length=200)
    seed: int = Field(default=42, ge=0, le=100000)
    controller: Literal["fcfs", "static", "fixture", "crusoe"] = "fixture"
    fixture_fault: Literal["none", "provider_timeout", "budget_exhausted"] = "none"
    spend_cap_usd: float = Field(default=0.5, ge=0, le=0.5)
    idempotency_key: str = Field(min_length=8, max_length=128)


class Control(Mutation):
    action: Literal["play", "pause", "step", "speed"]
    seconds: int = Field(default=1, ge=1, le=60)
    speed: int = Field(default=1, ge=1, le=30)


class Disruption(Mutation):
    kind: Literal[
        "runway_closure", "weather", "readback_error", "communications", "emergency"
    ]
    runway: Literal["28L", "28R"] = "28R"
    aircraft_id: str | None = None
    value: float = Field(default=1, ge=0, le=120)


class Clearance(Contract):
    aircraft_id: str
    kind: Literal[
        "heading",
        "altitude",
        "speed",
        "direct",
        "hold",
        "approach",
        "landing",
        "takeoff",
        "go_around",
        "handoff",
    ]
    value: float | None = None
    target: str | None = None


class ControllerProposal(Contract):
    clearances: list[Clearance] = Field(default_factory=list, max_length=32)
    sequence: list[str] = Field(default_factory=list, max_length=200)
    explanation: str = Field(default="", max_length=1500)


class Propose(Mutation):
    proposal: ControllerProposal


class Commit(Mutation):
    proposal_id: str


class Fork(Mutation):
    checkpoint_revision: int = Field(ge=1)


class CompareRun(Mutation):
    pass


class Login(Contract):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class Compare(Contract):
    scenario_id: str
    seed: int = Field(default=42, ge=0, le=100000)
    controllers: list[Literal["fcfs", "static"]] = Field(
        default_factory=lambda: ["fcfs", "static"], min_length=2, max_length=2
    )
    seconds: int = Field(default=900, ge=60, le=3600)
    idempotency_key: str = Field(min_length=8, max_length=128)


class RunEvent(Contract):
    sequence: int
    clock: float
    kind: str
    payload: dict


class RunView(Contract):
    id: str
    revision: int
    status: str
    state: dict


class VerificationReport(Contract):
    status: Literal["pass", "fail", "unresolved"]
    checks: list[dict]
    rule_version: str


class DatasetManifest(Contract):
    id: str
    source: str
    checksum: str
    split: str
    coverage: dict


class ScenarioDefinition(Contract):
    id: str
    dataset_id: str
    split: Literal["train", "validation", "test"]
    start: float
    end: float
    provenance: dict


class AircraftState(Contract):
    id: str
    callsign: str
    x_nm: float
    y_nm: float
    altitude_ft: float
    groundspeed_kt: float
    track_deg_true: float
    status: str
    provenance: dict


class ObservationFrame(Contract):
    clock: float
    aircraft: list[dict]
    weather: dict
    closed_runways: list[str]


class PilotResponse(Contract):
    clearance_id: str
    aircraft_id: str
    correct: bool
    clock: float
    fields: dict


class AirportRulePack(Contract):
    id: str
    effective_from: str
    effective_until: str
    rules: list[dict]
    limitations: list[str]


class EvaluationReport(Contract):
    scenario_id: str
    seed: int
    simulator_version: str
    results: list[dict]
    limitations: list[str]


class PresentationAircraft(Contract):
    id: str
    callsign: str
    longitude: float
    latitude: float
    altitude_ft: float | None
    altitude_reference: str = "research_altitude"
    track_deg_true: float | None = None
    groundspeed_kt: float | None = None
    status: str
    aircraft_type: str = "UNKNOWN"
    runway: str | None = None
    source_time: float
    age_seconds: float = 0
    provenance: dict


class PresentationFrame(Contract):
    source_id: str
    mode: Literal["simulation", "recording", "historical"]
    clock: float
    revision: int
    status: str
    event_cursor: int
    aircraft: list[PresentationAircraft]
    metrics: dict
    closed_runways: list[str]
    controller: str
    simulator_version: str
    rule_version: str
    provenance: dict
    spend: dict = Field(default_factory=dict)
    runtime: dict = Field(default_factory=dict)


class RecordingManifest(Contract):
    id: str
    title: str
    scenario_id: str
    scenario_checksum: str
    simulator_version: str
    rule_version: str
    policy_version: str
    model: str
    start: float
    end: float
    seed: int
    outcome: str
    model_responses: int
    fallback_count: int
    event_tape: list[dict]
    checksums: dict[str, str]
    limitations: list[str]


class RecordingWindow(Contract):
    frames: list[PresentationFrame]
    baseline_frames: list[PresentationFrame]
    events: list[RunEvent]

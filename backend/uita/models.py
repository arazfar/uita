"""Strict boundary contracts; local coordinates are NM, altitude MSL feet, time seconds."""
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class Control(Strict):
    action: Literal['play', 'pause', 'step', 'speed', 'reset']
    seconds: float = Field(10, ge=0, le=600)
    speed: float = Field(1, ge=.25, le=30)
    seed: int = Field(42, ge=0, le=100000)
    scenario: str = 'baseline'
    revision: Optional[int] = None
    idempotency_key: Optional[str] = Field(None,min_length=8,max_length=128)

class Disruption(Strict):
    kind: Literal['runway_closure','weather','emergency','communications','arrival_surge','gate_delay']
    runway: str = '28R'
    aircraft_id: Optional[str] = None
    severity: float = Field(1, ge=0, le=5)
    revision: Optional[int] = None
    idempotency_key: Optional[str] = Field(None,min_length=8,max_length=128)

class Propose(Strict):
    policy_id: Optional[str] = None
    source: Literal['fixture','crusoe'] = 'fixture'
    idempotency_key: Optional[str] = Field(None,min_length=8,max_length=128)

class Commit(Strict):
    idempotency_key: str = Field(min_length=8,max_length=128)
    revision: Optional[int] = None

class Policy(Strict):
    """Bounded declarative observation program: no expressions or executable code."""
    name: str = Field(min_length=1,max_length=80)
    observations: list[Literal['exit_occupancy','gate_ready','wake','weather']] = Field(max_length=4)
    order: Literal['fcfs','priority','wake_group'] = 'fcfs'
    reserve_seconds: int = Field(40,ge=0,le=120)
    lookahead: int = Field(12,ge=4,le=24)
    max_observations: int = Field(24,ge=4,le=96)

class Train(Strict):
    generations: int = Field(3,ge=1,le=8)
    source: Literal['fixture','crusoe'] = 'fixture'
    idempotency_key: Optional[str] = Field(None,min_length=8,max_length=128)

class Compare(Strict):
    policy_ids: list[str] = Field(default_factory=lambda:['baseline','static'],min_length=1,max_length=4)

class Point(Strict):
    t: float
    x: float
    y: float
    altitude: float

class Slot(Strict):
    aircraft_id: str
    runway: str
    time: float = Field(ge=0)

class Plan(Strict):
    id: str
    revision: int
    rule_version: str
    snapshot_hash: str
    valid_until: float
    slots: list[Slot]

class AircraftView(BaseModel):
    model_config=ConfigDict(extra='allow')
    id: str
    callsign: str
    type: str
    wake: str
    operation: str
    status: str
    x: float
    y: float
    altitude: float
    heading: float
    speed: float
    runway: str
    scheduled: float
    requested: float
    delay: float
    emergency: bool
    trajectory: list[Point]

class RunwayView(BaseModel):
    model_config=ConfigDict(extra='allow')
    id: str
    start: tuple[float,float]
    end: tuple[float,float]
    closed: bool

class MetricsView(BaseModel):
    model_config=ConfigDict(extra='allow')
    completed: int
    total: int
    mean_delay: float
    conflicts: Optional[int]
    throughput: float

class Snapshot(BaseModel):
    model_config=ConfigDict(extra='allow')
    session_id: str
    revision: int
    time: float
    running: bool
    speed: float
    seed: int
    scenario: str
    mode: str
    aircraft: list[AircraftView]
    runways: list[RunwayView]
    metrics: MetricsView
    weather: dict
    events: list[dict]
    proposals: list[dict] = Field(default_factory=list)
    policies: list[dict] = Field(default_factory=list)
    learning_jobs: list[dict] = Field(default_factory=list)
    sources: list[dict]
    limitations: list[str]

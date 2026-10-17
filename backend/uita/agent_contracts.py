"""Versioned, data-only contracts for the investigation boundary."""
from typing import Literal, Annotated
import json
from pydantic import Field, model_validator, ConfigDict
from .models import Strict, Policy

class AgentStrict(Strict):
    model_config=ConfigDict(strict=True,extra='forbid',allow_inf_nan=False)

    @model_validator(mode='after')
    def bounded_payload(self):
        if len(json.dumps(self.model_dump(),allow_nan=False).encode())>18000:
            raise ValueError('Agent boundary payload exceeds 18000 bytes')
        return self

GRAMMAR_VERSION = 'observations-2'
PROMPT_VERSION = 'investigator-2'

class AgentLimits(AgentStrict):
    model_requests: int = Field(6, ge=1, le=8)
    tool_calls: int = Field(12, ge=1, le=24)
    development_evaluations: int = Field(4, ge=1, le=6)
    revisions: int = Field(1, ge=0, le=2)
    input_tokens: int = Field(60000, ge=1000, le=100000)
    output_tokens: int = Field(6000, ge=256, le=12000)
    request_output_tokens: int = Field(1000, ge=256, le=4096)
    wall_seconds: int = Field(120, ge=10, le=300)
    spend_usd: float = Field(.02, gt=0, le=.05)

class CandidateDraft(AgentStrict):
    observation_scope: Literal['all','pending','pending-first'] = 'pending-first'
    allocation: Literal['tool-major','aircraft-major'] = 'tool-major'
    observations: list[Literal['exit_occupancy','gate_ready','wake','weather']] = Field(max_length=4)
    evidence_refs: list[Annotated[str,Field(min_length=1,max_length=100,pattern=r"^[a-z0-9-]+$")]] = Field(min_length=1, max_length=8)
    explanation: str = Field(min_length=1, max_length=400)

    @model_validator(mode='after')
    def unique(self):
        if len(self.observations) != len(set(self.observations)):
            raise ValueError('Observation operations must be unique')
        return self

class EvidenceRequest(AgentStrict):
    case_id: str = Field(pattern=r'^dev-[0-9]+-(baseline|exit-congestion|departure-bank|transfer)$')

class ObservationRequest(EvidenceRequest):
    tool: Literal['exit_occupancy','gate_ready','wake','weather']
    limit: int = Field(3, ge=1, le=8)

class EvaluationRequest(AgentStrict):
    observation_scope: Literal['all','pending','pending-first'] = 'pending-first'
    allocation: Literal['tool-major','aircraft-major'] = 'tool-major'
    observations: list[Literal['exit_occupancy','gate_ready','wake','weather']] = Field(max_length=4)

class Evidence(AgentStrict):
    id: str
    source: Literal['development-observation','development-evaluator','modeled-dependency']
    case_id: str
    snapshot_hash: str
    freshness: str
    units: dict[str,str]
    uncertainty: str
    available: bool
    data: dict

class AgentEvent(AgentStrict):
    sequence: int = Field(ge=1)
    stage: str
    kind: str
    message: str = Field(max_length=400)
    data: dict = Field(default_factory=dict)
    created_at: float

class LearningJobView(Strict):
    """Additive response contract: old job fields remain available to old clients."""
    model_config=ConfigDict(extra='allow',allow_inf_nan=False)
    id: str
    status: str
    stage: str | None = None
    events: list[AgentEvent] = Field(default_factory=list,max_length=200)
    limits: AgentLimits | None = None
    parent_id: str | None = None
    ancestry: list[str] = Field(default_factory=list)
    source: str | None = None
    provider_usage: dict = Field(default_factory=dict)

"""Typed response contract; domain-specific evidence may extend its named fields."""
from typing import Any, Literal
from pydantic import BaseModel, Field
from .models import Observation


class RegionOut(BaseModel):
    id: str
    name: str
    version: int
    geometry: dict[str, Any]
    created_at: str


class RuleOut(BaseModel):
    id: str
    kind: str
    version: int
    engine_version: str
    config: dict[str, Any]
    created_at: str


class AssetOut(BaseModel):
    id: str
    kind: Literal["vessel", "aircraft"]
    name: str
    imo: str | None
    mmsi: str | None
    registration: str | None


class FlightOut(BaseModel):
    id: str
    aircraft_id: str | None
    carrier: str
    flight_number: str
    service_date: str
    departure: str
    arrival: str
    scheduled_departure: str
    scheduled_arrival: str


class ObservationOut(BaseModel):
    id: str
    monitor_id: str
    raw_id: str
    observed_at: str
    data: Observation
    quality: str


class RawOut(BaseModel):
    id: str
    monitor_id: str
    provider: str
    received_at: str
    payload: dict[str, Any]
    sha256: str
    outcome: str
    error: str | None


class MonitorOut(BaseModel):
    id: str
    name: str
    kind: Literal["vessel", "flight", "aircraft"]
    asset_id: str | None
    flight_id: str | None
    rule_id: str
    provider: str
    enabled: bool
    cursor: int
    health: str
    last_poll_at: str | None
    last_error: str | None
    state: dict[str, Any]
    created_at: str
    rule: RuleOut
    asset: AssetOut | None
    flight: FlightOut | None
    region: RegionOut | None
    latest: ObservationOut | None


class MonitorDetail(MonitorOut):
    observations: list[ObservationOut]
    raw_records: list[RawOut]
    evaluations: list[dict[str, Any]]
    configuration_audit: list[dict[str, Any]]


class EventOut(BaseModel):
    id: str
    monitor_id: str
    monitor_name: str
    kind: Literal["vessel", "flight", "aircraft"]
    evaluation_id: str
    rule_id: str
    type: str
    severity: Literal["high", "warning", "info"]
    occurred_at: str
    created_at: str
    summary: str
    evidence: dict[str, Any] = Field(description="Includes observation_id, raw_id, raw_sha256, previous_observation_id, rule_version, engine_version, rule_config and deterministic calculation.")


class EventDetail(EventOut):
    raw_record: RawOut
    rule: RuleOut
    previous_observation: ObservationOut | None


class EventPage(BaseModel):
    items: list[EventOut]
    total: int
    limit: int
    offset: int


class PollResult(BaseModel):
    raw_id: str | None = None
    outcome: str
    events: list[str]


class BatchPollItem(BaseModel):
    monitor_id: str
    outcome: str
    raw_id: str | None = None
    events: list[str] = Field(default_factory=list)
    error: str | None = None


class BatchPollResult(BaseModel):
    items: list[BatchPollItem]


class HealthOut(BaseModel):
    status: Literal["ok"]
    mode: Literal["mock", "live", "mixed"]
    scheduler_seconds: int
    engine_version: str

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class HarnessVersion(ApiModel):
    id: str
    name: str
    version: str
    summary: str


class PlayerRef(ApiModel):
    harness_id: str
    name: str
    version: str
    color: Literal["white", "black"]


class PositionRecord(ApiModel):
    ply: int
    fen: str
    san: str
    player: Literal["white", "black"] | None = None
    from_square: str | None = None
    to_square: str | None = None


class TraceEvent(ApiModel):
    id: str
    timestamp: datetime
    ply: int
    player: Literal["white", "black"]
    phase: Literal["observe", "plan", "act", "verify"]
    status: Literal["complete", "active", "failed"]
    summary: str
    detail: str


class MatchSummary(ApiModel):
    id: str
    white: PlayerRef
    black: PlayerRef
    status: Literal["queued", "running", "completed", "stopped", "failed"]
    result: str | None
    started_at: datetime
    ended_at: datetime | None
    current_fen: str
    move_count: int
    last_move: str | None


class MatchDetail(MatchSummary):
    positions: list[PositionRecord]
    traces: list[TraceEvent]


class MatchList(ApiModel):
    items: list[MatchSummary]
    total: int


class StartMatchRequest(ApiModel):
    white_harness_id: str
    black_harness_id: str


class HealthResponse(ApiModel):
    status: Literal["ok"]
    data_source: Literal["mock"]


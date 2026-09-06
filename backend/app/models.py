from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class GameFolderRef(ApiModel):
    id: str
    name: str


class GameFolder(GameFolderRef):
    created_at: datetime
    match_count: int


class GameFolderList(ApiModel):
    items: list[GameFolder]
    total_matches: int
    unfiled_count: int


class CreateGameFolderRequest(ApiModel):
    name: str = Field(min_length=1, max_length=60)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Folder name cannot be blank.")
        return normalized


class AssignGameFolderRequest(ApiModel):
    folder_id: str | None


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
    current_player: Literal["white", "black"] | None = None
    current_phase: str | None = None
    termination_reason: str | None = None
    folder: GameFolderRef | None = None


class MatchDetail(MatchSummary):
    positions: list[PositionRecord]
    traces: list[TraceEvent]


class MatchList(ApiModel):
    items: list[MatchSummary]
    total: int


class StartMatchRequest(ApiModel):
    white_harness_id: str
    black_harness_id: str
    folder_id: str | None = None


class HealthResponse(ApiModel):
    status: Literal["ok"]
    data_source: Literal["sqlite"]
    model_selection: Literal["explicit", "loaded-model-discovery"]

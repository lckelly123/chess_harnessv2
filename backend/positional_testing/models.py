"""API models owned by the positional testing boundary."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import ModelSelection


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class PositionalTestingModel(BaseModel):
    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True)


class SavedPositionSnapshot(PositionalTestingModel):
    ply: int
    fen: str
    san: str
    player: Literal["white", "black"] | None = None
    from_square: str | None = None
    to_square: str | None = None


class SavedPosition(PositionalTestingModel):
    id: str
    name: str
    dataset_version: str
    split: Literal["train", "test"]
    phase: Literal["opening", "middlegame", "endgame"]
    position_type: Literal["quiet", "tactical"]
    source: Literal["lichess_game", "lichess_puzzle"]
    source_game_id: str
    source_url: str
    opening: str | None = None
    themes: list[str] = Field(default_factory=list)
    puzzle_rating: int | None = None
    side_to_move: Literal["white", "black"]
    move_count: int
    position: SavedPositionSnapshot


class SavedPositionList(PositionalTestingModel):
    items: list[SavedPosition]


class RunSavedPositionRequest(PositionalTestingModel):
    position_id: str = Field(min_length=1, max_length=240)
    harness_id: str = Field(min_length=1, max_length=120)
    model_selection: ModelSelection | None = None

    @field_validator("position_id", "harness_id")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Identifier cannot be blank.")
        return normalized


class SavedPositionMove(PositionalTestingModel):
    san: str
    uci: str
    from_square: str
    to_square: str
    promotion: str | None = None
    is_capture: bool
    gives_check: bool
    is_castling: bool
    is_en_passant: bool


class SavedPositionRun(PositionalTestingModel):
    run_id: str
    position_id: str
    position_name: str
    harness_id: str
    harness_name: str
    harness_version: str
    model: str
    side: Literal["white", "black"]
    ply: int
    move: SavedPositionMove
    justification: str
    defense_report: str | None = None
    attack_report: str | None = None


class ModelRunSummary(PositionalTestingModel):
    id: UUID
    position_id: UUID
    model: str
    harness: str
    config: dict[str, Any]
    status: Literal["running", "completed", "failed"]
    final_move_uci: str | None = None
    cp_loss: int | None = None
    classification: str | None = None
    expected_points_loss: float | None = None
    better_moves: list[dict[str, Any]] | None = None
    evaluation: dict[str, Any] | None = None
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class ModelRunPass(PositionalTestingModel):
    run_id: UUID
    pass_number: int
    phase: str
    tool_calls: list[dict[str, Any]]
    working_notes: str | None = None
    status: Literal["running", "completed", "failed"]
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class ModelRunDetail(ModelRunSummary):
    passes: list[ModelRunPass]


class ModelRunList(PositionalTestingModel):
    items: list[ModelRunSummary]
    total: int


class CreatePositionQueueRequest(PositionalTestingModel):
    dataset_version: str = Field(min_length=1, max_length=240)
    split: Literal["train", "test"]
    harness_id: str = Field(min_length=1, max_length=120)
    model_selection: ModelSelection | None = None

    @field_validator("dataset_version", "harness_id")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Identifier cannot be blank.")
        return value


class PositionQueueSummary(PositionalTestingModel):
    id: UUID
    dataset_version: str
    split: Literal["train", "test"]
    harness_id: str
    harness_name: str
    harness_version: str
    model_selection: ModelSelection
    status: Literal["queued", "running", "stopping", "completed", "stopped"]
    total: int
    completed: int
    failed: int
    pending: int
    running: int
    skipped: int
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class PositionQueueItem(PositionalTestingModel):
    queue_id: UUID
    ordinal: int
    position_id: UUID
    run_id: UUID | None = None
    status: Literal["queued", "running", "completed", "failed", "skipped"]
    phase: str
    position_type: str
    final_move_uci: str | None = None
    classification: str | None = None
    failure_stage: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class PositionQueueDetail(PositionQueueSummary):
    items: list[PositionQueueItem]


class PositionQueueList(PositionalTestingModel):
    items: list[PositionQueueSummary]

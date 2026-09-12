"""API models owned by the positional testing boundary."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    source_file: str
    white: str | None = None
    black: str | None = None
    side_to_move: Literal["white", "black"]
    move_count: int
    position: SavedPositionSnapshot


class SavedPositionList(PositionalTestingModel):
    items: list[SavedPosition]


class RunSavedPositionRequest(PositionalTestingModel):
    position_id: str = Field(min_length=1, max_length=240)
    harness_id: str = Field(min_length=1, max_length=120)

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

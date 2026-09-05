"""Immutable records returned by the deterministic chess domain."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ColorName = Literal["white", "black"]
ForcingScanStatus = Literal["ready", "in_check", "game_over"]
ScratchStatus = Literal["unused", "active"]


@dataclass(frozen=True, slots=True)
class MoveIdentity:
    """A legal move represented for both humans and chess libraries."""

    san: str
    uci: str
    from_square: str
    to_square: str
    promotion: str | None
    is_capture: bool
    gives_check: bool
    is_castling: bool
    is_en_passant: bool


@dataclass(frozen=True, slots=True)
class PositionStatus:
    """The rule-derived status of one canonical position."""

    side_to_move: ColorName
    is_check: bool
    is_checkmate: bool
    is_stalemate: bool
    is_insufficient_material: bool
    can_claim_draw: bool
    is_game_over: bool
    result: str | None
    winner: ColorName | None
    termination: str | None


@dataclass(frozen=True, slots=True)
class MoveTransition:
    """One verified move and the positions immediately around it."""

    move: MoveIdentity
    fen_before: str
    fen_after: str
    status_after: PositionStatus


@dataclass(frozen=True, slots=True)
class PieceInfo:
    """A piece located on a particular board square."""

    square: str
    color: ColorName
    piece: str
    symbol: str


@dataclass(frozen=True, slots=True)
class SquareInspection:
    """Geometric control of a square from one player's perspective."""

    square: str
    perspective: ColorName
    occupant: PieceInfo | None
    friendly_pieces_targeting: tuple[PieceInfo, ...]
    opponent_pieces_targeting: tuple[PieceInfo, ...]


@dataclass(frozen=True, slots=True)
class StaticExchangeResult:
    """Local capture result in centipawns from the initiating side's view."""

    score_cp: int
    capture_sequence: tuple[MoveIdentity, ...]


@dataclass(frozen=True, slots=True)
class ForcingMove:
    """A checking move or capture found by a deterministic forcing scan."""

    move: MoveIdentity
    is_checkmate: bool = False
    static_exchange: StaticExchangeResult | None = None


@dataclass(frozen=True, slots=True)
class ForcingMoveScan:
    """Checks and non-checking captures available to one side."""

    status: ForcingScanStatus
    actor: ColorName
    checks: tuple[ForcingMove, ...] = ()
    captures: tuple[ForcingMove, ...] = ()
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ScratchSnapshot:
    """Serializable state of an isolated, turn-local scratchboard."""

    status: ScratchStatus
    canonical_fen: str
    current_fen: str
    moves: tuple[MoveTransition, ...]

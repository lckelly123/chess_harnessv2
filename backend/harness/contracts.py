"""Provider-independent boundary between a match and a player."""

from dataclasses import dataclass

from chess_core import ColorName, MoveIdentity


@dataclass(frozen=True, slots=True)
class TurnRequest:
    game_id: str
    fen: str
    pgn: str
    side: ColorName
    ply: int = 0


@dataclass(frozen=True, slots=True)
class MoveDecision:
    move: MoveIdentity
    justification: str
    defense_report: str | None = None
    attack_report: str | None = None


class HarnessError(RuntimeError):
    """A turn failed without submitting a move; inspect its trace for details."""


class TurnCancelled(HarnessError):
    """The caller cancelled the turn."""

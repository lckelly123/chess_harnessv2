"""Provider-independent boundary between a match and a player."""

from dataclasses import dataclass
from typing import Protocol, TypedDict

from chess_core import ColorName, MoveIdentity


class TurnInput(TypedDict):
    """Serializable public input accepted by a one-turn LangGraph."""

    game_id: str
    fen: str
    pgn: str
    side: ColorName
    ply: int


@dataclass(frozen=True, slots=True)
class TurnRequest:
    game_id: str
    fen: str
    pgn: str
    side: ColorName
    ply: int = 0

    def as_graph_input(self) -> TurnInput:
        return {
            "game_id": self.game_id,
            "fen": self.fen,
            "pgn": self.pgn,
            "side": self.side,
            "ply": self.ply,
        }


def turn_request_from_input(value: TurnInput) -> TurnRequest:
    """Translate the public graph boundary to the domain request."""

    return TurnRequest(
        game_id=value["game_id"],
        fen=value["fen"],
        pgn=value["pgn"],
        side=value["side"],
        ply=value["ply"],
    )


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


class PlayerHarness(Protocol):
    """One move-producing player, independent of its internal orchestration."""

    async def choose_move(self, request: TurnRequest) -> MoveDecision: ...

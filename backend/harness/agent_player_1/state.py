"""Explicit, serializable turn state. No clients or mutable chess.Board objects."""

from typing import Any, Literal, TypedDict

from chess_core import legal_moves, parse_position, position_status
from harness.contracts import TurnInput, TurnRequest, turn_request_from_input

Phase = Literal["defense", "attack", "synthesis"]


class TurnState(TypedDict):
    game_id: str
    ply: int
    canonical_fen: str
    pgn: str
    side: str
    legal_san: list[str]
    phase: Phase
    scratch_moves: list[str]
    history: list[dict[str, Any]]
    correction: str
    pending_tool: dict[str, Any] | None
    next_step: str
    forced_retry: bool
    retry_output: str
    retry_trigger: str
    forced_retries: int
    model_calls: int
    tool_calls: int
    rejected_calls: int
    protocol_errors: int
    defense_report: str
    attack_report: str
    decision: dict[str, str] | None
    events: list[dict[str, Any]]


def phase_state(phase: Phase) -> dict[str, Any]:
    return dict(
        phase=phase,
        scratch_moves=[],
        history=[],
        correction="",
        pending_tool=None,
        next_step=phase,
        forced_retry=False,
        retry_output="",
        retry_trigger="reasoning_only_response",
        forced_retries=0,
        model_calls=0,
        tool_calls=0,
        rejected_calls=0,
        protocol_errors=0,
    )


def initial_state(request: TurnRequest) -> TurnState:
    fen = parse_position(request.fen)
    if request.side != position_status(fen).side_to_move:
        raise ValueError("Request side does not match the canonical side to move.")
    moves = sorted(move.san for move in legal_moves(fen))
    if not moves:
        raise ValueError("Cannot choose a move from a position with no legal moves.")
    return {
        **phase_state("defense"),
        "game_id": request.game_id,
        "ply": request.ply,
        "canonical_fen": fen,
        "pgn": request.pgn,
        "side": request.side,
        "legal_san": moves,
        "defense_report": "",
        "attack_report": "",
        "decision": None,
        "events": [],
    }


def prepare_turn(value: TurnInput) -> TurnState:
    """Initialize internal state from the small public graph input."""

    return initial_state(turn_request_from_input(value))

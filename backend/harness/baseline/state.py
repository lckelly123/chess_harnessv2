"""Fresh serializable state for one turn; no scratchboard or phased reports."""

from io import StringIO
from typing import Any, Literal, TypedDict

import chess.pgn

from chess_core import legal_moves, parse_position, position_status
from harness.contracts import TurnInput, TurnRequest, turn_request_from_input


class BaselineState(TypedDict):
    game_id: str
    ply: int
    canonical_fen: str
    pgn: str
    side: str
    legal_san: list[str]
    last_move: str
    history: list[dict[str, Any]]
    correction: str
    pending_tool: dict[str, Any] | None
    next_step: Literal["decide", "validate_submission", "end"]
    forced_retry: bool
    retry_output: str
    retry_trigger: str
    forced_retries: int
    model_calls: int
    protocol_errors: int
    rejected_calls: int
    decision: dict[str, str] | None
    events: list[dict[str, Any]]


def last_move_from_pgn(pgn: str, canonical_fen: str) -> str:
    """Recover legacy Last Move from the caller's record, never from the model."""
    if pgn.strip() in {"", "*"}:
        return "None."
    record = StringIO(pgn)
    game = chess.pgn.read_game(record)
    if game is None or game.errors:
        raise ValueError("PGN must be a valid single game or '*' for no record.")
    if chess.pgn.read_game(record) is not None:
        raise ValueError("PGN must contain exactly one game.")
    end = game.end()
    if end.board().fen() != canonical_fen:
        raise ValueError("PGN final position does not match the canonical FEN.")
    return end.san() if end.parent is not None else "None."


def initial_state(request: TurnRequest) -> BaselineState:
    fen = parse_position(request.fen)
    if request.side != position_status(fen).side_to_move:
        raise ValueError("Request side does not match the canonical side to move.")
    # Preserve the legacy legal-move order from python-chess, rather than rank moves.
    moves = [move.san for move in legal_moves(fen)]
    if not moves:
        raise ValueError("Cannot choose a move from a position with no legal moves.")
    return {
        "game_id": request.game_id,
        "ply": request.ply,
        "canonical_fen": fen,
        "pgn": request.pgn,
        "side": request.side,
        "legal_san": moves,
        "last_move": last_move_from_pgn(request.pgn, fen),
        "history": [],
        "correction": "",
        "pending_tool": None,
        "next_step": "decide",
        "forced_retry": False,
        "retry_output": "",
        "retry_trigger": "reasoning_only_response",
        "forced_retries": 0,
        "model_calls": 0,
        "protocol_errors": 0,
        "rejected_calls": 0,
        "decision": None,
        "events": [],
    }


def prepare_turn(value: TurnInput) -> BaselineState:
    """Initialize internal state from the small public graph input."""

    return initial_state(turn_request_from_input(value))

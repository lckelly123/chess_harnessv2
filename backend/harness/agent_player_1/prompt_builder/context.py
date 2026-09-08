"""Deterministic context builders for dynamic prompt sections."""

from __future__ import annotations

import json
from dataclasses import dataclass
from io import StringIO

import chess
import chess.pgn

from chess_core import (
    ForcingMove,
    ForcingMoveScan,
    ScratchBoard,
    legal_moves,
    scan_agent_forcing_moves,
    scan_opponent_forcing_moves,
)

from ..state import TurnState

PIECE_GROUPS = (
    (chess.PAWN, "Pawns"),
    (chess.KNIGHT, "Knights"),
    (chess.BISHOP, "Bishops"),
    (chess.ROOK, "Rooks"),
    (chess.QUEEN, "Queen"),
    (chess.KING, "King"),
)
TOOL_HISTORY_LIMIT = 7


@dataclass(frozen=True, slots=True)
class PieceView:
    square: str
    legal_moves: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PieceGroup:
    name: str
    pieces: tuple[PieceView, ...]


@dataclass(frozen=True, slots=True)
class BoardStateContext:
    moves_so_far: str
    side_to_move: str
    check_status: str
    castling_rights: str
    en_passant: str
    agent_piece_groups: tuple[PieceGroup, ...]
    opponent_piece_groups: tuple[PieceGroup, ...]


@dataclass(frozen=True, slots=True)
class SeeMoveContext:
    san: str
    exchange_sequence: tuple[str, ...] = ()
    agent_score_cp: int | None = None


@dataclass(frozen=True, slots=True)
class SeeEvalContext:
    status: str
    agent_side: str
    actor: str
    actor_role: str
    checks: tuple[SeeMoveContext, ...]
    captures: tuple[SeeMoveContext, ...]
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class SynthesisSeeEvalContext:
    canonical: SeeEvalContext
    scratch_status: str
    scratch_moves: tuple[str, ...]
    scratch: SeeEvalContext | None = None


@dataclass(frozen=True, slots=True)
class ToolHistoryEntry:
    tool: str
    justification: str
    arguments_json: str
    status: str | None
    result_summary: str | None


@dataclass(frozen=True, slots=True)
class ToolHistoryContext:
    entries: tuple[ToolHistoryEntry, ...]


@dataclass(frozen=True, slots=True)
class ForcedToolRetryContext:
    active: bool
    previous_output: str
    fence: str


def _moves_so_far(pgn_text: str) -> str:
    text = pgn_text.strip()
    if not text or text == "*":
        return "No moves played."

    game = chess.pgn.read_game(StringIO(text))
    if game is None:
        return "No moves played."
    if game.errors:
        raise ValueError(f"Invalid PGN supplied to prompt builder: {game.errors[0]}")

    board = game.board()
    tokens: list[str] = []
    for move in game.mainline_moves():
        if board.turn == chess.WHITE:
            tokens.append(f"{board.fullmove_number}.")
        elif not tokens:
            tokens.append(f"{board.fullmove_number}...")
        tokens.append(board.san(move))
        board.push(move)
    return " ".join(tokens) or "No moves played."


def _castling_rights(board: chess.Board) -> str:
    def rights(color: chess.Color) -> str:
        values = []
        if board.has_kingside_castling_rights(color):
            values.append("O-O")
        if board.has_queenside_castling_rights(color):
            values.append("O-O-O")
        return ", ".join(values) or "None"

    return f"White {rights(chess.WHITE)}; Black {rights(chess.BLACK)}"


def _piece_groups(
    board: chess.Board,
    color: chess.Color,
    legal_moves_by_square: dict[str, tuple[str, ...]] | None = None,
) -> tuple[PieceGroup, ...]:
    groups = []
    for piece_type, name in PIECE_GROUPS:
        squares = sorted(
            (chess.square_name(square) for square in board.pieces(piece_type, color))
        )
        pieces = tuple(
            PieceView(
                square=square,
                legal_moves=(legal_moves_by_square or {}).get(square, ()),
            )
            for square in squares
        )
        groups.append(PieceGroup(name=name, pieces=pieces))
    return tuple(groups)


def _build_board_state_context(state: TurnState) -> BoardStateContext:
    board = chess.Board(state["canonical_fen"])
    agent_color = chess.WHITE if state["side"] == "white" else chess.BLACK
    if board.turn != agent_color:
        raise ValueError("Canonical board side to move does not match agent side.")

    moves = legal_moves(state["canonical_fen"])
    rendered_moves = sorted(move.san for move in moves)
    if rendered_moves != sorted(state["legal_san"]):
        raise ValueError("Canonical legal moves do not match graph state.")

    moves_by_square: dict[str, list[str]] = {}
    for move in moves:
        moves_by_square.setdefault(move.from_square, []).append(move.san)
    grouped_moves = {
        square: tuple(sorted(san_moves))
        for square, san_moves in moves_by_square.items()
    }
    en_passant_moves = sorted(move.san for move in moves if move.is_en_passant)

    return BoardStateContext(
        moves_so_far=_moves_so_far(state["pgn"]),
        side_to_move=state["side"].capitalize(),
        check_status="Yes" if board.is_check() else "No",
        castling_rights=_castling_rights(board),
        en_passant=", ".join(en_passant_moves) or "None",
        agent_piece_groups=_piece_groups(board, agent_color, grouped_moves),
        opponent_piece_groups=_piece_groups(board, not agent_color),
    )


def build_attack_board_state_context(state: TurnState) -> BoardStateContext:
    """Build the attack phase's canonical board-state presentation."""

    if state["phase"] != "attack":
        raise ValueError("Attack board state requires attack phase state.")
    return _build_board_state_context(state)


def build_defense_board_state_context(state: TurnState) -> BoardStateContext:
    """Build the defense phase's canonical board-state presentation."""

    if state["phase"] != "defense":
        raise ValueError("Defense board state requires defense phase state.")
    return _build_board_state_context(state)


def build_synthesis_board_state_context(state: TurnState) -> BoardStateContext:
    """Build the synthesis phase's canonical board-state presentation."""

    if state["phase"] != "synthesis":
        raise ValueError("Synthesis board state requires synthesis phase state.")
    return _build_board_state_context(state)


def _see_move_context(
    forcing_move: ForcingMove,
    *,
    opponent_move: bool,
) -> SeeMoveContext:
    exchange = forcing_move.static_exchange
    if exchange is None:
        return SeeMoveContext(san=forcing_move.move.san)

    score_cp = -exchange.score_cp if opponent_move else exchange.score_cp
    return SeeMoveContext(
        san=forcing_move.move.san,
        exchange_sequence=tuple(move.san for move in exchange.capture_sequence),
        agent_score_cp=score_cp,
    )


def _see_eval_context(
    scan: ForcingMoveScan,
    *,
    agent_side: str,
    opponent_move: bool,
    sort_checks_by_san: bool = False,
) -> SeeEvalContext:
    checks = scan.checks
    if sort_checks_by_san:
        # Preserve the defensive prompt's mate-first, then SAN ordering.
        checks = tuple(
            sorted(checks, key=lambda move: (not move.is_checkmate, move.move.san))
        )

    return SeeEvalContext(
        status=scan.status,
        agent_side=agent_side.capitalize(),
        actor=scan.actor.capitalize(),
        actor_role="opponent" if opponent_move else "agent",
        checks=tuple(
            _see_move_context(move, opponent_move=opponent_move) for move in checks
        ),
        captures=tuple(
            _see_move_context(move, opponent_move=opponent_move)
            for move in scan.captures
        ),
        reason=(scan.reason or "game over").replace("_", " ")
        if scan.status != "ready"
        else None,
    )


def build_attack_see_eval_context(state: TurnState) -> SeeEvalContext:
    """Build SEE results for the agent's legal checks and captures."""

    if state["phase"] != "attack":
        raise ValueError("Attack SEE evaluation requires attack phase state.")
    return _see_eval_context(
        scan_agent_forcing_moves(state["canonical_fen"]),
        agent_side=state["side"],
        opponent_move=False,
    )


def build_defense_see_eval_context(state: TurnState) -> SeeEvalContext:
    """Build SEE results after hypothetically giving the opponent the move."""

    if state["phase"] != "defense":
        raise ValueError("Defense SEE evaluation requires defense phase state.")
    return _see_eval_context(
        scan_opponent_forcing_moves(state["canonical_fen"]),
        agent_side=state["side"],
        opponent_move=True,
        sort_checks_by_san=True,
    )


def build_synthesis_see_eval_context(state: TurnState) -> SynthesisSeeEvalContext:
    """Build canonical and current scratchboard SEE results for synthesis."""

    if state["phase"] != "synthesis":
        raise ValueError("Synthesis SEE evaluation requires synthesis phase state.")

    canonical = _see_eval_context(
        scan_agent_forcing_moves(state["canonical_fen"]),
        agent_side=state["side"],
        opponent_move=False,
    )
    scratchboard = ScratchBoard(state["canonical_fen"])
    for move in state["scratch_moves"]:
        scratchboard.play(move)
    if not scratchboard.moves:
        return SynthesisSeeEvalContext(
            canonical=canonical,
            scratch_status="unused",
            scratch_moves=(),
        )

    scratch_scan = scan_agent_forcing_moves(scratchboard.current_fen)
    opponent_move = scratch_scan.actor != state["side"]
    return SynthesisSeeEvalContext(
        canonical=canonical,
        scratch_status="active",
        scratch_moves=tuple(move.move.san for move in scratchboard.moves),
        scratch=_see_eval_context(
            scratch_scan,
            agent_side=state["side"],
            opponent_move=opponent_move,
        ),
    )


def build_tool_history_context(state: TurnState) -> ToolHistoryContext:
    """Build the visible window of tool calls for the current phase."""

    visible = [
        event for event in state["history"] if event.get("type") == "tool_call"
    ][-TOOL_HISTORY_LIMIT:]
    entries = []
    for event in visible:
        ok = event.get("ok")
        status = "success" if ok is True else "rejected" if ok is False else None
        summary = event.get("result_summary")
        entries.append(
            ToolHistoryEntry(
                tool=str(event.get("tool", "")),
                justification=str(event.get("justification", "")),
                arguments_json=json.dumps(
                    event.get("arguments") or {},
                    ensure_ascii=False,
                    indent=2,
                ),
                status=status,
                result_summary=str(summary) if summary else None,
            )
        )
    return ToolHistoryContext(entries=tuple(entries))


def build_forced_tool_retry_context(state: TurnState) -> ForcedToolRetryContext:
    """Build the optional context appended after a forced tool-call retry."""

    if not state["forced_retry"]:
        return ForcedToolRetryContext(active=False, previous_output="", fence="````")

    previous = state["retry_output"].strip()
    if not previous:
        previous = "(No visible previous output was captured.)"
    fence = "````"
    while fence in previous:
        fence += "`"
    return ForcedToolRetryContext(
        active=True,
        previous_output=previous,
        fence=fence,
    )

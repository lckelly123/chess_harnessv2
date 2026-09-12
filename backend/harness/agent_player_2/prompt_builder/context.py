"""Deterministic context providers for manifest prompt sections."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

import chess

from chess_core import (
    ForcingMove,
    ForcingMoveScan,
    MoveIdentity,
    ScratchBoard,
    legal_moves,
    scan_agent_forcing_moves,
    scan_opponent_forcing_moves,
)

from ..state import TurnState

PIECE_GROUPS = (
    (chess.KING, "King", "King"),
    (chess.QUEEN, "Queen", "Queen"),
    (chess.ROOK, "Rooks", "Rook"),
    (chess.BISHOP, "Bishops", "Bishop"),
    (chess.KNIGHT, "Knights", "Knight"),
    (chess.PAWN, "Pawns", "Pawn"),
)
PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}
TOOL_HISTORY_LIMIT = 7
PROVIDER_PARAMETER_NAMES = {
    "board_state": frozenset({"source", "include_scratch_moves"}),
    "see_eval": frozenset({"source", "actor", "score_perspective"}),
    "tool_history": frozenset(),
    "forced_tool_retry": frozenset(),
    "phase_reports": frozenset(),
}


@dataclass(frozen=True, slots=True)
class PieceView:
    square: str
    legal_moves: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PieceGroup:
    name: str
    piece_name: str
    pieces: tuple[PieceView, ...]


@dataclass(frozen=True, slots=True)
class BoardStateContext:
    board_label: str
    position_id: str
    scratch_moves: tuple[str, ...]
    include_scratch_moves: bool
    agent_side: str
    opponent_side: str
    side_to_move: str
    side_to_move_role: str
    agent_to_move: bool
    check_status: str
    castling_rights: str
    en_passant: str
    draw_claim_available: str
    agent_material_cp: int
    opponent_material_cp: int
    agent_material_balance: str
    agent_material_change_from_canonical: str
    agent_piece_groups: tuple[PieceGroup, ...]
    opponent_piece_groups: tuple[PieceGroup, ...]
    side_to_move_piece_groups: tuple[PieceGroup, ...]


@dataclass(frozen=True, slots=True)
class SeeMoveContext:
    san: str
    exchange_sequence: tuple[str, ...] = ()
    agent_score_cp: int | None = None


@dataclass(frozen=True, slots=True)
class SeeEvalContext:
    board_label: str
    board_name: str
    hypothetical_pass: bool
    status: str
    agent_side: str
    opponent_side: str
    actor: str
    actor_role: str
    checks: tuple[SeeMoveContext, ...]
    captures: tuple[SeeMoveContext, ...]
    reason: str | None = None


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
    previous_output: str
    correction: str
    fence: str


def _castling_rights(board: chess.Board) -> str:
    white = "".join(
        (
            "K" if board.has_kingside_castling_rights(chess.WHITE) else "",
            "Q" if board.has_queenside_castling_rights(chess.WHITE) else "",
        )
    )
    black = "".join(
        (
            "k" if board.has_kingside_castling_rights(chess.BLACK) else "",
            "q" if board.has_queenside_castling_rights(chess.BLACK) else "",
        )
    )
    return f"White {white or 'none'}, Black {black or 'none'}"


def _position_id(board: chess.Board) -> str:
    digest = hashlib.sha256(board.fen(en_passant="fen").encode("ascii")).hexdigest()
    return f"pos-{digest[:12]}"


def _material_cp(board: chess.Board, color: chess.Color) -> int:
    return sum(
        len(board.pieces(piece_type, color)) * value
        for piece_type, value in PIECE_VALUES.items()
    )


def _capture_value(board: chess.Board, move: MoveIdentity) -> int:
    if not move.is_capture:
        return 0
    if move.is_en_passant:
        return PIECE_VALUES[chess.PAWN]
    target = board.piece_at(chess.parse_square(move.to_square))
    return PIECE_VALUES[target.piece_type] if target else 0


def _legal_move_sort_key(
    board: chess.Board,
    move: MoveIdentity,
) -> tuple[int, int, int, str]:
    return (
        -int(move.san.endswith("#")),
        -int(move.gives_check),
        -_capture_value(board, move),
        move.san,
    )


def _piece_groups(
    board: chess.Board,
    color: chess.Color,
    legal_moves_by_square: dict[str, tuple[str, ...]] | None = None,
) -> tuple[PieceGroup, ...]:
    groups = []
    for piece_type, name, piece_name in PIECE_GROUPS:
        squares = sorted(
            chess.square_name(square) for square in board.pieces(piece_type, color)
        )
        pieces = tuple(
            PieceView(
                square=square,
                legal_moves=(legal_moves_by_square or {}).get(square, ()),
            )
            for square in squares
        )
        groups.append(PieceGroup(name=name, piece_name=piece_name, pieces=pieces))
    return tuple(groups)


def _scratchboard(state: TurnState) -> ScratchBoard:
    board = ScratchBoard(state["canonical_fen"])
    for move in state["scratch_moves"]:
        board.play(move)
    return board


def _board_for_source(
    state: TurnState,
    source: str,
) -> tuple[chess.Board, ScratchBoard | None]:
    if source == "canonical":
        return chess.Board(state["canonical_fen"]), None
    if source == "scratch":
        scratch = _scratchboard(state)
        if not scratch.moves:
            raise ValueError("Scratch board context requires an active scratchboard.")
        return chess.Board(scratch.current_fen), scratch
    raise ValueError(f"Unknown board source: {source}")


def build_board_state_context(
    state: TurnState,
    *,
    source: str,
    include_scratch_moves: bool,
) -> BoardStateContext:
    """Build one canonical or scratchboard presentation."""

    board, scratch = _board_for_source(state, source)
    if include_scratch_moves != (source == "scratch"):
        raise ValueError(
            "include_scratch_moves must be true only for the scratch board source."
        )

    agent_color = chess.WHITE if state["side"] == "white" else chess.BLACK
    if source == "canonical" and board.turn != agent_color:
        raise ValueError("Canonical board side to move does not match agent side.")

    moves = legal_moves(board.fen())
    if source == "canonical" and sorted(move.san for move in moves) != sorted(
        state["legal_san"]
    ):
        raise ValueError("Canonical legal moves do not match graph state.")

    moves_by_square: dict[str, list[MoveIdentity]] = {}
    for move in moves:
        moves_by_square.setdefault(move.from_square, []).append(move)
    grouped_moves = {
        square: tuple(
            move.san
            for move in sorted(
                square_moves,
                key=lambda candidate: _legal_move_sort_key(board, candidate),
            )
        )
        for square, square_moves in moves_by_square.items()
    }
    agent_to_move = board.turn == agent_color
    agent_side = "White" if agent_color == chess.WHITE else "Black"
    opponent_side = "Black" if agent_color == chess.WHITE else "White"
    agent_material_cp = _material_cp(board, agent_color)
    opponent_material_cp = _material_cp(board, not agent_color)
    canonical_board = chess.Board(state["canonical_fen"])
    canonical_material_balance = _material_cp(
        canonical_board, agent_color
    ) - _material_cp(canonical_board, not agent_color)
    agent_material_balance = agent_material_cp - opponent_material_cp
    agent_piece_groups = _piece_groups(
        board,
        agent_color,
        grouped_moves if agent_to_move else None,
    )
    opponent_piece_groups = _piece_groups(
        board,
        not agent_color,
        grouped_moves if not agent_to_move else None,
    )

    return BoardStateContext(
        board_label="Canonical Position"
        if source == "canonical"
        else "Scratch Position",
        position_id=_position_id(board),
        scratch_moves=tuple(move.move.san for move in scratch.moves) if scratch else (),
        include_scratch_moves=include_scratch_moves,
        agent_side=agent_side,
        opponent_side=opponent_side,
        side_to_move="White" if board.turn == chess.WHITE else "Black",
        side_to_move_role="agent" if agent_to_move else "opponent",
        agent_to_move=agent_to_move,
        check_status="Yes" if board.is_check() else "No",
        castling_rights=_castling_rights(board),
        en_passant=(
            chess.square_name(board.ep_square)
            if board.ep_square is not None
            else "none"
        ),
        draw_claim_available="yes" if board.can_claim_draw() else "no",
        agent_material_cp=agent_material_cp,
        opponent_material_cp=opponent_material_cp,
        agent_material_balance=f"{agent_material_balance:+d}",
        agent_material_change_from_canonical=(
            f"{agent_material_balance - canonical_material_balance:+d}"
        ),
        agent_piece_groups=agent_piece_groups,
        opponent_piece_groups=opponent_piece_groups,
        side_to_move_piece_groups=(
            agent_piece_groups if agent_to_move else opponent_piece_groups
        ),
    )


def _canonical_board_context(state: TurnState, phase: str) -> BoardStateContext:
    if state["phase"] != phase:
        raise ValueError(f"Canonical board state requires {phase} phase state.")
    return build_board_state_context(
        state,
        source="canonical",
        include_scratch_moves=False,
    )


def build_attack_board_state_context(state: TurnState) -> BoardStateContext:
    return _canonical_board_context(state, "attack")


def build_defense_board_state_context(state: TurnState) -> BoardStateContext:
    return _canonical_board_context(state, "defense")


def build_synthesis_board_state_context(state: TurnState) -> BoardStateContext:
    return _canonical_board_context(state, "synthesis")


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
    source: str,
    agent_side: str,
    opponent_move: bool,
    hypothetical_pass: bool,
    sort_checks_by_san: bool = False,
) -> SeeEvalContext:
    checks = scan.checks
    if sort_checks_by_san:
        checks = tuple(
            sorted(checks, key=lambda move: (not move.is_checkmate, move.move.san))
        )

    return SeeEvalContext(
        board_label="Canonical Board" if source == "canonical" else "Scratchboard",
        board_name="canonical board" if source == "canonical" else "scratchboard",
        hypothetical_pass=hypothetical_pass,
        status=scan.status,
        agent_side=agent_side.capitalize(),
        opponent_side="Black" if agent_side == "white" else "White",
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


def build_see_eval_context(
    state: TurnState,
    *,
    source: str,
    actor: str,
    score_perspective: str,
) -> SeeEvalContext:
    """Build one SEE scan according to manifest parameters."""

    if score_perspective != "agent":
        raise ValueError("SEE score_perspective must be agent.")
    board, _ = _board_for_source(state, source)
    agent_color = chess.WHITE if state["side"] == "white" else chess.BLACK
    hypothetical_pass = actor == "opponent_after_pass"

    if actor == "agent":
        if board.turn != agent_color:
            raise ValueError("Agent SEE scan requires the agent to be the side to move.")
        scan = scan_agent_forcing_moves(board.fen())
    elif actor == "opponent_after_pass":
        if board.turn != agent_color:
            raise ValueError(
                "Opponent-after-pass SEE scan requires the agent to move first."
            )
        scan = scan_opponent_forcing_moves(board.fen())
    elif actor == "side_to_move":
        scan = scan_agent_forcing_moves(board.fen())
    else:
        raise ValueError(f"Unknown SEE actor: {actor}")

    opponent_move = scan.actor != state["side"]
    return _see_eval_context(
        scan,
        source=source,
        agent_side=state["side"],
        opponent_move=opponent_move,
        hypothetical_pass=hypothetical_pass,
        sort_checks_by_san=hypothetical_pass,
    )


def build_attack_see_eval_context(state: TurnState) -> SeeEvalContext:
    if state["phase"] != "attack":
        raise ValueError("Attack SEE evaluation requires attack phase state.")
    return build_see_eval_context(
        state,
        source="canonical",
        actor="agent",
        score_perspective="agent",
    )


def build_defense_see_eval_context(state: TurnState) -> SeeEvalContext:
    if state["phase"] != "defense":
        raise ValueError("Defense SEE evaluation requires defense phase state.")
    return build_see_eval_context(
        state,
        source="canonical",
        actor="opponent_after_pass",
        score_perspective="agent",
    )


def build_synthesis_see_eval_context(state: TurnState) -> SeeEvalContext:
    if state["phase"] != "synthesis":
        raise ValueError("Synthesis SEE evaluation requires synthesis phase state.")
    return build_see_eval_context(
        state,
        source="canonical",
        actor="agent",
        score_perspective="agent",
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
    """Build context for a retry section selected by the manifest."""

    if not state["forced_retry"]:
        raise ValueError("Forced retry context requires an active forced retry.")
    previous = state["retry_output"].strip()
    if not previous:
        previous = "(No visible previous output was captured.)"
    fence = "````"
    while fence in previous:
        fence += "`"
    return ForcedToolRetryContext(
        previous_output=previous,
        correction=state["correction"].strip(),
        fence=fence,
    )


def build_condition_context(state: TurnState) -> dict[str, dict[str, object]]:
    """Expose the small normalized state surface allowed in manifest conditions."""

    return {
        "scratch": {"status": "active" if state["scratch_moves"] else "unused"},
        "retry": {"active": state["forced_retry"]},
    }


def _require_parameters(
    provider: str,
    parameters: Mapping[str, Any],
    expected: set[str],
) -> None:
    if set(parameters) != expected:
        raise ValueError(
            f"Provider {provider} requires parameters {sorted(expected)}; "
            f"received {sorted(parameters)}."
        )


def _board_state_provider(
    state: TurnState,
    parameters: Mapping[str, Any],
) -> dict[str, Any]:
    _require_parameters(
        "board_state",
        parameters,
        set(PROVIDER_PARAMETER_NAMES["board_state"]),
    )
    source = parameters["source"]
    include_scratch_moves = parameters["include_scratch_moves"]
    if not isinstance(source, str) or not isinstance(include_scratch_moves, bool):
        raise ValueError("board_state provider parameters have invalid types.")
    return asdict(
        build_board_state_context(
            state,
            source=source,
            include_scratch_moves=include_scratch_moves,
        )
    )


def _see_eval_provider(
    state: TurnState,
    parameters: Mapping[str, Any],
) -> dict[str, Any]:
    _require_parameters(
        "see_eval",
        parameters,
        set(PROVIDER_PARAMETER_NAMES["see_eval"]),
    )
    if not all(isinstance(value, str) for value in parameters.values()):
        raise ValueError("see_eval provider parameters must be strings.")
    return asdict(
        build_see_eval_context(
            state,
            source=parameters["source"],
            actor=parameters["actor"],
            score_perspective=parameters["score_perspective"],
        )
    )


def _tool_history_provider(
    state: TurnState,
    parameters: Mapping[str, Any],
) -> dict[str, Any]:
    _require_parameters("tool_history", parameters, set())
    return asdict(build_tool_history_context(state))


def _forced_tool_retry_provider(
    state: TurnState,
    parameters: Mapping[str, Any],
) -> dict[str, Any]:
    _require_parameters("forced_tool_retry", parameters, set())
    return asdict(build_forced_tool_retry_context(state))


def _phase_reports_provider(
    state: TurnState,
    parameters: Mapping[str, Any],
) -> dict[str, Any]:
    _require_parameters("phase_reports", parameters, set())
    if state["phase"] != "synthesis":
        raise ValueError("Phase reports are available only during synthesis.")
    return {
        "defense_report": state["defense_report"],
        "attack_report": state["attack_report"],
    }


PROVIDERS: dict[
    str,
    Callable[[TurnState, Mapping[str, Any]], dict[str, Any]],
] = {
    "board_state": _board_state_provider,
    "see_eval": _see_eval_provider,
    "tool_history": _tool_history_provider,
    "forced_tool_retry": _forced_tool_retry_provider,
    "phase_reports": _phase_reports_provider,
}


def build_section_context(
    provider: str | None,
    state: TurnState,
    parameters: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve a manifest provider into an isolated template context."""

    if provider is None:
        _require_parameters("static", parameters, set())
        return {}
    try:
        build_context = PROVIDERS[provider]
    except KeyError as exc:
        raise ValueError(f"Unknown prompt context provider: {provider}") from exc
    return build_context(state, parameters)

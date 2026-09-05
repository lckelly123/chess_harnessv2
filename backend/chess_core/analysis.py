"""Small deterministic analyses required by the live chess agents."""

from __future__ import annotations

from dataclasses import dataclass

import chess

from .errors import IllegalMoveError, InvalidSquareError
from .models import (
    ColorName,
    ForcingMove,
    ForcingMoveScan,
    MoveIdentity,
    PieceInfo,
    SquareInspection,
    StaticExchangeResult,
)
from .position import _board_from_fen, _color_name, _move_identity, _parse_move


_PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}


@dataclass(frozen=True, slots=True)
class _ExchangeResult:
    score_cp: int
    moves: tuple[chess.Move, ...]


def _parse_color(value: str | chess.Color) -> chess.Color:
    if value == chess.WHITE or value == chess.BLACK:
        return value
    normalized = str(value).strip().casefold()
    if normalized == "white":
        return chess.WHITE
    if normalized == "black":
        return chess.BLACK
    raise ValueError(f"Unsupported chess color: {value!r}")


def _piece_info(board: chess.Board, square: chess.Square) -> PieceInfo | None:
    piece = board.piece_at(square)
    if piece is None:
        return None
    return PieceInfo(
        square=chess.square_name(square),
        color=_color_name(piece.color),
        piece=chess.piece_name(piece.piece_type),
        symbol=piece.symbol(),
    )


def _pieces_targeting(
    board: chess.Board,
    *,
    color: chess.Color,
    square: chess.Square,
) -> tuple[PieceInfo, ...]:
    pieces = (
        _piece_info(board, source)
        for source in sorted(board.attackers(color, square))
    )
    return tuple(piece for piece in pieces if piece is not None)


def inspect_square(
    fen: str,
    square: str,
    *,
    perspective: ColorName,
) -> SquareInspection:
    """Return occupant and geometric square control without evaluation."""

    board = _board_from_fen(fen)
    try:
        square_index = chess.parse_square(str(square).strip().lower())
    except ValueError as exc:
        raise InvalidSquareError(f"Invalid square: {square!r}") from exc
    friendly = _parse_color(perspective)
    return SquareInspection(
        square=chess.square_name(square_index),
        perspective=_color_name(friendly),
        occupant=_piece_info(board, square_index),
        friendly_pieces_targeting=_pieces_targeting(
            board,
            color=friendly,
            square=square_index,
        ),
        opponent_pieces_targeting=_pieces_targeting(
            board,
            color=not friendly,
            square=square_index,
        ),
    )


def _captured_piece_type(board: chess.Board, move: chess.Move) -> chess.PieceType:
    if board.is_en_passant(move):
        return chess.PAWN
    captured = board.piece_at(move.to_square)
    if captured is None:
        raise IllegalMoveError(f"SEE move does not capture a piece: {move.uci()}")
    return captured.piece_type


def _capture_gain(board: chess.Board, move: chess.Move) -> int:
    gain = _PIECE_VALUES[_captured_piece_type(board, move)]
    if move.promotion is not None:
        gain += _PIECE_VALUES[move.promotion] - _PIECE_VALUES[chess.PAWN]
    return gain


def _attacker_order(board: chess.Board, move: chess.Move) -> tuple[int, str]:
    attacker = board.piece_at(move.from_square)
    if attacker is None:
        raise IllegalMoveError(f"SEE move has no attacking piece: {move.uci()}")
    return _PIECE_VALUES[attacker.piece_type], move.uci()


def _forced_capture_result(
    board: chess.Board,
    move: chess.Move,
    target_square: chess.Square,
) -> _ExchangeResult:
    gain = _capture_gain(board, move)
    board.push(move)
    try:
        replies = sorted(
            (
                reply
                for reply in board.generate_legal_captures()
                if reply.to_square == target_square
            ),
            key=lambda reply: _attacker_order(board, reply),
        )
        best_reply: _ExchangeResult | None = None
        for reply in replies:
            result = _forced_capture_result(board, reply, target_square)
            if best_reply is None or result.score_cp > best_reply.score_cp:
                best_reply = result
        if best_reply is None or best_reply.score_cp < 0:
            return _ExchangeResult(score_cp=gain, moves=(move,))
        return _ExchangeResult(
            score_cp=gain - best_reply.score_cp,
            moves=(move, *best_reply.moves),
        )
    finally:
        board.pop()


def _static_exchange_for_move(
    board: chess.Board,
    move: chess.Move,
) -> StaticExchangeResult:
    working_board = board.copy(stack=False)
    if move not in working_board.legal_moves:
        raise IllegalMoveError(f"SEE move must be legal: {move.uci()}")
    if not working_board.is_capture(move):
        raise IllegalMoveError(f"SEE move must be a capture: {move.uci()}")

    result = _forced_capture_result(working_board, move, move.to_square)
    replay = board.copy(stack=False)
    sequence: list[MoveIdentity] = []
    for capture in result.moves:
        sequence.append(_move_identity(replay, capture))
        replay.push(capture)
    return StaticExchangeResult(
        score_cp=result.score_cp,
        capture_sequence=tuple(sequence),
    )


def static_exchange(fen: str, move_text: str) -> StaticExchangeResult:
    """Evaluate a legal capture from the initiating side's perspective."""

    board = _board_from_fen(fen)
    return _static_exchange_for_move(board, _parse_move(board, move_text))


def _is_checkmate_after(board: chess.Board, move: chess.Move) -> bool:
    board.push(move)
    try:
        return board.is_checkmate()
    finally:
        board.pop()


def _game_over_reason(board: chess.Board) -> str:
    outcome = board.outcome(claim_draw=False)
    return outcome.termination.name.lower() if outcome else "game_over"


def _forcing_scan(board: chess.Board) -> ForcingMoveScan:
    actor = _color_name(board.turn)
    if board.is_game_over(claim_draw=False):
        return ForcingMoveScan(
            status="game_over",
            actor=actor,
            reason=_game_over_reason(board),
        )

    checks: list[ForcingMove] = []
    captures: list[ForcingMove] = []
    for move in board.legal_moves:
        is_check = board.gives_check(move)
        is_capture = board.is_capture(move)
        if not is_check and not is_capture:
            continue
        exchange = _static_exchange_for_move(board, move) if is_capture else None
        forcing_move = ForcingMove(
            move=_move_identity(board, move),
            is_checkmate=_is_checkmate_after(board, move) if is_check else False,
            static_exchange=exchange,
        )
        if is_check:
            checks.append(forcing_move)
        else:
            captures.append(forcing_move)

    checks.sort(
        key=lambda item: (
            not item.is_checkmate,
            -(item.static_exchange.score_cp if item.static_exchange else 0),
            item.move.san,
        )
    )
    captures.sort(
        key=lambda item: (
            -(item.static_exchange.score_cp if item.static_exchange else 0),
            item.move.san,
        )
    )
    return ForcingMoveScan(
        status="ready",
        actor=actor,
        checks=tuple(checks),
        captures=tuple(captures),
    )


def scan_agent_forcing_moves(fen: str) -> ForcingMoveScan:
    """Scan checks and captures for the side to move."""

    return _forcing_scan(_board_from_fen(fen))


def scan_opponent_forcing_moves(fen: str) -> ForcingMoveScan:
    """Scan the opponent's hypothetical checks and captures after a pass."""

    board = _board_from_fen(fen)
    opponent = _color_name(not board.turn)
    if board.is_check():
        return ForcingMoveScan(
            status="game_over" if board.is_checkmate() else "in_check",
            actor=opponent,
            reason="checkmate" if board.is_checkmate() else "agent_in_check",
        )
    if board.is_game_over(claim_draw=False):
        return ForcingMoveScan(
            status="game_over",
            actor=opponent,
            reason=_game_over_reason(board),
        )
    opponent_board = board.copy(stack=False)
    opponent_board.push(chess.Move.null())
    return _forcing_scan(opponent_board)

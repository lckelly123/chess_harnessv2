"""Authoritative deterministic position and move operations."""

from __future__ import annotations

import re

import chess

from .errors import IllegalMoveError, InvalidPositionError
from .models import ColorName, MoveIdentity, MoveTransition, PositionStatus

STARTING_FEN = chess.Board().fen()
_UCI_MOVE = re.compile(r"^[a-h][1-8][a-h][1-8][qrbn]$")
_UCI_MOVE_WITHOUT_PROMOTION = re.compile(r"^[a-h][1-8][a-h][1-8]$")


def _color_name(color: chess.Color) -> ColorName:
    return "white" if color == chess.WHITE else "black"


def _board_from_fen(fen: str) -> chess.Board:
    text = str(fen or "").strip()
    if not text or text == "startpos":
        return chess.Board()
    try:
        board = chess.Board(text)
    except ValueError as exc:
        raise InvalidPositionError(f"Invalid FEN: {text}") from exc
    if not board.is_valid():
        raise InvalidPositionError(
            f"FEN does not describe a valid chess position: {text}"
        )
    return board


def _move_identity(board: chess.Board, move: chess.Move) -> MoveIdentity:
    return MoveIdentity(
        san=board.san(move),
        uci=move.uci(),
        from_square=chess.square_name(move.from_square),
        to_square=chess.square_name(move.to_square),
        promotion=chess.piece_name(move.promotion) if move.promotion else None,
        is_capture=board.is_capture(move),
        gives_check=board.gives_check(move),
        is_castling=board.is_castling(move),
        is_en_passant=board.is_en_passant(move),
    )


def _position_status_from_board(board: chess.Board) -> PositionStatus:
    outcome = board.outcome(claim_draw=True)
    return PositionStatus(
        side_to_move=_color_name(board.turn),
        is_check=board.is_check(),
        is_checkmate=board.is_checkmate(),
        is_stalemate=board.is_stalemate(),
        is_insufficient_material=board.is_insufficient_material(),
        can_claim_draw=board.can_claim_draw(),
        is_game_over=board.is_game_over(claim_draw=True),
        result=outcome.result() if outcome else None,
        winner=(
            _color_name(outcome.winner)
            if outcome is not None and outcome.winner is not None
            else None
        ),
        termination=outcome.termination.name.lower() if outcome else None,
    )


def parse_position(fen: str) -> str:
    """Validate and return the normalized FEN for a position."""

    return _board_from_fen(fen).fen()


def legal_moves(fen: str) -> tuple[MoveIdentity, ...]:
    """Return all legal moves without exposing the mutable board."""

    board = _board_from_fen(fen)
    return tuple(_move_identity(board, move) for move in board.legal_moves)


def _parse_move(board: chess.Board, move_text: str) -> chess.Move:
    text = str(move_text or "").strip()
    if not text:
        raise IllegalMoveError("Move text is empty.")

    lowered = text.lower()
    if _UCI_MOVE.fullmatch(lowered) or _UCI_MOVE_WITHOUT_PROMOTION.fullmatch(lowered):
        try:
            move = chess.Move.from_uci(lowered)
        except ValueError as exc:
            raise IllegalMoveError(f"Invalid UCI move: {text}") from exc
        if move not in board.legal_moves and _UCI_MOVE_WITHOUT_PROMOTION.fullmatch(
            lowered
        ):
            queen_promotion = chess.Move(
                move.from_square,
                move.to_square,
                promotion=chess.QUEEN,
            )
            if queen_promotion in board.legal_moves:
                return queen_promotion
        if move not in board.legal_moves:
            raise IllegalMoveError(f"Move is illegal in this position: {text}")
        return move

    try:
        move = board.parse_san(text)
    except ValueError as exc:
        text_without_check = text.rstrip("+#")
        for candidate in board.legal_moves:
            if candidate.promotion != chess.QUEEN:
                continue
            san_without_queen = board.san(candidate).replace("=Q", "")
            if (
                text == san_without_queen
                or text_without_check == san_without_queen.rstrip("+#")
            ):
                return candidate
        raise IllegalMoveError(
            f"Move is not legal SAN or UCI in this position: {text}"
        ) from exc
    # python-chess also parses null-move SAN; a pass is not a legal game move.
    if move not in board.legal_moves:
        raise IllegalMoveError(f"Move is illegal in this position: {text}")
    return move


def normalize_move(fen: str, move_text: str) -> MoveIdentity:
    """Validate SAN or UCI and return one canonical move identity.

    An otherwise legal pawn promotion defaults to a queen when its promotion
    piece is omitted. Explicit underpromotions remain unchanged.
    """

    board = _board_from_fen(fen)
    return _move_identity(board, _parse_move(board, move_text))


def apply_move(fen: str, move_text: str) -> MoveTransition:
    """Apply one legal move and return a complete immutable transition."""

    board = _board_from_fen(fen)
    fen_before = board.fen()
    move = _parse_move(board, move_text)
    identity = _move_identity(board, move)
    board.push(move)
    return MoveTransition(
        move=identity,
        fen_before=fen_before,
        fen_after=board.fen(),
        status_after=_position_status_from_board(board),
    )


def position_status(fen: str) -> PositionStatus:
    """Return the rule-derived state of a position."""

    return _position_status_from_board(_board_from_fen(fen))

from __future__ import annotations

import pytest

from chess_core import (
    STARTING_FEN,
    IllegalMoveError,
    InvalidPositionError,
    apply_move,
    legal_moves,
    normalize_move,
    parse_position,
    position_status,
)


def test_starting_position_exposes_normalized_legal_moves() -> None:
    moves = legal_moves(STARTING_FEN)

    assert len(moves) == 20
    e4 = next(move for move in moves if move.san == "e4")
    assert e4.uci == "e2e4"
    assert e4.from_square == "e2"
    assert e4.to_square == "e4"
    assert not e4.is_capture


def test_normalize_move_accepts_san_and_uci() -> None:
    san_move = normalize_move(STARTING_FEN, "Nf3")
    uci_move = normalize_move(STARTING_FEN, "g1f3")

    assert san_move == uci_move
    assert san_move.san == "Nf3"


def test_apply_move_returns_a_complete_transition() -> None:
    transition = apply_move(STARTING_FEN, "e4")

    assert transition.fen_before == STARTING_FEN
    assert transition.move.san == "e4"
    assert transition.move.uci == "e2e4"
    assert transition.status_after.side_to_move == "black"
    assert normalize_move(transition.fen_after, "e5").uci == "e7e5"


def test_illegal_move_does_not_produce_a_transition() -> None:
    with pytest.raises(IllegalMoveError, match="not legal"):
        apply_move(STARTING_FEN, "e5")


def test_invalid_position_is_rejected() -> None:
    with pytest.raises(InvalidPositionError):
        parse_position("8/8/8/8/8/8/8/8 w - - 0 1")


def test_special_moves_are_normalized_correctly() -> None:
    castling = normalize_move(
        "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
        "O-O",
    )
    promotion = normalize_move(
        "7k/P7/8/8/8/8/8/7K w - - 0 1",
        "a8=Q+",
    )
    en_passant = normalize_move(
        "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1",
        "exd6",
    )

    assert castling.uci == "e1g1"
    assert castling.is_castling
    assert promotion.uci == "a7a8q"
    assert promotion.promotion == "queen"
    assert en_passant.uci == "e5d6"
    assert en_passant.is_en_passant


@pytest.mark.parametrize("move", ["a8", "a8+", "a7a8"])
def test_omitted_promotion_piece_defaults_to_queen(move) -> None:
    promotion = normalize_move(
        "7k/P7/8/8/8/8/8/7K w - - 0 1",
        move,
    )

    assert promotion.san == "a8=Q+"
    assert promotion.uci == "a7a8q"
    assert promotion.promotion == "queen"


def test_explicit_underpromotion_is_preserved() -> None:
    promotion = normalize_move(
        "7k/P7/8/8/8/8/8/7K w - - 0 1",
        "a8=N",
    )

    assert promotion.san == "a8=N"
    assert promotion.uci == "a7a8n"
    assert promotion.promotion == "knight"


def test_position_status_reports_checkmate() -> None:
    status = position_status("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1")

    assert status.is_checkmate
    assert status.is_game_over
    assert status.result == "1-0"
    assert status.winner == "white"
    assert status.termination == "checkmate"

from __future__ import annotations

import pytest

from chess_core import (
    IllegalMoveError,
    InvalidSquareError,
    inspect_square,
    scan_agent_forcing_moves,
    scan_opponent_forcing_moves,
    static_exchange,
)


def test_inspect_square_reports_occupant_and_both_sides_targeting() -> None:
    inspection = inspect_square(
        "4k3/8/8/3p4/4P3/5P2/8/4K3 w - - 0 1",
        "e4",
        perspective="white",
    )

    assert inspection.occupant is not None
    assert inspection.occupant.piece == "pawn"
    assert [piece.square for piece in inspection.friendly_pieces_targeting] == ["f3"]
    assert [piece.square for piece in inspection.opponent_pieces_targeting] == ["d5"]


def test_inspect_square_rejects_invalid_square() -> None:
    with pytest.raises(InvalidSquareError):
        inspect_square(
            "4k3/8/8/8/8/8/8/4K3 w - - 0 1",
            "z9",
            perspective="white",
        )


def test_static_exchange_returns_score_and_capture_sequence() -> None:
    result = static_exchange(
        "3rq1k1/8/8/8/8/8/8/3R2K1 w - - 0 1",
        "Rxd8",
    )

    assert result.score_cp == 0
    assert [move.uci for move in result.capture_sequence] == ["d1d8", "e8d8"]


def test_static_exchange_handles_en_passant_and_rejects_non_capture() -> None:
    result = static_exchange(
        "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1",
        "exd6",
    )

    assert result.score_cp == 100
    assert result.capture_sequence[0].is_en_passant

    with pytest.raises(IllegalMoveError, match="capture"):
        static_exchange(
            "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1",
            "e4",
        )


def test_agent_forcing_scan_separates_checks_and_captures() -> None:
    scan = scan_agent_forcing_moves("3r3k/8/8/8/8/8/K7/3Q4 w - - 0 1")

    checking_capture = next(move for move in scan.checks if move.move.san == "Qxd8+")
    assert scan.status == "ready"
    assert scan.actor == "white"
    assert checking_capture.static_exchange is not None
    assert checking_capture.static_exchange.score_cp == 500
    assert all(move.move.san != "Qxd8+" for move in scan.captures)


def test_opponent_scan_uses_hypothetical_pass_or_defers_in_check() -> None:
    ready = scan_opponent_forcing_moves(
        "3r3k/8/8/8/8/8/K7/3Q4 w - - 0 1"
    )
    checked = scan_opponent_forcing_moves(
        "k3r3/8/8/8/8/8/3R4/4K3 w - - 0 1"
    )

    assert ready.status == "ready"
    assert ready.actor == "black"
    assert any(move.move.san == "Rxd1" for move in ready.captures)
    assert checked.status == "in_check"
    assert checked.reason == "agent_in_check"
    assert checked.checks == ()
    assert checked.captures == ()

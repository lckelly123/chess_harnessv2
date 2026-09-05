from __future__ import annotations

import pytest

from chess_core import IllegalMoveError, STARTING_FEN, ScratchBoard


def test_scratchboard_isolated_play_undo_and_reset() -> None:
    scratch = ScratchBoard(STARTING_FEN)

    initial = scratch.snapshot()
    first = scratch.play("e4")
    second = scratch.play("e5")

    assert initial.status == "unused"
    assert scratch.canonical_fen == STARTING_FEN
    assert scratch.current_fen == second.fen_after
    assert [transition.move.san for transition in scratch.moves] == ["e4", "e5"]

    undone = scratch.undo()
    assert undone == second
    assert scratch.current_fen == first.fen_after

    scratch.reset()
    assert scratch.current_fen == STARTING_FEN
    assert scratch.moves == ()
    assert scratch.snapshot().status == "unused"


def test_illegal_scratch_move_preserves_state() -> None:
    scratch = ScratchBoard(STARTING_FEN)
    before = scratch.snapshot()

    with pytest.raises(IllegalMoveError):
        scratch.play("e5")

    assert scratch.snapshot() == before


def test_scratchboards_do_not_share_state() -> None:
    first = ScratchBoard(STARTING_FEN)
    second = ScratchBoard(STARTING_FEN)

    first.play("d4")

    assert first.current_fen != second.current_fen
    assert second.current_fen == STARTING_FEN
    assert second.moves == ()


def test_undo_on_unused_scratchboard_is_a_noop() -> None:
    scratch = ScratchBoard(STARTING_FEN)

    assert scratch.undo() is None
    assert scratch.current_fen == STARTING_FEN

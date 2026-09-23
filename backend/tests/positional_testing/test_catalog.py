from uuid import uuid4

import psycopg
import pytest

from positional_testing.catalog import (
    InvalidSavedPositionError,
    PositionLibraryUnavailableError,
    get_saved_position,
    list_saved_positions,
)
from positional_testing.datasets import store


def test_lists_database_exercises_with_public_classifiers(library_rows):
    positions = list_saved_positions()
    assert len(positions) == 400
    saved = positions[0]
    row = library_rows[0]
    assert saved.id == row["id"]
    assert saved.dataset_version == "v1"
    assert saved.split == "train"
    assert saved.phase == "opening"
    assert saved.position_type == "quiet"
    assert saved.side_to_move == "white"
    assert saved.position.san == "Bb4"
    assert saved.position.from_square == "f8"
    assert saved.position.to_square == "b4"
    assert saved.position.fen == row["fen"]
    assert saved.puzzle_rating is None
    puzzle = next(
        position for position in positions if position.position_type == "tactical"
    )
    assert puzzle.themes and puzzle.puzzle_rating is not None
    assert set(saved.model_dump()).isdisjoint(
        {"pgn_prefix", "metadata", "best_move_uci", "evaluations"}
    )


def test_get_retains_exact_clean_history_for_model_inputs(library_rows):
    document = get_saved_position(library_rows[0]["id"])
    assert document is not None
    assert document.pgn == library_rows[0]["pgn_prefix"]
    assert '[Result "*"]' in document.pgn
    assert "[%eval" not in document.pgn


def test_unknown_and_legacy_ids_are_not_found(library_rows):
    assert get_saved_position(str(uuid4())) is None
    assert get_saved_position("before_queen_blunder") is None
    assert get_saved_position("../../anything") is None


def test_corrupt_history_is_rejected_before_a_run(library_rows):
    library_rows[0]["last_move_san"] = "Qh8#"
    with pytest.raises(InvalidSavedPositionError, match="history is inconsistent"):
        get_saved_position(library_rows[0]["id"])


def test_empty_database_is_empty_without_a_file_fallback(monkeypatch):
    monkeypatch.setattr(store, "list_position_rows", lambda: [])
    assert list_saved_positions() == []


def test_database_failure_is_actionable_and_does_not_expose_credentials(
    monkeypatch, library_rows
):
    def unavailable(*args):
        raise psycopg.OperationalError("private connection details")

    monkeypatch.setattr(store, "list_position_rows", unavailable)
    monkeypatch.setattr(store, "get_position_row", unavailable)
    for read in (
        list_saved_positions,
        lambda: get_saved_position(library_rows[0]["id"]),
    ):
        with pytest.raises(
            PositionLibraryUnavailableError, match="database service"
        ) as error:
            read()
        assert "private" not in str(error.value)

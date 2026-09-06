import pytest

from app.matches.repository import (
    FolderNameConflictError,
    MatchRepository,
    UnknownFolderError,
)
from chess_core import STARTING_FEN, apply_move
from harness.contracts import MoveDecision


def test_persists_replay_and_search(database_path, harnesses) -> None:
    path = database_path
    repository = MatchRepository(str(path))
    white, black = harnesses
    repository.create_match("match-persisted", white, black)
    transition = apply_move(STARTING_FEN, "e4")
    decision = MoveDecision(
        move=transition.move,
        justification="This explanation is persisted for the public match event.",
    )
    assert repository.append_move_if_running(
        "match-persisted",
        ply=1,
        player="white",
        move=transition.move,
        fen_after=transition.fen_after,
        decision=decision,
    )
    repository.stop("match-persisted", "Test complete.")
    repository.close()

    reopened = MatchRepository(str(path))
    try:
        match = reopened.get_match("match-persisted")
        assert match is not None
        assert match.move_count == 1
        assert match.positions[-1].san == "e4"
        assert match.positions[-1].fen == transition.fen_after
        assert any(decision.justification in event.detail for event in match.traces)
        assert reopened.list_matches("baseline").total == 1
    finally:
        reopened.close()


def test_stopped_match_rejects_late_move(repository, harnesses) -> None:
    white, black = harnesses
    repository.create_match("match-stopped", white, black)
    repository.stop("match-stopped", "Stopped by the user.")
    transition = apply_move(STARTING_FEN, "e4")

    committed = repository.append_move_if_running(
        "match-stopped",
        ply=1,
        player="white",
        move=transition.move,
        fen_after=transition.fen_after,
        decision=MoveDecision(
            move=transition.move,
            justification="This late result must never reach durable match state.",
        ),
    )

    assert committed is False
    match = repository.get_match("match-stopped")
    assert match is not None
    assert match.move_count == 0
    assert match.current_fen == STARTING_FEN


def test_folders_persist_filter_and_reassign_matches(database_path, harnesses) -> None:
    white, black = harnesses
    repository = MatchRepository(str(database_path))
    analysis = repository.create_folder("  Baseline   comparisons  ")
    repository.create_match("match-filed", white, black, analysis.id)
    repository.create_match("match-unfiled", white, black)

    assert repository.get_match("match-filed").folder.name == "Baseline comparisons"
    assert repository.list_matches(folder_id=analysis.id).total == 1
    assert repository.list_matches(unfiled_only=True).items[0].id == "match-unfiled"
    assert repository.list_matches("baseline comparisons").total == 1

    moved = repository.assign_match_folder("match-unfiled", analysis.id)
    assert moved is not None
    assert moved.folder is not None
    assert moved.folder.id == analysis.id

    folders = repository.list_folders()
    assert folders.total_matches == 2
    assert folders.unfiled_count == 0
    assert folders.items[0].match_count == 2
    repository.close()

    reopened = MatchRepository(str(database_path))
    try:
        folders = reopened.list_folders()
        assert folders.items[0].name == "Baseline comparisons"
        assert folders.items[0].match_count == 2
    finally:
        reopened.close()


def test_folder_names_are_unique_and_assignments_require_existing_folder(
    repository, harnesses
) -> None:
    white, black = harnesses
    repository.create_folder("Regression set")
    with pytest.raises(FolderNameConflictError):
        repository.create_folder("regression SET")

    repository.create_match("match-folder-errors", white, black)
    with pytest.raises(UnknownFolderError):
        repository.assign_match_folder("match-folder-errors", "folder-missing")

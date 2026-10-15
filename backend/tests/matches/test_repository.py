import pytest

from app.matches.repository import (
    FolderNameConflictError,
    MatchRepository,
    UnknownFolderError,
)
from app.models import HarnessVersion
from chess_core import STARTING_FEN, apply_move
from harness.contracts import MoveDecision


@pytest.mark.parametrize(
    ("harness_id", "old_name", "name"),
    [
        ("agent-player-1-langgraph-v1", "Agent Player 1", "legacy"),
        ("agent-player-2-langgraph-v1", "Agent Player 2", "chess_harness"),
        ("agent-player-3-langgraph-v1", "Agent Player 3", "chess_charness_alt"),
        ("custom-harness", "Agent Player 2", "Agent Player 2"),
    ],
)
def test_saved_harness_names_migrate_without_changing_replay(
    database_path, harness_id, old_name, name
):
    definition = HarnessVersion(
        id=harness_id, name=old_name, version="original-version", summary="Fixture"
    )
    repository = MatchRepository(str(database_path))
    repository.create_match("historical", definition, definition)
    repository.set_turn("historical", "white", 1, old_name)
    move = apply_move(STARTING_FEN, "e4")
    repository.append_move_if_running(
        "historical",
        ply=1,
        player="white",
        move=move.move,
        fen_after=move.fen_after,
        decision=MoveDecision(
            move=move.move, justification=f"{old_name}: original output"
        ),
    )
    repository.set_turn("historical", "black", 2, old_name)
    before = repository.get_match("historical")
    repository.close()

    for _ in range(2):
        reopened = MatchRepository(str(database_path))
        try:
            after = reopened.get_match("historical")
            assert after.white.name == after.black.name == name
            assert after.white.harness_id == after.black.harness_id == harness_id
            assert after.white.version == after.black.version == "original-version"
            assert after.positions == before.positions
            assert after.current_fen == before.current_fen
            assert after.status == before.status
            assert [event.detail for event in after.traces] == [
                event.detail for event in before.traces
            ]
            assert {event.summary for event in after.traces} == {
                f"{name} is choosing a move",
                f"{name} played e4",
            }
            assert reopened.list_matches(name).total == 1
        finally:
            reopened.close()


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

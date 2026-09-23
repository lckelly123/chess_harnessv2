import asyncio

import pytest

from app.matches.catalog import HARNESSES, UnknownHarnessError
from chess_core import normalize_move
from harness.contracts import MoveDecision
from positional_testing.runner import PositionalTestRunner, UnknownSavedPositionError


class RecordingPlayer:
    def __init__(self):
        self.requests = []

    async def choose_move(self, request):
        self.requests.append(request)
        return MoveDecision(
            move=normalize_move(request.fen, "e5"),
            justification="Advance the center pawn.",
            defense_report="No forced defensive obligation.",
            attack_report="The pawn attacks the knight.",
        )


class FakeCatalog:
    def __init__(self, player):
        self.player = player
        self.definitions = {item.id: item for item in HARNESSES}

    def definition(self, harness_id):
        try:
            return self.definitions[harness_id]
        except KeyError as exc:
            raise UnknownHarnessError(f"Unknown harness version: {harness_id}") from exc

    async def create_player(self, harness_id, cancellation_check, model_selection=None):
        self.definition(harness_id)
        assert cancellation_check() is False
        return self.player, "loaded-model"


def test_runs_exactly_one_turn_from_database_history(library_rows) -> None:
    player = RecordingPlayer()
    runner = PositionalTestRunner(
        FakeCatalog(player),
        id_factory=lambda: "positional-test-fixed",
    )

    result = asyncio.run(
        runner.run_once(
            library_rows[0]["id"],
            "agent-player-1-langgraph-v1",
        )
    )

    assert len(player.requests) == 1
    request = player.requests[0]
    assert request.game_id == "positional-test-fixed"
    assert request.side == "white"
    assert request.ply == library_rows[0]["source_ply"]
    assert request.fen == library_rows[0]["fen"]
    assert request.pgn == library_rows[0]["pgn_prefix"]
    assert not hasattr(request, "themes")
    assert not hasattr(request, "evaluations")
    assert result.run_id == request.game_id
    assert result.move.san == "e5"
    assert result.move.uci == "e4e5"
    assert result.model == "loaded-model"
    assert result.attack_report == "The pawn attacks the knight."
    stored = runner.repository.get(result.run_id)
    assert stored["status"] == "completed"
    assert stored["final_move_uci"] == result.move.uci
    assert stored["evaluation"]["status"] == "completed"
    assert stored["classification"] == "good"
    assert stored["expected_points_loss"] == 0.03


def test_rejects_unknown_saved_position() -> None:
    runner = PositionalTestRunner(FakeCatalog(RecordingPlayer()))

    try:
        asyncio.run(runner.run_once("missing", "agent-player-1-langgraph-v1"))
    except UnknownSavedPositionError as exc:
        assert str(exc) == "Unknown saved position: missing"
    else:
        raise AssertionError("Expected UnknownSavedPositionError")


def test_failed_turn_remains_in_history(library_rows, run_store):
    from harness.contracts import HarnessError

    class FailingPlayer:
        async def choose_move(self, request):
            raise HarnessError("Scripted model unavailable")

    runner = PositionalTestRunner(FakeCatalog(FailingPlayer()))
    with pytest.raises(HarnessError, match="Scripted model unavailable"):
        asyncio.run(
            runner.run_once(library_rows[0]["id"], "agent-player-3-langgraph-v1")
        )
    rows, total = run_store.list()
    assert total == 1
    assert rows[0]["status"] == "failed"
    assert rows[0]["error"] == "Scripted model unavailable"
    assert rows[0]["final_move_uci"] is None
    assert rows[0]["evaluation"] is None


def test_evaluation_failure_preserves_successful_model_trace(library_rows, run_store):
    class FailingEvaluator:
        async def evaluate(self, **kwargs):
            from harness.recording import current_recorder

            assert current_recorder.get() is None
            assert kwargs == {
                "fen": library_rows[0]["fen"],
                "pgn": library_rows[0]["pgn_prefix"],
                "move_uci": "e4e5",
            }
            assert next(iter(run_store.runs.values()))["final_move_uci"] == "e4e5"
            raise TimeoutError("Engine timed out")

    runner = PositionalTestRunner(
        FakeCatalog(RecordingPlayer()), evaluator=FailingEvaluator()
    )
    result = asyncio.run(
        runner.run_once(library_rows[0]["id"], "agent-player-3-langgraph-v1")
    )
    stored = run_store.get(result.run_id)
    assert stored["status"] == "completed"
    assert stored["final_move_uci"] == "e4e5"
    assert stored["error"] is None
    assert stored["classification"] is None
    assert stored["better_moves"] is None
    assert stored["evaluation"]["error"] == "Engine timed out"


def test_evaluation_cancellation_keeps_move_and_does_not_backfill(
    library_rows, run_store
):
    run_store.create("legacy", library_rows[0]["id"], "old", "old", {})
    run_store.finish("legacy", move="e4e5")

    class CancelledEvaluator:
        async def evaluate(self, **kwargs):
            raise asyncio.CancelledError()

    runner = PositionalTestRunner(
        FakeCatalog(RecordingPlayer()), evaluator=CancelledEvaluator()
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            runner.run_once(library_rows[0]["id"], "agent-player-3-langgraph-v1")
        )
    assert run_store.get("legacy")["evaluation"] is None
    new_run = next(row for key, row in run_store.runs.items() if key != "legacy")
    assert new_run["status"] == "completed"
    assert new_run["final_move_uci"] == "e4e5"
    assert new_run["evaluation"]["status"] == "failed"

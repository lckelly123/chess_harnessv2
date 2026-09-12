import asyncio

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
            move=normalize_move(request.fen, "Qxe3+"),
            justification="Wins the bishop with check.",
            defense_report="No forced defensive obligation.",
            attack_report="The queen can capture e3 with check.",
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

    async def create_player(self, harness_id, cancellation_check):
        self.definition(harness_id)
        assert cancellation_check() is False
        return self.player, "loaded-model"


def test_runs_exactly_one_turn_from_the_saved_pgn() -> None:
    player = RecordingPlayer()
    runner = PositionalTestRunner(
        FakeCatalog(player),
        id_factory=lambda: "positional-test-fixed",
    )

    result = asyncio.run(
        runner.run_once(
            "before_queen_blunder",
            "agent-player-1-langgraph-v1",
        )
    )

    assert len(player.requests) == 1
    request = player.requests[0]
    assert request.game_id == "positional-test-fixed"
    assert request.side == "black"
    assert request.ply == 23
    assert request.fen == (
        "2r1kb1r/p1p1pppp/2p5/8/3q4/2N1B3/PPP2PPP/R3K2R b KQk - 1 12"
    )
    assert '[Event "Agent Player 1 Queen Blunder Test"]' in request.pgn
    assert result.run_id == request.game_id
    assert result.move.san == "Qxe3+"
    assert result.move.uci == "d4e3"
    assert result.model == "loaded-model"
    assert result.attack_report == "The queen can capture e3 with check."


def test_rejects_unknown_saved_position() -> None:
    runner = PositionalTestRunner(FakeCatalog(RecordingPlayer()))

    try:
        asyncio.run(runner.run_once("missing", "agent-player-1-langgraph-v1"))
    except UnknownSavedPositionError as exc:
        assert str(exc) == "Unknown saved position: missing"
    else:
        raise AssertionError("Expected UnknownSavedPositionError")

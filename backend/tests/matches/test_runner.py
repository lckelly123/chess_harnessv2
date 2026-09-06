import asyncio
import io

import chess.pgn

from app.matches.runner import MatchRunner
from chess_core import normalize_move
from harness.contracts import MoveDecision


class ScriptedPlayer:
    def __init__(self, moves):
        self.requests = []
        self.moves = iter(moves)

    async def choose_move(self, request):
        self.requests.append(request)
        move = normalize_move(request.fen, next(self.moves))
        return MoveDecision(
            move=move,
            justification="Choose the next scripted legal move for an offline test.",
        )


def test_runner_alternates_players_and_completes_checkmate(
    repository, harnesses
) -> None:
    white_definition, black_definition = harnesses
    repository.create_match("match-runner", white_definition, black_definition)
    white = ScriptedPlayer(["f3", "g4"])
    black = ScriptedPlayer(["e5", "Qh4#"])
    runner = MatchRunner(repository)

    asyncio.run(
        runner.run(
            "match-runner",
            white=white,
            black=black,
            white_name=white_definition.name,
            black_name=black_definition.name,
            cancelled=asyncio.Event(),
        )
    )

    match = repository.get_match("match-runner")
    assert match is not None
    assert match.status == "completed"
    assert match.result == "0-1"
    assert match.termination_reason == "checkmate"
    assert match.move_count == 4
    assert [position.player for position in match.positions[1:]] == [
        "white",
        "black",
        "white",
        "black",
    ]
    assert [request.ply for request in white.requests] == [0, 2]
    assert [request.ply for request in black.requests] == [1, 3]

    requests = sorted(white.requests + black.requests, key=lambda item: item.ply)
    for request in requests:
        game = chess.pgn.read_game(io.StringIO(request.pgn))
        assert game is not None
        assert game.end().board().fen() == request.fen

import asyncio
import os
import shutil

import chess
import chess.engine
import chess.pgn
import pytest

from positional_testing.evaluation import (
    CompleteCandidates,
    EvaluationSettings,
    StockfishEvaluator,
    classification,
    grade_candidates,
)


@pytest.mark.parametrize(
    ("units", "expected"),
    [
        (0, "excellent"),
        (39, "excellent"),
        (40, "good"),
        (99, "good"),
        (100, "inaccuracy"),
        (199, "inaccuracy"),
        (200, "mistake"),
        (399, "mistake"),
        (400, "blunder"),
        (2000, "blunder"),
    ],
)
def test_exact_thresholds(units, expected):
    assert classification(units, is_best=False) == expected
    assert classification(0, is_best=True) == "best"


def candidate(board, move, *, index, cp=-300, wdl=(0, 200, 800), depth=12, mate=None):
    # Deliberately encode everything from White's POV to detect sign mistakes.
    score = chess.engine.Cp(cp) if mate is None else chess.engine.Mate(mate)
    root_score = chess.engine.PovScore(score, board.turn)
    root_wdl = chess.engine.PovWdl(chess.engine.Wdl(*wdl), board.turn)
    return {
        "pv": [move],
        "depth": depth,
        "multipv": index,
        "score": chess.engine.PovScore(root_score.white(), chess.WHITE),
        "wdl": chess.engine.PovWdl(root_wdl.white(), chess.WHITE),
    }


@pytest.mark.parametrize("black", [False, True])
def test_all_better_moves_sorted_by_loss_from_original_mover(black):
    board = chess.Board()
    if black:
        board.push_uci("e2e4")
    moves = list(board.legal_moves)
    lines = [candidate(board, m, index=i + 1) for i, m in enumerate(moves)]
    # Eight strictly better moves: prove this is not a top-five shortlist.
    for i in range(8):
        lines[i] = candidate(
            board,
            moves[i],
            index=i + 1,
            cp=180 - i * 10,
            wdl=(500 - i * 10, 400, 100 + i * 10),
        )
    lines[8] = candidate(board, moves[8], index=9, cp=70, wdl=(200, 600, 200))
    # Same expected points as chosen, with a higher CP value: not a training target.
    lines[9] = candidate(board, moves[9], index=10, cp=80, wdl=(200, 600, 200))
    result = grade_candidates(board, moves[8].uci(), list(reversed(lines)))
    assert result["expected_points_loss"] == 0.20
    assert result["classification"] == "blunder"
    assert result["cp_loss"] == 110
    assert len(result["better_moves"]) == 8
    assert [m["move_uci"] for m in result["better_moves"]] == [
        m.uci() for m in moves[:8]
    ]
    assert result["better_moves"][0]["expected_points_loss"] == 0
    assert result["better_moves"][-1]["expected_points_loss"] == 0.07
    assert result["better_moves"][-1]["improvement_over_chosen"] == 0.13
    assert result["chosen"]["wdl"] == {"wins": 200, "draws": 600, "losses": 200}
    assert grade_candidates(board, moves[0].uci(), lines)["better_moves"] == []
    assert grade_candidates(board, moves[0].uci(), lines)["classification"] == "best"


def test_rounded_equal_expected_scores_do_not_all_become_best():
    board = chess.Board()
    moves = list(board.legal_moves)
    lines = [
        candidate(board, m, index=i + 1, cp=10, wdl=(0, 1000, 0))
        for i, m in enumerate(moves)
    ]
    lines[0] = candidate(board, moves[0], index=1, cp=20, wdl=(0, 1000, 0))
    result = grade_candidates(board, moves[1].uci(), lines)
    assert result["expected_points_loss"] == 0
    assert result["classification"] == "excellent"
    assert result["better_moves"] == []
    lines[1] = candidate(board, moves[1], index=2, cp=20, wdl=(0, 1000, 0))
    assert grade_candidates(board, moves[1].uci(), lines)["classification"] == "best"


@pytest.mark.parametrize(
    "mate,wdl,loss,label",
    [
        (1, (1000, 0, 0), 0.9, "blunder"),
        (-1, (0, 0, 1000), 0, "excellent"),
    ],
)
def test_mate_scores_remain_separate_from_cp(mate, wdl, loss, label):
    board = chess.Board()
    moves = list(board.legal_moves)
    lines = [
        candidate(board, m, index=i + 1, mate=mate, wdl=wdl)
        for i, m in enumerate(moves)
    ]
    lines[1] = candidate(board, moves[1], index=2)
    result = grade_candidates(board, moves[1].uci(), lines)
    assert result["expected_points_loss"] == loss
    # In the losing-mate case the finite evaluation is the best alternative.
    if mate < 0:
        result = grade_candidates(board, moves[0].uci(), lines)
        assert result["expected_points_loss"] == 0.1
        assert result["classification"] == "mistake"
    else:
        assert result["classification"] == label
    assert result["cp_loss"] is None


def test_partial_and_bounded_depths_are_discarded():
    board = chess.Board()
    moves = list(board.legal_moves)
    complete = [candidate(board, m, index=i + 1) for i, m in enumerate(moves)]
    collector = CompleteCandidates(moves)
    for info in complete:
        collector.add(info)
    for info in complete:
        collector.add({**info, "depth": 13, "lowerbound": True})
    collector.add({**complete[0], "depth": 14})
    assert collector.finish() == complete
    with pytest.raises(ValueError, match="every legal move"):
        grade_candidates(board, moves[0].uci(), complete[:5])
    with pytest.raises(ValueError, match="complete depth"):
        CompleteCandidates(moves).finish()


def test_history_and_legality_are_verified_before_starting_engine():
    evaluator = StockfishEvaluator(EvaluationSettings(executable="missing-engine"))
    with pytest.raises(ValueError, match="recreate"):
        asyncio.run(
            evaluator.evaluate(fen=chess.STARTING_FEN, pgn="1. e4 *", move_uci="e7e5")
        )
    with pytest.raises(ValueError, match="not legal"):
        asyncio.run(
            evaluator.evaluate(fen=chess.STARTING_FEN, pgn="*", move_uci="e2e5")
        )


def test_pgn_move_stack_reaches_evaluator():
    class InspectHistory(StockfishEvaluator):
        async def _analyse(self, board, move_uci):
            assert len(board.move_stack) == 4
            assert board.is_repetition(2)
            return {"ok": True}

    result = asyncio.run(
        InspectHistory().evaluate(
            fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 4 3",
            pgn="1. Nf3 Nf6 2. Ng1 Ng8 *",
            move_uci="g1f3",
        )
    )
    assert result == {"ok": True}


@pytest.mark.skipif(
    os.getenv("POSITIONS_INTEGRATION_TEST") != "1",
    reason="Opt-in Stockfish integration",
)
@pytest.mark.parametrize(
    "fen,chosen",
    [
        (chess.STARTING_FEN, "e2e4"),
        ("7k/5K2/6Q1/8/8/8/8/8 w - - 0 1", "f7f6"),
    ],
)
def test_real_stockfish_full_coverage_and_mate(fen, chosen):
    executable = os.getenv("STOCKFISH_PATH", "stockfish")
    assert shutil.which(executable), "Integration tests require Stockfish"
    board = chess.Board(fen)
    pgn = str(chess.pgn.Game.from_board(board))
    evaluator = StockfishEvaluator(
        EvaluationSettings(executable=executable, nodes_per_move=20_000)
    )
    result = asyncio.run(evaluator.evaluate(fen=fen, pgn=pgn, move_uci=chosen))
    meta = result["evaluation"]
    assert (
        meta["legal_move_count"]
        == meta["evaluated_move_count"]
        == board.legal_moves.count()
    )
    assert len(meta["engine_sha256"]) == 64
    assert all(
        m["expected_points"] > meta["chosen"]["expected_points"]
        for m in result["better_moves"]
    )
    if fen != chess.STARTING_FEN:
        assert meta["best"]["mate"] == 1
        assert result["expected_points_loss"] == 0.5
        assert result["classification"] == "blunder"

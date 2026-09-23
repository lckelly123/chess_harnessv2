import copy
import hashlib
import json
import uuid
from pathlib import Path

import chess
import chess.engine
import pytest

from positional_testing.datasets.curate import complete_variations, quiet_rejection
from positional_testing.datasets.validation import (
    clean_prefix,
    load_collection,
    load_evaluations,
    position_key,
    validate_collection,
    validate_position,
)

SEED = Path(__file__).resolve().parents[2] / "positional_testing/datasets/seed/v1"


@pytest.fixture
def position():
    board = chess.Board()
    for san in "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6 c3 O-O".split():
        board.push_san(san)
    return {
        "id": str(uuid.uuid4()),
        "dataset_version": "test",
        "split": "train",
        "phase": "opening",
        "position_type": "quiet",
        "fen": board.fen(),
        "pgn_prefix": clean_prefix(board),
        "last_move_uci": "e8g8",
        "last_move_san": "O-O",
        "source": "lichess_game",
        "source_game_id": "Test0001",
        "source_ply": 16,
        "position_key": position_key(board),
        "metadata": {},
    }


def test_history_represents_position_after_opponent_move(position):
    board = validate_position(position)
    assert board.turn == chess.WHITE
    assert board.piece_at(chess.G8) == chess.Piece(chess.KING, chess.BLACK)
    assert position["last_move_uci"] not in {move.uci() for move in board.legal_moves}


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("fen", chess.STARTING_FEN, "FEN does not match"),
        ("last_move_uci", "d7d6", "Last move"),
        ("last_move_san", "d6", "Last move"),
        ("source_ply", 15, "Source ply"),
        ("phase", "middlegame", "phase classification"),
    ],
)
def test_reject_inconsistent_history(position, field, value, error):
    position[field] = value
    with pytest.raises(ValueError, match=error):
        validate_position(position)


@pytest.mark.parametrize(
    "leak",
    [
        lambda pgn: pgn.replace('[Result "*"]', '[Result "1-0"]'),
        lambda pgn: pgn.replace("1. e4", "1. e4 { [%eval 0.3] }"),
        lambda pgn: pgn.replace("1. e4", "1. e4 (1. d4)"),
        lambda pgn: pgn.rstrip("*") + " 9. h3 *",
    ],
)
def test_reject_answers_annotations_and_future_moves(position, leak):
    position["pgn_prefix"] = leak(position["pgn_prefix"])
    with pytest.raises(ValueError):
        validate_position(position)


def test_duplicate_identity_ignores_clocks_but_keeps_castling_and_turn():
    board = chess.Board()
    key = position_key(board)
    board.fullmove_number = 32
    board.halfmove_clock = 8
    assert position_key(board) == key
    board.castling_rights = 0
    assert position_key(board) != key
    board = chess.Board()
    board.turn = chess.BLACK
    assert position_key(board) != key


@pytest.mark.parametrize("duplicate", ["game", "board"])
def test_train_test_overlap_is_rejected(position, duplicate):
    other = copy.deepcopy(position)
    other.update(id=str(uuid.uuid4()), split="test")
    if duplicate == "board":
        other["source_game_id"] = "Test0002"
    with pytest.raises(
        ValueError, match="Duplicate source game|Duplicate board position"
    ):
        validate_collection([position, other], "test")


def test_multipv_uses_complete_depth_before_partial_search():
    def info(depth, index, uci, **kwargs):
        return {
            "depth": depth,
            "multipv": index,
            "pv": [chess.Move.from_uci(uci)],
            "score": chess.engine.PovScore(chess.engine.Cp(10), chess.WHITE),
            **kwargs,
        }

    complete = [info(10, i, move) for i, move in enumerate(["e2e4", "d2d4", "g1f3"], 1)]
    interrupted = [
        info(11, 1, "g1f3", lowerbound=True),
        info(11, 1, "g1f3"),
        info(11, 2, "d2d4"),
    ]
    assert complete_variations(iter(complete + interrupted), 3) == complete


@pytest.fixture(scope="module")
def frozen():
    rows, manifest, report = load_collection(SEED)
    return rows, manifest, report, load_evaluations(SEED, manifest, rows)


def test_frozen_pilot_has_exact_disjoint_balanced_sets_and_legal_references(frozen):
    rows, _, report, evaluations = frozen
    assert (
        report["positions"] == report["unique_games"] == report["unique_boards"] == 400
    )
    assert report["reference_evaluations"] == 400
    references = {item["position_id"]: item for item in evaluations}
    for row in rows:
        reference = references[row["id"]]
        assert len({pv["depth"] for pv in reference["payload"]["pvs"]}) == 1
        if row["position_type"] == "quiet":
            assert quiet_rejection(reference["payload"]) is None
            assert row["metadata"]["difficulty_rating"] is None
            assert (
                abs(
                    reference["best_score_cp"]
                    - reference["payload"]["screening"]["quick_best_cp"]
                )
                <= 40
            )
        else:
            assert (
                reference["best_move_uci"]
                == reference["payload"]["screening"]["source_solution_first_move"]
            )


def test_reference_checksum_is_enforced(tmp_path, frozen):
    rows, manifest, _, _ = frozen
    (tmp_path / "evaluations.jsonl").write_text("{}\n")
    with pytest.raises(ValueError, match="checksum"):
        load_evaluations(tmp_path, manifest, rows)


def test_reference_illegal_pv_is_rejected_even_with_matching_checksum(tmp_path, frozen):
    rows, manifest, _, evaluations = copy.deepcopy(frozen)
    evaluations[0]["payload"]["pvs"][0]["moves_uci"].append("0000")
    evaluations[0]["payload"]["pvs"][0]["moves_san"].append("--")
    payload = ("\n".join(json.dumps(item) for item in evaluations) + "\n").encode()
    (tmp_path / "evaluations.jsonl").write_bytes(payload)
    manifest["evaluations_sha256"] = hashlib.sha256(payload).hexdigest()
    with pytest.raises(ValueError, match="illegal move"):
        load_evaluations(tmp_path, manifest, rows)


def test_postgres_import_is_idempotent_and_version_is_frozen(postgres, tmp_path):
    result = postgres.import_collection(SEED)
    assert result["imported"] == 400
    assert postgres.import_collection(SEED)["status"] == "already_present"
    assert sum(row["positions"] for row in postgres.summary()) == 400
    for name in ("positions.jsonl", "evaluations.jsonl", "manifest.json"):
        (tmp_path / name).write_bytes((SEED / name).read_bytes())
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["seed"] += 1
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="already frozen"):
        postgres.import_collection(tmp_path)
    with postgres.connect() as conn:
        conn.execute(
            "UPDATE positions SET last_move_san = 'corrupted' WHERE id = (SELECT id FROM positions LIMIT 1)"
        )
    with pytest.raises(ValueError, match="content differs"):
        postgres.import_collection(SEED)


def test_postgres_failed_import_rolls_back_entire_dataset(postgres):
    import psycopg

    with postgres.connect() as conn:
        conn.execute(postgres.SCHEMA.read_text())
        conn.execute(
            "ALTER TABLE positions ADD CONSTRAINT fail_during_import CHECK (split = 'train')"
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        postgres.import_collection(SEED)
    with postgres.connect() as conn:
        for table in ("position_datasets", "positions", "position_evaluations"):
            assert (
                conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0
            )


def test_run_history_roundtrip_with_real_postgres_and_native_passes(
    postgres, monkeypatch
):
    import chess
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.matches.catalog import AGENT_PLAYER_3_ID, HarnessCatalog
    from app.matches.repository import MatchRepository

    monkeypatch.setenv("POSITION_EVAL_NODES_PER_MOVE", "20000")
    postgres.import_collection(SEED)
    position = postgres.list_position_rows()[0]
    legacy_run_id = uuid.uuid4()
    with postgres.connect() as conn:
        # Exercise additive migration against a volume predating these columns.
        conn.execute(
            "ALTER TABLE model_runs DROP COLUMN expected_points_loss, DROP COLUMN better_moves"
        )
        conn.execute(
            "INSERT INTO model_runs (id, position_id, model, harness, status) VALUES (%s, %s, 'legacy', 'legacy', 'completed')",
            (legacy_run_id, position["id"]),
        )
    board = chess.Board(position["fen"])
    move = board.san(next(iter(board.legal_moves)))
    board.push_san(move)
    reply = board.san(next(iter(board.legal_moves)))

    def action(tool, **arguments):
        return {"tool": tool, "arguments": arguments}

    batches = [
        (
            f"Test {move} from the saved board, then inspect the opponent reply.",
            [action("scratch_play_move", move=move)],
        ),
        (
            f"Branch B1 contains {move}. Annotate it before testing {reply}.",
            [
                action(
                    "annotate_branch",
                    branch_id="B1",
                    annotation="Opponent reply to be checked.",
                ),
                action("scratch_play_move", move=reply),
            ],
        ),
        (
            f"The branch now contains {move} {reply}. Submit the candidate from the original board.",
            [
                action(
                    "annotate_branch",
                    branch_id="B1.1",
                    annotation="Opponent reply recorded on the scratch board.",
                ),
                action(
                    "submit_move",
                    move=move,
                    tested_branch="B1",
                    decision_summary="The chosen move has been checked against a legal opponent reply.",
                ),
            ],
        ),
    ]

    class OfflineModel:
        def __init__(self):
            self.passes = iter(enumerate(batches, 1))

        async def complete(self, **kwargs):
            number, (notes, actions) = next(self.passes)
            return {
                "status": "completed",
                "output": [
                    {
                        "type": "function_call",
                        "name": "agent_step",
                        "call_id": f"pass-{number}",
                        "arguments": json.dumps(
                            {"running_thoughts": notes, "tool_calls": actions}
                        ),
                    }
                ],
            }

    async def resolve():
        return "offline-verification"

    catalog = HarnessCatalog(OfflineModel(), model_resolver=resolve)
    repository = MatchRepository(":memory:")
    app = create_app(repository=repository, catalog=catalog)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/positional-testing/runs",
                json={
                    "positionId": str(position["id"]),
                    "harnessId": AGENT_PLAYER_3_ID,
                },
            )
            assert response.status_code == 200, response.text
            run_id = response.json()["runId"]
            detail_response = client.get(f"/api/positional-testing/runs/{run_id}")
            assert detail_response.status_code == 200, detail_response.text
            detail = detail_response.json()
            assert detail["finalMoveUci"] == response.json()["move"]["uci"]
            assert detail["status"] == "completed"
            assert detail["evaluation"]["status"] == "completed", detail["evaluation"]
            assert detail["classification"] in {
                "best",
                "excellent",
                "good",
                "inaccuracy",
                "mistake",
                "blunder",
            }
            assert 0 <= detail["expectedPointsLoss"] <= 1
            assert isinstance(detail["betterMoves"], list)
            assert all(
                m["expected_points_loss"] < detail["expectedPointsLoss"]
                for m in detail["betterMoves"]
            )
            assert [len(p["toolCalls"]) for p in detail["passes"]] == [1, 2, 2]
            assert [p["workingNotes"] for p in detail["passes"]] == [
                b[0] for b in batches
            ]
            assert all(p["finishedAt"] for p in detail["passes"])
            assert all(
                c["result"] is not None
                for p in detail["passes"]
                for c in p["toolCalls"]
            )
            query = client.get(
                "/api/positional-testing/runs",
                params={"position_id": str(position["id"]), "run_id": run_id},
            )
            assert query.status_code == 200
            assert query.json()["total"] == 1
            assert "passes" not in query.json()["items"][0]
            assert (
                client.get(
                    "/api/positional-testing/runs",
                    params={"position_id": str(uuid.uuid4()), "run_id": run_id},
                ).json()["total"]
                == 0
            )
            assert (
                client.get(
                    "/api/positional-testing/runs", params={"run_id": "invalid"}
                ).status_code
                == 422
            )
            assert (
                client.get(f"/api/positional-testing/runs/{uuid.uuid4()}").status_code
                == 404
            )
            # Reopening the repository reads persisted history, including ordered passes.
            from positional_testing.run_repository import RunRepository

            assert len(RunRepository().get(run_id)["passes"]) == 3
            legacy = RunRepository().get(legacy_run_id)
            assert legacy["expected_points_loss"] is None
            assert legacy["better_moves"] is None
            assert legacy["classification"] is None
            assert legacy["evaluation"] is None
            output = Path(".test-data/run-history-fixture.json")
            output.parent.mkdir(exist_ok=True)
            output.write_text(json.dumps(detail, indent=2))
    finally:
        repository.close()

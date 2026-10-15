from pathlib import Path
from uuid import uuid4

from psycopg.types.json import Jsonb

SEED = Path(__file__).resolve().parents[2] / "positional_testing/datasets/seed/v1"


def test_saved_run_names_migrate_without_changing_exchanges_or_queue(postgres):
    postgres.import_collection(SEED)
    expected_names = {}
    with postgres.connect() as conn:
        position_id = conn.execute("SELECT id FROM positions LIMIT 1").fetchone()["id"]
        for harness_id, old_name, name in (
            ("agent-player-1-langgraph-v1", "Agent Player 1", "legacy"),
            ("agent-player-2-langgraph-v1", "Agent Player 2", "chess_harness"),
            ("agent-player-3-langgraph-v1", "Agent Player 3", "chess_charness_alt"),
            ("custom-harness", "Agent Player 2", "Agent Player 2"),
        ):
            run_id = uuid4()
            expected_names[run_id] = name
            conn.execute(
                "INSERT INTO model_runs "
                "(id, position_id, queue_tag, model, harness, config, status) "
                "VALUES (%s, %s, %s, 'original-model', %s, %s, 'completed')",
                (
                    run_id,
                    position_id,
                    uuid4(),
                    harness_id,
                    Jsonb(
                        {
                            "harness_name": old_name,
                            "harness_version": harness_id,
                            "queue": {"name": "Original queue name"},
                            "notes": old_name,
                        }
                    ),
                ),
            )
            conn.execute(
                "INSERT INTO model_run_passes "
                "(run_id, pass_number, phase, status, started_at, "
                "working_notes, model_input, model_output) "
                "VALUES (%s, 1, 'synthesis', 'completed', now(), %s, %s, %s)",
                (
                    run_id,
                    old_name,
                    Jsonb({"input": old_name}),
                    Jsonb({"output": old_name}),
                ),
            )
        before_runs = conn.execute("SELECT * FROM model_runs ORDER BY id").fetchall()
        before_passes = conn.execute(
            "SELECT * FROM model_run_passes ORDER BY run_id"
        ).fetchall()
        before_positions = conn.execute(
            "SELECT * FROM positions ORDER BY id"
        ).fetchall()

    for _ in range(2):
        with postgres.connect() as conn:
            postgres.ensure_schema(conn)
            after_runs = conn.execute("SELECT * FROM model_runs ORDER BY id").fetchall()
            assert after_runs == [
                {
                    **row,
                    "config": {
                        **row["config"],
                        "harness_name": expected_names[row["id"]],
                    },
                }
                for row in before_runs
            ]
            assert (
                conn.execute(
                    "SELECT * FROM model_run_passes ORDER BY run_id"
                ).fetchall()
                == before_passes
            )
            assert (
                conn.execute("SELECT * FROM positions ORDER BY id").fetchall()
                == before_positions
            )

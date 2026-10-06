import hashlib
import json
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from positional_testing.datasets.validation import load_collection, load_evaluations
from positional_testing.queue_repository import QueueRepository

SEED = Path(__file__).resolve().parents[2] / "positional_testing/datasets/seed/v1"
LEGACY_SCHEMA = Path(__file__).with_name("fixtures") / "legacy_schema.sql"


@pytest.fixture
def legacy_database(postgres):
    rows, manifest, _ = load_collection(SEED)
    evaluations = load_evaluations(SEED, manifest, rows)
    digest = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with postgres.connect() as conn:
        conn.execute(LEGACY_SCHEMA.read_text())
        conn.execute(
            "INSERT INTO position_datasets "
            "(version,description,seed,position_count,content_sha256,manifest) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (
                manifest["version"],
                manifest["description"],
                manifest["seed"],
                len(rows),
                digest,
                Jsonb(manifest),
            ),
        )
        with conn.cursor() as cursor:
            for table, fields, data, json_field in (
                ("positions", postgres.POSITION_FIELDS, rows, "metadata"),
                (
                    "position_evaluations",
                    postgres.EVALUATION_FIELDS,
                    evaluations,
                    "payload",
                ),
            ):
                cursor.executemany(
                    f"INSERT INTO {table} ({', '.join(fields)}) "
                    f"VALUES ({', '.join(['%s'] * len(fields))})",
                    [
                        tuple(
                            Jsonb(row[f]) if f == json_field else row[f] for f in fields
                        )
                        for row in data
                    ],
                )
    return postgres, rows, manifest, evaluations


@pytest.mark.parametrize("queue_status", ["running", "stopping"])
def test_migration_preserves_content_and_pending_queue_membership(
    legacy_database, queue_status
):
    store, positions, manifest, evaluations = legacy_database
    tag = uuid4()
    run_ids = [uuid4() for _ in range(4)]
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO position_run_queues "
            "(id,dataset_version,split,harness_id,harness_name,harness_version,model_selection,status) "
            "VALUES (%s,'v1','train','test-harness','Test harness','v1',%s,%s)",
            (
                tag,
                Jsonb({"model_id": "qwen", "reasoning_effort": "medium"}),
                queue_status,
            ),
        )
        for index, run_id in enumerate(run_ids):
            conn.execute(
                "INSERT INTO model_runs "
                "(id,position_id,model,harness,config,status,final_move_uci,"
                "classification,cp_loss,expected_points_loss,better_moves,evaluation,error,finished_at) "
                "VALUES (%s,%s,'saved-model','test-harness',%s,%s,%s,%s,%s,%s,%s,%s,%s,now())",
                (
                    run_id,
                    positions[index]["id"],
                    Jsonb({"original": "keep me"}),
                    "failed" if index == 1 else "completed",
                    None if index == 1 else "e2e4",
                    "excellent" if index == 0 else None,
                    5 if index == 0 else None,
                    0.01 if index == 0 else None,
                    Jsonb([{"move_uci": "d2d4", "expected_points_loss": 0}])
                    if index == 0
                    else None,
                    Jsonb({"status": "failed", "error": "Engine failed"})
                    if index == 2
                    else Jsonb({"status": "completed"})
                    if index == 0
                    else None,
                    "Provider failed" if index == 1 else None,
                ),
            )
        for index, state in enumerate(
            ["completed", "failed", "failed", "queued", "running", "skipped"]
        ):
            conn.execute(
                "INSERT INTO position_run_queue_items "
                "(queue_id,ordinal,position_id,run_id,status,failure_stage,error) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (
                    tag,
                    index + 1,
                    positions[index]["id"],
                    run_ids[index] if index < 3 else None,
                    state,
                    "execution" if index == 1 else "evaluation" if index == 2 else None,
                    "Provider failed"
                    if index == 1
                    else "Engine failed"
                    if index == 2
                    else None,
                ),
            )
        conn.execute(
            "INSERT INTO model_run_passes "
            "(run_id,pass_number,phase,tool_calls,working_notes,status,started_at,finished_at) "
            "VALUES (%s,1,'synthesis',%s,'Keep these working notes exactly.','completed',now(),now())",
            (
                run_ids[0],
                Jsonb(
                    [
                        {
                            "tool_name": "scratch_play_move",
                            "arguments": {"move": "e4"},
                            "result": {"branch_id": "B1"},
                            "executed": True,
                        }
                    ]
                ),
            ),
        )
        old_passes = conn.execute("SELECT * FROM model_run_passes").fetchall()
        old_runs = conn.execute("SELECT * FROM model_runs ORDER BY id").fetchall()
        old_references = conn.execute(
            "SELECT to_jsonb(e) AS value FROM position_evaluations e"
        ).fetchall()
        old_dataset = conn.execute(
            "SELECT to_jsonb(d) AS value FROM position_datasets d"
        ).fetchone()["value"]
        old_positions = conn.execute("SELECT * FROM positions ORDER BY id").fetchall()

    with store.connect() as conn:
        store.ensure_schema(conn)
    with store.connect() as conn:
        store.ensure_schema(conn)  # Repeat safely after upgrade.
        tables = {
            r["tablename"]
            for r in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname=current_schema()"
            )
        }
        assert tables == {"positions", "model_runs", "model_run_passes"}
        assert conn.execute("SELECT * FROM model_run_passes").fetchall() == old_passes
        assert conn.execute("SELECT count(*) AS n FROM model_runs").fetchone()["n"] == 7
        new_positions = conn.execute("SELECT * FROM positions ORDER BY id").fetchall()
        for before, after in zip(old_positions, new_positions, strict=True):
            for field in (*store.CORE_FIELDS, "created_at"):
                assert before[field] == after[field]
            assert after["metadata"]["provenance"] == {
                f: before[f] for f in store.PROVENANCE_FIELDS
            }
            assert after["metadata"]["dataset"] == old_dataset
            assert {
                k: v
                for k, v in after["metadata"].items()
                if k not in {"provenance", "dataset", "reference_evaluations"}
            } == before["metadata"]
        archived_references = [
            ref
            for row in new_positions
            for ref in row["metadata"]["reference_evaluations"]
        ]

        def key(row):
            return row["position_id"], row["analysis_id"]

        assert sorted(archived_references, key=key) == sorted(
            [r["value"] for r in old_references], key=key
        )
        for before in old_runs:
            after = conn.execute(
                "SELECT * FROM model_runs WHERE id=%s", (before["id"],)
            ).fetchone()
            for field in (
                "id",
                "position_id",
                "model",
                "harness",
                "final_move_uci",
                "classification",
                "cp_loss",
                "expected_points_loss",
                "better_moves",
                "evaluation",
                "started_at",
                "finished_at",
            ):
                assert before[field] == after[field]
            assert after["config"]["original"] == "keep me"
            assert after["queue_tag"] == (None if before["id"] == run_ids[3] else tag)
        store.verify_stored_content(conn, positions, evaluations, manifest["version"])

    assert store.import_collection(SEED)["status"] == "already_present"
    queue = QueueRepository().get_queue(tag)
    assert queue["total"] == 6
    assert queue["completed"] == 1 and queue["failed"] == 2 and queue["running"] == 1
    assert queue["pending"] == (1 if queue_status == "running" else 0)
    assert queue["skipped"] == (1 if queue_status == "running" else 2)
    assert queue["items"][2]["failure_stage"] == "evaluation"
    assert all(
        "reference_evaluations" not in p["metadata"] for p in store.list_position_rows()
    )
    assert "dataset" not in store.get_position_row(positions[0]["id"])["metadata"]


def test_unexpected_dependency_rolls_back_entire_migration(legacy_database):
    store, _, _, _ = legacy_database
    with store.connect() as conn:
        conn.execute(
            "CREATE TABLE migration_guard (version text REFERENCES position_datasets(version))"
        )
    with pytest.raises(psycopg.errors.DependentObjectsStillExist):
        with store.connect() as conn:
            store.ensure_schema(conn)
    with store.connect() as conn:
        assert (
            conn.execute("SELECT count(*) AS n FROM position_datasets").fetchone()["n"]
            == 1
        )
        assert (
            conn.execute("SELECT count(*) AS n FROM positions").fetchone()["n"] == 400
        )
        assert "source" in conn.execute("SELECT * FROM positions LIMIT 1").fetchone()
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM information_schema.columns WHERE table_schema=current_schema() "
                "AND table_name='model_runs' AND column_name='queue_tag'"
            ).fetchone()["n"]
            == 0
        )

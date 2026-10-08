"""Durable positional attempts and one aggregate row per model pass."""

from contextlib import contextmanager
from threading import Lock

import psycopg
from psycopg.types.json import Jsonb

from .catalog import PositionLibraryUnavailableError
from .datasets import store

RUN_SOURCE = " FROM model_runs r JOIN positions p ON p.id = r.position_id"
DATASET = "coalesce(r.config->'queue'->>'dataset_version', p.dataset_version)"
SPLIT = "coalesce(r.config->'queue'->>'split', p.split)"
ANALYSIS = """CASE
    WHEN r.evaluation->>'status' = 'completed' THEN 'completed'
    WHEN r.evaluation->>'status' = 'failed' OR r.failure_stage = 'evaluation' THEN 'failed'
    ELSE 'missing' END"""
RUN_COLUMNS = (
    "r.*, p.fen AS position_fen, p.phase, p.position_type, "
    "r.config->'queue'->>'name' AS queue_name, "
    f"{DATASET} AS dataset_version, {SPLIT} AS split, {ANALYSIS} AS analysis_status"
)


class RunDeletionConflictError(ValueError):
    """An active attempt must finish before its saved history can be removed."""


def lock_state(conn):
    # Enqueue, claim, stop and delete must agree on which attempts are active.
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ':position-queue-state', 0))"
    )


class RunRepository:
    def __init__(self):
        self._ready = False
        self._schema_lock = Lock()

    @contextmanager
    def connection(self):
        try:
            # Existing Docker volumes receive the transactional three-table upgrade.
            with self._schema_lock:
                if not self._ready:
                    with store.connect() as conn:
                        store.ensure_schema(conn)
                    self._ready = True
            with store.connect() as conn:
                yield conn
        except psycopg.Error as exc:
            raise PositionLibraryUnavailableError(
                "Run history is unavailable. Check the positions database and retry."
            ) from exc

    def delete_run(self, run_id):
        with self.connection() as conn:
            lock_state(conn)
            row = conn.execute(
                "SELECT status FROM model_runs WHERE id = %s FOR UPDATE", (run_id,)
            ).fetchone()
            if row is None:
                return False
            if row["status"] in {"queued", "running"}:
                raise RunDeletionConflictError(
                    "This run is still active. Wait for it to finish, or stop its "
                    "queue in Positional testing and wait for the current run to finish."
                )
            # Saved passes cascade; the source position and other attempts remain.
            conn.execute("DELETE FROM model_runs WHERE id = %s", (run_id,))
            return True

    def create(self, run_id, position_id, model, harness, config):
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO model_runs "
                "(id, position_id, model, harness, config, status, started_at) "
                "VALUES (%s, %s, %s, %s, %s, 'running', now())",
                (
                    run_id,
                    position_id,
                    model,
                    harness,
                    Jsonb(config),
                ),
            )

    def configure(self, run_id, model, config):
        with self.connection() as conn:
            conn.execute(
                "UPDATE model_runs SET model = %s, config = config || %s WHERE id = %s",
                (model, Jsonb(config), run_id),
            )

    def finish(self, run_id, *, move=None, error=None, grade=None):
        grade = grade or {}
        failure_stage = "execution" if error else None
        if grade.get("evaluation", {}).get("status") == "failed":
            failure_stage = "evaluation"
            error = error or grade["evaluation"].get("error") or "Evaluation failed."
        with self.connection() as conn:
            conn.execute(
                "UPDATE model_runs SET status = %s, final_move_uci = %s, error = %s, "
                "classification = %s, cp_loss = %s, expected_points_loss = %s, "
                "better_moves = %s, evaluation = %s, failure_stage = %s, "
                "finished_at = now() WHERE id = %s",
                (
                    "failed" if error else "completed",
                    move,
                    error,
                    grade.get("classification"),
                    grade.get("cp_loss"),
                    grade.get("expected_points_loss"),
                    Jsonb(grade["better_moves"]) if "better_moves" in grade else None,
                    Jsonb(grade["evaluation"]) if "evaluation" in grade else None,
                    failure_stage,
                    run_id,
                ),
            )

    def save_move(self, run_id, move):
        """Retain the model's answer before starting potentially slow evaluation."""
        with self.connection() as conn:
            conn.execute(
                "UPDATE model_runs SET final_move_uci = %s WHERE id = %s",
                (move, run_id),
            )

    def save_pass(self, row):
        fields = tuple(row)
        values = tuple(Jsonb(row[k]) if k == "tool_calls" else row[k] for k in fields)
        # All field names are supplied by the recorder, never by HTTP input.
        with self.connection() as conn:
            conn.execute(
                f"INSERT INTO model_run_passes ({', '.join(fields)}) "
                f"VALUES ({', '.join(['%s'] * len(fields))}) "
                "ON CONFLICT (run_id, pass_number) DO UPDATE SET "
                + ", ".join(
                    f"{k} = EXCLUDED.{k}"
                    for k in fields
                    if k not in {"run_id", "pass_number", "started_at"}
                ),
                values,
            )

    def save_pass_exchange(
        self, run_id, pass_number, *, model_input=None, model_output=None
    ):
        """Write each snapshot once; subsequent tool/pass updates never copy or replace it."""
        with self.connection() as conn:
            conn.execute(
                "UPDATE model_run_passes SET "
                "model_input = coalesce(model_input, %s), "
                "model_output = coalesce(model_output, %s) "
                "WHERE run_id = %s AND pass_number = %s",
                (
                    Jsonb(model_input) if model_input is not None else None,
                    Jsonb(model_output) if model_output is not None else None,
                    run_id,
                    pass_number,
                ),
            )

    def get_pass_exchange(self, run_id, pass_number):
        with self.connection() as conn:
            return conn.execute(
                "SELECT model_input, model_output FROM model_run_passes "
                "WHERE run_id = %s AND pass_number = %s",
                (run_id, pass_number),
            ).fetchone()

    def list(
        self,
        position_id=None,
        run_id=None,
        *,
        queue_tag=None,
        limit=30,
        offset=0,
        split=None,
        dataset_version=None,
        harness=None,
        model=None,
        status=None,
        analysis=None,
        classification=None,
        run_source=None,
        query=None,
        sort="newest",
    ):
        clauses, args = [], []
        for column, value in (
            ("r.position_id", position_id),
            ("r.id", run_id),
            ("r.queue_tag", queue_tag),
            (SPLIT, split),
            (DATASET, dataset_version),
            ("r.harness", harness),
            ("r.model", model),
            ("r.status", status),
            (ANALYSIS, analysis),
            ("r.classification", classification),
        ):
            if value:
                clauses.append(f"{column} = %s")
                args.append(value)
        if run_source == "single":
            clauses.append("r.queue_tag IS NULL")
        elif run_source == "queue":
            clauses.append("r.queue_tag IS NOT NULL")
        if query and query.strip():
            # Treat search literally, including SQL wildcard characters.
            needle = (
                query.strip()
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            clauses.append(
                "concat_ws(' ', r.id, r.position_id, r.queue_tag, r.model, "
                "r.harness, r.config->>'harness_name', r.config->'queue'->>'name', p.phase) ILIKE %s"
            )
            args.append(f"%{needle}%")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        direction = "ASC" if sort == "oldest" else "DESC"
        with self.connection() as conn:
            total = conn.execute(
                "SELECT count(*) AS n" + RUN_SOURCE + where, args
            ).fetchone()["n"]
            items = conn.execute(
                "SELECT "
                + RUN_COLUMNS
                + RUN_SOURCE
                + where
                + f" ORDER BY r.created_at {direction}, r.id {direction} LIMIT %s OFFSET %s",
                [*args, limit, offset],
            ).fetchall()
        return items, total

    def get(self, run_id):
        with self.connection() as conn:
            row = conn.execute(
                "SELECT " + RUN_COLUMNS + RUN_SOURCE + " WHERE r.id = %s", (run_id,)
            ).fetchone()
            if row is None:
                return None
            passes = conn.execute(
                "SELECT run_id, pass_number, phase, tool_calls, working_notes, status, "
                "error, started_at, finished_at, (model_input IS NOT NULL) AS has_model_exchange "
                "FROM model_run_passes WHERE run_id = %s ORDER BY pass_number",
                (run_id,),
            ).fetchall()
        return {**row, "passes": passes}

    def filter_options(self):
        """Build options from the entire saved history, including retired harnesses."""
        with self.connection() as conn:
            datasets = conn.execute(
                f"SELECT DISTINCT {DATASET} AS value" + RUN_SOURCE + " ORDER BY value"
            ).fetchall()
            models = conn.execute(
                "SELECT DISTINCT model FROM model_runs ORDER BY model"
            ).fetchall()
            harnesses = conn.execute(
                "SELECT harness AS id, coalesce(max(config->>'harness_name'), harness) AS name "
                "FROM model_runs GROUP BY harness ORDER BY name, id"
            ).fetchall()
            queues = conn.execute(
                f"SELECT r.queue_tag AS id, min({DATASET}) AS dataset_version, "
                "min(r.config->'queue'->>'name') AS name, "
                f"min({SPLIT}) AS split, "
                "coalesce(max(r.config->>'harness_name'), min(r.harness)) AS harness_name, "
                "min(r.created_at) AS created_at"
                + RUN_SOURCE
                + " WHERE r.queue_tag IS NOT NULL GROUP BY r.queue_tag ORDER BY created_at DESC, id DESC"
            ).fetchall()
        return dict(
            datasets=[r["value"] for r in datasets],
            models=[r["model"] for r in models],
            harnesses=harnesses,
            queues=queues,
        )

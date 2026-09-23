"""PostgreSQL queue membership, progress, and failure records."""

from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from .catalog import PositionLibraryUnavailableError
from .datasets import store
from .run_repository import RunRepository

ACTIVE = "('queued', 'running', 'stopping')"
COUNTS = """
    SELECT q.*,
        count(*)::int AS total,
        count(*) FILTER (WHERE i.status = 'completed')::int AS completed,
        count(*) FILTER (WHERE i.status = 'failed')::int AS failed,
        count(*) FILTER (WHERE i.status = 'queued')::int AS pending,
        count(*) FILTER (WHERE i.status = 'running')::int AS running,
        count(*) FILTER (WHERE i.status = 'skipped')::int AS skipped
    FROM position_run_queues q JOIN position_run_queue_items i ON i.queue_id = q.id
"""


class QueueConflictError(ValueError):
    pass


class EmptyPositionSetError(ValueError):
    pass


class QueueRepository(RunRepository):
    def enqueue(self, *, dataset_version, split, definition, model_selection):
        queue_id = str(uuid4())
        try:
            with self.connection() as conn:
                positions = conn.execute(
                    "SELECT id FROM positions WHERE dataset_version = %s AND split = %s "
                    "ORDER BY id",
                    (dataset_version, split),
                ).fetchall()
                if not positions:
                    raise EmptyPositionSetError(
                        "This dataset has no positions in that set."
                    )
                conn.execute(
                    "INSERT INTO position_run_queues "
                    "(id, dataset_version, split, harness_id, harness_name, harness_version, "
                    "model_selection, status) VALUES (%s,%s,%s,%s,%s,%s,%s,'queued')",
                    (
                        queue_id,
                        dataset_version,
                        split,
                        definition.id,
                        definition.name,
                        definition.version,
                        Jsonb(model_selection.model_dump(mode="json")),
                    ),
                )
                with conn.cursor() as cursor:
                    cursor.executemany(
                        "INSERT INTO position_run_queue_items "
                        "(queue_id, ordinal, position_id, status) VALUES (%s,%s,%s,'queued')",
                        [
                            (queue_id, ordinal, row["id"])
                            for ordinal, row in enumerate(positions, 1)
                        ],
                    )
        except PositionLibraryUnavailableError as exc:
            if isinstance(exc.__cause__, psycopg.errors.UniqueViolation):
                raise QueueConflictError(
                    "A queue is already active. Wait for it to finish or stop it first."
                ) from exc
            raise
        return self.get_queue(queue_id)

    def list_queues(self, limit=20):
        with self.connection() as conn:
            return conn.execute(
                COUNTS
                + " GROUP BY q.id ORDER BY q.created_at DESC, q.id DESC LIMIT %s",
                (limit,),
            ).fetchall()

    def get_queue(self, queue_id):
        with self.connection() as conn:
            row = conn.execute(
                COUNTS + " WHERE q.id = %s GROUP BY q.id", (queue_id,)
            ).fetchone()
            if row is None:
                return None
            items = conn.execute(
                "SELECT i.*, p.phase, p.position_type, r.final_move_uci, r.classification "
                "FROM position_run_queue_items i JOIN positions p ON p.id = i.position_id "
                "LEFT JOIN model_runs r ON r.id = i.run_id "
                "WHERE i.queue_id = %s ORDER BY i.ordinal",
                (queue_id,),
            ).fetchall()
        return {**row, "items": items}

    def stop(self, queue_id):
        with self.connection() as conn:
            conn.execute(
                "UPDATE position_run_queues SET status = 'stopping' "
                f"WHERE id = %s AND status IN {ACTIVE}",
                (queue_id,),
            )
        return self.get_queue(queue_id)

    def acquire_worker(self):
        # A session lock prevents two Uvicorn processes from consuming the same
        # queue. Schema-scoped keys also keep integration tests fully isolated.
        with self.connection():
            pass
        conn = store.connect()
        try:
            conn.commit()
            conn.autocommit = True
            acquired = conn.execute(
                "SELECT pg_try_advisory_lock("
                "hashtextextended(current_schema() || ':position-queue', 0)) AS acquired"
            ).fetchone()["acquired"]
            if acquired:
                return conn
        except BaseException:
            conn.close()
            raise
        conn.close()
        return None

    def recover(self):
        """Only the worker holding the session lock may recover interrupted items."""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT i.*, r.status AS run_status, r.evaluation FROM "
                "position_run_queue_items i LEFT JOIN model_runs r ON r.id = i.run_id "
                "WHERE i.status = 'running'"
            ).fetchall()
            for row in rows:
                evaluation = row["evaluation"] or {}
                complete = (
                    row["run_status"] == "completed"
                    and evaluation.get("status") == "completed"
                )
                error = (
                    None
                    if complete
                    else "Worker interrupted before this position finished."
                )
                if row["run_status"] == "running":
                    conn.execute(
                        "UPDATE model_runs SET status = 'failed', error = %s, finished_at = now() "
                        "WHERE id = %s",
                        (error, row["run_id"]),
                    )
                    conn.execute(
                        "UPDATE model_run_passes SET status = 'failed', error = %s, finished_at = now() "
                        "WHERE run_id = %s AND status = 'running'",
                        (error, row["run_id"]),
                    )
                conn.execute(
                    "UPDATE position_run_queue_items SET status = %s, failure_stage = %s, "
                    "error = %s, finished_at = now() WHERE queue_id = %s AND ordinal = %s",
                    (
                        "completed" if complete else "failed",
                        None if complete else "interrupted",
                        error,
                        row["queue_id"],
                        row["ordinal"],
                    ),
                )

    def claim_next(self):
        with self.connection() as conn:
            queue = conn.execute(
                f"SELECT * FROM position_run_queues WHERE status IN {ACTIVE} FOR UPDATE"
            ).fetchone()
            if queue is None:
                return None
            if queue["status"] == "stopping":
                conn.execute(
                    "UPDATE position_run_queue_items SET status = 'skipped', finished_at = now() "
                    "WHERE queue_id = %s AND status = 'queued'",
                    (queue["id"],),
                )
            item = conn.execute(
                "SELECT * FROM position_run_queue_items WHERE queue_id = %s "
                "AND status = 'queued' ORDER BY ordinal LIMIT 1 FOR UPDATE",
                (queue["id"],),
            ).fetchone()
            if item is None:
                conn.execute(
                    "UPDATE position_run_queues SET status = %s, finished_at = now() WHERE id = %s",
                    (
                        "stopped" if queue["status"] == "stopping" else "completed",
                        queue["id"],
                    ),
                )
                return None
            conn.execute(
                "UPDATE position_run_queues SET status = 'running', started_at = coalesce(started_at, now()) "
                "WHERE id = %s",
                (queue["id"],),
            )
            conn.execute(
                "UPDATE position_run_queue_items SET status = 'running', started_at = now() "
                "WHERE queue_id = %s AND ordinal = %s",
                (queue["id"], item["ordinal"]),
            )
        return queue, item

    def finish_item(self, queue_id, ordinal, *, error=None, failure_stage=None):
        with self.connection() as conn:
            if error:
                # Also close a trace left open by a persistence failure outside
                # the model call. Never overwrite a completed model/evaluation.
                run = conn.execute(
                    "UPDATE model_runs SET status = 'failed', error = %s, finished_at = now() "
                    "WHERE status = 'running' AND id = (SELECT run_id FROM "
                    "position_run_queue_items WHERE queue_id = %s AND ordinal = %s) RETURNING id",
                    (error, queue_id, ordinal),
                ).fetchone()
                if run:
                    conn.execute(
                        "UPDATE model_run_passes SET status = 'failed', error = %s, finished_at = now() "
                        "WHERE run_id = %s AND status = 'running'",
                        (error, run["id"]),
                    )
            conn.execute(
                "UPDATE position_run_queue_items SET status = %s, error = %s, "
                "failure_stage = %s, finished_at = now() "
                "WHERE queue_id = %s AND ordinal = %s AND status = 'running'",
                (
                    "failed" if error else "completed",
                    error,
                    failure_stage,
                    queue_id,
                    ordinal,
                ),
            )

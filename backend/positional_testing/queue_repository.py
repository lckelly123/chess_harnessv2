"""Queue projections and worker coordination over model_runs; no queue tables."""

from uuid import uuid4

from psycopg.types.json import Jsonb

from .datasets import store
from .run_repository import RunRepository

COUNTS = """
    SELECT queue_tag AS id,
        min(config->'queue'->>'dataset_version') AS dataset_version,
        min(config->'queue'->>'split') AS split,
        min(harness) AS harness_id,
        min(config->>'harness_name') AS harness_name,
        min(config->>'harness_version') AS harness_version,
        (jsonb_agg(config->'queue'->'model_selection')->0) AS model_selection,
        min((config->'queue'->>'created_at')::timestamptz) AS created_at,
        min(started_at) AS started_at, max(finished_at) AS finished_at,
        bool_or(coalesce((config->'queue'->>'stop_requested')::boolean, false)) AS stop_requested,
        count(*)::int AS total,
        count(*) FILTER (WHERE status = 'completed')::int AS completed,
        count(*) FILTER (WHERE status = 'failed')::int AS failed,
        count(*) FILTER (WHERE status = 'queued')::int AS pending,
        count(*) FILTER (WHERE status = 'running')::int AS running,
        count(*) FILTER (WHERE status = 'skipped')::int AS skipped
    FROM model_runs WHERE queue_tag IS NOT NULL
"""


class QueueConflictError(ValueError):
    pass


class EmptyPositionSetError(ValueError):
    pass


def queue_summary(row):
    if row is None:
        return None
    stopping = row.pop("stop_requested")
    if row["running"]:
        row["status"] = "stopping" if stopping else "running"
    elif row["pending"]:
        row["status"] = "running" if row["started_at"] else "queued"
    else:
        row["status"] = "stopped" if stopping or row["skipped"] else "completed"
    if row["running"] or row["pending"]:
        row["finished_at"] = None
    return row


def lock_state(conn):
    # Enqueue, claim and stop share this lock so two batches cannot start together.
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ':position-queue-state', 0))"
    )


class QueueRepository(RunRepository):
    def enqueue(self, *, dataset_version, split, definition, model_selection):
        queue_tag = uuid4()
        with self.connection() as conn:
            lock_state(conn)
            if conn.execute(
                "SELECT 1 FROM model_runs WHERE queue_tag IS NOT NULL "
                "AND status IN ('queued', 'running') LIMIT 1"
            ).fetchone():
                raise QueueConflictError(
                    "A queue is already active. Wait for it to finish or stop it first."
                )
            positions = conn.execute(
                "SELECT id FROM positions WHERE dataset_version = %s AND split = %s ORDER BY id",
                (dataset_version, split),
            ).fetchall()
            if not positions:
                raise EmptyPositionSetError(
                    "This dataset has no positions in that set."
                )
            created_at = conn.execute("SELECT now() AS value").fetchone()["value"]
            config = {
                "harness_name": definition.name,
                "harness_version": definition.version,
                "queue": {
                    "dataset_version": dataset_version,
                    "split": split,
                    "model_selection": model_selection.model_dump(mode="json"),
                    "created_at": created_at.isoformat(),
                    "stop_requested": False,
                },
            }
            with conn.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO model_runs "
                    "(id, position_id, queue_tag, model, harness, config, status) "
                    "VALUES (%s,%s,%s,%s,%s,%s,'queued')",
                    [
                        (
                            uuid4(),
                            row["id"],
                            queue_tag,
                            model_selection.model_id,
                            definition.id,
                            Jsonb({**config, "queue_ordinal": ordinal}),
                        )
                        for ordinal, row in enumerate(positions, 1)
                    ],
                )
        return self.get_queue(queue_tag)

    def list_queues(self, limit=20):
        with self.connection() as conn:
            rows = conn.execute(
                COUNTS
                + " GROUP BY queue_tag ORDER BY created_at DESC, id DESC LIMIT %s",
                (limit,),
            ).fetchall()
        return [queue_summary(row) for row in rows]

    def get_queue(self, queue_tag):
        with self.connection() as conn:
            row = queue_summary(
                conn.execute(
                    COUNTS + " AND queue_tag = %s GROUP BY queue_tag", (queue_tag,)
                ).fetchone()
            )
            if row is None:
                return None
            items = conn.execute(
                "SELECT r.queue_tag, (r.config->>'queue_ordinal')::int AS ordinal, "
                "r.position_id, r.id AS run_id, r.status, r.failure_stage, r.error, "
                "r.started_at, r.finished_at, p.phase, p.position_type, "
                "r.final_move_uci, r.classification "
                "FROM model_runs r JOIN positions p ON p.id = r.position_id "
                "WHERE r.queue_tag = %s ORDER BY ordinal",
                (queue_tag,),
            ).fetchall()
        return {**row, "items": items}

    def stop(self, queue_tag):
        with self.connection() as conn:
            lock_state(conn)
            if conn.execute(
                "SELECT 1 FROM model_runs WHERE queue_tag = %s "
                "AND status IN ('queued', 'running') LIMIT 1",
                (queue_tag,),
            ).fetchone():
                conn.execute(
                    "UPDATE model_runs SET config = jsonb_set(config, "
                    "'{queue,stop_requested}', 'true'::jsonb) WHERE queue_tag = %s",
                    (queue_tag,),
                )
                conn.execute(
                    "UPDATE model_runs SET status = 'skipped', finished_at = now() "
                    "WHERE queue_tag = %s AND status = 'queued'",
                    (queue_tag,),
                )
        return self.get_queue(queue_tag)

    def acquire_worker(self):
        # Session lock ensures one consumer; schema scoping isolates integration tests.
        with self.connection():
            pass
        conn = store.connect()
        try:
            conn.commit()
            conn.autocommit = True
            if conn.execute(
                "SELECT pg_try_advisory_lock("
                "hashtextextended(current_schema() || ':position-queue', 0)) AS acquired"
            ).fetchone()["acquired"]:
                return conn
        except BaseException:
            conn.close()
            raise
        conn.close()
        return None

    def recover(self):
        """Only the worker holding the session lock recovers interrupted attempts."""
        with self.connection() as conn:
            rows = conn.execute(
                "UPDATE model_runs SET "
                "status = CASE WHEN evaluation->>'status' = 'completed' THEN 'completed' ELSE 'failed' END, "
                "failure_stage = CASE WHEN evaluation->>'status' = 'completed' THEN NULL ELSE 'interrupted' END, "
                "error = CASE WHEN evaluation->>'status' = 'completed' THEN NULL "
                "ELSE 'Worker interrupted before this position finished.' END, "
                "finished_at = coalesce(finished_at, now()) "
                "WHERE queue_tag IS NOT NULL AND status = 'running' RETURNING id, status, error"
            ).fetchall()
            for row in rows:
                if row["status"] == "failed":
                    conn.execute(
                        "UPDATE model_run_passes SET status = 'failed', error = %s, finished_at = now() "
                        "WHERE run_id = %s AND status = 'running'",
                        (row["error"], row["id"]),
                    )

    def claim_next(self):
        with self.connection() as conn:
            lock_state(conn)
            if conn.execute(
                "SELECT 1 FROM model_runs WHERE queue_tag IS NOT NULL AND status = 'running' LIMIT 1"
            ).fetchone():
                return None
            item = conn.execute(
                "SELECT id AS run_id, position_id, queue_tag, "
                "(config->>'queue_ordinal')::int AS ordinal "
                "FROM model_runs WHERE queue_tag IS NOT NULL AND status = 'queued' "
                "ORDER BY created_at, ordinal, id LIMIT 1 FOR UPDATE"
            ).fetchone()
            if item is None:
                return None
            conn.execute(
                "UPDATE model_runs SET status = 'running', started_at = now() WHERE id = %s",
                (item["run_id"],),
            )
            queue = queue_summary(
                conn.execute(
                    COUNTS + " AND queue_tag = %s GROUP BY queue_tag",
                    (item["queue_tag"],),
                ).fetchone()
            )
        return queue, item

    def finish_item(self, run_id, *, error=None, failure_stage=None):
        with self.connection() as conn:
            row = conn.execute(
                "UPDATE model_runs SET status = %s, error = %s, failure_stage = %s, "
                "finished_at = coalesce(finished_at, now()) "
                "WHERE id = %s AND queue_tag IS NOT NULL "
                "AND status IN ('running', 'failed', 'completed') "
                "AND NOT (status = 'completed' AND coalesce(evaluation->>'status', '') = 'completed') "
                "RETURNING id",
                ("failed" if error else "completed", error, failure_stage, run_id),
            ).fetchone()
            if row and error:
                conn.execute(
                    "UPDATE model_run_passes SET status = 'failed', error = %s, finished_at = now() "
                    "WHERE run_id = %s AND status = 'running'",
                    (error, run_id),
                )

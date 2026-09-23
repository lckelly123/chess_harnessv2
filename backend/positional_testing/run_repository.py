"""Durable positional attempts and one aggregate row per model pass."""

from contextlib import contextmanager
from threading import Lock

import psycopg
from psycopg.types.json import Jsonb

from .catalog import PositionLibraryUnavailableError
from .datasets import store


class RunRepository:
    def __init__(self):
        self._ready = False
        self._schema_lock = Lock()

    @contextmanager
    def connection(self):
        try:
            # Existing Docker volumes also receive the additive migration.
            with self._schema_lock:
                if not self._ready:
                    with store.connect() as conn:
                        conn.execute(store.SCHEMA.read_text(encoding="utf-8"))
                    self._ready = True
            with store.connect() as conn:
                yield conn
        except psycopg.Error as exc:
            raise PositionLibraryUnavailableError(
                "Run history is unavailable. Check the positions database and retry."
            ) from exc

    def create(self, run_id, position_id, model, harness, config, *, queue_item=None):
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO model_runs (id, position_id, model, harness, config, status) "
                "VALUES (%s, %s, %s, %s, %s, 'running')",
                (run_id, position_id, model, harness, Jsonb(config)),
            )
            if queue_item is not None:
                linked = conn.execute(
                    "UPDATE position_run_queue_items SET run_id = %s "
                    "WHERE queue_id = %s AND ordinal = %s AND position_id = %s "
                    "AND status = 'running' AND run_id IS NULL",
                    (run_id, *queue_item, position_id),
                )
                if linked.rowcount != 1:
                    raise ValueError("Queue item is no longer available for this run.")

    def configure(self, run_id, model, config):
        with self.connection() as conn:
            conn.execute(
                "UPDATE model_runs SET model = %s, config = %s WHERE id = %s",
                (model, Jsonb(config), run_id),
            )

    def finish(self, run_id, *, move=None, error=None, grade=None):
        grade = grade or {}
        with self.connection() as conn:
            conn.execute(
                "UPDATE model_runs SET status = %s, final_move_uci = %s, error = %s, "
                "classification = %s, cp_loss = %s, expected_points_loss = %s, "
                "better_moves = %s, evaluation = %s, finished_at = now() WHERE id = %s",
                (
                    "failed" if error else "completed",
                    move,
                    error,
                    grade.get("classification"),
                    grade.get("cp_loss"),
                    grade.get("expected_points_loss"),
                    Jsonb(grade["better_moves"]) if "better_moves" in grade else None,
                    Jsonb(grade["evaluation"]) if "evaluation" in grade else None,
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

    def list(self, position_id=None, run_id=None, *, limit=30, offset=0):
        clauses, args = [], []
        if position_id:
            clauses.append("position_id = %s")
            args.append(position_id)
        if run_id:
            clauses.append("id = %s")
            args.append(run_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connection() as conn:
            total = conn.execute(
                "SELECT count(*) AS n FROM model_runs" + where, args
            ).fetchone()["n"]
            items = conn.execute(
                "SELECT * FROM model_runs"
                + where
                + " ORDER BY started_at DESC, id DESC LIMIT %s OFFSET %s",
                [*args, limit, offset],
            ).fetchall()
        return items, total

    def get(self, run_id):
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM model_runs WHERE id = %s", (run_id,)
            ).fetchone()
            if row is None:
                return None
            passes = conn.execute(
                "SELECT * FROM model_run_passes WHERE run_id = %s ORDER BY pass_number",
                (run_id,),
            ).fetchall()
        return {**row, "passes": passes}

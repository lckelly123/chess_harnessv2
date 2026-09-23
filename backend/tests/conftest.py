import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def disable_background_queue(monkeypatch):
    # Unit/API tests must never consume queues in a developer's public DB.
    # Queue integration tests explicitly drive serve()/execute_item() in an isolated schema.
    from positional_testing.queue import PositionQueueManager

    monkeypatch.setattr(PositionQueueManager, "start", lambda self: None)


@pytest.fixture
def library_rows(monkeypatch, run_store):
    """Use the real frozen exercises without requiring PostgreSQL in unit tests."""
    from positional_testing.datasets import store

    path = (
        Path(__file__).resolve().parents[1]
        / "positional_testing/datasets/seed/v1/positions.jsonl"
    )
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    monkeypatch.setattr(store, "list_position_rows", lambda: copy.deepcopy(rows))
    monkeypatch.setattr(
        store,
        "get_position_row",
        lambda identifier: next(
            (copy.deepcopy(row) for row in rows if row["id"] == identifier), None
        ),
    )
    return rows


class MemoryRunRepository:
    def __init__(self):
        self.runs = {}
        self.passes = {}

    def create(self, run_id, position_id, model, harness, config):
        self.runs[run_id] = dict(
            id=run_id,
            position_id=position_id,
            model=model,
            harness=harness,
            config=copy.deepcopy(config),
            status="running",
            final_move_uci=None,
            cp_loss=None,
            classification=None,
            expected_points_loss=None,
            better_moves=None,
            evaluation=None,
            error=None,
            started_at=datetime.now(UTC),
            finished_at=None,
        )

    def configure(self, run_id, model, config):
        self.runs[run_id].update(model=model, config=copy.deepcopy(config))

    def finish(self, run_id, *, move=None, error=None, grade=None):
        self.runs[run_id].update(
            status="failed" if error else "completed",
            final_move_uci=move,
            error=error,
            finished_at=datetime.now(UTC),
            **(grade or {}),
        )

    def save_move(self, run_id, move):
        self.runs[run_id]["final_move_uci"] = move

    def save_pass(self, row):
        self.passes[(row["run_id"], row["pass_number"])] = copy.deepcopy(row)

    def list(self, position_id=None, run_id=None, *, limit=30, offset=0):
        rows = [
            r
            for r in self.runs.values()
            if (not position_id or r["position_id"] == str(position_id))
            and (not run_id or r["id"] == str(run_id))
        ]
        rows.sort(key=lambda r: r["started_at"], reverse=True)
        return copy.deepcopy(rows[offset : offset + limit]), len(rows)

    def get(self, run_id):
        run_id = str(run_id)
        if run_id not in self.runs:
            return None
        return copy.deepcopy(
            {
                **self.runs[run_id],
                "passes": [
                    row
                    for (rid, _), row in sorted(self.passes.items())
                    if rid == run_id
                ],
            }
        )


@pytest.fixture
def run_store(monkeypatch):
    from positional_testing import evaluation, run_repository

    class OfflineEvaluator:
        async def evaluate(self, **kwargs):
            return dict(
                classification="good",
                cp_loss=40,
                expected_points_loss=0.03,
                better_moves=[],
                evaluation={"status": "completed", "engine_name": "test-fixture"},
            )

    repository = MemoryRunRepository()
    monkeypatch.setattr(run_repository, "RunRepository", lambda: repository)
    monkeypatch.setattr(evaluation, "StockfishEvaluator", OfflineEvaluator)
    return repository


@pytest.fixture
def database_path():
    directory = Path.cwd() / ".test-data"
    directory.mkdir(exist_ok=True)
    path = directory / f"matches-{uuid4().hex}.sqlite3"
    yield path
    for candidate in (path, Path(f"{path}-shm"), Path(f"{path}-wal")):
        candidate.unlink(missing_ok=True)

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from positional_testing.catalog import PositionLibraryUnavailableError
from positional_testing.queue_repository import QueueRepository
from positional_testing.routes import router

SEED = Path(__file__).resolve().parents[2] / "positional_testing/datasets/seed/v1"


@pytest.fixture
def deletion_library(postgres):
    postgres.import_collection(SEED)
    positions = postgres.list_position_rows()[:5]
    repository = QueueRepository()
    queue_id, other_queue_id = uuid4(), uuid4()
    identifiers = [uuid4() for _ in positions]
    for index, (identifier, position) in enumerate(zip(identifiers, positions)):
        repository.create(identifier, position["id"], "offline", "baseline", {
            "harness_name": "Baseline", "harness_version": "v1",
            "queue_ordinal": index + 1,
            "queue": {
                "name": "Same display name",
                "dataset_version": "v1", "split": "train",
                "created_at": datetime.now(UTC).isoformat(),
                "model_selection": {"model_id": "qwen", "reasoning_effort": "medium"},
            },
        })
        repository.save_pass({
            "run_id": identifier, "pass_number": 1, "phase": "respond",
            "status": "completed", "started_at": datetime.now(UTC),
        })
        repository.save_pass_exchange(identifier, 1, model_input={"messages": []})
        repository.finish(identifier, move="e2e4")
        with repository.connection() as conn:
            conn.execute("UPDATE model_runs SET queue_tag = %s WHERE id = %s", (
                None if index == 0 else queue_id if index < 3 else other_queue_id,
                identifier,
            ))
    app = FastAPI()
    app.state.positional_test_runner = SimpleNamespace(repository=repository)
    app.state.position_queue = SimpleNamespace(repository=repository)
    app.include_router(router)
    with TestClient(app) as client:
        yield client, repository, identifiers, queue_id, other_queue_id


@pytest.mark.parametrize("index", [0, 1])
def test_delete_one_run_preserves_positions_and_sibling_runs(deletion_library, index):
    client, repository, identifiers, queue_id, _ = deletion_library
    identifier = identifiers[index]
    response = client.delete(f"/api/positional-testing/runs/{identifier}")
    assert response.status_code == 204 and not response.content
    assert client.get(f"/api/positional-testing/runs/{identifier}").status_code == 404
    assert repository.get_pass_exchange(identifier, 1) is None
    assert client.get("/api/positional-testing/runs").json()["total"] == 4
    queue = client.get(f"/api/positional-testing/queues/{queue_id}").json()
    assert queue["total"] == (1 if index == 1 else 2)
    with repository.connection() as conn:
        assert conn.execute("SELECT count(*) AS total FROM positions").fetchone()["total"] == 400
    assert client.delete(f"/api/positional-testing/runs/{identifier}").status_code == 404


def test_delete_entire_queue_ignores_filters_and_preserves_same_named_queue(deletion_library):
    client, repository, identifiers, queue_id, other_queue_id = deletion_library
    response = client.delete(f"/api/positional-testing/queues/{queue_id}")
    assert response.status_code == 204 and not response.content
    assert client.get(f"/api/positional-testing/queues/{queue_id}").status_code == 404
    assert client.get(f"/api/positional-testing/queues/{other_queue_id}").json()["total"] == 2
    assert client.get("/api/positional-testing/runs").json()["total"] == 3
    options = client.get("/api/positional-testing/run-filters").json()
    assert [queue["id"] for queue in options["queues"]] == [str(other_queue_id)]
    for identifier in identifiers[1:3]:
        assert repository.get_pass_exchange(identifier, 1) is None
    assert repository.get_pass_exchange(identifiers[0], 1) is not None
    assert client.delete(f"/api/positional-testing/queues/{queue_id}").status_code == 404


@pytest.mark.parametrize("status", ["queued", "running"])
def test_active_run_blocks_atomic_queue_deletion(deletion_library, status):
    client, repository, identifiers, queue_id, _ = deletion_library
    with repository.connection() as conn:
        conn.execute("UPDATE model_runs SET status = %s WHERE id = %s", (status, identifiers[2]))
    assert client.delete(f"/api/positional-testing/runs/{identifiers[2]}").status_code == 409
    assert client.delete(f"/api/positional-testing/queues/{queue_id}").status_code == 409
    assert client.get("/api/positional-testing/runs").json()["total"] == 5
    assert repository.get_pass_exchange(identifiers[1], 1) is not None
    # A completed sibling can still be removed while the queue is active.
    assert client.delete(f"/api/positional-testing/runs/{identifiers[1]}").status_code == 204
    if status == "queued":
        repository.stop(queue_id)
    else:
        repository.finish(identifiers[2], error="Stopped")
    assert client.delete(f"/api/positional-testing/queues/{queue_id}").status_code == 204


@pytest.mark.parametrize("resource,method", [("runs", "delete_run"), ("queues", "delete_queue")])
def test_delete_reports_unavailable_database_and_rejects_invalid_ids(resource, method):
    def unavailable(_identifier):
        raise PositionLibraryUnavailableError("Database unavailable; retry.")

    app = FastAPI()
    state = SimpleNamespace(repository=SimpleNamespace(**{method: unavailable}))
    app.state.positional_test_runner = app.state.position_queue = state
    app.include_router(router)
    with TestClient(app) as client:
        assert client.delete(f"/api/positional-testing/{resource}/invalid").status_code == 422
        response = client.delete(f"/api/positional-testing/{resource}/{uuid4()}")
        assert response.status_code == 503
        assert response.json()["detail"] == "Database unavailable; retry."

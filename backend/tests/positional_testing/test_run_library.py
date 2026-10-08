"""The library filters the full persisted history before pagination."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from positional_testing.routes import router
from positional_testing.run_repository import RunRepository

SEED = Path(__file__).resolve().parents[2] / "positional_testing/datasets/seed/v1"


@pytest.fixture
def library(postgres):
    postgres.import_collection(SEED)
    positions = postgres.list_position_rows()
    training = next(row for row in positions if row["split"] == "train")
    testing = next(row for row in positions if row["split"] == "test")
    repository = RunRepository()
    for index in range(36):
        identifier = UUID(int=index + 1)
        position = training if index % 2 == 0 else testing
        config = {"harness_name": "Retired harness" if index >= 30 else "Baseline"}
        if index == 34:
            config["queue"] = {"split": "test", "dataset_version": "captured-v1"}
        repository.create(
            identifier,
            position["id"],
            "model_%" if index == 35 else "offline",
            "retired" if index >= 30 else "baseline",
            config,
        )
        if index % 3 == 0:
            repository.finish(
                identifier,
                move="a2a3",
                grade={
                    "classification": "best",
                    "cp_loss": 0,
                    "expected_points_loss": 0,
                    "evaluation": {"status": "completed"},
                },
            )
        elif index % 3 == 1:
            repository.finish(
                identifier,
                move="a2a3",
                grade={
                    "evaluation": {"status": "failed", "error": "Engine unavailable"}
                },
            )
        else:
            repository.finish(identifier, error="Provider unavailable")
        with repository.connection() as conn:
            conn.execute(
                "UPDATE model_runs SET created_at = %s, queue_tag = %s WHERE id = %s",
                (
                    datetime(2025, 1, 1, tzinfo=UTC) + timedelta(minutes=index),
                    UUID(int=100 + index) if index >= 5 else None,
                    identifier,
                ),
            )
    app = FastAPI()
    app.state.positional_test_runner = SimpleNamespace(repository=repository)
    app.include_router(router)
    with TestClient(app) as client:
        yield client, repository, training


def test_filters_apply_before_pagination_and_preserve_totals(library):
    client, _, _ = library
    response = client.get(
        "/api/positional-testing/runs",
        params={
            "split": "train",
            "harness": "retired",
            "model": "offline",
            "analysis": "completed",
            "classification": "best",
            "status": "completed",
            "run_source": "queue",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    run = payload["items"][0]
    assert run["id"] == str(UUID(int=31))
    assert run["analysisStatus"] == "completed"
    assert run["cpLoss"] == 0
    assert run["positionFen"] and run["phase"] and run["datasetVersion"]
    assert "passes" not in run
    assert (
        client.get(
            "/api/positional-testing/runs",
            params={
                "run_id": run["id"],
                "queue_tag": run["queueTag"],
                "position_id": run["positionId"],
            },
        ).json()["total"]
        == 1
    )
    assert (
        client.get(
            "/api/positional-testing/runs",
            params={"queue_tag": run["queueTag"], "run_source": "single"},
        ).json()["total"]
        == 0
    )


def test_grading_states_and_captured_queue_membership(library):
    client, repository, training = library
    for state in ("completed", "failed", "missing"):
        result = client.get(
            "/api/positional-testing/runs", params={"analysis": state}
        ).json()
        assert result["total"] == 12
        assert all(row["analysisStatus"] == state for row in result["items"])
    assert (
        client.get(
            "/api/positional-testing/runs", params={"run_source": "single"}
        ).json()["total"]
        == 5
    )
    captured = client.get(
        "/api/positional-testing/runs",
        params={"dataset_version": "captured-v1", "split": "test"},
    ).json()
    assert captured["total"] == 1
    assert captured["items"][0]["positionId"] == str(training["id"])
    # Interrupted evaluation may have a failure stage but no engine JSON.
    with repository.connection() as conn:
        conn.execute(
            "UPDATE model_runs SET failure_stage = 'evaluation', evaluation = %s WHERE id = %s",
            (Jsonb({}), UUID(int=36)),
        )
    assert (
        client.get(
            "/api/positional-testing/runs", params={"analysis": "failed"}
        ).json()["total"]
        == 13
    )


def test_sort_search_and_later_pages(library):
    client, _, _ = library
    path = "/api/positional-testing/runs"
    newest = client.get(path).json()
    assert newest["total"] == 36 and len(newest["items"]) == 30
    assert newest["items"][0]["id"] == str(UUID(int=36))
    older = client.get(path, params={"offset": 30}).json()
    assert older["total"] == 36 and len(older["items"]) == 6
    assert not {row["id"] for row in older["items"]} & {
        row["id"] for row in newest["items"]
    }
    assert client.get(path, params={"sort": "oldest"}).json()["items"][0]["id"] == str(
        UUID(int=1)
    )
    assert client.get(path, params={"query": "Retired harness"}).json()["total"] == 6
    assert client.get(path, params={"query": "%"}).json()["total"] == 1
    assert client.get(path, params={"query": "no such run"}).json()["total"] == 0


def test_options_include_old_queues_and_retired_harnesses(library):
    client, _, _ = library
    response = client.get("/api/positional-testing/run-filters")
    assert response.status_code == 200
    options = response.json()
    assert len(options["queues"]) == 31
    assert options["queues"][-1]["id"] == str(UUID(int=105))
    assert {"id": "retired", "name": "Retired harness"} in options["harnesses"]
    assert "captured-v1" in options["datasets"]
    assert options["models"] == ["model_%", "offline"]
    detail = client.get(f"/api/positional-testing/runs/{UUID(int=31)}").json()
    assert detail["positionFen"] and detail["passes"] == []


@pytest.mark.parametrize(
    "params",
    [
        {"analysis": "unknown"},
        {"split": "invalid"},
        {"sort": "id; DROP TABLE model_runs"},
        {"classification": "invented"},
        {"offset": -1},
        {"query": "x" * 241},
    ],
)
def test_rejects_invalid_filters(params):
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        assert (
            client.get("/api/positional-testing/runs", params=params).status_code == 422
        )

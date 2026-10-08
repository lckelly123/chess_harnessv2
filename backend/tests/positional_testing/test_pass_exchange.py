import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from positional_testing.catalog import PositionLibraryUnavailableError
from positional_testing.recording import PassRecorder
from positional_testing.routes import router
from positional_testing.run_repository import RunRepository

SEED = Path(__file__).resolve().parents[2] / "positional_testing/datasets/seed/v1"


def client_for(repository):
    app = FastAPI()
    app.include_router(router)
    app.state.positional_test_runner = SimpleNamespace(repository=repository)
    return TestClient(app)


def test_migration_roundtrip_is_immutable_and_lazy(postgres):
    postgres.import_collection(SEED)
    position = postgres.list_position_rows()[0]
    run_id = str(uuid4())
    repository = RunRepository()
    repository.create(run_id, position["id"], "offline", "baseline", {})
    recorder = PassRecorder(repository, run_id)
    recorder.begin({})

    # An existing database keeps its old passes with explicit capture absence.
    with postgres.connect() as connection:
        connection.execute(
            "ALTER TABLE model_run_passes DROP COLUMN model_input, DROP COLUMN model_output"
        )
    repository = RunRepository()
    assert repository.get(run_id)["passes"][0]["has_model_exchange"] is False
    assert repository.get_pass_exchange(run_id, 1) == {
        "model_input": None,
        "model_output": None,
    }
    with postgres.connect() as connection:
        postgres.ensure_schema(connection)
        postgres.ensure_schema(connection)

    recorder.repository = repository
    recorder.begin({"phase": "synthesis"})
    request = {
        "model": "offline",
        "input": [{"role": "user", "content": "\n snow 雪\r\n\t" + "long " * 16000}],
        "store": False,
    }
    raw = ' \n{"running_thoughts":"雪", "tool_calls": [invalid\t '
    response = {
        "output": [{"type": "function_call", "name": "agent_step", "arguments": raw}]
    }
    recorder.capture_input(request)
    recorder.capture_output(response)
    recorder.capture_input({"input": "must not replace"})
    recorder.capture_output({"output_text": "must not replace"})
    recorder.current["working_notes"] = "Derived notes updated later"
    recorder.save()
    recorder.fail("Parsing rejected this response")

    # Fresh repository represents a later process/restart.
    restarted = RunRepository()
    assert restarted.get_pass_exchange(run_id, 2) == {
        "model_input": request,
        "model_output": response,
    }
    with client_for(restarted) as client:
        detail = client.get(f"/api/positional-testing/runs/{run_id}").json()
        assert [item["hasModelExchange"] for item in detail["passes"]] == [False, True]
        assert all(
            "modelInput" not in item and "modelOutput" not in item
            for item in detail["passes"]
        )
        assert "long long long" not in json.dumps(detail)
        fetched = client.get(f"/api/positional-testing/runs/{run_id}/passes/2/exchange")
        assert fetched.status_code == 200
        assert json.loads(fetched.json()["input"]) == request
        assert fetched.json()["output"] == [raw]
        assert set(fetched.json()) == {"input", "output"}
        assert (
            client.get(
                f"/api/positional-testing/runs/{run_id}/passes/1/exchange"
            ).status_code
            == 409
        )
        assert (
            client.get(
                f"/api/positional-testing/runs/{run_id}/passes/3/exchange"
            ).status_code
            == 404
        )
        assert (
            client.get(
                f"/api/positional-testing/runs/{uuid4()}/passes/2/exchange"
            ).status_code
            == 404
        )


@pytest.mark.parametrize(
    "suffix",
    [
        "not-a-uuid/passes/1/exchange",
        f"{uuid4()}/passes/0/exchange",
        f"{uuid4()}/passes/-1/exchange",
    ],
)
def test_exchange_validates_path(suffix, run_store):
    with client_for(run_store) as client:
        assert client.get(f"/api/positional-testing/runs/{suffix}").status_code == 422


def test_exchange_reports_database_failure():
    class Unavailable:
        def get_pass_exchange(self, *_):
            raise PositionLibraryUnavailableError("Database unavailable")

    with client_for(Unavailable()) as client:
        result = client.get(f"/api/positional-testing/runs/{uuid4()}/passes/1/exchange")
        assert result.status_code == 503
        assert result.json()["detail"] == "Database unavailable"


def test_input_only_pass_has_empty_output(run_store):
    run_id = str(uuid4())
    recorder = PassRecorder(run_store, run_id)
    recorder.begin({})
    recorder.capture_input({"input": [{"role": "user", "content": "Actual prompt"}]})
    with client_for(run_store) as client:
        result = client.get(f"/api/positional-testing/runs/{run_id}/passes/1/exchange")
        assert result.status_code == 200
        assert result.json()["output"] == []

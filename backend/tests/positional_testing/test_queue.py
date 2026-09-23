import asyncio
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

import chess
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.matches.catalog import HARNESSES, UnknownHarnessError
from app.matches.repository import MatchRepository
from app.models import ModelSelection
from chess_core import normalize_move
from harness.contracts import MoveDecision
from harness.recording import current_recorder
from positional_testing.models import CreatePositionQueueRequest
from positional_testing.queue import PositionQueueManager
from positional_testing.queue_repository import QueueConflictError, QueueRepository
from positional_testing.run_repository import RunRepository
from positional_testing.runner import PositionalTestRunner

SEED = Path(__file__).resolve().parents[2] / "positional_testing/datasets/seed/v1"


class ScriptedCatalog:
    def __init__(self, fail_at=2, wait_at=None):
        self.calls = 0
        self.fail_at = fail_at
        self.wait_at = wait_at
        self.selections = []
        self.inflight = 0
        self.max_inflight = 0
        self.release = asyncio.Event()

    def definition(self, harness_id):
        definition = next((h for h in HARNESSES if h.id == harness_id), None)
        if definition is None:
            raise UnknownHarnessError("Unknown harness")
        return definition

    async def create_player(self, harness_id, cancellation_check, model_selection=None):
        self.definition(harness_id)
        self.selections.append(model_selection)
        return self, "offline-queue-model"

    async def choose_move(self, request):
        self.calls += 1
        self.inflight += 1
        self.max_inflight = max(self.max_inflight, self.inflight)
        try:
            if self.calls == self.fail_at:
                current_recorder.get().begin({"phase": "decide"})
                raise RuntimeError("Scripted provider failure")
            if self.calls == self.wait_at:
                await self.release.wait()
            board = chess.Board(request.fen)
            return MoveDecision(
                move=normalize_move(request.fen, next(iter(board.legal_moves)).uci()),
                justification="Offline queue test.",
            )
        finally:
            self.inflight -= 1


class OfflineEvaluator:
    def __init__(self, fail_at=2):
        self.calls = 0
        self.fail_at = fail_at

    async def evaluate(self, **kwargs):
        self.calls += 1
        if self.calls == self.fail_at:
            raise RuntimeError("Scripted engine failure")
        return dict(
            classification="blunder",
            expected_points_loss=0.25,
            cp_loss=200,
            better_moves=[],
            evaluation={"status": "completed"},
        )


@pytest.fixture
def queue_env(postgres):
    postgres.import_collection(SEED)
    repository = QueueRepository()
    catalog = ScriptedCatalog()
    runner = PositionalTestRunner(catalog, evaluator=OfflineEvaluator())
    manager = PositionQueueManager(runner, catalog, repository=repository)
    version = postgres.list_position_rows()[0]["dataset_version"]
    request = CreatePositionQueueRequest(
        dataset_version=version,
        split="train",
        harness_id=HARNESSES[0].id,
        model_selection=ModelSelection(model_id="gpt-terra"),
    )
    return manager, request


async def wait_until(predicate, timeout=20):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


def test_full_queue_is_sequential_and_continues_after_model_and_evaluation_failures(
    queue_env,
):
    manager, request = queue_env

    async def run():
        queued = await manager.enqueue(request)
        task = asyncio.create_task(manager.serve())
        try:
            await wait_until(
                lambda: (
                    manager.repository.get_queue(queued["id"])["status"] == "completed"
                ),
                timeout=120,
            )
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        return manager.repository.get_queue(queued["id"])

    result = asyncio.run(run())
    assert result["total"] == 200
    assert result["completed"] == 198
    assert result["failed"] == 2
    assert result["pending"] == result["running"] == result["skipped"] == 0
    assert manager.catalog.max_inflight == 1
    assert manager.catalog.calls == 200
    assert manager.catalog.selections == [request.model_selection] * 200
    assert len({item["run_id"] for item in result["items"]}) == 200
    model_failure, eval_failure = result["items"][1:3]
    assert model_failure["failure_stage"] == "execution"
    assert model_failure["error"] == "Scripted provider failure"
    failed_run = manager.runner.repository.get(model_failure["run_id"])
    assert failed_run["status"] == "failed"
    assert failed_run["passes"][0]["status"] == "failed"
    assert eval_failure["failure_stage"] == "evaluation"
    assert eval_failure["error"] == "Scripted engine failure"
    # An engine failure retains the submitted move and completed model trace.
    eval_run = manager.runner.repository.get(eval_failure["run_id"])
    assert eval_run["status"] == "completed"
    assert eval_run["evaluation"]["status"] == "failed"
    assert result["items"][-1]["classification"] == "blunder"
    assert result["items"][-1]["status"] == "completed"


def test_full_split_membership_duplicate_start_and_stop_before_start(
    queue_env, postgres
):
    manager, request = queue_env
    request = request.model_copy(update={"split": "test"})
    result = asyncio.run(manager.enqueue(request))
    expected = {
        str(p["id"]) for p in postgres.list_position_rows() if p["split"] == "test"
    }
    assert {str(i["position_id"]) for i in result["items"]} == expected
    assert result["model_selection"] == {
        "model_id": "gpt-terra",
        "reasoning_effort": "medium",
    }
    with pytest.raises(QueueConflictError):
        asyncio.run(manager.enqueue(request))
    manager.repository.stop(result["id"])
    assert manager.repository.claim_next() is None
    stopped = manager.repository.get_queue(result["id"])
    assert stopped["status"] == "stopped"
    assert stopped["skipped"] == 200
    assert stopped["completed"] == stopped["failed"] == 0
    assert len(manager.repository.list_queues()) == 1
    assert manager.runner.repository.list()[1] == 0


def test_stop_waits_for_current_then_skips_remaining(queue_env):
    manager, request = queue_env
    manager.catalog.wait_at = 1

    async def run():
        queued = await manager.enqueue(request)
        claimed = manager.repository.claim_next()
        task = asyncio.create_task(manager.execute_item(*claimed))
        await wait_until(lambda: manager.catalog.calls == 1)
        stopping = manager.repository.stop(queued["id"])
        assert stopping["status"] == "stopping"
        assert stopping["running"] == 1
        assert not task.done()
        manager.catalog.release.set()
        await task
        assert manager.repository.claim_next() is None
        return manager.repository.get_queue(queued["id"])

    result = asyncio.run(run())
    assert result["completed"] == 1
    assert result["skipped"] == 199
    assert result["status"] == "stopped"
    assert manager.catalog.calls == 1


def test_timeout_is_recorded_and_next_position_still_runs(queue_env):
    manager, request = queue_env
    manager.catalog.wait_at = 1
    manager.catalog.fail_at = None
    manager.item_timeout = 0.3

    async def run():
        queued = await manager.enqueue(request)
        await manager.execute_item(*manager.repository.claim_next())
        manager.item_timeout = 20
        await manager.execute_item(*manager.repository.claim_next())
        return manager.repository.get_queue(queued["id"])

    result = asyncio.run(run())
    assert result["items"][0]["failure_stage"] == "timeout"
    assert result["items"][0]["status"] == "failed"
    assert result["items"][1]["status"] == "completed"
    assert (
        manager.runner.repository.get(result["items"][0]["run_id"])["status"]
        == "failed"
    )


def test_restart_recovers_only_queue_attempts_and_does_not_repeat_paid_calls(queue_env):
    manager, request = queue_env
    queue = asyncio.run(manager.enqueue(request))
    q, item = manager.repository.claim_next()
    run_id, unrelated_id = str(uuid4()), str(uuid4())
    runs = RunRepository()
    runs.create(unrelated_id, item["position_id"], "old", "old", {})
    runs.create(
        run_id,
        item["position_id"],
        "offline",
        q["harness_id"],
        {},
        queue_item=(q["id"], item["ordinal"]),
    )
    # Simulate process death without a normal finally handler.
    restarted = QueueRepository()
    lease = restarted.acquire_worker()
    assert lease is not None
    try:
        assert QueueRepository().acquire_worker() is None
        restarted.recover()
        restarted.recover()  # Idempotent recovery does not change final items.
        next_queue, next_item = restarted.claim_next()
        assert next_item["ordinal"] == 2
        assert next_queue["id"] == queue["id"]
        assert runs.get(run_id)["status"] == "failed"
        assert runs.get(unrelated_id)["status"] == "running"
        failed = restarted.get_queue(queue["id"])["items"][0]
        assert failed["failure_stage"] == "interrupted"
    finally:
        lease.close()


def test_recovery_keeps_success_saved_just_before_crash(queue_env):
    manager, request = queue_env
    queue = asyncio.run(manager.enqueue(request))
    q, item = manager.repository.claim_next()
    run_id = str(uuid4())
    manager.runner.repository.create(
        run_id,
        item["position_id"],
        "offline",
        q["harness_id"],
        {},
        queue_item=(q["id"], item["ordinal"]),
    )
    manager.runner.repository.finish(
        run_id, move="a2a3", grade={"evaluation": {"status": "completed"}}
    )
    manager.repository.recover()
    result = manager.repository.get_queue(queue["id"])
    assert result["completed"] == 1
    assert result["failed"] == 0


def test_queue_api_contract_and_validation(queue_env):
    manager, request = queue_env
    app = create_app(repository=MatchRepository(":memory:"), catalog=manager.catalog)
    with TestClient(app) as client:
        app.state.position_queue = manager
        payload = request.model_dump(mode="json", by_alias=True)
        created = client.post("/api/positional-testing/queues", json=payload)
        assert created.status_code == 202
        body = created.json()
        assert body["total"] == body["pending"] == 200
        assert body["modelSelection"]["modelId"] == "gpt-terra"
        assert body["items"][0]["runId"] is None
        assert (
            client.post("/api/positional-testing/queues", json=payload).status_code
            == 409
        )
        assert (
            client.get("/api/positional-testing/queues").json()["items"][0]["id"]
            == body["id"]
        )
        path = "/api/positional-testing/queues/" + body["id"]
        assert client.get(path).json()["items"] == body["items"]
        assert client.post(path + "/stop").json()["status"] == "stopping"
        assert client.post(path + "/stop").status_code == 200
        assert (
            client.post(
                "/api/positional-testing/queues", json={**payload, "split": "all"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/positional-testing/queues",
                json={**payload, "harnessId": "missing"},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/positional-testing/queues",
                json={**payload, "datasetVersion": "missing"},
            ).status_code
            == 422
        )
        assert (
            client.get("/api/positional-testing/queues/" + str(uuid4())).status_code
            == 404
        )
        assert (
            client.post(
                "/api/positional-testing/queues/" + str(uuid4()) + "/stop"
            ).status_code
            == 404
        )

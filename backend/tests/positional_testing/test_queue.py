import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import chess
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.matches.catalog import AGENT_PLAYER_2_ID, HARNESSES, UnknownHarnessError
from app.matches.repository import MatchRepository
from app.models import ModelSelection
from chess_core import normalize_move
from codex_training.jobs import WorkerJobs
from codex_training.service import CodexTrainingService
from harness.contracts import MoveDecision
from harness.recording import current_recorder
from positional_testing.models import CreatePositionQueueRequest, PositionQueueDetail
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

    async def pin_model_selection(self, selection):
        return selection

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


async def queue_with_failures(manager, request):
    queued = await manager.enqueue(request)
    # A completed blunder is not a failed run. Include three different failure stages.
    for stage in (None, "execution", "evaluation", "timeout"):
        _, item = manager.repository.claim_next()
        if stage is None:
            manager.runner.repository.finish(
                item["run_id"],
                move="a2a3",
                grade={
                    "classification": "blunder",
                    "evaluation": {"status": "completed"},
                },
            )
        else:
            manager.repository.finish_item(
                item["run_id"], error=f"Fixture {stage} failure", failure_stage=stage
            )
    manager.repository.stop(queued["id"])
    return manager.repository.get_queue(queued["id"])


@pytest.mark.parametrize("codex", [False, True])
def test_retry_only_failed_positions_in_place_preserves_traces_and_settings(
    queue_env, codex
):
    manager, request = queue_env
    request.name = "Long queue name " + "x" * 104
    request.model_selection = ModelSelection(
        model_id="qwen", model_name="original-checkpoint"
    )
    if codex:
        request.harness_id = "codex-training"
        jobs = WorkerJobs(
            CodexTrainingService(manager.runner.repository, OfflineEvaluator())
        )
        manager.codex_jobs = jobs
        identity = dict(
            worker_id=str(uuid4()),
            model="original-teacher",
            reasoning_effort="xhigh",
            cli_version="fixture",
        )
        jobs.heartbeat(identity)

    async def run():
        source = await queue_with_failures(manager, request)
        source_runs = {
            item["run_id"]: manager.runner.repository.get(item["run_id"])
            for item in source["items"][:4]
        }
        failed = [item for item in source["items"] if item["status"] == "failed"]
        if codex:
            jobs.seen -= 60
            with pytest.raises(QueueConflictError, match="Windows Codex worker"):
                await manager.retry_failed(source["id"])
            jobs.heartbeat(
                {**identity, "model": "new-worker-model", "reasoning_effort": "low"}
            )
        retried = await manager.retry_failed(source["id"])
        assert retried["id"] == source["id"]
        assert retried["name"] == source["name"]
        assert retried["created_at"] == source["created_at"]
        assert retried["total"] == source["total"] == 200
        assert retried["pending"] == len(failed) == 3
        assert retried["completed"] == 1 and retried["skipped"] == 196
        assert retried["failed"] == 0 and retried["finished_at"] is None
        replacements = [item for item in retried["items"] if item["status"] == "queued"]
        assert [item["position_id"] for item in retried["items"]] == [
            item["position_id"] for item in source["items"]
        ]
        assert [item["ordinal"] for item in replacements] == [2, 3, 4]
        assert [item for item in retried["items"] if item["status"] != "queued"] == [
            item for item in source["items"] if item["status"] != "failed"
        ]
        assert retried["model_selection"] == source["model_selection"]
        assert retried["harness_id"] == source["harness_id"]
        assert retried["split"] == source["split"]
        for old, new in zip(failed, replacements, strict=True):
            stored = manager.runner.repository.get(new["run_id"])
            assert new["run_id"] != old["run_id"]
            assert stored["passes"] == [] and stored["evaluation"] is None
            assert stored["config"]["retry_of_run_id"] == str(old["run_id"])
        for run_id, before in source_runs.items():
            after = manager.runner.repository.get(run_id)
            # Only retry/queue coordination metadata changes; results and passes remain.
            assert {k: v for k, v in after.items() if k != "config"} == {
                k: v for k, v in before.items() if k != "config"
            }
        assert PositionQueueDetail.model_validate(retried).id == source["id"]
        assert manager.runner.repository.list(queue_tag=retried["id"])[1] == 203
        assert len(manager.repository.list_queues()) == 1
        if not codex:
            await manager.execute_item(*manager.repository.claim_next())
            assert manager.repository.get_queue(retried["id"])["completed"] == 2
            assert manager.catalog.selections[-1].model_name == "original-checkpoint"
        manager.repository.stop(retried["id"])
        # Deleting the queue includes its retained historical attempts.
        assert manager.repository.delete_queue(source["id"])
        assert manager.repository.get_queue(source["id"]) is None
        assert manager.runner.repository.list()[1] == 0

    asyncio.run(run())


def test_retry_queue_api_validates_source_state_and_returns_same_queue(queue_env):
    manager, request = queue_env
    app = create_app(repository=MatchRepository(":memory:"), catalog=manager.catalog)
    with TestClient(app) as client:
        app.state.position_queue = manager
        prefix = "/api/positional-testing/queues/"
        assert client.post(prefix + str(uuid4()) + "/retry-failed").status_code == 404
        assert client.post(prefix + "invalid/retry-failed").status_code == 422
        first = asyncio.run(manager.enqueue(request))
        path = prefix + str(first["id"]) + "/retry-failed"
        assert client.post(path).status_code == 409
        manager.repository.stop(first["id"])
        assert client.post(path).status_code == 422
        source = asyncio.run(queue_with_failures(manager, request))
        path = prefix + str(source["id"]) + "/retry-failed"
        result = client.post(path)
        assert result.status_code == 202, result.text
        body = result.json()
        assert body["total"] == 200 and body["pending"] == 3
        assert body["id"] == str(source["id"])
        assert body["name"] is None
        assert client.post(path).status_code == 409
        assert client.get(prefix + body["id"]).json()["id"] == str(source["id"])
        assert len(manager.repository.list_queues()) == 2


def test_concurrent_failure_retries_replace_failed_entries_only_once(queue_env):
    manager, request = queue_env
    source = asyncio.run(queue_with_failures(manager, request))

    def retry():
        try:
            return QueueRepository().retry_failed(source["id"])
        except QueueConflictError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: retry(), range(2)))
    assert sum(result is not None for result in results) == 1
    assert manager.runner.repository.list()[1] == 203
    assert len(manager.repository.list_queues()) == 1


def test_repeated_retry_uses_latest_failures_without_duplicate_positions(queue_env):
    manager, request = queue_env

    async def run():
        original = await queue_with_failures(manager, request)
        first = await manager.retry_failed(original["id"])
        _, item = manager.repository.claim_next()
        first_attempt = item["run_id"]
        manager.repository.finish_item(
            first_attempt, error="Failed again", failure_stage="execution"
        )
        # Other failures now succeed, so only the newest failure is retried next time.
        for _ in range(2):
            _, item = manager.repository.claim_next()
            manager.repository.finish_item(item["run_id"])
        again = await manager.retry_failed(first["id"])
        assert again["id"] == original["id"] and again["total"] == 200
        assert again["pending"] == 1 and again["completed"] == 3
        assert len({item["position_id"] for item in again["items"]}) == 200
        fresh = next(item for item in again["items"] if item["status"] == "queued")
        assert manager.runner.repository.get(fresh["run_id"])["config"][
            "retry_of_run_id"
        ] == str(first_attempt)
        assert manager.runner.repository.list(queue_tag=original["id"])[1] == 204
        assert len(manager.repository.list_queues()) == 1

    asyncio.run(run())


def test_retry_upgrades_unique_index_and_keeps_original_exchange(queue_env, postgres):
    import psycopg

    manager, request = queue_env
    source = asyncio.run(queue_with_failures(manager, request))
    failed = next(item for item in source["items"] if item["status"] == "failed")
    repository = manager.repository
    repository.save_pass(
        {
            "run_id": failed["run_id"],
            "pass_number": 1,
            "phase": "decide",
            "status": "failed",
            "started_at": datetime.now(UTC),
            "error": "Original error",
        }
    )
    exchange = {
        "model_input": {"input": "Original input"},
        "model_output": {"output": "Original output"},
    }
    repository.save_pass_exchange(failed["run_id"], 1, **exchange)
    # Simulate the existing-volume index, then repeat the additive upgrade safely.
    with postgres.connect() as conn:
        conn.execute("DROP INDEX model_runs_current_queue_position")
        conn.execute(
            "CREATE UNIQUE INDEX model_runs_queue_position ON model_runs (queue_tag, position_id) WHERE queue_tag IS NOT NULL"
        )
        postgres.ensure_schema(conn)
        postgres.ensure_schema(conn)
    result = asyncio.run(manager.retry_failed(source["id"]))
    assert repository.get_pass_exchange(failed["run_id"], 1) == exchange
    assert result["total"] == 200
    replacement = next(
        item for item in result["items"] if item["position_id"] == failed["position_id"]
    )
    assert repository.get(replacement["run_id"])["passes"] == []
    with pytest.raises(psycopg.errors.UniqueViolation), postgres.connect() as conn:
        conn.execute(
            "INSERT INTO model_runs (id,position_id,queue_tag,model,harness,config,status) "
            "SELECT %s,position_id,queue_tag,model,harness,config,'queued' FROM model_runs WHERE id=%s",
            (uuid4(), replacement["run_id"]),
        )


def test_codex_queue_real_harness_capture_failure_offline_wait_and_stop(queue_env):
    """Script a teacher through the real bridge; never invoke Codex or a model API."""
    manager, request = queue_env
    request.harness_id = "codex-training"
    request.model_selection = None
    request.name = "Codex queue fixture"
    training = CodexTrainingService(
        manager.runner.repository, OfflineEvaluator(fail_at=None)
    )
    jobs = WorkerJobs(training)
    manager.codex_jobs = jobs
    identity = dict(
        worker_id=str(uuid4()),
        model="fixture-teacher",
        reasoning_effort="high",
        cli_version="fixture",
    )

    async def run():
        with pytest.raises(QueueConflictError, match="Windows Codex worker"):
            await manager.enqueue(request)
        jobs.heartbeat(identity)
        queued = await manager.enqueue(request)
        parsed = PositionQueueDetail.model_validate(queued)
        assert parsed.model_selection.model_id == "codex"
        assert parsed.harness_name == "Codex (training)"
        assert parsed.harness_id == AGENT_PLAYER_2_ID
        assert manager.repository.claim_next(codex_ready=False) is None
        assert manager.repository.get_queue(queued["id"])["pending"] == 200

        # Later worker configuration changes must not alter this queue's model.
        jobs.heartbeat(
            {**identity, "model": "different-teacher", "reasoning_effort": "low"}
        )
        task = asyncio.create_task(manager.serve())
        try:
            await wait_until(jobs.active_jobs)
            first = jobs.claim(identity["worker_id"])
            assert first["run_id"] == str(queued["items"][0]["run_id"])
            assert first["model"] == "fixture-teacher"
            assert first["reasoning_effort"] == "high"
            assert jobs.status()["active_queue_id"] == str(queued["id"])
            assert jobs.snapshot(first["run_id"])["queue_tag"] == str(queued["id"])
            with pytest.raises(QueueConflictError, match="current Codex"):
                await manager.enqueue(request)

            # A failed teacher is retained; losing the worker must not consume the rest.
            jobs.seen -= 60
            jobs.report(
                first["run_id"],
                identity["worker_id"],
                progress="Fixture failure",
                error="Scripted teacher failure",
            )
            await wait_until(
                lambda: manager.repository.get_queue(queued["id"])["failed"] == 1
            )
            assert manager.repository.claim_next(codex_ready=False) is None
            assert manager.repository.get_queue(queued["id"])["pending"] == 199
            jobs.heartbeat(identity)
            manager._wake.set()
            await wait_until(
                lambda: any(run_id != first["run_id"] for run_id in jobs.active_jobs())
            )
            second = jobs.claim(identity["worker_id"])
            run_id = second["run_id"]
            assert run_id == str(queued["items"][1]["run_id"])
            session = training.sessions[run_id]

            from positional_testing.datasets import store

            board = chess.Board(store.get_position_row(session.position_id)["fen"])
            move = board.san(next(iter(board.legal_moves)))
            board.push_san(move)
            reply = board.san(next(iter(board.legal_moves)))
            calls = [
                ("scratch_play_move", {"move": move}),
                ("scratch_play_move", {"move": reply}),
                (
                    "submit_move",
                    {
                        "move": move,
                        "tested_branch": "B1",
                        "decision_summary": "Transport fixture: legal move and opponent reply tested.",
                    },
                ),
            ]
            # Lazy standalone recovery must leave an active queued teacher untouched.
            manager.runner.repository.recover_codex_training()
            assert manager.runner.repository.get(run_id)["status"] == "running"
            manager.repository.stop(queued["id"])
            assert manager.repository.get_queue(queued["id"])["status"] == "stopping"
            for tool, arguments in calls:
                current = await session.current(10)
                assert current["pass"] is not None, current
                raw = (
                    "<running_thoughts>Transport fixture.</running_thoughts>\n<agent_tool_calls>"
                    + json.dumps([{"tool": tool, "arguments": arguments}])
                    + "</agent_tool_calls>"
                )
                session.submit(
                    current["pass"]["pass_id"], raw, "Teacher fixture explanation."
                )
            await asyncio.wait_for(asyncio.shield(training.tasks[run_id]), 10)
            await wait_until(
                lambda: (
                    manager.repository.get_queue(queued["id"])["status"] == "stopped"
                )
            )
            result = manager.repository.get_queue(queued["id"])
            assert (
                result["total"],
                result["completed"],
                result["failed"],
                result["skipped"],
            ) == (200, 1, 1, 198)
            assert result["harness_name"] == "Codex (training)"
            stored = manager.runner.repository.get(run_id)
            assert stored["queue_tag"] == queued["id"]
            assert stored["config"]["provider"] == "codex_mcp"
            assert stored["config"]["teacher_model"] == "fixture-teacher"
            assert stored["evaluation"]["status"] == "completed"
            assert len(stored["passes"]) == 3
            exchange = manager.runner.repository.get_pass_exchange(run_id, 3)
            assert exchange["model_input"]
            assert "Teacher fixture explanation." in json.dumps(
                exchange["model_output"]
            )
            assert manager.runner.repository.list(queue_tag=queued["id"])[1] == 200
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await training.close()

    asyncio.run(run())


def test_codex_queue_timeout_stops_teacher_and_preserves_pending(queue_env):
    manager, request = queue_env
    request.harness_id = "codex-training"
    training = CodexTrainingService(manager.runner.repository, OfflineEvaluator())
    jobs = WorkerJobs(training)
    manager.codex_jobs = jobs

    async def run():
        jobs.heartbeat(
            dict(
                worker_id=str(uuid4()),
                model="fixture",
                reasoning_effort="medium",
                cli_version="fixture",
            )
        )
        queued = await manager.enqueue(request)
        claimed = manager.repository.claim_next()
        run_id = str(claimed[1]["run_id"])
        # Start the real teacher first, so the timeout covers a pending model call.
        await jobs.enqueue(
            str(claimed[1]["position_id"]),
            queued_run_id=run_id,
            queue_tag=queued["id"],
            selection=queued["model_selection"],
        )
        original_enqueue = jobs.enqueue

        async def existing_job(*args, **kwargs):
            return jobs.snapshot(run_id)

        jobs.enqueue = existing_job
        manager.item_timeout = 0.05
        try:
            await manager.execute_item(*claimed)
            result = manager.repository.get_queue(queued["id"])
            assert result["failed"] == 1 and result["pending"] == 199
            assert result["items"][0]["failure_stage"] == "timeout"
            assert training.tasks[run_id].done()
            assert not jobs.active_jobs()
            assert (
                manager.runner.repository.get(run_id)["passes"][0]["status"] == "failed"
            )
        finally:
            jobs.enqueue = original_enqueue
            await training.close()

    asyncio.run(run())


@pytest.mark.parametrize("split", ["train", "test"])
def test_named_queues_survive_restart_and_search_without_replacing_ids(
    queue_env, split
):
    manager, request = queue_env
    request.split = split
    request.name = "Prompt v2 · 50%_budget 雪"
    first = asyncio.run(manager.enqueue(request))
    manager.repository.stop(first["id"])
    second = asyncio.run(manager.enqueue(request))
    manager.repository.stop(second["id"])
    assert first["id"] != second["id"]  # Reusing a label never merges two attempts.
    restarted = QueueRepository()
    assert restarted.get_queue(first["id"])["name"] == request.name
    assert [q["name"] for q in restarted.list_queues()] == [request.name, request.name]
    runs, total = restarted.list(query="50%_budget", split=split)
    assert total == 400
    assert all(row["queue_name"] == request.name for row in runs)
    assert restarted.list(query="50X_budget")[1] == 0
    assert restarted.list(query="50%Xbudget")[1] == 0
    assert restarted.list(queue_tag=first["id"], query=request.name)[1] == 200
    assert restarted.get(first["items"][0]["run_id"])["queue_name"] == request.name

    # Older snapshots have no name key, and still appear under their UUID.
    with restarted.connection() as conn:
        conn.execute(
            "UPDATE model_runs SET config = config #- '{queue,name}' WHERE queue_tag = %s",
            (first["id"],),
        )
    assert restarted.get_queue(first["id"])["name"] is None
    assert restarted.get(first["items"][0]["run_id"])["queue_name"] is None
    assert (
        next(q for q in restarted.filter_options()["queues"] if q["id"] == first["id"])[
            "name"
        ]
        is None
    )


@pytest.mark.parametrize(
    "name, expected",
    [
        (None, None),
        ("", None),
        (" \n\t ", None),
        ("  test   run\n雪  ", "test run 雪"),
        ("a" * 120, "a" * 120),
    ],
)
def test_queue_name_normalization(name, expected):
    request = CreatePositionQueueRequest(
        name=name, dataset_version="v1", split="test", harness_id=HARNESSES[0].id
    )
    assert request.name == expected


@pytest.mark.parametrize(
    "name", ["a" * 121, "bad\x00name", 123, {"name": "wrong type"}]
)
def test_queue_name_rejects_invalid_values(name):
    with pytest.raises(ValidationError):
        CreatePositionQueueRequest(
            name=name, dataset_version="v1", split="test", harness_id=HARNESSES[0].id
        )


def test_full_queue_is_sequential_and_continues_after_model_and_evaluation_failures(
    queue_env,
):
    manager, request = queue_env
    request.name = "Baseline · revised prompt"

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
    assert result["name"] == request.name
    assert result["total"] == 200
    assert result["completed"] == 198
    assert result["failed"] == 2
    assert result["pending"] == result["running"] == result["skipped"] == 0
    assert manager.catalog.max_inflight == 1
    assert manager.catalog.calls == 200
    assert manager.catalog.selections == [request.model_selection] * 200
    assert len({item["run_id"] for item in result["items"]}) == 200
    first_page, total = manager.runner.repository.list(
        queue_tag=result["id"], limit=100
    )
    last_page, _ = manager.runner.repository.list(
        queue_tag=result["id"], limit=100, offset=100
    )
    assert total == 200
    assert {r["id"] for r in first_page + last_page} == {
        item["run_id"] for item in result["items"]
    }
    assert all(r["queue_tag"] == result["id"] for r in first_page + last_page)
    assert all(r["queue_name"] == request.name for r in first_page + last_page)
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
    assert eval_run["status"] == "failed"
    assert eval_run["failure_stage"] == "evaluation"
    assert eval_run["evaluation"]["status"] == "failed"
    assert result["items"][-1]["classification"] == "blunder"
    assert result["items"][-1]["status"] == "completed"


def test_queue_rows_exist_before_execution_and_tag_filters_combine(queue_env):
    manager, request = queue_env
    queue = asyncio.run(manager.enqueue(request))
    runs = manager.runner.repository
    rows, total = runs.list(queue_tag=queue["id"], limit=100)
    assert total == 200
    assert all(r["status"] == "queued" and r["started_at"] is None for r in rows)
    original_ids = {i["run_id"] for i in queue["items"]}
    q, item = manager.repository.claim_next()
    assert manager.repository.claim_next() is None
    runs.configure(item["run_id"], "resolved-model", {"custom": 123})
    assert runs.get(item["run_id"])["config"]["queue"]["split"] == request.split
    asyncio.run(manager.execute_item(q, item))
    assert {
        i["run_id"] for i in manager.repository.get_queue(q["id"])["items"]
    } == original_ids
    standalone_id = uuid4()
    runs.create(standalone_id, item["position_id"], "offline", q["harness_id"], {})
    runs.finish(standalone_id, move="a2a3")
    assert runs.get(standalone_id)["queue_tag"] is None
    assert runs.list(run_id=standalone_id, queue_tag=q["id"]) == ([], 0)
    app = create_app(repository=MatchRepository(":memory:"), catalog=manager.catalog)
    with TestClient(app) as client:
        path = "/api/positional-testing/runs"
        response = client.get(path, params={"queue_tag": str(q["id"])})
        assert response.status_code == 200
        assert response.json()["total"] == 200
        assert all(r["queueTag"] == str(q["id"]) for r in response.json()["items"])
        assert client.get(f"{path}/{standalone_id}").json()["queueTag"] is None
        assert (
            client.get(
                path,
                params={
                    "queue_tag": str(q["id"]),
                    "run_id": str(item["run_id"]),
                    "position_id": str(item["position_id"]),
                },
            ).json()["total"]
            == 1
        )
        assert client.get(path, params={"queue_tag": str(uuid4())}).json()["total"] == 0
        assert client.get(path, params={"queue_tag": "invalid"}).status_code == 422


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
        "model_name": None,
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
    assert manager.runner.repository.list()[1] == 200


def test_concurrent_enqueues_and_claims_are_serialized(queue_env):
    manager, request = queue_env

    def enqueue():
        try:
            return QueueRepository().enqueue(
                dataset_version=request.dataset_version,
                split=request.split,
                definition=manager.catalog.definition(request.harness_id),
                model_selection=request.model_selection,
            )
        except QueueConflictError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: enqueue(), range(2)))
    assert sum(result is not None for result in results) == 1
    assert manager.runner.repository.list()[1] == 200
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: QueueRepository().claim_next(), range(2)))
    assert sum(claim is not None for claim in claims) == 1
    queue = manager.repository.list_queues()[0]
    assert queue["running"] == 1 and queue["pending"] == 199


def test_invalid_position_is_failed_on_its_scheduled_run_and_queue_continues(
    queue_env, postgres
):
    manager, request = queue_env
    queued = asyncio.run(manager.enqueue(request))
    first_id = queued["items"][0]["run_id"]
    with postgres.connect() as conn:
        conn.execute(
            "UPDATE positions SET pgn_prefix = '*' WHERE id = %s",
            (queued["items"][0]["position_id"],),
        )
    asyncio.run(manager.execute_item(*manager.repository.claim_next()))
    asyncio.run(manager.execute_item(*manager.repository.claim_next()))
    first = manager.runner.repository.get(first_id)
    assert first["status"] == "failed" and first["failure_stage"] == "position"
    assert first["passes"] == []
    assert (
        manager.repository.get_queue(queued["id"])["items"][1]["status"] == "completed"
    )
    assert manager.catalog.calls == 1


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
    run_id, unrelated_id = item["run_id"], str(uuid4())
    runs = RunRepository()
    runs.create(unrelated_id, item["position_id"], "old", "old", {})
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
    run_id = item["run_id"]
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
        payload["name"] = "  Training   baseline\n雪  "
        created = client.post("/api/positional-testing/queues", json=payload)
        assert created.status_code == 202
        body = created.json()
        assert body["name"] == "Training baseline 雪"
        assert body["total"] == body["pending"] == 200
        assert body["modelSelection"]["modelId"] == "gpt-terra"
        assert body["items"][0]["runId"] is not None
        assert body["items"][0]["queueTag"] == body["id"]
        assert (
            client.post("/api/positional-testing/queues", json=payload).status_code
            == 409
        )
        assert (
            client.get("/api/positional-testing/queues").json()["items"][0]["id"]
            == body["id"]
        )
        path = "/api/positional-testing/queues/" + body["id"]
        assert client.get(path).json()["name"] == body["name"]
        assert (
            client.get("/api/positional-testing/queues").json()["items"][0]["name"]
            == body["name"]
        )
        options = client.get("/api/positional-testing/run-filters").json()
        assert options["queues"][0]["name"] == body["name"]
        named_runs = client.get(
            "/api/positional-testing/runs", params={"query": "baseline 雪"}
        ).json()
        assert named_runs["total"] == 200
        assert named_runs["items"][0]["queueName"] == body["name"]
        assert client.get(path).json()["items"] == body["items"]
        assert client.post(path + "/stop").json()["status"] == "stopped"
        assert client.get(path).json()["name"] == body["name"]
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

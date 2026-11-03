"""Exercise collection orchestration without a GPU, model server or database."""

import asyncio
import copy
import json
from types import SimpleNamespace

import httpx2 as httpx
import pytest

from app.matches.catalog import AGENT_PLAYER_2_ID, HarnessCatalog
from grpo import service as service_module
from grpo.client import CaptureClient, CaptureUnavailable
from grpo.routes import StartCollection
from grpo.service import CollectionConflict, GrpoService
from grpo.storage import CollectionStore
from harness.recording import current_recorder

MODEL = "Qwen_Qwen3-14B__project-true_trial_v1.2_1792812112"
POSITION = "00000000-0000-4000-8000-000000000001"
GENERATED = (
    "<running_thoughts>Compare the candidate.</running_thoughts>"
    '<agent_tool_calls>[{"tool":"inspect_square","arguments":{"square":"e4"}},'
    '{"tool":"scratch_play_move","arguments":{"move":"e4"}}]'
    "</agent_tool_calls>"
)


def request(name="collection", **changes):
    return StartCollection.model_validate(
        {
            "name": name,
            "positionId": POSITION,
            "harnessId": AGENT_PLAYER_2_ID,
            "modelSelection": {"modelId": "unsloth", "modelName": MODEL},
            **changes,
        }
    )


def read_calls(store, name="collection", trajectory=1):
    path = store.path(name) / f"trajectory_{trajectory:02d}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


class CaptureFixture:
    def __init__(self, *, block_at=None, corrupt_at=None, wrong_session=False):
        self.block_at = block_at
        self.corrupt_at = corrupt_at
        self.wrong_session = wrong_session
        self.blocked = asyncio.Event()
        self.proceed = asyncio.Event()
        self.calls = []
        self.events = []
        self.prepared = []
        self.released = []
        self.cancelled = []
        self.closed = False
        self.inflight = 0
        self.max_inflight = 0

    async def health(self):
        return {"ready": True, "busy": False}

    async def unload_studio(self, model_name):
        self.events.append(("unload", model_name))

    async def prepare(self, model_name, session_id):
        self.prepared.append((model_name, session_id))
        self.events.append(("prepare", model_name))
        return {
            "session_id": "wrong-session" if self.wrong_session else session_id,
            "metadata": {
                "adapter_fingerprint": "frozen-test-adapter",
                "logprob_convention": "raw-model-log-softmax",
            },
        }

    async def complete(self, session_id, provider_request, seed, timeout_seconds):
        self.calls.append((session_id, copy.deepcopy(provider_request), seed))
        call = len(self.calls)
        self.inflight += 1
        self.max_inflight = max(self.max_inflight, self.inflight)
        try:
            if call == self.block_at:
                self.blocked.set()
                await self.proceed.wait()
            cancelled = session_id in self.cancelled
            capture = {
                "input": "<exact rendered prompt>",
                "prompt_token_ids": [100, 101, 102],
                "generated_response": GENERATED,
                "completion_token_ids": [200, 201, 202],
                "old_logprobs": [-0.1, -1.2, -0.3],
                "sampling_logprobs": [-0.05, -0.8, -0.2],
                "finish_reason": "cancelled" if cancelled else "eos",
                "status": "cancelled" if cancelled else "completed",
                "truncated": False,
            }
            if cancelled:
                capture["error"] = "Stopped after partial generation."
            if call == self.corrupt_at:
                capture["old_logprobs"] = [-0.1]
            return {
                "capture": capture,
                "response": {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": GENERATED}],
                        }
                    ],
                },
            }
        finally:
            self.inflight -= 1

    async def cancel(self, session_id):
        self.cancelled.append(session_id)
        self.proceed.set()

    async def release(self, session_id):
        self.released.append(session_id)

    async def close(self):
        self.closed = True


@pytest.fixture
def collection_factory(monkeypatch, run_store, tmp_path):
    """Use the actual token adapter, pass recorder and append-only file store."""
    instances = []
    behavior = SimpleNamespace(fail_trajectory=None)
    document = SimpleNamespace(
        pgn='[Result "*"]\n\n*',
        position=SimpleNamespace(
            position=SimpleNamespace(
                fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
            )
        ),
    )
    monkeypatch.setattr(service_module, "get_saved_position", lambda _: document)
    monkeypatch.setattr(service_module.secrets, "randbelow", lambda _: 42)

    class TurnFixture:
        def __init__(
            self, catalog, *, repository, evaluator, active_runs, recorder_factory
        ):
            self.catalog = catalog
            self.repository = repository
            self.active_runs = active_runs
            self.recorder_factory = recorder_factory
            self.index = len(instances) + 1
            self.run_id = None
            instances.append(self)

        async def run_once(
            self,
            position_id,
            harness_id,
            model_selection,
            *,
            run_id,
            cancellation_check,
            config_metadata,
        ):
            assert not self.active_runs, "Trajectories must not overlap."
            assert not cancellation_check()
            self.run_id = run_id
            self.active_runs[run_id] = self
            self.repository.create(
                run_id,
                position_id,
                model_selection.model_name,
                harness_id,
                config_metadata,
            )
            recorder = self.recorder_factory(self.repository, run_id)
            token = current_recorder.set(recorder)
            try:
                for call in (1, 2):
                    recorder.begin({"phase": "synthesis"})
                    response = await self.catalog._unsloth_model.complete(
                        model=model_selection.model_name,
                        instructions="Stable harness instructions",
                        dynamic_input=f"Fresh trajectory {self.index}, call {call}",
                        reasoning_effort="medium",
                        max_output_tokens=100,
                        forced_retry=call == 2,
                    )
                    recorder.response(response)
                    events = (
                        [{"type": "response_retry", "reason": "Rejected test call"}]
                        if call == 1
                        else []
                    )
                    recorder.state({"events": []}, {"events": events})
                if self.index == behavior.fail_trajectory:
                    raise RuntimeError("This trajectory failed in the harness.")
                self.repository.finish(
                    run_id, move="e2e4", grade={"cp_loss": 10 * self.index}
                )
            except BaseException as exc:
                recorder.fail(exc)
                self.repository.finish(run_id, error=str(exc))
                raise
            finally:
                current_recorder.reset(token)
                self.active_runs.pop(run_id, None)

    monkeypatch.setattr(service_module, "PositionalTestRunner", TurnFixture)

    def make(client=None, *, busy_check=None):
        base_runner = SimpleNamespace(
            repository=run_store, evaluator=object(), active_runs={}
        )
        store = CollectionStore(tmp_path / "RL_testing")
        worker = client or CaptureFixture()
        service = GrpoService(
            base_runner,
            HarnessCatalog(None),
            store=store,
            client=worker,
            busy_check=busy_check,
        )
        return service, store, worker

    return make, instances, behavior


def test_ten_fresh_sequential_attempts_save_incrementally(collection_factory):
    async def scenario():
        make, instances, behavior = collection_factory
        behavior.fail_trajectory = 4
        worker = CaptureFixture(block_at=3)
        service, store, _ = make(worker)
        initial = await service.start(request())
        assert initial["status"] == "preparing"
        await asyncio.wait_for(worker.blocked.wait(), timeout=5)

        # The first trajectory is already durable while the second is generating.
        assert service.active
        first = read_calls(store)
        assert len(first) == 2
        assert first[0]["completion_token_ids"] == [200, 201, 202]
        assert first[0]["old_logprobs"] == [-0.1, -1.2, -0.3]
        assert first[0]["harness_rejected"] is True
        partial = store.get("collection")
        assert partial["completedTrajectories"] == 1
        assert partial["currentTrajectory"] == 2
        assert partial["trajectories"][0]["toolCounts"]["inspect_square"] == 2
        worker.proceed.set()
        await asyncio.wait_for(service.task, timeout=10)

        group = store.get("collection")
        assert group["status"] == "completed"
        assert group["completedTrajectories"] == 10
        assert len(instances) == 10
        assert len({instance.run_id for instance in instances}) == 10
        assert worker.max_inflight == 1
        assert len(worker.calls) == 20
        assert [item["trajectory"] for item in group["trajectories"]] == list(
            range(1, 11)
        )
        assert group["trajectories"][3]["status"] == "failed"
        assert group["trajectories"][3]["cpLoss"] is None
        assert group["trajectories"][9]["cpLoss"] == 100
        assert all(t["rejectedModelCalls"] == 1 for t in group["trajectories"])
        assert all(len(read_calls(store, trajectory=i)) == 2 for i in range(1, 11))

        assert worker.events == [("unload", MODEL), ("prepare", MODEL)]
        assert worker.prepared == [(MODEL, service.session_id)]
        assert {call[0] for call in worker.calls} == {service.session_id}
        assert {call[1]["model"] for call in worker.calls} == {MODEL}
        assert [call[2] for call in worker.calls] == [
            42 + trajectory * 100000 + call
            for trajectory in range(1, 11)
            for call in (1, 2)
        ]
        assert worker.released == [service.session_id]
        metadata = json.loads(
            (store.path("collection") / "capture_config.json").read_text()
        )
        assert (
            metadata["capture_worker"]["adapter_fingerprint"] == "frozen-test-adapter"
        )
        assert (
            "advantage" not in (store.path("collection") / "manifest.json").read_text()
        )
        await service.close()
        assert worker.closed

    asyncio.run(scenario())


def test_stop_signals_worker_preserves_partial_data_and_does_not_restart(
    collection_factory,
):
    async def scenario():
        make, instances, _ = collection_factory
        worker = CaptureFixture(block_at=2)
        service, store, _ = make(worker)
        await service.start(request())
        await asyncio.wait_for(worker.blocked.wait(), timeout=5)
        assert len(read_calls(store)) == 1
        await service.stop("collection")
        await asyncio.wait_for(service.task, timeout=5)

        group = store.get("collection")
        assert group["status"] == "stopped"
        assert group["stopping"] is False
        assert group["trajectories"][0]["status"] == "stopped"
        assert all(t["status"] == "pending" for t in group["trajectories"][1:])
        assert len(instances) == 1
        assert worker.cancelled == [service.session_id]
        assert worker.released == [service.session_id]
        calls = read_calls(store)
        assert len(calls) == 2
        assert calls[-1]["capture_valid"] is True
        assert calls[-1]["finish_reason"] == "cancelled"
        assert calls[-1]["completion_token_ids"] == [200, 201, 202]
        assert len(service.runner.repository.runs) == 1, "Stop must not discard runs."
        await service.close()

    asyncio.run(scenario())


def test_invalid_token_alignment_fails_collection_before_another_trajectory(
    collection_factory,
):
    async def scenario():
        make, instances, _ = collection_factory
        service, store, worker = make(CaptureFixture(corrupt_at=1))
        await service.start(request())
        await asyncio.wait_for(service.task, timeout=5)
        group = store.get("collection")
        assert group["status"] == "failed"
        assert "misaligned old_logprobs" in group["error"]
        assert len(instances) == 1
        assert len(worker.calls) == 1
        assert worker.released == [service.session_id]
        calls = read_calls(store)
        assert len(calls) == 1
        assert calls[0]["capture_valid"] is False
        assert calls[0]["finish_reason"] == "capture_error"
        assert calls[0]["request"]["model"] == MODEL
        assert all(t["status"] == "pending" for t in group["trajectories"][1:])
        await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "changes",
    [
        {"harnessId": "baseline-direct-submit-langgraph-v1"},
        {"modelSelection": {"modelId": "qwen", "modelName": MODEL}},
        {"modelSelection": {"modelId": "unsloth"}},
    ],
)
def test_unsupported_selection_never_unloads_or_creates_files(
    collection_factory, changes
):
    async def scenario():
        make, instances, _ = collection_factory
        service, store, worker = make()
        with pytest.raises(ValueError):
            await service.start(request(**changes))
        assert not store.path("collection").exists()
        assert worker.events == []
        assert instances == []
        await service.close()

    asyncio.run(scenario())


def test_existing_directory_is_never_overwritten(collection_factory):
    async def scenario():
        make, _, _ = collection_factory
        service, store, worker = make()
        existing = store.path("collection")
        existing.mkdir(parents=True)
        sentinel = existing / "manifest.json"
        sentinel.write_text('{"keep":"original"}', encoding="utf-8")
        with pytest.raises(CollectionConflict, match="already exists"):
            await service.start(request())
        assert sentinel.read_text() == '{"keep":"original"}'
        assert list(existing.iterdir()) == [sentinel]
        assert worker.events == []
        await service.close()

    asyncio.run(scenario())


def test_wrong_prepared_policy_session_is_released_without_generation(
    collection_factory,
):
    async def scenario():
        make, instances, _ = collection_factory
        service, store, worker = make(CaptureFixture(wrong_session=True))
        await service.start(request())
        await asyncio.wait_for(service.task, timeout=5)
        group = store.get("collection")
        assert group["status"] == "failed"
        assert "different policy session" in group["error"]
        assert worker.calls == []
        assert instances == []
        assert worker.released == [service.session_id]
        await service.close()

    asyncio.run(scenario())


def test_failed_prepare_still_releases_and_preserves_manifest(collection_factory):
    class CannotPrepare(CaptureFixture):
        async def prepare(self, model_name, session_id):
            self.prepared.append((model_name, session_id))
            raise CaptureUnavailable("Insufficient VRAM for this checkpoint.")

    async def scenario():
        make, instances, _ = collection_factory
        service, store, worker = make(CannotPrepare())
        await service.start(request())
        await asyncio.wait_for(service.task, timeout=5)
        group = store.get("collection")
        assert group["status"] == "failed"
        assert "Insufficient VRAM" in group["error"]
        assert group["completedTrajectories"] == 0
        assert len(list(store.path("collection").glob("trajectory_*.jsonl"))) == 10
        assert worker.calls == []
        assert instances == []
        assert worker.released == [service.session_id]
        await service.close()

    asyncio.run(scenario())


def test_dead_worker_fails_collection_without_replacing_attempt(collection_factory):
    class DeadWorker(CaptureFixture):
        async def complete(self, session_id, provider_request, seed, timeout_seconds):
            self.calls.append((session_id, provider_request, seed))
            raise CaptureUnavailable(
                "Capture worker disconnected; no result recovered."
            )

    async def scenario():
        make, instances, _ = collection_factory
        service, store, worker = make(DeadWorker())
        await service.start(request())
        await asyncio.wait_for(service.task, timeout=5)
        group = store.get("collection")
        assert group["status"] == "failed"
        assert "no result recovered" in group["error"]
        assert len(instances) == len(worker.calls) == 1
        assert all(t["status"] == "pending" for t in group["trajectories"][1:])
        assert worker.released == [service.session_id]
        calls = read_calls(store)
        assert len(calls) == 1
        assert calls[0]["capture_valid"] is False
        assert calls[0]["request"]["model"] == MODEL
        await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel_fails", [False, True])
def test_lost_completion_response_recovers_raw_result_even_if_cancel_fails(
    cancel_fails,
):
    async def scenario():
        raw = {"capture": {"completion_token_ids": [7], "old_logprobs": [-0.5]}}
        requests = []
        polls = []
        client = CaptureClient.__new__(CaptureClient)
        client.base_url = "http://capture-fixture"
        client.headers = lambda: {"Authorization": "Bearer fixture"}

        async def post(endpoint, body, **kwargs):
            requests.append((endpoint, body))
            if endpoint == "/complete":
                raise CaptureUnavailable("Original response connection lost.")
            if cancel_fails:
                raise CaptureUnavailable("Cancellation response connection lost.")
            return {"cancelled": True}

        async def get(url, **kwargs):
            polls.append((url, kwargs))
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"busy": False, "last_result": raw},
            )

        client.post = post
        client.http = SimpleNamespace(get=get)
        result = await client.complete("pinned-session", {"model": MODEL}, 42, 600)
        assert result is raw
        assert [endpoint for endpoint, _ in requests] == ["/complete", "/cancel"]
        assert requests[1][1] == {"session_id": "pinned-session"}
        assert polls[0][0] == "http://capture-fixture/result/pinned-session"
        assert polls[0][1]["params"]["request_id"] == requests[0][1]["request_id"]

    asyncio.run(scenario())


def test_lost_completion_without_recoverable_result_keeps_failure():
    async def scenario():
        client = CaptureClient.__new__(CaptureClient)
        client.base_url = "http://capture-fixture"
        client.headers = lambda: {}

        async def post(endpoint, body, **kwargs):
            if endpoint == "/complete":
                raise CaptureUnavailable("Original response connection lost.")
            return {"cancelled": True}

        async def get(url, **kwargs):
            raise httpx.ConnectError("Worker is offline.")

        client.post = post
        client.http = SimpleNamespace(get=get)
        with pytest.raises(
            CaptureUnavailable, match="Original response connection lost"
        ):
            await client.complete("session", {"model": MODEL}, 42, 600)

    asyncio.run(scenario())


def test_composed_api_preserves_capture_and_guards_other_run_starts(collection_factory):
    # ASGI transport exercises the real composition root without its DB/GPU lifespan.
    from app.main import create_app

    async def scenario():
        make, instances, _ = collection_factory
        worker = CaptureFixture(block_at=1)
        service, _, _ = make(worker)
        app = create_app()
        app.state.grpo = service
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://fixture"
        ) as client:
            try:
                idle = await client.get("/api/grpo/status")
                assert idle.status_code == 200
                assert idle.json()["workerOnline"] is True
                assert idle.json()["activeRun"] is None
                body = request().model_dump(mode="json", by_alias=True)
                started = await client.post("/api/grpo/runs", json=body)
                assert started.status_code == 202
                assert started.json()["status"] == "preparing"
                await asyncio.wait_for(worker.blocked.wait(), timeout=5)
                active = (await client.get("/api/grpo/status")).json()["activeRun"]
                assert active["name"] == "collection"
                assert active["currentTrajectory"] == 1
                assert (
                    await client.get("/api/grpo/runs/collection")
                ).status_code == 200
                assert (await client.get("/api/grpo/runs/missing")).status_code == 404
                assert (await client.get("/api/health")).status_code == 200
                conflicting = [
                    ("/api/grpo/runs", {**body, "name": "second"}),
                    (
                        "/api/matches",
                        {
                            "whiteHarnessId": AGENT_PLAYER_2_ID,
                            "blackHarnessId": AGENT_PLAYER_2_ID,
                        },
                    ),
                    (
                        "/api/positional-testing/runs",
                        {"positionId": POSITION, "harnessId": AGENT_PLAYER_2_ID},
                    ),
                    (
                        "/api/positional-testing/queues",
                        {
                            "datasetVersion": "v1",
                            "split": "train",
                            "harnessId": AGENT_PLAYER_2_ID,
                        },
                    ),
                    (f"/api/positional-testing/queues/{POSITION}/retry-failed", None),
                ]
                for url, payload in conflicting:
                    response = await client.post(url, json=payload)
                    assert response.status_code == 409, (url, response.text)
                stopped = await client.post("/api/grpo/runs/collection/stop")
                assert stopped.status_code == 200
                await asyncio.wait_for(service.task, timeout=5)
                final = (await client.get("/api/grpo/runs/collection")).json()
                assert final["status"] == "stopped"
                assert final["stopping"] is False
                assert len(instances) == 1
                assert (await client.get("/api/grpo/status")).json()[
                    "activeRun"
                ] is None
                assert (
                    await client.post("/api/grpo/runs/missing/stop")
                ).status_code == 404
                invalid = await client.post(
                    "/api/grpo/runs", json={**body, "name": "../invalid"}
                )
                assert invalid.status_code == 422
            finally:
                await service.close()

    asyncio.run(scenario())

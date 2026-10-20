"""One durable, sequential positional queue, independent of browser requests."""

import asyncio
import logging
import os
from contextlib import suppress

from starlette.concurrency import run_in_threadpool

from app.matches.catalog import AGENT_PLAYER_2_ID
from app.models import ModelSelection

from .catalog import InvalidSavedPositionError
from .models import CodexQueueSelection
from .queue_repository import (
    EmptyPositionSetError,
    QueueConflictError,
    QueueRepository,
    UnknownQueueError,
)
from .runner import UnknownSavedPositionError

logger = logging.getLogger(__name__)


class PositionQueueManager:
    def __init__(
        self, runner, catalog, *, repository=None, item_timeout=None, codex_jobs=None
    ):
        self.runner = runner
        self.catalog = catalog
        self.codex_jobs = codex_jobs
        self.repository = repository or QueueRepository()
        self.item_timeout = (
            item_timeout
            if item_timeout is not None
            else float(os.getenv("POSITION_QUEUE_ITEM_TIMEOUT_SECONDS", "1800"))
        )
        if self.item_timeout <= 0:
            raise ValueError("Queue item timeout must be positive.")
        self._task = None
        self._wake = asyncio.Event()

    def start(self):
        self._task = asyncio.create_task(self.serve(), name="position-queue")

    async def close(self):
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def enqueue(self, request):
        if request.harness_id == "codex-training":
            worker = self.ready_codex_worker()
            definition = self.catalog.definition(AGENT_PLAYER_2_ID).model_copy(
                update={"name": "Codex (training)"}
            )
            selection = CodexQueueSelection(
                model_name=worker["model"], reasoning_effort=worker["reasoning_effort"]
            )
        else:
            definition = self.catalog.definition(request.harness_id)
            selection = await self.catalog.pin_model_selection(
                request.model_selection or ModelSelection(model_id="qwen")
            )
        row = await run_in_threadpool(
            self.repository.enqueue,
            name=request.name,
            dataset_version=request.dataset_version,
            split=request.split,
            definition=definition,
            model_selection=selection,
        )
        self._wake.set()
        return row

    def ready_codex_worker(self):
        if not self.codex_jobs or not self.codex_jobs.online():
            raise QueueConflictError("Start the Windows Codex worker, then try again.")
        if self.codex_jobs.active_jobs():
            raise QueueConflictError(
                "Finish or stop the current Codex training run first."
            )
        return self.codex_jobs.status()

    async def retry_failed(self, queue_id):
        source = await run_in_threadpool(self.repository.get_queue, queue_id)
        if source is None:
            raise UnknownQueueError("The original queue no longer exists.")
        if source["status"] not in {"completed", "stopped"}:
            raise QueueConflictError(
                "Finish or stop the original queue before retrying its failures."
            )
        if not source["failed"]:
            raise EmptyPositionSetError("This queue has no failed positions to retry.")
        self.catalog.definition(source["harness_id"])
        if source["model_selection"]["model_id"] == "codex":
            self.ready_codex_worker()
            CodexQueueSelection.model_validate(source["model_selection"])
        else:
            await self.catalog.pin_model_selection(
                ModelSelection.model_validate(source["model_selection"])
            )
        row = await run_in_threadpool(
            self.repository.retry_failed,
            queue_id,
        )
        self._wake.set()
        return row

    async def _wait(self, seconds=2):
        with suppress(TimeoutError):
            await asyncio.wait_for(self._wake.wait(), seconds)
        self._wake.clear()

    async def serve(self):
        lease = None
        try:
            while True:
                try:
                    if lease is None:
                        lease = await run_in_threadpool(self.repository.acquire_worker)
                        if lease is None:
                            await self._wait()
                            continue
                        await run_in_threadpool(self.repository.recover)
                    # Detect a dropped lease before claiming another position.
                    await run_in_threadpool(lease.execute, "SELECT 1")
                    claimed = await run_in_threadpool(
                        self.repository.claim_next,
                        codex_ready=bool(
                            self.codex_jobs
                            and self.codex_jobs.online()
                            and not self.codex_jobs.active_jobs()
                        ),
                    )
                    if claimed is None:
                        await self._wait()
                    else:
                        await self.execute_item(*claimed)
                except Exception:
                    # Persistence failures pause consumption. Recovery reconciles
                    # the unfinished item before taking another when DB returns.
                    logger.exception(
                        "Position queue paused; retrying database connection"
                    )
                    if lease is not None:
                        await run_in_threadpool(lease.close)
                        lease = None
                    await self._wait(5)
        finally:
            if lease is not None:
                await run_in_threadpool(lease.close)

    async def execute_item(self, queue, item):
        run_id = str(item["run_id"])
        error = failure_stage = None
        try:
            async with asyncio.timeout(self.item_timeout):
                if queue["model_selection"]["model_id"] == "codex":
                    await self.execute_codex(queue, item)
                else:
                    await self.runner.run_once(
                        str(item["position_id"]),
                        queue["harness_id"],
                        ModelSelection.model_validate(queue["model_selection"]),
                        queued_run_id=run_id,
                    )
                run = await run_in_threadpool(self.runner.repository.get, run_id)
                evaluation = (run or {}).get("evaluation") or {}
                if evaluation.get("status") != "completed":
                    failure_stage = "evaluation"
                    error = (
                        evaluation.get("error")
                        or "The move was saved but evaluation did not finish."
                    )
        except asyncio.CancelledError:
            # Shutdown preserves the failed attempt. The next worker continues
            # with unstarted positions; it never silently retries a paid call.
            await run_in_threadpool(
                self.repository.finish_item,
                run_id,
                error="Worker interrupted before this position finished.",
                failure_stage="interrupted",
            )
            raise
        except TimeoutError:
            failure_stage = "timeout"
            error = f"Position exceeded the {self.item_timeout:g}-second time limit."
        except (UnknownSavedPositionError, InvalidSavedPositionError) as exc:
            failure_stage, error = "position", str(exc)
        except Exception as exc:
            failure_stage = "execution"
            error = str(exc) or type(exc).__name__
        await run_in_threadpool(
            self.repository.finish_item,
            run_id,
            error=error,
            failure_stage=failure_stage,
        )

    async def execute_codex(self, queue, item):
        run_id = str(item["run_id"])
        training = self.codex_jobs.training
        try:
            await self.codex_jobs.enqueue(
                str(item["position_id"]),
                queued_run_id=run_id,
                queue_tag=queue["id"],
                selection=queue["model_selection"],
            )
            # Queue timeouts/shutdown must cleanly stop the independent teacher task.
            await asyncio.shield(training.tasks[run_id])
            session = training.sessions[run_id]
            if session.result is None:
                raise RuntimeError(
                    session.error or "Codex training did not submit a move."
                )
        finally:
            if run_id in training.sessions and not training.tasks[run_id].done():
                await training.stop(training.sessions[run_id])

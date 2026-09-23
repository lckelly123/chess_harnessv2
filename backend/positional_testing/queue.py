"""One durable, sequential positional queue, independent of browser requests."""

import asyncio
import logging
import os
from contextlib import suppress

from starlette.concurrency import run_in_threadpool

from app.models import ModelSelection

from .catalog import InvalidSavedPositionError
from .queue_repository import QueueRepository
from .runner import UnknownSavedPositionError

logger = logging.getLogger(__name__)


class PositionQueueManager:
    def __init__(self, runner, catalog, *, repository=None, item_timeout=None):
        self.runner = runner
        self.catalog = catalog
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
        definition = self.catalog.definition(request.harness_id)
        row = await run_in_threadpool(
            self.repository.enqueue,
            dataset_version=request.dataset_version,
            split=request.split,
            definition=definition,
            model_selection=request.model_selection or ModelSelection(model_id="qwen"),
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
                    claimed = await run_in_threadpool(self.repository.claim_next)
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
        queue_id, ordinal = str(queue["id"]), item["ordinal"]
        error = failure_stage = None
        try:
            async with asyncio.timeout(self.item_timeout):
                result = await self.runner.run_once(
                    str(item["position_id"]),
                    queue["harness_id"],
                    ModelSelection.model_validate(queue["model_selection"]),
                    queue_item=(queue_id, ordinal),
                )
                run = await run_in_threadpool(self.runner.repository.get, result.run_id)
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
                queue_id,
                ordinal,
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
            queue_id,
            ordinal,
            error=error,
            failure_stage=failure_stage,
        )

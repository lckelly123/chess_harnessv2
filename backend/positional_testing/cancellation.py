"""Turn-scoped cancellation without cancelling a queue or abandoning DB writes."""

import asyncio

from starlette.concurrency import run_in_threadpool


class RunDiscardedError(Exception):
    """The user cancelled this attempt and requested removal of its history."""


class RunConflictError(ValueError):
    """A caller-supplied run identifier already belongs to another attempt."""


class RunControl:
    def __init__(self, on_cancel=None):
        self.cancelled = asyncio.Event()
        self.finished = asyncio.Event()
        self.recorder = None
        self.on_cancel = on_cancel
        self.discard_error = None
        self.cleanup = None
        self._retry_lock = asyncio.Lock()

    def check(self):
        if self.cancelled.is_set():
            raise RunDiscardedError("Run cancelled and discarded.")

    async def discard(self):
        if self.finished.is_set() and self.discard_error is not None:
            async with self._retry_lock:
                if self.discard_error is not None:
                    try:
                        await self.cleanup()
                    except Exception as exc:
                        self.discard_error = exc
                        raise
                    self.discard_error = None
            return
        if not self.cancelled.is_set():
            self.cancelled.set()
            if self.on_cancel is not None:
                self.on_cancel()
        # A disconnected browser must not abandon the actual cancellation.
        await asyncio.shield(self.finished.wait())
        if self.discard_error is not None:
            raise self.discard_error

    async def wait(self, operation):
        """Interrupt model/evaluation I/O; ordinary DB operations finish normally."""
        task = asyncio.create_task(operation)
        stop = asyncio.create_task(self.cancelled.wait())
        try:
            await asyncio.wait({task, stop}, return_when=asyncio.FIRST_COMPLETED)
            if self.cancelled.is_set():
                # Sync graph nodes can outlive a cancelled asyncio task. Disable
                # their recorder, draining its current write before deleting rows.
                if self.recorder is not None:
                    await run_in_threadpool(self.recorder.discard)
                raise RunDiscardedError("Run cancelled and discarded.")
            return await task
        finally:
            stop.cancel()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, stop, return_exceptions=True)

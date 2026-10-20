"""Manage external runs while reusing the positional runner and its DB recorder."""

import asyncio
import logging
from uuid import uuid4

from starlette.concurrency import run_in_threadpool

from app.matches.catalog import AGENT_PLAYER_2_ID, HarnessCatalog
from positional_testing.catalog import get_saved_position
from positional_testing.runner import PositionalTestRunner, UnknownSavedPositionError

from . import PROTOCOL_VERSION, PROVIDER
from .bridge import TERMINAL, RunSession
from .provider import CodexModel
from .teacher import teacher_metadata


class RunCapacityError(ValueError):
    """Too many external runs are waiting on this backend."""


class CodexTrainingService:
    """Single-backend-process bridge. Finished traces live in the normal database."""

    def __init__(self, repository, evaluator, *, max_active=4):
        self.repository = repository
        self.evaluator = evaluator
        self.max_active = max_active
        self.sessions: dict[str, RunSession] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()
        self._recovered = False
        self._closed = False

    async def start(
        self,
        position_id: str,
        *,
        model_label: str,
        pass_timeout: float,
        metadata: dict | None = None,
        queued_run_id: str | None = None,
    ):
        if await run_in_threadpool(get_saved_position, position_id) is None:
            raise UnknownSavedPositionError(f"Unknown saved position: {position_id}")
        async with self._lock:
            if self._closed:
                raise RunCapacityError("The backend is shutting down.")
            if not self._recovered:
                await run_in_threadpool(self.repository.recover_codex_training)
                self._recovered = True
            if sum(not task.done() for task in self.tasks.values()) >= self.max_active:
                raise RunCapacityError("Finish or stop an active Codex run first.")
            # Retain recent acknowledgements for retries, without retaining all
            # finished sessions forever. Database history is independent of this cache.
            for run_id in list(self.sessions):
                if len(self.sessions) < 128:
                    break
                if self.tasks[run_id].done():
                    del self.tasks[run_id]
                    del self.sessions[run_id]
            session = RunSession(
                queued_run_id or str(uuid4()), pass_timeout=pass_timeout
            )
            session.position_id = position_id
            session.metadata = metadata or {}
            self.sessions[session.run_id] = session
            self.tasks[session.run_id] = asyncio.create_task(
                self._run(session, position_id, model_label, queued_run_id),
                name=f"codex-training-{session.run_id}",
            )
        # Usually returns the first input immediately; slow startup stays observable.
        await session.current(10)
        return session

    def authenticated(self, run_id: str, token: str) -> RunSession:
        session = self.sessions.get(run_id)
        if session is None:
            raise KeyError(
                "No live bridge session for this run. See saved run history."
            )
        session.token_scope(token)
        return session

    async def _run(
        self,
        session: RunSession,
        position_id: str,
        model_label: str,
        queued_run_id: str | None = None,
    ):
        async def resolve_model():
            return model_label

        catalog = HarnessCatalog(
            CodexModel(session),
            model_resolver=resolve_model,
            model_provider=PROVIDER,
        )
        runner = PositionalTestRunner(
            catalog,
            id_factory=lambda: session.run_id,
            repository=self.repository,
            evaluator=self.evaluator,
        )
        try:
            result = await runner.run_once(
                position_id,
                AGENT_PLAYER_2_ID,
                queued_run_id=queued_run_id,
                config_metadata={
                    "provider": PROVIDER,
                    "capture_scope": "harness_exchange",
                    "model_identity_source": "caller_label",
                    "bridge_protocol": PROTOCOL_VERSION,
                    "pass_timeout_seconds": session.pass_timeout,
                    **teacher_metadata(),
                    **session.metadata,
                },
                cancellation_check=lambda: session.cancel_requested,
            )
            stored = await run_in_threadpool(self.repository.get, session.run_id)
            session.result = result.model_dump(mode="json", by_alias=True)
            session.finish(
                stored["status"], error=stored["error"], move=result.move.uci
            )
        except asyncio.CancelledError:
            session.finish("cancelled", error="Codex training run stopped.")
        except Exception as exc:
            session.finish(
                "cancelled" if session.cancel_requested else "failed",
                error=session.stop_error
                if session.cancel_requested
                else str(exc) or "Codex training run failed.",
            )
            logging.getLogger(__name__).warning(
                "Codex run %s failed: %s", session.run_id, session.error
            )

    async def stop(self, session: RunSession):
        if session.status not in TERMINAL:
            # Wake a waiting provider, or let the next harness cancellation check
            # stop execution. Do not abandon an in-flight database write/thread.
            session.cancel()
            await self.tasks[session.run_id]
        return session.snapshot()

    async def close(self):
        async with self._lock:
            self._closed = True
            sessions = list(self.sessions.values())
        await asyncio.gather(*(self.stop(s) for s in sessions))

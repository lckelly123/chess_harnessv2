"""A collection owns one frozen worker session and ten sequential fresh turns."""

import asyncio
import logging
import secrets
from contextlib import suppress
from dataclasses import asdict
from uuid import uuid4

from starlette.concurrency import run_in_threadpool

from app.matches.catalog import AGENT_PLAYER_2_ID, HarnessCatalog
from harness.agent_player_2.config import AgentConfig
from positional_testing.catalog import get_saved_position
from positional_testing.runner import PositionalTestRunner, UnknownSavedPositionError

from .client import CaptureClient, CaptureModel, CaptureUnavailable
from .recording import GrpoRecorder
from .storage import CollectionStore

logger = logging.getLogger(__name__)


class CollectionConflict(ValueError):
    pass


class GrpoService:
    def __init__(self, runner, catalog, *, store=None, client=None, busy_check=None):
        self.runner, self.catalog = runner, catalog
        self.store, self.client = store or CollectionStore(), client or CaptureClient()
        self.busy_check = busy_check
        self.task = None
        self.active_name = self.session_id = None
        self.stopped = asyncio.Event()
        self._lock = asyncio.Lock()
        self.store.recover()

    @property
    def active(self):
        return self.task is not None and not self.task.done()

    async def status(self):
        try:
            health = await self.client.health()
            online = bool(health.get("ready", True))
            message = None if online else "The GRPO capture worker is not ready."
            if (health.get("busy") or health.get("session_id")) and not self.active:
                online = False
                message = "The capture worker has another session. Finish it or restart the worker."
        except CaptureUnavailable as exc:
            online, message = False, str(exc)
        group = (
            await run_in_threadpool(self.store.get, self.active_name)
            if self.active_name
            else None
        )
        return {
            "workerOnline": online,
            "workerMessage": message,
            "activeRun": group if self.active else None,
        }

    async def start(self, request):
        async with self._lock:
            if self.active or self.runner.active_runs:
                raise CollectionConflict(
                    "Finish the active run before starting a GRPO collection."
                )
            if (
                request.harness_id != AGENT_PLAYER_2_ID
                or request.model_selection.model_id != "unsloth"
            ):
                raise ValueError(
                    "Save for GRPO currently requires Unsloth and chess_harness."
                )
            model_name = request.model_selection.model_name
            if not model_name:
                raise ValueError("Select the exact QLoRA adapter before starting.")
            if self.store.path(request.name).exists():
                raise CollectionConflict(
                    "That run folder already exists. Choose a new run name."
                )
            document = await run_in_threadpool(get_saved_position, request.position_id)
            if document is None:
                raise UnknownSavedPositionError(
                    "The selected position no longer exists."
                )
            health = await self.client.health()
            if (
                health.get("busy")
                or health.get("session_id")
                or not health.get("ready", True)
            ):
                raise CollectionConflict(
                    "The GRPO capture worker is busy or not ready."
                )
            if self.runner.active_runs or (self.busy_check and await self.busy_check()):
                raise CollectionConflict(
                    "Finish active matches, runs and queues before GRPO capture."
                )
            seed = secrets.randbelow(1_000_000_000)
            definition = self.catalog.definition(request.harness_id)
            group = await run_in_threadpool(
                self.store.create,
                request.name,
                request.position_id,
                request.harness_id,
                model_name,
                seed=seed,
                position={
                    "position_id": request.position_id,
                    "fen": document.position.position.fen,
                    "pgn": document.pgn,
                },
                harness={
                    **definition.model_dump(mode="json"),
                    "execution_config": asdict(
                        AgentConfig(
                            model=model_name,
                            provider="unsloth",
                            reasoning_effort=request.model_selection.reasoning_effort,
                        )
                    ),
                },
            )
            self.active_name, self.session_id = request.name, str(uuid4())
            self.stopped = asyncio.Event()
            self.task = asyncio.create_task(
                self._collect(request, seed), name=f"grpo-{request.name}"
            )
            return group

    async def _collect(self, request, seed):
        name, session_id = request.name, self.session_id
        status, error = "completed", None
        current, recorder = None, None
        try:
            await self.client.unload_studio(request.model_selection.model_name)
            if self.stopped.is_set():
                status = "stopped"
                return
            prepared = await self.client.prepare(
                request.model_selection.model_name, session_id
            )
            if prepared.get("session_id") != session_id:
                raise CaptureUnavailable(
                    "Capture worker returned a different policy session."
                )
            await run_in_threadpool(
                self.store.update,
                name,
                metadata={**prepared["metadata"], "session_id": session_id},
                status="running",
            )
            model = CaptureModel(self.client, session_id, seed, self.stopped)
            catalog = HarnessCatalog(model, unsloth_model=model)
            for current in range(1, 11):
                if self.stopped.is_set():
                    status = "stopped"
                    current = None
                    break
                await run_in_threadpool(
                    self.store.update,
                    name,
                    trajectory=current,
                    trajectory_status="running",
                    currentTrajectory=current,
                    currentCall=0,
                )
                model.seed = seed + current * 100000

                def make_recorder(repository, run_id):
                    nonlocal recorder
                    recorder = GrpoRecorder(
                        repository, run_id, self.store, name, current
                    )
                    return recorder

                runner = PositionalTestRunner(
                    catalog,
                    repository=self.runner.repository,
                    evaluator=self.runner.evaluator,
                    active_runs=self.runner.active_runs,
                    recorder_factory=make_recorder,
                )
                run_id = str(uuid4())
                trajectory_status, cp_loss = "completed", None
                try:
                    await runner.run_once(
                        request.position_id,
                        request.harness_id,
                        request.model_selection,
                        run_id=run_id,
                        cancellation_check=self.stopped.is_set,
                        config_metadata={
                            "grpo_collection": name,
                            "trajectory": current,
                        },
                    )
                    row = await run_in_threadpool(self.runner.repository.get, run_id)
                    if row is None or row["status"] != "completed":
                        trajectory_status = "failed"
                    if row:
                        cp_loss = row.get("cp_loss")
                except asyncio.CancelledError:
                    raise
                except Exception:
                    trajectory_status = "failed"
                    logger.exception("GRPO %s trajectory %s failed", name, current)
                finally:
                    if recorder is not None:
                        await run_in_threadpool(recorder.flush)
                if self.stopped.is_set():
                    trajectory_status, status = "stopped", "stopped"
                await run_in_threadpool(
                    self.store.update,
                    name,
                    trajectory=current,
                    trajectory_status=trajectory_status,
                    cp_loss=cp_loss,
                )
                if model.failure:
                    raise CaptureUnavailable(model.failure)
                if self.stopped.is_set():
                    break
        except asyncio.CancelledError:
            status, error = (
                "interrupted",
                "Backend stopped. Captured calls have been preserved.",
            )
            if current:
                await run_in_threadpool(
                    self.store.update,
                    name,
                    trajectory=current,
                    trajectory_status="interrupted",
                )
        except Exception as exc:
            status, error = "failed", str(exc) or "Collection failed."
            logger.exception("GRPO collection %s failed", name)
            if current:
                await run_in_threadpool(
                    self.store.update,
                    name,
                    trajectory=current,
                    trajectory_status="failed",
                )
        finally:
            try:
                await self.client.release(session_id)
            except Exception:
                logger.exception("Could not release GRPO worker session %s", session_id)
            await run_in_threadpool(
                self.store.update, name, status=status, error=error, stopping=False
            )

    async def stop(self, name):
        group = await run_in_threadpool(self.store.get, name)
        if not self.active or self.active_name != name:
            return group
        self.stopped.set()
        await run_in_threadpool(self.store.update, name, stopping=True)
        try:
            await self.client.cancel(self.session_id)
        except CaptureUnavailable:
            # Preparing sessions can be stopped between unload and prepare.
            logger.warning("GRPO cancellation signal could not reach the worker")
        return await run_in_threadpool(self.store.get, name)

    async def close(self):
        if self.active:
            await self.stop(self.active_name)
            try:
                await asyncio.wait_for(asyncio.shield(self.task), timeout=45)
            except TimeoutError:
                self.task.cancel()
                with suppress(asyncio.CancelledError):
                    await self.task
        await self.client.close()

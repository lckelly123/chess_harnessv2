"""Public local UI controls and authenticated worker-only dispatch endpoints."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from positional_testing.catalog import PositionLibraryUnavailableError
from positional_testing.runner import UnknownSavedPositionError

from .service import RunCapacityError

router = APIRouter(prefix="/api/codex-training", tags=["codex training"])


class WorkerIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worker_id: UUID


class Heartbeat(WorkerIdentity):
    model: str = Field(min_length=1, max_length=240, pattern=r"^[A-Za-z0-9_.:/-]+$")
    reasoning_effort: Literal["low", "medium", "high", "xhigh", "max", "ultra"]
    cli_version: str = Field(min_length=1, max_length=100)


class StartJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position_id: UUID


class Progress(WorkerIdentity):
    progress: str = Field(min_length=1, max_length=240)
    error: str | None = Field(default=None, max_length=2000)


def jobs(request, authorization=None, *, authenticate=False):
    manager = request.app.state.codex_jobs
    if authenticate:
        try:
            manager.authenticate(authorization)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
    return manager


@router.get("/worker")
async def worker_status(request: Request):
    return jobs(request).status()


@router.post("/worker/heartbeat")
async def heartbeat(
    body: Heartbeat,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
):
    try:
        return jobs(request, authorization, authenticate=True).heartbeat(
            body.model_dump(mode="json")
        )
    except RunCapacityError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/worker/claim")
async def claim(
    body: WorkerIdentity,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
):
    try:
        return {
            "job": jobs(request, authorization, authenticate=True).claim(
                str(body.worker_id)
            )
        }
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc


@router.post("/jobs", status_code=202)
async def start_job(body: StartJob, request: Request):
    try:
        return await jobs(request).enqueue(str(body.position_id))
    except RunCapacityError as exc:
        raise HTTPException(409, str(exc)) from exc
    except UnknownSavedPositionError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PositionLibraryUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/jobs/{run_id}")
async def get_job(run_id: UUID, request: Request):
    try:
        return jobs(request).snapshot(str(run_id))
    except KeyError as exc:
        raise HTTPException(404, exc.args[0]) from exc


@router.post("/jobs/{run_id}/stop", status_code=202)
async def stop_job(run_id: UUID, request: Request):
    manager = jobs(request)
    await get_job(run_id, request)
    manager.training.sessions[str(run_id)].cancel()
    return manager.snapshot(str(run_id))


@router.post("/jobs/{run_id}/progress")
async def progress(
    run_id: UUID,
    body: Progress,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
):
    manager = jobs(request, authorization, authenticate=True)
    try:
        manager.report(
            str(run_id), str(body.worker_id), progress=body.progress, error=body.error
        )
        return manager.snapshot(str(run_id))
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, exc.args[0]) from exc

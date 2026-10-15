"""Local control endpoints; MCP receives a credential scoped to one run."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from positional_testing.catalog import PositionLibraryUnavailableError
from positional_testing.runner import UnknownSavedPositionError

from .bridge import SubmissionConflict
from .service import CodexTrainingService, RunCapacityError

router = APIRouter(prefix="/api/codex-training", tags=["codex training"])


class StartRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position_id: UUID
    model_label: str = Field(default="codex-external", min_length=1, max_length=240)
    pass_timeout_seconds: float = Field(default=900, ge=1, le=7200)


class SubmitResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pass_id: UUID
    response: str = Field(min_length=1, max_length=256_000, strict=True)
    reasoning_text: str = Field(min_length=1, max_length=16_000, strict=True)

    @field_validator("reasoning_text")
    @classmethod
    def explanation_is_plain_text(cls, value):
        if not value.strip() or "<think>" in value or "</think>" in value:
            raise ValueError("Provide a non-empty explanation without think tags.")
        return value


def service(request: Request) -> CodexTrainingService:
    return request.app.state.codex_training


def session(request: Request, run_id: UUID, authorization: str | None):
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="A run token is required.")
    try:
        return service(request).authenticated(str(run_id), authorization[7:])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=exc.args[0]) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/runs", status_code=202)
async def start_run(body: StartRun, request: Request):
    if not body.model_label.strip():
        raise HTTPException(status_code=422, detail="Model label cannot be blank.")
    try:
        active = await service(request).start(
            str(body.position_id),
            model_label=body.model_label,
            pass_timeout=body.pass_timeout_seconds,
        )
    except UnknownSavedPositionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RunCapacityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PositionLibraryUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {**active.scoped_snapshot(None), "run_token": active.token}


@router.get("/runs/{run_id}/pass")
async def current_pass(
    run_id: UUID,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    wait_seconds: float = Query(default=0, ge=0, le=25),
):
    active = session(request, run_id, authorization)
    scope = active.token_scope(authorization[7:])
    if scope is None:
        await active.current(wait_seconds)
    return active.scoped_snapshot(scope)


@router.post("/runs/{run_id}/response")
async def submit_response(
    run_id: UUID,
    body: SubmitResponse,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    wait_seconds: float = Query(default=25, ge=0, le=25),
):
    active = session(request, run_id, authorization)
    scope = active.token_scope(authorization[7:])
    if scope is not None and scope != str(body.pass_id):
        raise HTTPException(status_code=403, detail="This token is scoped to one pass.")
    try:
        first_submission = active.submit(
            str(body.pass_id), body.response, body.reasoning_text
        )
    except SubmissionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if scope is None:
        await active.current(wait_seconds)
    return {
        **active.scoped_snapshot(scope),
        "accepted_pass_id": str(body.pass_id),
        "duplicate": not first_submission,
    }


@router.post("/runs/{run_id}/stop")
async def stop_run(
    run_id: UUID,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
):
    active = session(request, run_id, authorization)
    if active.token_scope(authorization[7:]) is not None:
        raise HTTPException(status_code=403, detail="A run token is required to stop.")
    return await service(request).stop(active)

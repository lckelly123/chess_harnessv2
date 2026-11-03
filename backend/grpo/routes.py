"""Collection controls; training is deliberately outside this API."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, field_validator
from starlette.concurrency import run_in_threadpool

from app.models import ModelSelection
from positional_testing.catalog import PositionLibraryUnavailableError
from positional_testing.models import PositionalTestingModel
from positional_testing.runner import UnknownSavedPositionError

from .client import CaptureUnavailable
from .service import CollectionConflict
from .storage import valid_name

router = APIRouter(prefix="/api/grpo", tags=["GRPO collection"])


class StartCollection(PositionalTestingModel):
    name: str
    position_id: str = Field(min_length=1, max_length=240)
    harness_id: str = Field(min_length=1, max_length=120)
    model_selection: ModelSelection

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value):
        return valid_name(value)


def require_idle(request):
    service = getattr(request.app.state, "grpo", None)
    if service is not None and service.active:
        raise HTTPException(
            409, "Finish or stop the GRPO collection before starting another run."
        )


@router.get("/status")
async def status(request: Request):
    return await request.app.state.grpo.status()


@router.post("/runs", status_code=202)
async def start(body: StartCollection, request: Request):
    try:
        return await request.app.state.grpo.start(body)
    except (CollectionConflict, FileExistsError) as exc:
        raise HTTPException(409, str(exc)) from exc
    except UnknownSavedPositionError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (CaptureUnavailable, PositionLibraryUnavailableError) as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            503,
            "Could not create the collection in RL_testing. Check its storage mount and permissions.",
        ) from exc


@router.get("/runs/{name}")
async def get(name: str, request: Request):
    try:
        return await run_in_threadpool(request.app.state.grpo.store.get, name)
    except FileNotFoundError as exc:
        raise HTTPException(404, "GRPO collection not found.") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/runs/{name}/stop")
async def stop(name: str, request: Request):
    try:
        return await request.app.state.grpo.stop(name)
    except FileNotFoundError as exc:
        raise HTTPException(404, "GRPO collection not found.") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

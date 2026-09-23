"""HTTP routes for saved positional tests and one-turn harness runs."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.matches.catalog import UnknownHarnessError
from harness.contracts import HarnessError
from harness.model import ModelResolutionError

from .catalog import (
    InvalidSavedPositionError,
    PositionLibraryUnavailableError,
    list_saved_positions,
)
from .models import (
    CreatePositionQueueRequest,
    ModelRunDetail,
    ModelRunList,
    PositionQueueDetail,
    PositionQueueList,
    RunSavedPositionRequest,
    SavedPositionList,
    SavedPositionRun,
)
from .queue_repository import EmptyPositionSetError, QueueConflictError
from .runner import PositionalTestRunner, UnknownSavedPositionError

router = APIRouter(prefix="/api/positional-testing", tags=["positional testing"])


def _runner(request: Request) -> PositionalTestRunner:
    return request.app.state.positional_test_runner


@router.get("/queues", response_model=PositionQueueList)
def list_queues(request: Request) -> PositionQueueList:
    try:
        return PositionQueueList(
            items=request.app.state.position_queue.repository.list_queues()
        )
    except PositionLibraryUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/queues", response_model=PositionQueueDetail, status_code=202)
async def create_queue(request_body: CreatePositionQueueRequest, request: Request):
    try:
        return await request.app.state.position_queue.enqueue(request_body)
    except QueueConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (UnknownHarnessError, EmptyPositionSetError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PositionLibraryUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/queues/{queue_id}", response_model=PositionQueueDetail)
def get_queue(queue_id: UUID, request: Request):
    try:
        row = request.app.state.position_queue.repository.get_queue(queue_id)
    except PositionLibraryUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Queue not found.")
    return row


@router.post("/queues/{queue_id}/stop", response_model=PositionQueueDetail)
def stop_queue(queue_id: UUID, request: Request):
    try:
        row = request.app.state.position_queue.repository.stop(queue_id)
    except PositionLibraryUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Queue not found.")
    return row


@router.get("/runs", response_model=ModelRunList)
def list_model_runs(
    request: Request,
    position_id: UUID | None = None,
    run_id: UUID | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ModelRunList:
    try:
        items, total = _runner(request).repository.list(
            position_id,
            run_id,
            limit=limit,
            offset=offset,
        )
        return ModelRunList(items=items, total=total)
    except PositionLibraryUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/runs/{run_id}", response_model=ModelRunDetail)
def get_model_run(run_id: UUID, request: Request) -> ModelRunDetail:
    try:
        row = _runner(request).repository.get(run_id)
    except PositionLibraryUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return ModelRunDetail(**row)


@router.get("/positions", response_model=SavedPositionList)
def get_saved_positions() -> SavedPositionList:
    try:
        return SavedPositionList(items=list_saved_positions())
    except PositionLibraryUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except InvalidSavedPositionError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.post("/runs", response_model=SavedPositionRun)
async def run_saved_position(
    request_body: RunSavedPositionRequest,
    request: Request,
) -> SavedPositionRun:
    try:
        return await _runner(request).run_once(
            request_body.position_id,
            request_body.harness_id,
            model_selection=request_body.model_selection,
        )
    except UnknownSavedPositionError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PositionLibraryUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except UnknownHarnessError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except ModelResolutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except HarnessError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except InvalidSavedPositionError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

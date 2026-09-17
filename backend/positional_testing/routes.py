"""HTTP routes for saved positional tests and one-turn harness runs."""

from fastapi import APIRouter, HTTPException, Request, status

from app.matches.catalog import UnknownHarnessError
from harness.contracts import HarnessError
from harness.model import ModelResolutionError

from .catalog import InvalidSavedPositionError, list_saved_positions
from .models import RunSavedPositionRequest, SavedPositionList, SavedPositionRun
from .runner import PositionalTestRunner, UnknownSavedPositionError

router = APIRouter(prefix="/api/positional-testing", tags=["positional testing"])


def _runner(request: Request) -> PositionalTestRunner:
    return request.app.state.positional_test_runner


@router.get("/positions", response_model=SavedPositionList)
def get_saved_positions() -> SavedPositionList:
    try:
        return SavedPositionList(items=list_saved_positions())
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

"""Thin HTTP boundary over the match manager and repository."""

import os

from fastapi import APIRouter, HTTPException, Query, Request, status

from harness.model import ModelResolutionError

from .matches.catalog import UnknownHarnessError
from .matches.manager import MatchConflictError, MatchManager
from .matches.repository import FolderNameConflictError, UnknownFolderError
from .models import (
    AssignGameFolderRequest,
    CreateGameFolderRequest,
    GameFolder,
    GameFolderList,
    HarnessVersion,
    HealthResponse,
    MatchDetail,
    MatchList,
    StartMatchRequest,
)

router = APIRouter(prefix="/api")


def _manager(request: Request) -> MatchManager:
    return request.app.state.match_manager


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        data_source="sqlite",
        model_selection=(
            "explicit"
            if os.getenv("LMSTUDIO_MODEL", "").strip()
            else "loaded-model-discovery"
        ),
    )


@router.get("/harnesses", response_model=list[HarnessVersion])
def list_harnesses(request: Request) -> list[HarnessVersion]:
    return _manager(request).catalog.list()


@router.get("/folders", response_model=GameFolderList)
def list_folders(request: Request) -> GameFolderList:
    return _manager(request).repository.list_folders()


@router.post("/folders", response_model=GameFolder, status_code=status.HTTP_201_CREATED)
def create_folder(
    request_body: CreateGameFolderRequest, request: Request
) -> GameFolder:
    try:
        return _manager(request).repository.create_folder(request_body.name)
    except FolderNameConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.get("/matches", response_model=MatchList)
def list_matches(
    request: Request,
    query: str = Query(default="", max_length=100),
    folder_id: str | None = Query(default=None),
    unfiled_only: bool = Query(default=False),
) -> MatchList:
    if folder_id is not None and unfiled_only:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Choose either a folder or unfiled matches, not both.",
        )
    if folder_id is not None and not _manager(request).repository.folder_exists(
        folder_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Game folder not found"
        )
    return _manager(request).repository.list_matches(
        query,
        folder_id=folder_id,
        unfiled_only=unfiled_only,
    )


@router.get("/matches/{match_id}", response_model=MatchDetail)
def get_match(match_id: str, request: Request) -> MatchDetail:
    match = _manager(request).repository.get_match(match_id)
    if match is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Match not found"
        )
    return match


@router.post(
    "/matches", response_model=MatchDetail, status_code=status.HTTP_201_CREATED
)
async def start_match(request_body: StartMatchRequest, request: Request) -> MatchDetail:
    try:
        return await _manager(request).start(
            request_body.white_harness_id,
            request_body.black_harness_id,
            request_body.folder_id,
        )
    except (UnknownHarnessError, UnknownFolderError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except MatchConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except ModelResolutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@router.patch("/matches/{match_id}/folder", response_model=MatchDetail)
def assign_match_folder(
    match_id: str,
    request_body: AssignGameFolderRequest,
    request: Request,
) -> MatchDetail:
    try:
        match = _manager(request).repository.assign_match_folder(
            match_id, request_body.folder_id
        )
    except UnknownFolderError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    if match is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Match not found"
        )
    return match


@router.post("/matches/{match_id}/stop", response_model=MatchDetail)
async def stop_match(match_id: str, request: Request) -> MatchDetail:
    match = await _manager(request).stop(match_id)
    if match is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Match not found"
        )
    return match

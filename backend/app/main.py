from fastapi import FastAPI, HTTPException, Query, status

from .mock_data import HARNESSES, MATCHES, create_match
from .models import (
    HarnessVersion,
    HealthResponse,
    MatchDetail,
    MatchList,
    MatchSummary,
    StartMatchRequest,
)


app = FastAPI(
    title="Chess Harness v2 Mock API",
    version="0.1.0",
    description="An in-memory contract stub. It runs no chess engine or agent.",
)


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", data_source="mock")


@app.get("/api/harnesses", response_model=list[HarnessVersion])
def list_harnesses() -> list[HarnessVersion]:
    return HARNESSES


@app.get("/api/matches", response_model=MatchList)
def list_matches(query: str = Query(default="", max_length=100)) -> MatchList:
    needle = query.strip().lower()
    matches = sorted(MATCHES.values(), key=lambda item: item.started_at, reverse=True)
    if needle:
        matches = [
            match
            for match in matches
            if needle
            in " ".join(
                (
                    match.id,
                    match.white.name,
                    match.white.version,
                    match.black.name,
                    match.black.version,
                    match.status,
                    match.result or "",
                )
            ).lower()
        ]
    summaries = [MatchSummary.model_validate(match.model_dump()) for match in matches]
    return MatchList(items=summaries, total=len(summaries))


@app.get("/api/matches/{match_id}", response_model=MatchDetail)
def get_match(match_id: str) -> MatchDetail:
    match = MATCHES.get(match_id)
    if match is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match not found")
    return match


@app.post("/api/matches", response_model=MatchDetail, status_code=status.HTTP_201_CREATED)
def start_match(request: StartMatchRequest) -> MatchDetail:
    harness_ids = {harness.id for harness in HARNESSES}
    if request.white_harness_id not in harness_ids or request.black_harness_id not in harness_ids:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown harness version")
    return create_match(request.white_harness_id, request.black_harness_id)


@app.post("/api/matches/{match_id}/stop", response_model=MatchDetail)
def stop_match(match_id: str) -> MatchDetail:
    match = get_match(match_id)
    if match.status == "running":
        match.status = "stopped"
        match.result = "aborted"
        match.ended_at = match.started_at
        for event in match.traces:
            event.status = "complete"
    return match


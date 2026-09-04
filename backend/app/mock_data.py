from datetime import UTC, datetime, timedelta
from uuid import uuid4

from .models import HarnessVersion, MatchDetail, PlayerRef, PositionRecord, TraceEvent


HARNESSES = [
    HarnessVersion(
        id="agent-player-1-v1",
        name="Agent Player 1",
        version="v1.0",
        summary="Baseline tool-calling loop from the original harness.",
    ),
    HarnessVersion(
        id="agent-player-1-graph",
        name="Agent Player 1 Graph",
        version="v0.1",
        summary="Placeholder for the LangGraph state-machine rebuild.",
    ),
    HarnessVersion(
        id="material-baseline",
        name="Material Baseline",
        version="v0.2",
        summary="Deterministic mock opponent for harness smoke tests.",
    ),
]


POSITIONS = [
    PositionRecord(
        ply=0,
        fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        san="Start",
    ),
    PositionRecord(
        ply=1,
        fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        san="e4",
        player="white",
        from_square="e2",
        to_square="e4",
    ),
    PositionRecord(
        ply=2,
        fen="rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq c6 0 2",
        san="c5",
        player="black",
        from_square="c7",
        to_square="c5",
    ),
    PositionRecord(
        ply=3,
        fen="rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2",
        san="Nf3",
        player="white",
        from_square="g1",
        to_square="f3",
    ),
    PositionRecord(
        ply=4,
        fen="rnbqkbnr/pp2pppp/3p4/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 3",
        san="d6",
        player="black",
        from_square="d7",
        to_square="d6",
    ),
    PositionRecord(
        ply=5,
        fen="rnbqkbnr/pp2pppp/3p4/2p5/3PP3/5N2/PPP2PPP/RNBQKB1R b KQkq d3 0 3",
        san="d4",
        player="white",
        from_square="d2",
        to_square="d4",
    ),
    PositionRecord(
        ply=6,
        fen="rnbqkbnr/pp2pppp/3p4/8/3pP3/5N2/PPP2PPP/RNBQKB1R w KQkq - 0 4",
        san="cxd4",
        player="black",
        from_square="c5",
        to_square="d4",
    ),
    PositionRecord(
        ply=7,
        fen="rnbqkbnr/pp2pppp/3p4/8/3NP3/8/PPP2PPP/RNBQKB1R b KQkq - 0 4",
        san="Nxd4",
        player="white",
        from_square="f3",
        to_square="d4",
    ),
    PositionRecord(
        ply=8,
        fen="rnbqkb1r/pp2pppp/3p1n2/8/3NP3/8/PPP2PPP/RNBQKB1R w KQkq - 1 5",
        san="Nf6",
        player="black",
        from_square="g8",
        to_square="f6",
    ),
]


def player(harness_id: str, color: str) -> PlayerRef:
    harness = next(item for item in HARNESSES if item.id == harness_id)
    return PlayerRef(
        harness_id=harness.id,
        name=harness.name,
        version=harness.version,
        color=color,
    )


def traces(started_at: datetime, through_ply: int) -> list[TraceEvent]:
    phase_copy = {
        "observe": "Read the board snapshot and legal-move envelope.",
        "plan": "Compared candidate continuations from the current position.",
        "act": "Submitted the selected move to the match coordinator.",
        "verify": "Confirmed the authoritative position returned by the game service.",
    }
    events: list[TraceEvent] = []
    for position in POSITIONS[1 : through_ply + 1]:
        phase = ("observe", "plan", "act", "verify")[(position.ply - 1) % 4]
        events.append(
            TraceEvent(
                id=f"trace-{position.ply}",
                timestamp=started_at + timedelta(seconds=position.ply * 7),
                ply=position.ply,
                player=position.player or "white",
                phase=phase,
                status="active" if position.ply == through_ply else "complete",
                summary=f"{phase.title()} · {position.san}",
                detail=phase_copy[phase],
            )
        )
    return events


def make_match(
    match_id: str,
    white_id: str,
    black_id: str,
    status: str,
    result: str | None,
    started_at: datetime,
    through_ply: int,
) -> MatchDetail:
    selected_positions = [position.model_copy(deep=True) for position in POSITIONS[: through_ply + 1]]
    selected_traces = traces(started_at, through_ply)
    if status != "running":
        for event in selected_traces:
            event.status = "complete"
    return MatchDetail(
        id=match_id,
        white=player(white_id, "white"),
        black=player(black_id, "black"),
        status=status,
        result=result,
        started_at=started_at,
        ended_at=None if status == "running" else started_at + timedelta(minutes=14),
        current_fen=selected_positions[-1].fen,
        move_count=through_ply,
        last_move=selected_positions[-1].san if through_ply else None,
        positions=selected_positions,
        traces=selected_traces,
    )


now = datetime.now(UTC)
MATCHES: dict[str, MatchDetail] = {
    "match-live-001": make_match(
        "match-live-001",
        "agent-player-1-graph",
        "agent-player-1-v1",
        "running",
        None,
        now - timedelta(minutes=4),
        8,
    ),
    "match-2026-041": make_match(
        "match-2026-041",
        "agent-player-1-v1",
        "material-baseline",
        "completed",
        "1-0",
        now - timedelta(hours=3),
        8,
    ),
    "match-2026-040": make_match(
        "match-2026-040",
        "material-baseline",
        "agent-player-1-graph",
        "completed",
        "½-½",
        now - timedelta(days=1),
        7,
    ),
    "match-2026-039": make_match(
        "match-2026-039",
        "agent-player-1-graph",
        "agent-player-1-v1",
        "stopped",
        "aborted",
        now - timedelta(days=2),
        5,
    ),
}


def create_match(white_id: str, black_id: str) -> MatchDetail:
    match_id = f"match-mock-{uuid4().hex[:6]}"
    match = make_match(match_id, white_id, black_id, "running", None, datetime.now(UTC), 4)
    MATCHES[match_id] = match
    return match


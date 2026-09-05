"""Stable tool contracts and deterministic adapters; no orchestration loops."""

import re
from dataclasses import asdict
from typing import Any

from langsmith import traceable

from chess_core import ScratchBoard, inspect_square, position_status
from harness.protocol import (
    ToolProtocolError,
    ToolRejected,
    validate_string_arguments,
)
from harness.protocol import (
    function_tool as _tool,
)
from harness.protocol import (
    require_legal_san as _require_san,
)
from harness.protocol import (
    string_schema as _string,
)

from .state import Phase

TERMINAL_TOOLS = {
    "defense": "submit_defense_report",
    "attack": "submit_attack_report",
    "synthesis": "submit_move",
}
SCRATCH_TOOLS = ("scratch_play_move", "scratch_undo", "scratch_reset", "inspect_square")


def tool_schemas(phase: Phase) -> list[dict[str, Any]]:
    justification = _string(
        "Visible sentence explaining the concrete uncertainty this call resolves."
    )
    tools = [
        _tool(
            "scratch_play_move",
            "Play one legal SAN move on the scratchboard only.",
            {
                "justification": justification,
                "move": _string(
                    "Legal SAN move from the current scratchboard legal moves."
                ),
            },
        ),
        _tool(
            "scratch_undo",
            "Undo the most recent scratchboard move.",
            {"justification": justification},
        ),
        _tool(
            "scratch_reset",
            "Reset the scratchboard to the canonical position.",
            {"justification": justification},
        ),
        _tool(
            "inspect_square",
            "Inspect one square on the canonical board or current scratchboard. "
            "Returns the occupant and the agent and opponent pieces targeting it.",
            {
                "justification": justification,
                "board": {
                    "type": "string",
                    "enum": ["canonical", "scratch"],
                    "description": "Board state to inspect.",
                },
                "square": {
                    "type": "string",
                    "pattern": "^[a-h][1-8]$",
                    "description": "Board square to inspect, such as e4.",
                },
            },
        ),
    ]
    if phase == "synthesis":
        terminal = _tool(
            "submit_move",
            "Submit the final legal SAN move for the canonical board and end Phase 3.",
            {
                "justification": _string(
                    "Visible summary of the report comparison, candidate verification, and final decision."
                ),
                "move": _string(
                    "Legal SAN move from the current canonical legal moves."
                ),
            },
        )
    else:
        defense = phase == "defense"
        label = "Defense" if defense else "Attack"
        pattern = (
            r"^Severity: (Critical|Urgent|Manageable|None)\. [^\r\n]+$"
            if defense
            else r"^Opportunity: (Decisive|Strong|Practical|None)\. [^\r\n]+$"
        )
        terminal = _tool(
            TERMINAL_TOOLS[phase],
            f"Submit the terminal one-paragraph {label} Report and end Phase {1 if defense else 2}.",
            {
                "report": {
                    "type": "string",
                    "minLength": 40,
                    "maxLength": 1200,
                    "pattern": pattern,
                    "description": "One concise paragraph stating threat severity, evidence, and credible responses."
                    if defense
                    else "One concise paragraph stating attacking potential, evidence, and tested continuations.",
                },
            },
        )
    return [*tools, terminal]


def validate_arguments(phase: Phase, name: str, arguments: Any) -> dict[str, str]:
    schema = next((t for t in tool_schemas(phase) if t["name"] == name), None)
    if schema is None:
        raise ToolProtocolError(f"Unsupported tool for {phase}: {name}.")
    fields = schema["parameters"]["properties"]
    args = validate_string_arguments(name, arguments, fields)
    if "report" in args:
        report = args["report"]
        if (
            not 40 <= len(report) <= 1200
            or re.fullmatch(fields["report"]["pattern"], report) is None
        ):
            raise ToolProtocolError(
                f"{name} requires one 40–1200 character paragraph with the approved severity/opportunity label."
            )
    return args


def scratchboard(fen: str, moves: list[str]) -> ScratchBoard:
    board = ScratchBoard(fen)
    for move in moves:
        board.play(move)
    return board


def scratch_payload(board: ScratchBoard) -> dict[str, Any]:
    if not board.moves:
        return {"status": "unused"}
    return {
        "status": "active",
        "fen": board.current_fen,
        "side_to_move": position_status(board.current_fen).side_to_move,
        "moves_from_canonical": [{"san": move.move.san} for move in board.moves],
    }


def _piece(piece):
    if piece is None:
        return None
    return {key: value for key, value in asdict(piece).items() if key != "symbol"}


@traceable(run_type="tool", name="chess tool")
def execute_tool(
    *,
    phase: Phase,
    name: str,
    arguments: dict[str, str],
    canonical_fen: str,
    side: str,
    scratch_moves: list[str],
) -> dict[str, Any]:
    """Return a new scratch stack/result. Never mutate the caller's state."""
    args = validate_arguments(phase, name, arguments)
    if name == "submit_move":
        _require_san(canonical_fen, args["move"], "canonical board")
        return {"terminal": True, "decision": args}
    if name in ("submit_defense_report", "submit_attack_report"):
        return {"terminal": True, "report": args["report"]}

    board = scratchboard(canonical_fen, scratch_moves)
    if name == "scratch_play_move":
        _require_san(board.current_fen, args["move"], "scratchboard")
        identity = board.play(args["move"]).move
        result = {
            "ok": True,
            "tool": name,
            "move": {"san": identity.san},
            "scratchboard": scratch_payload(board),
        }
        summary = f"Scratchboard played {identity.san}; side to move={position_status(board.current_fen).side_to_move}; moves from canonical={len(board.moves)}."
    elif name == "scratch_undo":
        undone = board.undo()
        result = {
            "ok": True,
            "tool": name,
            "undone_move": {"san": undone.move.san} if undone else None,
            "scratchboard": scratch_payload(board),
        }
        if not undone:
            summary = "Scratchboard had no move to undo; side to move=."
        elif not board.moves:
            summary = f"Scratchboard undid {undone.move.san} and returned to unused."
        else:
            summary = f"Scratchboard undid {undone.move.san}; side to move={position_status(board.current_fen).side_to_move}; moves from canonical={len(board.moves)}."
    elif name == "scratch_reset":
        board.reset()
        result = {"ok": True, "tool": name, "scratchboard": scratch_payload(board)}
        summary = "Scratchboard reset and returned to unused."
    else:
        selected = args["board"].lower()
        square = args["square"].lower()
        if selected not in {"canonical", "scratch"}:
            raise ToolRejected(
                "Rejected. `board` must be either `canonical` or `scratch`."
            )
        if re.fullmatch(r"[a-h][1-8]", square) is None:
            raise ToolRejected(
                f"Rejected. `{square}` is not a valid square. Select a square from a1 through h8."
            )
        fen = canonical_fen if selected == "canonical" else board.current_fen
        inspection = inspect_square(fen, square, perspective=side)
        result = {
            "ok": True,
            "tool": name,
            "board": selected,
            "square": square,
            "side_to_move": position_status(fen).side_to_move,
            "agent_side": side,
            "piece": _piece(inspection.occupant),
            "opponent_attackers": [
                _piece(p) for p in inspection.opponent_pieces_targeting
            ],
            "agent_pieces_targeting_square": [
                _piece(p) for p in inspection.friendly_pieces_targeting
            ],
        }
        occupant = (
            f"{inspection.occupant.color} {inspection.occupant.piece}"
            if inspection.occupant
            else "empty"
        )
        summary = f"Inspected {selected} {square}; occupant={occupant}; opponent attackers={len(inspection.opponent_pieces_targeting)}; agent pieces targeting={len(inspection.friendly_pieces_targeting)}."
    return {
        "terminal": False,
        "scratch_moves": [m.move.san for m in board.moves],
        "result": result,
        "result_summary": summary,
    }

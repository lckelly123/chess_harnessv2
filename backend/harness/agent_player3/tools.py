"""Stable tool contracts and deterministic adapters; no orchestration loops."""

import re
from dataclasses import asdict
from typing import Any

import chess
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

from .state import Phase, TestedLineNode
from .tested_lines import (
    BRANCH_ID_PATTERN,
    MAX_SCRATCH_HALFMOVES,
    base_verification_done,
    copy_nodes,
    find_child,
    find_node,
    material_change_cp,
    moves_to_branch,
    next_branch_id,
    require_node,
)

TERMINAL_TOOLS = {
    "synthesis": "submit_move",
}
SCRATCH_TOOLS = ("scratch_play_move", "scratch_undo", "scratch_reset", "inspect_square")
ANNOTATION_TOOLS = frozenset({"annotate_branch"})
INSPECTION_TOOLS = frozenset({"inspect_square"})
BOARD_MUTATING_TOOLS = frozenset(
    {"scratch_play_move", "scratch_undo", "scratch_reset", "submit_move"}
)


def tool_schemas(phase: Phase) -> list[dict[str, Any]]:
    tools = [
        _tool(
            "scratch_play_move",
            "Play one legal SAN move on the scratchboard only.",
            {
                "move": _string(
                    "Legal SAN move from the current scratchboard legal moves."
                ),
            },
        ),
        _tool(
            "scratch_undo",
            "Undo the most recent scratchboard move.",
            {},
        ),
        _tool(
            "scratch_reset",
            "Reset the scratchboard to the canonical position.",
            {},
        ),
        _tool(
            "annotate_branch",
            "Replace the annotation on one existing tested-line branch.",
            {
                "branch_id": _string("Existing branch id, such as B1 or B1.1."),
                "annotation": _string(
                    "Concise prose conclusion supported by that tested branch."
                ),
            },
        ),
        _tool(
            "inspect_square",
            "Inspect one square on the canonical board or current scratchboard. "
            "Returns the occupant and the agent and opponent pieces targeting it.",
            {
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
    terminal = _tool(
        "submit_move",
        "Submit the final legal SAN move for the canonical board and end the turn.",
        {
            "decision_summary": _string(
                "Visible summary of candidate verification and the final decision."
            ),
            "move": _string("Legal SAN move from the canonical legal moves."),
            "tested_branch": _string(
                "Completed base branch that begins with the submitted move."
            ),
        },
    )
    return [*tools, terminal]


def validate_arguments(phase: Phase, name: str, arguments: Any) -> dict[str, str]:
    schema = next((t for t in tool_schemas(phase) if t["name"] == name), None)
    if schema is None:
        raise ToolProtocolError(f"Unsupported tool for {phase}: {name}.")
    fields = schema["parameters"]["properties"]
    args = validate_string_arguments(name, arguments, fields)
    if name == "submit_move":
        summary = re.sub(r"\s+", " ", args["decision_summary"])
        if len(summary) < 20:
            raise ToolProtocolError(
                "submit_move decision_summary must be at least 20 characters."
            )
        args["decision_summary"] = summary
    if name == "annotate_branch":
        annotation = re.sub(r"\s+", " ", args["annotation"])
        if not annotation:
            raise ToolProtocolError("annotate_branch annotation cannot be empty.")
        if len(annotation) > 600:
            raise ToolProtocolError(
                "annotate_branch annotation must be at most 600 characters."
            )
        args["annotation"] = annotation
    branch_field = "branch_id" if name == "annotate_branch" else "tested_branch"
    if branch_field in args:
        branch_id = args[branch_field]
        if BRANCH_ID_PATTERN.fullmatch(branch_id) is None:
            raise ToolProtocolError(
                f"{name} {branch_field} must be a branch id such as B1 or B1.1."
            )
    return args


def validate_tool_batch(calls: list[dict[str, Any]]) -> None:
    """Reject ambiguous combinations before any tool in the batch can run."""

    names = [str(call["tool"]) for call in calls]
    mutating = [name for name in names if name in BOARD_MUTATING_TOOLS]
    inspections = [name for name in names if name in INSPECTION_TOOLS]
    if len(mutating) > 1:
        raise ToolProtocolError(
            "A tool batch may contain at most one board-mutating call."
        )
    if mutating and inspections:
        raise ToolProtocolError(
            "inspect_square cannot share a batch with a board-mutating call."
        )

    annotation_targets = [
        call["arguments"]["branch_id"]
        for call in calls
        if call["tool"] == "annotate_branch"
    ]
    if len(annotation_targets) != len(set(annotation_targets)):
        raise ToolProtocolError(
            "A tool batch cannot annotate the same branch more than once."
        )


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


def _piece_locations(pieces) -> str:
    return (
        ", ".join(f"{piece.color} {piece.piece} {piece.square}" for piece in pieces)
        or "none"
    )


@traceable(run_type="tool", name="chess tool")
def execute_tool(
    *,
    phase: Phase,
    name: str,
    arguments: dict[str, str],
    canonical_fen: str,
    side: str,
    scratch_moves: list[str],
    tested_lines: list[TestedLineNode],
    active_branch_id: str | None,
) -> dict[str, Any]:
    """Return copied branch/scratch state. Never mutate the caller's state."""

    args = validate_arguments(phase, name, arguments)
    nodes = copy_nodes(tested_lines)
    tree_moves = moves_to_branch(nodes, active_branch_id)
    if tree_moves != scratch_moves:
        raise ValueError("Scratch moves do not match the active tested-line branch.")

    if name == "submit_move":
        _require_san(canonical_fen, args["move"], "canonical board")
        branch_id = args["tested_branch"]
        branch = find_node(nodes, branch_id)
        if branch is None:
            raise ToolRejected(f"Rejected. Tested branch `{branch_id}` does not exist.")
        if branch["parent_id"] is not None:
            raise ToolRejected(
                f"Rejected. `{branch_id}` is not a base branch. Submit its B-level root."
            )
        if branch["move"] != args["move"]:
            raise ToolRejected(
                f"Rejected. `{branch_id}` begins with `{branch['move']}`, not `{args['move']}`."
            )
        if not base_verification_done(nodes, branch_id):
            raise ToolRejected(
                f"Rejected. `{branch_id}` is incomplete. Test an opponent reply before submitting."
            )
        return {
            "terminal": True,
            "scratch_moves": list(scratch_moves),
            "tested_lines": nodes,
            "active_branch_id": active_branch_id,
            "decision": {
                "move": args["move"],
                "justification": args["decision_summary"],
            },
            "result_summary": (
                f"Submission accepted: {args['move']} from verified branch {branch_id}."
            ),
        }

    board = scratchboard(canonical_fen, scratch_moves)
    if name == "scratch_play_move":
        if len(scratch_moves) >= MAX_SCRATCH_HALFMOVES:
            raise ToolRejected(
                f"Rejected. Scratch branches are limited to {MAX_SCRATCH_HALFMOVES} halfmoves."
            )
        active = find_node(nodes, active_branch_id)
        if active is not None and active["terminal"]:
            raise ToolRejected(
                f"Rejected. Branch `{active_branch_id}` is already terminal."
            )
        actor_side = position_status(board.current_fen).side_to_move
        _require_san(board.current_fen, args["move"], "scratchboard")
        identity = board.play(args["move"]).move
        branch = find_child(nodes, active_branch_id, identity.san)
        reused = branch is not None
        if branch is None:
            branch = TestedLineNode(
                branch_id=next_branch_id(nodes, active_branch_id),
                parent_id=active_branch_id,
                ply=len(scratch_moves) + 1,
                actor="agent" if actor_side == side else "opponent",
                side=actor_side,
                move=identity.san,
                fen=board.current_fen,
                material_change_cp=material_change_cp(
                    canonical_fen, board.current_fen, side
                ),
                annotation=None,
                terminal=chess.Board(board.current_fen).is_game_over(claim_draw=True),
            )
            nodes.append(branch)
        elif branch["fen"] != board.current_fen:
            raise ValueError(
                f"Stored branch {branch['branch_id']} does not match its replayed position."
            )
        active_branch_id = branch["branch_id"]
        scratch_moves = moves_to_branch(nodes, active_branch_id)
        result = {
            "ok": True,
            "tool": name,
            "move": {"san": identity.san},
            "branch_id": active_branch_id,
            "reused": reused,
            "scratchboard": scratch_payload(board),
        }
        action = "Reused" if reused else "Created"
        summary = (
            f"{action} branch {active_branch_id} by playing {identity.san}; "
            f"material change from canonical for {side.capitalize()}="
            f"{branch['material_change_cp']:+d} cp; "
            f"side to move={position_status(board.current_fen).side_to_move}."
        )
    elif name == "scratch_undo":
        active = find_node(nodes, active_branch_id)
        undone_branch_id = active_branch_id
        active_branch_id = active["parent_id"] if active is not None else None
        scratch_moves = moves_to_branch(nodes, active_branch_id)
        board = scratchboard(canonical_fen, scratch_moves)
        result = {
            "ok": True,
            "tool": name,
            "undone_branch_id": undone_branch_id,
            "active_branch_id": active_branch_id,
            "scratchboard": scratch_payload(board),
        }
        if active is None:
            summary = (
                "Scratchboard was already unused; the tested-line tree was preserved."
            )
        elif active_branch_id is None:
            summary = (
                f"Scratchboard moved back from {undone_branch_id} to canonical; "
                "the tested-line tree was preserved."
            )
        else:
            summary = (
                f"Scratchboard moved back from {undone_branch_id} to "
                f"{active_branch_id}; the tested-line tree was preserved."
            )
    elif name == "scratch_reset":
        active_branch_id = None
        scratch_moves = []
        board = scratchboard(canonical_fen, scratch_moves)
        result = {
            "ok": True,
            "tool": name,
            "scratchboard": scratch_payload(board),
        }
        summary = "Scratchboard reset to canonical; the tested-line tree was preserved."
    elif name == "annotate_branch":
        branch_id = args["branch_id"]
        try:
            branch = require_node(nodes, branch_id)
        except KeyError as exc:
            raise ToolRejected(
                f"Rejected. Tested branch `{branch_id}` does not exist yet."
            ) from exc
        previous = branch["annotation"]
        branch["annotation"] = args["annotation"]
        result = {
            "ok": True,
            "tool": name,
            "branch_id": branch_id,
            "previous_annotation": previous,
            "annotation": args["annotation"],
        }
        summary = f"Annotation for {branch_id} is now: {args['annotation']}"
    elif name == "inspect_square":
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
        if inspection.occupant is None:
            summary = (
                f"Inspected {selected} {square}; occupant={occupant}; "
                f"agent control={_piece_locations(inspection.friendly_pieces_targeting)}; "
                f"opponent control={_piece_locations(inspection.opponent_pieces_targeting)}."
            )
        else:
            occupant_is_friendly = inspection.occupant.color == inspection.perspective
            attackers = (
                inspection.opponent_pieces_targeting
                if occupant_is_friendly
                else inspection.friendly_pieces_targeting
            )
            defenders = (
                inspection.friendly_pieces_targeting
                if occupant_is_friendly
                else inspection.opponent_pieces_targeting
            )
            summary = (
                f"Inspected {selected} {square}; occupant={occupant}; "
                f"attackers={_piece_locations(attackers)}; "
                f"defenders={_piece_locations(defenders)}."
            )
    else:
        raise ValueError(f"Unhandled tool: {name}")
    return {
        "terminal": False,
        "scratch_moves": list(scratch_moves),
        "tested_lines": nodes,
        "active_branch_id": active_branch_id,
        "result": result,
        "result_summary": summary,
    }

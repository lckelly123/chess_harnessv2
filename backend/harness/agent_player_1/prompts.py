"""Legacy phase packets, rebuilt from explicit graph state on every pass."""

from pathlib import Path

from chess_core import (
    legal_moves,
    position_status,
    scan_agent_forcing_moves,
    scan_opponent_forcing_moves,
)
from harness.prompting import forced_input as forced_input
from harness.prompting import format_history, text_tool_protocol

from .state import Phase, TurnState
from .tools import scratchboard, tool_schemas

PROMPT_ROOT = Path(__file__).with_name("prompts")
TITLES = {
    "defense": "Phase 1: Defensive Review",
    "attack": "Phase 2: Attacking Review",
    "synthesis": "Phase 3: Final Decision",
}
EVASIONS = {
    "king_move": "King move",
    "king_captures_checker": "King captures checking piece",
    "piece_captures_checker": "Piece captures checking piece",
    "interposition": "Interposition",
    "other": "Other legal check resolution",
}


def _pgn_move(san, side):
    return f"...{san}" if side == "black" else san


def _exchange_lines(exchange, side, *, opponent=False):
    if exchange is None:
        return ["SEE sequence: Not applicable", "Material result: Not evaluated"]
    sequence = [move.san for move in exchange.capture_sequence]
    if sequence:
        sequence[0] = _pgn_move(sequence[0], side)
    score = -exchange.score_cp if opponent else exchange.score_cp
    material = (
        f"Agent loss: {abs(score)} cp"
        if score < 0
        else f"Agent gain: {score} cp"
        if score > 0
        else "Material result: Equal"
    )
    return [f"SEE sequence: {' '.join(sequence)}", material]


def _move_group(moves, side, *, checks=False, opponent=False):
    if not moves:
        return ["None.", ""]
    lines = []
    for index, move in enumerate(moves, 1):
        lines.extend([f"#### {index}. {_pgn_move(move.move.san, side)}", ""])
        if checks:
            kind = "Capturing" if move.move.is_capture else "Non-capturing"
            lines.append(
                f"Type: {kind} {'checkmate' if move.is_checkmate else 'check'}"
            )
        lines.extend(
            [*_exchange_lines(move.static_exchange, side, opponent=opponent), ""]
        )
    return lines


def defensive_scan(fen):
    scan = scan_opponent_forcing_moves(fen)
    agent_side = position_status(fen).side_to_move
    check = scan.current_check
    if check is None:
        lines = ["## Current Check", "", "Status: None", ""]
    else:
        pieces = "; ".join(
            f"{piece.color.capitalize()} {piece.piece} on {piece.square}"
            for piece in check.checking_pieces
        )
        label = (
            "Checking piece" if len(check.checking_pieces) == 1 else "Checking pieces"
        )
        lines = [
            "## Current Check",
            "",
            f"Status: {'Checkmate' if check.checkmate else 'Active'}",
            "Response requirement: None; no legal move exists"
            if check.checkmate
            else "Response requirement: Mandatory",
            f"Check type: {check.check_type.replace('_', ' ').capitalize()}",
            f"{label}: {pieces or 'Unknown'}",
            "",
            "### Legal Evasions",
            "",
        ]
        if not check.legal_evasions:
            lines.extend(["None.", ""])
        for index, evasion in enumerate(check.legal_evasions, 1):
            lines.extend(
                [
                    f"#### {index}. {_pgn_move(evasion.move.san, agent_side)}",
                    "",
                    f"Type: {EVASIONS[evasion.evasion_type]}",
                    *_exchange_lines(evasion.static_exchange, agent_side),
                    "",
                ]
            )
    lines.extend(["## Opponent Forcing-Move Scan", ""])
    if scan.status == "in_check":
        lines.extend(
            [
                "Status: Deferred",
                "",
                "A hypothetical pass is illegal while the agent is in check. Opponent checks and captures were not generated.",
                "",
                "### Checks",
                "",
                "Deferred.",
                "",
                "### Captures",
                "",
                "Deferred.",
            ]
        )
    elif scan.status == "game_over":
        lines.extend(
            [
                "Status: Unavailable",
                "",
                f"Game over: {(scan.reason or 'game over').replace('_', ' ')}.",
            ]
        )
    else:
        # The legacy defensive scan sorts checks by mate, then SAN (not SEE).
        checks = sorted(
            scan.checks, key=lambda move: (not move.is_checkmate, move.move.san)
        )
        lines.extend(
            [
                f"Assumption: {agent_side.capitalize()} passes without changing the position and {scan.actor.capitalize()} is given the move.",
                "",
                "### Checks",
                "",
                *_move_group(checks, scan.actor, checks=True, opponent=True),
                "### Captures",
                "",
                *_move_group(scan.captures, scan.actor, opponent=True),
            ]
        )
    return "\n".join(lines).rstrip()


def attacking_scan(fen):
    scan = scan_agent_forcing_moves(fen)
    lines = ["## Agent Forcing-Move Scan", ""]
    if scan.status == "game_over":
        lines.extend(
            [
                "Status: Unavailable",
                "",
                f"Game over: {(scan.reason or 'game over').replace('_', ' ')}.",
            ]
        )
    else:
        lines.extend(
            [
                f"Perspective: {scan.actor.capitalize()} is the agent and moves from the current canonical position.",
                "",
                "### Checks",
                "",
                *_move_group(scan.checks, scan.actor, checks=True),
                "### Captures",
                "",
                *_move_group(scan.captures, scan.actor),
            ]
        )
    return "\n".join(lines).rstrip()


def format_scratch(state: TurnState):
    if not state["scratch_moves"]:
        return "Status: unused"
    board = scratchboard(state["canonical_fen"], state["scratch_moves"])
    side = position_status(board.current_fen).side_to_move
    return "\n".join(
        [
            "Status: active",
            f"Side to move: {side}",
            f"FEN: `{board.current_fen}`",
            "",
            "Moves from canonical:",
            "",
            "```pgn",
            " ".join(state["scratch_moves"]),
            "```",
            "",
            f"Scratchboard legal moves for {side}:",
            "",
            "```text",
            ", ".join(move.san for move in legal_moves(board.current_fen)) or "None.",
            "```",
        ]
    )


def build_input(state: TurnState) -> str:
    phase = state["phase"]
    lines = [
        f"# {TITLES[phase]}",
        "",
        "## Game Record",
        "",
        f"Agent to move: {state['side'].capitalize()}",
        "",
        "```pgn",
        state["pgn"].strip() or "*",
        "```",
        "",
    ]
    if phase == "defense":
        lines.extend([defensive_scan(state["canonical_fen"]), ""])
    elif phase == "attack":
        lines.extend([attacking_scan(state["canonical_fen"]), ""])
    else:
        lines.extend(
            [
                "## Phase 1 Defense Report",
                "",
                state["defense_report"],
                "",
                "## Phase 2 Attack Report",
                "",
                state["attack_report"],
                "",
                "## Canonical Legal Moves",
                "",
                "```text",
                ", ".join(state["legal_san"]),
                "```",
                "",
            ]
        )
    lines.extend(
        [
            "## Scratchboard",
            "",
            format_scratch(state),
            "",
            "## Tool History",
            "",
            format_history(state["history"]),
            "",
        ]
    )
    if state["correction"]:
        lines.extend(["## Protocol Correction", "", state["correction"], ""])
    # Legacy formatters accept working_notes but do not render them. Preserve
    # actual packets; the forced retry carries the previous exposed output.
    return "\n".join(lines)


def load_instructions(phase: Phase) -> str:
    introductions = {
        "defense": "You are Agent Player 1 running only Phase 1: Defense. Produce a defensive report, not a chess move.",
        "attack": "You are Agent Player 1 running only Phase 2: Attack. Produce an attacking report, not a chess move.",
        "synthesis": "You are Agent Player 1 running only Phase 3: Decision. Compare the prior reports, verify serious candidates, and submit exactly one legal move.",
    }
    example = {
        "tool": "scratch_play_move",
        "arguments": {
            "justification": "I need to test whether e4 changes the forcing-move picture before ranking candidates.",
            "move": "e4",
        },
    }
    protocol = text_tool_protocol(tool_schemas(phase), example)
    return "\n\n".join(
        [
            introductions[phase]
            + " Do not use an engine, opening book, best-move source, or outside evaluator.",
            "## Shared Contract\n\n"
            + (PROMPT_ROOT / "shared.md").read_text(encoding="utf-8").strip(),
            "## Phase Instructions\n\n"
            + (PROMPT_ROOT / f"{phase}.md").read_text(encoding="utf-8").strip(),
            "## Current Output Protocol\n\n" + protocol,
        ]
    )

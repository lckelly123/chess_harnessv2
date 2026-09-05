"""Legacy baseline position packet with the shared v2 text-tool protocol."""

from pathlib import Path

from chess_core import position_status
from harness.prompting import format_history, text_tool_protocol

from .state import BaselineState
from .tools import tool_schemas


def format_status(fen: str) -> str:
    status = position_status(fen)
    _, _, castling, en_passant, halfmove, fullmove = fen.split()
    return "\n".join(
        [
            f"Game over: {str(status.is_game_over).lower()}",
            f"Check: {str(status.is_check).lower()}",
            f"Checkmate: {str(status.is_checkmate).lower()}",
            f"Stalemate: {str(status.is_stalemate).lower()}",
            f"Insufficient material: {str(status.is_insufficient_material).lower()}",
            f"Can claim draw: {str(status.can_claim_draw).lower()}",
            f"Outcome: {status.result or 'none'}",
            f"Halfmove clock: {halfmove}",
            f"Fullmove number: {fullmove}",
            f"Castling rights: {castling}",
            f"En passant square: {en_passant if en_passant != '-' else 'none'}",
        ]
    )


def build_input(state: BaselineState) -> str:
    lines = [
        "# Chess Move Request",
        "",
        "## Task",
        "",
        "Choose one legal move for the side to move.",
        "",
        "When ready, call the terminal `submit_move` tool.",
        "",
        "## Player",
        "",
        f"Game ID: `{state['game_id']}`  ",
        f"Agent side: {state['side']}  ",
        f"Side to move: {state['side']}",
        "",
        "## Position",
        "",
        f"FEN: `{state['canonical_fen']}`",
        "",
        "PGN so far:",
        "",
        "```pgn",
        state["pgn"].strip() or "*",
        "```",
        "",
        "## Last Move",
        "",
        "```text",
        state["last_move"],
        "```",
        "",
        "## Legal Moves",
        "",
        "```text",
        "\n".join(state["legal_san"]),
        "```",
        "",
        "## Game Status",
        "",
        "```text",
        format_status(state["canonical_fen"]),
        "```",
        "",
        "## Scratchboard",
        "",
        "Status: unused",
        "",
        # Stable Available Actions moved into developer instructions so the
        # dynamic packet cannot contradict the LM Studio text-tool protocol.
        "## Tool History",
        "",
        format_history(state["history"]),
        "",
    ]
    if state["correction"]:
        lines.extend(["## Protocol Correction", "", state["correction"], ""])
    return "\n".join(lines)


def load_instructions() -> str:
    example = {
        "tool": "submit_move",
        "arguments": {
            "move": "e4",
            "justification": "e4 claims central space and opens development for the king bishop and queen.",
        },
    }
    return "\n\n".join(
        [
            Path(__file__).with_name("prompt.md").read_text(encoding="utf-8").strip(),
            "## Current Output Protocol\n\n"
            + text_tool_protocol(tool_schemas(), example),
        ]
    )

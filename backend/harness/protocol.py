"""Shared text-tool parsing, schemas, and deterministic argument validation."""

import json
import re
from typing import Any

from chess_core import legal_moves

LOW_INFORMATION = {
    "analyze",
    "analysis",
    "because",
    "because i want to",
    "check",
    "checking",
    "for analysis",
    "i need it",
    "needed",
    "to analyze",
    "tool",
    "use tool",
}


class ToolProtocolError(ValueError):
    """Malformed or unsupported tool call; request a corrected response."""


class ToolRejected(ValueError):
    """Well-formed action rejected without changing either board."""


def string_schema(description):
    return {"type": "string", "description": description}


def function_tool(name, description, properties):
    return {
        "type": "function",
        "name": name,
        "description": description,
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


def parse_tool_call(text: str) -> dict[str, Any]:
    opening, closing = "<agent_tool_call>", "</agent_tool_call>"
    if (
        text.count(opening) != 1
        or text.count(closing) != 1
        or text.find(closing) < text.find(opening)
    ):
        raise ToolProtocolError(
            "Response must contain exactly one complete <agent_tool_call> block."
        )
    _, body = text.split(opening)
    content, after = body.split(closing)
    if after.strip():
        raise ToolProtocolError("No text is allowed after </agent_tool_call>.")
    try:
        value = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ToolProtocolError(
            "The tagged tool call must contain valid JSON."
        ) from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"tool", "arguments"}
        or not isinstance(value["tool"], str)
    ):
        raise ToolProtocolError(
            "The tagged object requires only `tool` and `arguments`."
        )
    return value


def validate_string_arguments(name, arguments, fields) -> dict[str, str]:
    """Validate our flat string-only tool contracts, not arbitrary JSON Schema."""
    if not isinstance(arguments, dict):
        raise ToolProtocolError("Tool arguments must be a JSON object.")
    if set(arguments) != set(fields):
        raise ToolProtocolError(
            f"{name} requires only these fields: {', '.join(fields)}."
        )
    if any(not isinstance(value, str) for value in arguments.values()):
        raise ToolProtocolError("All tool argument values must be strings.")
    args = {key: value.strip() for key, value in arguments.items()}
    if "justification" in args:
        normalized = re.sub(r"\s+", " ", args["justification"])
        if len(normalized) < 20 or normalized.lower() in LOW_INFORMATION:
            raise ToolProtocolError(
                "Justification must be at least 20 characters and describe the concrete decision uncertainty."
            )
    return args


def require_legal_san(fen, move, board_name):
    if move not in {identity.san for identity in legal_moves(fen)}:
        moves_name = (
            "canonical legal moves"
            if board_name == "canonical board"
            else "scratchboard legal moves"
        )
        raise ToolRejected(
            f"Rejected. `{move}` is not legal on the current {board_name}. Select a move from the {moves_name}."
        )

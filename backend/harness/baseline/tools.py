"""The baseline's entire tool surface: submit one canonical legal SAN move."""

from typing import Any

from langsmith import traceable

from harness.protocol import (
    ToolProtocolError,
    function_tool,
    require_legal_san,
    string_schema,
    validate_string_arguments,
)


def tool_schemas() -> list[dict[str, Any]]:
    return [
        function_tool(
            "submit_move",
            "Submit the final legal SAN move for the canonical board and end the turn.",
            {
                "justification": string_schema(
                    "Visible summary of the most important reasoning from this turn."
                ),
                "move": string_schema(
                    "Legal SAN move from the current canonical legal moves."
                ),
            },
        )
    ]


def validate_arguments(name: str, arguments: Any) -> dict[str, str]:
    if name != "submit_move":
        raise ToolProtocolError("Baseline must call only the `submit_move` tool.")
    return validate_string_arguments(
        name, arguments, tool_schemas()[0]["parameters"]["properties"]
    )


@traceable(run_type="tool", name="submit_move")
def submit_move(canonical_fen: str, arguments: dict[str, str]) -> dict[str, str]:
    """Check the submission without applying a move to the canonical position."""
    args = validate_arguments("submit_move", arguments)
    require_legal_san(canonical_fen, args["move"], "canonical board")
    return args

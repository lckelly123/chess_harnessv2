"""Agent Player 2's atomic working-notes and text-tool batch protocol."""

import json
from dataclasses import dataclass
from typing import Any

from harness.protocol import ToolProtocolError

RUNNING_THOUGHTS_OPEN = "<running_thoughts>"
RUNNING_THOUGHTS_CLOSE = "</running_thoughts>"
TOOL_CALLS_OPEN = "<agent_tool_calls>"
TOOL_CALLS_CLOSE = "</agent_tool_calls>"


@dataclass(frozen=True, slots=True)
class AgentResponse:
    running_thoughts: str
    tool_calls: tuple[dict[str, Any], ...]


def _parse_tool_calls(content: str) -> tuple[dict[str, Any], ...]:
    try:
        value = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ToolProtocolError(
            "The tagged tool batch must contain valid JSON."
        ) from exc
    if not isinstance(value, list) or not value:
        raise ToolProtocolError(
            "The <agent_tool_calls> block must contain a non-empty JSON array."
        )

    calls = []
    for index, call in enumerate(value):
        if (
            not isinstance(call, dict)
            or set(call) != {"tool", "arguments"}
            or not isinstance(call["tool"], str)
        ):
            raise ToolProtocolError(
                f"Tool call {index + 1} requires only `tool` and `arguments`."
            )
        calls.append(call)
    return tuple(calls)


def parse_agent_response(text: str) -> AgentResponse:
    """Require one notes snapshot immediately before one JSON tool-call array."""

    if (
        text.count(RUNNING_THOUGHTS_OPEN) != 1
        or text.count(RUNNING_THOUGHTS_CLOSE) != 1
    ):
        raise ToolProtocolError(
            "Response must contain exactly one complete <running_thoughts> block."
        )
    if text.count(TOOL_CALLS_OPEN) != 1 or text.count(TOOL_CALLS_CLOSE) != 1:
        raise ToolProtocolError(
            "Response must contain exactly one complete <agent_tool_calls> block."
        )

    thoughts_start = text.find(RUNNING_THOUGHTS_OPEN)
    thoughts_content_start = thoughts_start + len(RUNNING_THOUGHTS_OPEN)
    thoughts_end = text.find(RUNNING_THOUGHTS_CLOSE)
    calls_start = text.find(TOOL_CALLS_OPEN)
    calls_content_start = calls_start + len(TOOL_CALLS_OPEN)
    calls_end = text.find(TOOL_CALLS_CLOSE)
    if thoughts_end < thoughts_content_start:
        raise ToolProtocolError("The <running_thoughts> block is malformed.")
    if calls_end < calls_content_start:
        raise ToolProtocolError("The <agent_tool_calls> block is malformed.")
    if calls_start < thoughts_end + len(RUNNING_THOUGHTS_CLOSE):
        raise ToolProtocolError(
            "The <running_thoughts> block must appear before <agent_tool_calls>."
        )
    if (
        text[:thoughts_start].strip()
        or text[thoughts_end + len(RUNNING_THOUGHTS_CLOSE) : calls_start].strip()
        or text[calls_end + len(TOOL_CALLS_CLOSE) :].strip()
    ):
        raise ToolProtocolError(
            "Output only the running-thoughts block followed by the tool-calls block."
        )

    running_thoughts = text[thoughts_content_start:thoughts_end].strip()
    if not running_thoughts:
        raise ToolProtocolError("The <running_thoughts> block cannot be empty.")
    return AgentResponse(
        running_thoughts=running_thoughts,
        tool_calls=_parse_tool_calls(text[calls_content_start:calls_end]),
    )

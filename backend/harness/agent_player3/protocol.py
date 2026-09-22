"""Native Responses API envelope for one atomic working-notes/tool batch."""

import json
from dataclasses import dataclass
from typing import Any

from harness.protocol import ToolProtocolError, function_tool

from .tools import tool_schemas

AGENT_STEP = "agent_step"


def agent_step_schema() -> dict[str, Any]:
    actions = [
        {
            "type": "object",
            "properties": {
                "tool": {"type": "string", "enum": [tool["name"]]},
                "arguments": tool["parameters"],
            },
            "required": ["tool", "arguments"],
            "additionalProperties": False,
            "description": tool["description"],
        }
        for tool in tool_schemas("synthesis")
    ]
    return function_tool(
        AGENT_STEP,
        "Replace Working Notes and execute one compatible batch of chess tools. "
        "Wait for the result before making another step. Rejected batches commit "
        "neither notes nor board changes.",
        {
            "running_thoughts": {
                "type": "string",
                "minLength": 1,
                "description": "Complete updated Vulnerabilities, Opportunities, "
                "and Synthesis paragraphs, based only on observed evidence.",
            },
            "tool_calls": {
                "type": "array",
                "minItems": 1,
                "items": {"anyOf": actions},
                "description": "One atomic batch: annotations and compatible "
                "actions, with at most one board mutation and no inspections "
                "alongside a board mutation.",
            },
        },
    )


@dataclass(frozen=True, slots=True)
class AgentResponse:
    call_id: str
    running_thoughts: str
    tool_calls: tuple[dict[str, Any], ...]


def function_calls(response: dict[str, Any]) -> list[dict[str, Any]]:
    output = response.get("output")
    if not isinstance(output, list):
        return []
    return [
        item
        for item in output
        if isinstance(item, dict) and item.get("type") == "function_call"
    ]


def parse_agent_response(response: dict[str, Any]) -> AgentResponse:
    """Read native function arguments only; assistant text is never executable."""

    if response.get("status") != "completed":
        raise ToolProtocolError("An incomplete response cannot execute an agent_step.")
    calls = function_calls(response)
    if len(calls) != 1:
        raise ToolProtocolError("Call the native agent_step function exactly once.")
    call = calls[0]
    if call.get("name") != AGENT_STEP:
        raise ToolProtocolError("Use the native agent_step function.")
    if call.get("status") not in (None, "completed"):
        raise ToolProtocolError("The native agent_step call is incomplete.")
    call_id = call.get("call_id")
    if not isinstance(call_id, str) or not call_id.strip():
        raise ToolProtocolError("The native call requires a non-empty call_id.")
    arguments = call.get("arguments")
    if not isinstance(arguments, str):
        raise ToolProtocolError("Native agent_step arguments must be JSON text.")
    try:
        value = json.loads(arguments)
    except json.JSONDecodeError as exc:
        raise ToolProtocolError(
            "Native agent_step arguments must be valid JSON."
        ) from exc
    if not isinstance(value, dict) or set(value) != {"running_thoughts", "tool_calls"}:
        raise ToolProtocolError("agent_step requires running_thoughts and tool_calls.")
    notes = value["running_thoughts"]
    if not isinstance(notes, str) or not notes.strip():
        raise ToolProtocolError("running_thoughts must be a non-empty string.")
    actions = value["tool_calls"]
    if not isinstance(actions, list) or not actions:
        raise ToolProtocolError("tool_calls must be a non-empty array.")
    for action in actions:
        if (
            not isinstance(action, dict)
            or set(action) != {"tool", "arguments"}
            or not isinstance(action["tool"], str)
        ):
            raise ToolProtocolError("Each action requires only tool and arguments.")
    return AgentResponse(call_id, notes.strip(), tuple(actions))


def tool_output(call_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function_call_output",
        "call_id": call_id,
        "output": json.dumps(result, ensure_ascii=True),
    }


def replayable_output(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Never replay partial calls or a simulated text-only tool trajectory."""

    calls = function_calls(response)
    ids = [call.get("call_id") for call in calls]
    if (
        response.get("status") != "completed"
        or not calls
        or not all(isinstance(value, str) and value.strip() for value in ids)
        or len(ids) != len(set(ids))
        or any(
            call.get("status") not in (None, "completed")
            or not isinstance(call.get("arguments"), str)
            or not isinstance(call.get("name"), str)
            for call in calls
        )
    ):
        return []
    # Reasoning items (including encrypted content) must accompany native calls.
    return response["output"]

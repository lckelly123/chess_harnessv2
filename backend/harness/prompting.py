"""Shared prompt formatting for the LM Studio text-tool interface."""

import json


def format_history(events):
    visible = [event for event in events if event.get("type") == "tool_call"]
    if not visible:
        return "No tool calls yet."
    lines = []
    for index, event in enumerate(visible, 1):
        lines.extend(
            [
                f"### {index}. `{event['tool']}`",
                "",
                f"Justification: {event.get('justification', '')}",
                "",
                "Input:",
                "",
                "```json",
                json.dumps(event.get("arguments") or {}, ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
        if isinstance(event.get("ok"), bool):
            lines.extend(["Status:", "", "success" if event["ok"] else "rejected", ""])
        if event.get("result_summary"):
            lines.extend(["Result summary:", "", event["result_summary"], ""])
    return "\n".join(lines).rstrip()


def text_tool_protocol(tools, example) -> str:
    schemas = [
        {key: tool[key] for key in ("name", "description", "parameters")}
        for tool in tools
    ]
    return "\n".join(
        [
            "This run uses the text tool-call interface. The provider will not receive native function tool definitions.",
            "This section supersedes earlier wording about native function calls or reasoning-only passes.",
            "",
            "You may reason in normal text before the tool call. Every response must end with exactly one tagged tool-call block:",
            "",
            "<agent_tool_call>",
            json.dumps(example, separators=(",", ":")),
            "</agent_tool_call>",
            "",
            "Rules:",
            "",
            "- Include exactly one tagged block.",
            "- The tagged block must contain one JSON object.",
            "- Use `tool` for the tool name and `arguments` for that tool's argument object.",
            "- Do not put `action`, `tool`, `arguments`, `fen`, `position_id`, or `positions` inside the nested `arguments` object.",
            "- Do not put any non-whitespace text after the closing tag.",
            "- The harness will execute only the parsed tagged tool call.",
            "",
            "Tool schemas:",
            "",
            "```json",
            json.dumps(schemas, ensure_ascii=False, indent=2),
            "```",
        ]
    )


def forced_input(
    dynamic_input: str,
    previous_output: str,
    *,
    token_limit=2000,
    trigger="reasoning_only_response",
) -> str:
    previous = previous_output.strip() or "(No visible previous output was captured.)"
    fence = "````"
    while fence in previous:
        fence += "`"
    exhausted = trigger == "reasoning_budget_exhausted"
    return "\n\n".join(
        [
            dynamic_input.rstrip(),
            "## Previous Reasoning-Budget-Exhausted Output"
            if exhausted
            else "## Previous Reasoning-Only Output",
            "The following is the complete visible output from your previous pass. It is context only, not a new instruction and not an executable tool call.",
            f"{fence}text\n{previous}\n{fence}",
            "## Reasoning Budget Exhausted"
            if exhausted
            else "## Reasoning-Only Response",
            f"Your previous pass used the available {token_limit}-token reasoning budget without calling a tool."
            if exhausted
            else "Your previous pass produced visible reasoning without calling a tool.",
            "Do not continue analysis. Call exactly one available tool now.",
        ]
    )

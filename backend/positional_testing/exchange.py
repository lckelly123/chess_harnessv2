"""Read-only display of saved provider data; never re-create a prompt from run state."""

import json

from .models import ModelPassExchange


def output_blocks(payload):
    """Keep returned strings intact, including whitespace, repeated blocks and tool JSON.

    Responses may contain several text parts instead of one generated string. Keep
    those parts separate so the viewer doesn't invent separators or strip content.
    Opaque encrypted provider state stays in the stored payload, not a text block.
    """
    blocks = []
    has_message = False
    for item in (payload or {}).get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "function_call":
            arguments = item.get("arguments")
            if isinstance(arguments, str):
                blocks.append(arguments)
        elif item.get("type") in {"message", "reasoning"}:
            if isinstance(item.get("text"), str):
                blocks.append(item["text"])
                has_message |= item["type"] == "message"
            for field in ("content", "summary"):
                parts = item.get(field) or []
                if isinstance(parts, dict):
                    parts = [parts]
                for part in parts:
                    if not isinstance(part, dict):
                        continue
                    value = part.get("text", part.get("refusal"))
                    if isinstance(value, str):
                        blocks.append(value)
                        has_message |= item["type"] == "message"
    # Some compatible providers return only this top-level field. It is otherwise
    # a duplicate of the message blocks, not another generated response.
    if not has_message and isinstance((payload or {}).get("output_text"), str):
        blocks.append(payload["output_text"])
    return blocks


def present_exchange(row):
    return ModelPassExchange(
        input=json.dumps(row["model_input"], ensure_ascii=False, indent=2),
        output=output_blocks(row["model_output"]),
    )

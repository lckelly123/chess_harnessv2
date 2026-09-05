"""LM Studio's stateless Responses API, isolated from chess and orchestration."""

import os
from typing import Any, Protocol

from langsmith.wrappers import wrap_openai
from openai import AsyncOpenAI


class Model(Protocol):
    async def complete(
        self,
        *,
        model: str,
        instructions: str,
        dynamic_input: str,
        reasoning_effort: str,
        max_output_tokens: int,
        forced_retry: bool,
    ) -> dict[str, Any]: ...


class LMStudioModel:
    def __init__(self, client: AsyncOpenAI | None = None):
        self.client = wrap_openai(
            client
            or AsyncOpenAI(
                base_url=os.getenv("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1"),
                api_key=os.getenv("LMSTUDIO_API_KEY") or "lm-studio",
                timeout=120.0,
                max_retries=0,  # Retry decisions belong to the graph, not the SDK.
            )
        )

    async def complete(
        self,
        *,
        model: str,
        instructions: str,
        dynamic_input: str,
        reasoning_effort: str,
        max_output_tokens: int,
        forced_retry: bool,
    ) -> dict[str, Any]:
        response = await self.client.responses.create(
            model=model,
            input=[
                {"role": "developer", "content": instructions},
                {"role": "user", "content": dynamic_input},
            ],
            reasoning={"effort": reasoning_effort},
            max_output_tokens=max_output_tokens,
            store=False,
            # The legacy local path embeds schemas and a tagged call in text.
            # No native tools, conversation IDs, or provider history are sent.
            langsmith_extra={
                "name": "LM Studio forced tool retry"
                if forced_retry
                else "LM Studio pass",
                "metadata": {"ls_provider": "lmstudio", "ls_model_name": model},
            },
        )
        return response.model_dump(mode="json")

    async def aclose(self):
        await self.client.close()


def visible_output(response: dict[str, Any]) -> tuple[str, str]:
    """Return message text and provider-exposed reasoning, never hidden internals."""
    messages, reasoning = [], []
    for item in response.get("output", []):
        if item.get("type") == "message":
            messages.extend(
                block["text"]
                for block in item.get("content", [])
                if isinstance(block.get("text"), str)
            )
        elif item.get("type") == "reasoning":
            if isinstance(item.get("text"), str):
                reasoning.append(item["text"])
            for field in ("content", "summary"):
                blocks = item.get(field) or []
                if isinstance(blocks, dict):
                    blocks = [blocks]
                reasoning.extend(
                    block["text"]
                    for block in blocks
                    if isinstance(block, dict) and isinstance(block.get("text"), str)
                )
    if not messages and isinstance(response.get("output_text"), str):
        messages.append(response["output_text"])
    return "\n".join(messages).strip(), "\n".join(dict.fromkeys(reasoning)).strip()

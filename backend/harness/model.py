"""LM Studio's stateless Responses API, isolated from chess and orchestration."""

import asyncio
import json
import os
import urllib.error
import urllib.request
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


class ModelResolutionError(RuntimeError):
    """A stable LM Studio model could not be selected for a match."""


def _native_models_url(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    return f"{root}/api/v1/models"


def _fetch_loaded_models(base_url: str, api_key: str) -> tuple[str, ...]:
    request = urllib.request.Request(
        _native_models_url(base_url),
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise ModelResolutionError(
            "LM Studio is unavailable. Start its local server and load one model."
        ) from exc

    models = payload.get("models")
    if not isinstance(models, list):
        raise ModelResolutionError("LM Studio returned an invalid model inventory.")
    return tuple(
        model["key"]
        for model in models
        if isinstance(model, dict)
        and model.get("type") in {"llm", "vlm"}
        and model.get("loaded_instances")
        and isinstance(model.get("key"), str)
    )


async def loaded_lmstudio_models(
    *, base_url: str | None = None, api_key: str | None = None
) -> tuple[str, ...]:
    """List only models with loaded instances via LM Studio's native API."""

    return await asyncio.to_thread(
        _fetch_loaded_models,
        base_url or os.getenv("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1"),
        api_key or os.getenv("LMSTUDIO_API_KEY") or "lm-studio",
    )


async def resolve_lmstudio_model(
    explicit: str | None = None,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
) -> str:
    """Resolve one model once; never guess when the loaded set is ambiguous."""

    configured = (
        explicit if explicit is not None else os.getenv("LMSTUDIO_MODEL", "")
    ).strip()
    if configured:
        return configured

    if base_url is None and api_key is None:
        loaded = await loaded_lmstudio_models()
    else:
        loaded = await loaded_lmstudio_models(base_url=base_url, api_key=api_key)
    if not loaded:
        raise ModelResolutionError(
            "LM Studio has no loaded language model. Load one model and try again."
        )
    if len(loaded) > 1:
        choices = ", ".join(loaded)
        raise ModelResolutionError(
            "LM Studio has multiple loaded models. Set LMSTUDIO_MODEL explicitly "
            f"to one of: {choices}"
        )
    return loaded[0]


class LMStudioModel:
    def __init__(
        self,
        client: AsyncOpenAI | None = None,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ):
        self.client = wrap_openai(
            client
            or AsyncOpenAI(
                base_url=base_url
                or os.getenv("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1"),
                api_key=api_key or os.getenv("LMSTUDIO_API_KEY") or "lm-studio",
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

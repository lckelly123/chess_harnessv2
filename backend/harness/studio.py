"""LangGraph Studio factories for the production harness graphs."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langgraph.graph.state import CompiledStateGraph
from langgraph_sdk.runtime import ServerRuntime

from harness.agent_player_1 import AgentConfig
from harness.agent_player_1 import build_graph as build_agent_player_1_graph
from harness.baseline import BaselineConfig
from harness.baseline import build_graph as build_baseline_graph
from harness.model import LMStudioModel, resolve_lmstudio_model


class _IntrospectionModel:
    """Keeps schema and diagram requests independent from LM Studio."""

    async def complete(self, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        raise RuntimeError("The Studio introspection model cannot execute a turn.")


_INTROSPECTION_MODEL = _IntrospectionModel()


def _studio_base_url() -> str:
    """Use a host-reachable URL independently of the Docker backend setting."""

    return os.getenv("LMSTUDIO_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1").strip()


async def _studio_model() -> tuple[LMStudioModel, str]:
    base_url = _studio_base_url()
    api_key = os.getenv("LMSTUDIO_API_KEY") or "lm-studio"
    model_name = await resolve_lmstudio_model(base_url=base_url, api_key=api_key)
    return LMStudioModel(base_url=base_url, api_key=api_key), model_name


def _model_name_for_introspection() -> str:
    return os.getenv("LMSTUDIO_MODEL", "").strip() or "loaded-lmstudio-model"


def _agent_config(model_name: str) -> AgentConfig:
    return AgentConfig(
        model=model_name,
        reasoning_effort=os.getenv("LMSTUDIO_REASONING_EFFORT", "medium"),
        retry_reasoning_effort=os.getenv("LMSTUDIO_RETRY_REASONING_EFFORT", "none"),
    )


def _baseline_config(model_name: str) -> BaselineConfig:
    return BaselineConfig(
        model=model_name,
        reasoning_effort=os.getenv("LMSTUDIO_REASONING_EFFORT", "medium"),
        retry_reasoning_effort=os.getenv("LMSTUDIO_RETRY_REASONING_EFFORT", "none"),
    )


@asynccontextmanager
async def make_agent_player_1_graph(
    runtime: ServerRuntime,
) -> AsyncIterator[CompiledStateGraph]:
    """Build Agent Player 1 for one Studio run and close its HTTP client."""

    if runtime.execution_runtime is None:
        yield build_agent_player_1_graph(
            _INTROSPECTION_MODEL,
            _agent_config(_model_name_for_introspection()),
            accept_turn_input=True,
        )
        return

    model, model_name = await _studio_model()
    try:
        yield build_agent_player_1_graph(
            model,
            _agent_config(model_name),
            accept_turn_input=True,
        )
    finally:
        await model.aclose()


@asynccontextmanager
async def make_baseline_graph(
    runtime: ServerRuntime,
) -> AsyncIterator[CompiledStateGraph]:
    """Build the baseline for one Studio run and close its HTTP client."""

    if runtime.execution_runtime is None:
        yield build_baseline_graph(
            _INTROSPECTION_MODEL,
            _baseline_config(_model_name_for_introspection()),
            accept_turn_input=True,
        )
        return

    model, model_name = await _studio_model()
    try:
        yield build_baseline_graph(
            model,
            _baseline_config(model_name),
            accept_turn_input=True,
        )
    finally:
        await model.aclose()

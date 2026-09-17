"""Stable UI player identifiers and construction of concrete harness graphs."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.models import HarnessVersion, ModelSelection
from harness.agent_player_1 import AgentConfig as AgentPlayer1Config
from harness.agent_player_1 import AgentPlayer1
from harness.agent_player_2 import AgentConfig as AgentPlayer2Config
from harness.agent_player_2 import AgentPlayer2
from harness.baseline import BaselineAgent, BaselineConfig
from harness.contracts import PlayerHarness
from harness.model import Model, ModelResolutionError, resolve_lmstudio_model

BASELINE_ID = "baseline-direct-submit-langgraph-v1"
AGENT_PLAYER_1_ID = "agent-player-1-langgraph-v1"
AGENT_PLAYER_2_ID = "agent-player-2-langgraph-v1"
GPT_LUNA_MODEL = "gpt-5.6-luna"

HARNESSES = (
    HarnessVersion(
        id=BASELINE_ID,
        name="Baseline",
        version="baseline-direct-submit-langgraph-v1",
        summary="Direct legal move submission through a two-node LangGraph.",
    ),
    HarnessVersion(
        id=AGENT_PLAYER_1_ID,
        name="Agent Player 1",
        version="agent-player-1-langgraph-v1",
        summary="Defense, attack, and synthesis phases with deterministic tools.",
    ),
    HarnessVersion(
        id=AGENT_PLAYER_2_ID,
        name="Agent Player 2",
        version="agent-player-2-langgraph-v1",
        summary="Single synthesis phase with deterministic analysis tools.",
    ),
)


class UnknownHarnessError(ValueError):
    """A requested player identifier is not registered."""


@dataclass(frozen=True, slots=True)
class _ResolvedModel:
    client: Model
    name: str
    provider: str
    reasoning_effort: str
    retry_reasoning_effort: str
    max_output_tokens: int | None = None
    retry_max_output_tokens: int | None = None


def _output_limit(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ModelResolutionError(f"{name} must be a positive integer.") from exc
    if not 1 <= value <= 128000:
        raise ModelResolutionError(f"{name} must be between 1 and 128000.")
    return value


class HarnessCatalog:
    def __init__(
        self,
        model: Model,
        model_resolver: Callable[[], Awaitable[str]] = resolve_lmstudio_model,
        *,
        openai_model: Model | None = None,
    ):
        self._model = model
        self._model_resolver = model_resolver
        self._openai_model = openai_model
        self._definitions = {definition.id: definition for definition in HARNESSES}

    def list(self) -> list[HarnessVersion]:
        return list(self._definitions.values())

    def definition(self, harness_id: str) -> HarnessVersion:
        try:
            return self._definitions[harness_id]
        except KeyError as exc:
            raise UnknownHarnessError(f"Unknown harness version: {harness_id}") from exc

    async def create_players(
        self,
        white_id: str,
        black_id: str,
        cancellation_check: Callable[[], bool],
        model_selection: ModelSelection | None = None,
    ) -> tuple[PlayerHarness, PlayerHarness, str]:
        self.definition(white_id)
        self.definition(black_id)
        resolved = await self._resolve_model(model_selection)
        return (
            self._create(white_id, resolved, cancellation_check),
            self._create(black_id, resolved, cancellation_check),
            resolved.name,
        )

    async def create_player(
        self,
        harness_id: str,
        cancellation_check: Callable[[], bool],
        model_selection: ModelSelection | None = None,
    ) -> tuple[PlayerHarness, str]:
        """Resolve one model and construct one harness for a single turn."""

        self.definition(harness_id)
        resolved = await self._resolve_model(model_selection)
        return self._create(harness_id, resolved, cancellation_check), resolved.name

    async def _resolve_model(self, selection: ModelSelection | None) -> _ResolvedModel:
        if selection is not None and selection.model_id == "gpt-luna":
            if self._openai_model is None:
                raise ModelResolutionError(
                    "GPT Luna requires OPENAI_API_KEY in the backend environment. "
                    "Set it and restart the backend."
                )
            return _ResolvedModel(
                client=self._openai_model,
                name=GPT_LUNA_MODEL,
                provider="openai",
                reasoning_effort=selection.reasoning_effort,
                retry_reasoning_effort="none",
                # Includes hidden reasoning and visible notes/tool-call text.
                max_output_tokens=_output_limit("OPENAI_MAX_OUTPUT_TOKENS", 8000),
                retry_max_output_tokens=_output_limit(
                    "OPENAI_RETRY_MAX_OUTPUT_TOKENS", 2000
                ),
            )
        return _ResolvedModel(
            client=self._model,
            name=await self._model_resolver(),
            provider="lmstudio",
            reasoning_effort=selection.reasoning_effort
            if selection is not None
            else os.getenv("LMSTUDIO_REASONING_EFFORT", "medium"),
            retry_reasoning_effort=os.getenv("LMSTUDIO_RETRY_REASONING_EFFORT", "none"),
        )

    def _create(
        self,
        harness_id: str,
        resolved: _ResolvedModel,
        cancellation_check: Callable[[], bool],
    ) -> PlayerHarness:
        settings = {
            "model": resolved.name,
            "provider": resolved.provider,
            "reasoning_effort": resolved.reasoning_effort,
            "retry_reasoning_effort": resolved.retry_reasoning_effort,
        }
        if resolved.max_output_tokens is not None:
            settings["max_output_tokens"] = resolved.max_output_tokens
        if resolved.retry_max_output_tokens is not None:
            settings["retry_max_output_tokens"] = resolved.retry_max_output_tokens
        if harness_id == BASELINE_ID:
            return BaselineAgent(
                resolved.client,
                BaselineConfig(**settings),
                cancellation_check,
            )
        if harness_id == AGENT_PLAYER_1_ID:
            return AgentPlayer1(
                resolved.client,
                AgentPlayer1Config(**settings),
                cancellation_check,
            )
        if harness_id == AGENT_PLAYER_2_ID:
            return AgentPlayer2(
                resolved.client,
                AgentPlayer2Config(**settings),
                cancellation_check,
            )
        raise UnknownHarnessError(f"Unknown harness version: {harness_id}")

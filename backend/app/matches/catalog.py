"""Stable UI player identifiers and construction of concrete harness graphs."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

from app.models import HarnessVersion
from harness.agent_player_1 import AgentConfig, AgentPlayer1
from harness.baseline import BaselineAgent, BaselineConfig
from harness.contracts import PlayerHarness
from harness.model import Model, resolve_lmstudio_model

BASELINE_ID = "baseline-direct-submit-langgraph-v1"
AGENT_PLAYER_1_ID = "agent-player-1-langgraph-v1"

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
)


class UnknownHarnessError(ValueError):
    """A requested player identifier is not registered."""


class HarnessCatalog:
    def __init__(
        self,
        model: Model,
        model_resolver: Callable[[], Awaitable[str]] = resolve_lmstudio_model,
    ):
        self._model = model
        self._model_resolver = model_resolver
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
    ) -> tuple[PlayerHarness, PlayerHarness, str]:
        self.definition(white_id)
        self.definition(black_id)
        model_name = await self._model_resolver()
        return (
            self._create(white_id, model_name, cancellation_check),
            self._create(black_id, model_name, cancellation_check),
            model_name,
        )

    def _create(
        self,
        harness_id: str,
        model_name: str,
        cancellation_check: Callable[[], bool],
    ) -> PlayerHarness:
        reasoning = os.getenv("LMSTUDIO_REASONING_EFFORT", "medium")
        retry_reasoning = os.getenv("LMSTUDIO_RETRY_REASONING_EFFORT", "none")
        if harness_id == BASELINE_ID:
            return BaselineAgent(
                self._model,
                BaselineConfig(
                    model=model_name,
                    reasoning_effort=reasoning,
                    retry_reasoning_effort=retry_reasoning,
                ),
                cancellation_check,
            )
        if harness_id == AGENT_PLAYER_1_ID:
            return AgentPlayer1(
                self._model,
                AgentConfig(
                    model=model_name,
                    reasoning_effort=reasoning,
                    retry_reasoning_effort=retry_reasoning,
                ),
                cancellation_check,
            )
        raise UnknownHarnessError(f"Unknown harness version: {harness_id}")

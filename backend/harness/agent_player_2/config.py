"""Non-secret execution settings. Clients/credentials never enter graph state."""

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentConfig:
    model: str
    reasoning_effort: str | None = None
    max_output_tokens: int = 2000
    max_tool_calls: int = 1000
    max_response_retries: int = 10  # Additional attempts per unchanged input.
    max_model_calls: int = 100
    history_event_limit: int = 7  # Current legacy runtime default (not its older docs).
    prompt_version: str = "agent-player-2-langgraph-v1"
    provider: str = "lmstudio"

    def __post_init__(self):
        if not self.model.strip():
            raise ValueError("Set LMSTUDIO_MODEL to the exact loaded model identifier.")
        for name in (
            "max_output_tokens",
            "max_tool_calls",
            "max_model_calls",
            "history_event_limit",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive.")
        if self.max_response_retries < 0:
            raise ValueError("max_response_retries must be nonnegative.")

    @classmethod
    def from_env(cls):
        return cls(
            model=os.getenv("LMSTUDIO_MODEL", ""),
            reasoning_effort=os.getenv("LMSTUDIO_REASONING_EFFORT") or None,
        )

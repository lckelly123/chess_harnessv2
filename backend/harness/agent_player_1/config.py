"""Non-secret execution settings. Clients/credentials never enter graph state."""

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentConfig:
    model: str
    reasoning_effort: str = "medium"
    retry_reasoning_effort: str = "none"
    max_output_tokens: int = 2000
    retry_max_output_tokens: int = 600
    max_tool_calls: int = 30
    max_failed_tool_calls: int = 3
    max_protocol_retries: int = 20
    max_forced_retries: int = 3
    max_model_calls: int = 80
    history_event_limit: int = 7  # Current legacy runtime default (not its older docs).
    prompt_version: str = "agent-player-1-langgraph-v1"

    def __post_init__(self):
        if not self.model.strip():
            raise ValueError("Set LMSTUDIO_MODEL to the exact loaded model identifier.")
        for name in (
            "max_output_tokens",
            "retry_max_output_tokens",
            "max_tool_calls",
            "max_failed_tool_calls",
            "max_protocol_retries",
            "max_forced_retries",
            "max_model_calls",
            "history_event_limit",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive.")

    @classmethod
    def from_env(cls):
        return cls(
            model=os.getenv("LMSTUDIO_MODEL", ""),
            reasoning_effort=os.getenv("LMSTUDIO_REASONING_EFFORT", "medium"),
            retry_reasoning_effort=os.getenv("LMSTUDIO_RETRY_REASONING_EFFORT", "none"),
        )

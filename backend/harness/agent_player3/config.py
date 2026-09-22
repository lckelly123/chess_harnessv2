"""Non-secret execution settings. Clients/credentials never enter graph state."""

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentConfig:
    model: str
    reasoning_effort: str = "medium"
    retry_reasoning_effort: str = "none"
    max_output_tokens: int = 8000
    retry_max_output_tokens: int = 2000
    max_tool_calls: int = 30
    max_failed_tool_calls: int = 3
    max_protocol_retries: int = 20
    max_forced_retries: int = 3
    max_model_calls: int = 80
    history_event_limit: int = 7  # Current legacy runtime default (not its older docs).
    prompt_version: str = "agent-player-3-langgraph-v1"
    provider: str = "openai"

    def __post_init__(self):
        if not self.model.strip():
            raise ValueError("The OpenAI model identifier cannot be empty.")
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
            model=os.getenv("OPENAI_MODEL", "gpt-5.6-terra"),
            reasoning_effort="medium",
            retry_reasoning_effort="none",
            max_output_tokens=int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "8000")),
            retry_max_output_tokens=int(
                os.getenv("OPENAI_RETRY_MAX_OUTPUT_TOKENS", "2000")
            ),
        )

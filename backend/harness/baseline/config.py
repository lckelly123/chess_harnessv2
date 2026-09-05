"""Versioned baseline settings, independent of the phased agent's config."""

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BaselineConfig:
    model: str
    reasoning_effort: str = "medium"
    retry_reasoning_effort: str = "none"
    max_output_tokens: int = 4000  # Legacy direct-submit baseline cap per call.
    retry_max_output_tokens: int = 600
    max_failed_tool_calls: int = 3
    max_protocol_retries: int = 20
    max_forced_retries: int = 3
    max_model_calls: int = 20
    history_event_limit: int = 7
    prompt_version: str = "baseline-direct-submit-langgraph-v1"

    def __post_init__(self):
        if not self.model.strip():
            raise ValueError("Set LMSTUDIO_MODEL to the exact loaded model identifier.")
        for name in (
            "max_output_tokens",
            "retry_max_output_tokens",
            "max_failed_tool_calls",
            "max_model_calls",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive.")
        for name in (
            "max_protocol_retries",
            "max_forced_retries",
            "history_event_limit",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be nonnegative.")

    @classmethod
    def from_env(cls):
        return cls(
            model=os.getenv("LMSTUDIO_MODEL", ""),
            reasoning_effort=os.getenv("LMSTUDIO_REASONING_EFFORT", "medium"),
            retry_reasoning_effort=os.getenv("LMSTUDIO_RETRY_REASONING_EFFORT", "none"),
        )

"""Manifest-driven prompt sections for Agent Player 1."""

from .builder import (
    PromptPacket,
    build_attack_prompt,
    build_defense_prompt,
    build_prompt,
    build_synthesis_prompt,
)

__all__ = [
    "PromptPacket",
    "build_attack_prompt",
    "build_defense_prompt",
    "build_prompt",
    "build_synthesis_prompt",
]

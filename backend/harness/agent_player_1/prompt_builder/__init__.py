"""Manifest-driven prompt sections for Agent Player 1."""

from .builder import (
    PromptPacket,
    build_attack_prompt,
    build_defense_prompt,
    build_synthesis_prompt,
)
from .context import (
    BoardStateContext,
    ForcedToolRetryContext,
    SeeEvalContext,
    SeeMoveContext,
    SynthesisSeeEvalContext,
    ToolHistoryContext,
    ToolHistoryEntry,
    build_attack_board_state_context,
    build_attack_see_eval_context,
    build_defense_board_state_context,
    build_defense_see_eval_context,
    build_forced_tool_retry_context,
    build_synthesis_board_state_context,
    build_synthesis_see_eval_context,
    build_tool_history_context,
)

__all__ = [
    "BoardStateContext",
    "ForcedToolRetryContext",
    "PromptPacket",
    "SeeEvalContext",
    "SeeMoveContext",
    "SynthesisSeeEvalContext",
    "ToolHistoryContext",
    "ToolHistoryEntry",
    "build_attack_board_state_context",
    "build_attack_prompt",
    "build_attack_see_eval_context",
    "build_defense_board_state_context",
    "build_defense_prompt",
    "build_defense_see_eval_context",
    "build_forced_tool_retry_context",
    "build_synthesis_board_state_context",
    "build_synthesis_prompt",
    "build_synthesis_see_eval_context",
    "build_tool_history_context",
]

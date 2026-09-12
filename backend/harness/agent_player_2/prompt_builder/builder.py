"""Compose model inputs from ordered manifest sections."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined

from ..state import TurnState
from .context import build_condition_context, build_section_context
from .manifest import ConditionSpec, SectionSpec, load_manifest

INPUT_ROOT = Path(__file__).with_name("input_sections")
TEMPLATE_ENVIRONMENT = Environment(
    autoescape=False,
    undefined=StrictUndefined,
    trim_blocks=False,
    lstrip_blocks=True,
    keep_trailing_newline=False,
)


@dataclass(frozen=True, slots=True)
class PromptPacket:
    instructions: str
    dynamic_input: str


def _compact_markdown(value: str) -> str:
    value = re.sub(r"\n{3,}", "\n\n", value)
    return re.sub(r"(?m)(^- [^\n]+)\n\n(?=- )", r"\1\n", value).strip()


def _condition_value(context: dict[str, Any], field: str) -> object:
    value: object = context
    for part in field.split("."):
        if not isinstance(value, dict) or part not in value:
            raise ValueError(f"Unknown prompt manifest condition field: {field}")
        value = value[part]
    return value


def _condition_matches(
    condition: ConditionSpec | None,
    context: dict[str, Any],
) -> bool:
    if condition is None:
        return True
    return _condition_value(context, condition.field) == condition.equals


def _render_section(
    phase: str,
    section: SectionSpec,
    state: TurnState,
) -> str:
    phase_root = (INPUT_ROOT / phase).resolve()
    path = (phase_root / section.template).resolve()
    if not path.is_relative_to(phase_root):
        raise ValueError(f"Prompt section escapes its phase directory: {section.template}")
    template = TEMPLATE_ENVIRONMENT.from_string(path.read_text(encoding="utf-8"))
    context = build_section_context(section.provider, state, section.parameters)
    return _compact_markdown(template.render(**context))


def build_prompt(state: TurnState) -> PromptPacket:
    """Build both model messages from the active phase's manifest."""

    phase = state["phase"]
    manifest = load_manifest(INPUT_ROOT / phase / "manifest.yaml", phase)
    condition_context = build_condition_context(state)
    rendered: dict[str, list[str]] = {"system": [], "user": []}

    for message in manifest.messages:
        for section in message.sections:
            if not _condition_matches(section.condition, condition_context):
                continue
            value = _render_section(phase, section, state)
            if value:
                rendered[message.role].append(value)

    return PromptPacket(
        instructions="\n\n".join(rendered["system"]),
        dynamic_input="\n\n".join(rendered["user"]),
    )


def _build_phase_prompt(state: TurnState, phase: str) -> PromptPacket:
    if state["phase"] != phase:
        raise ValueError(f"Prompt requires {phase} phase state.")
    return build_prompt(state)


def build_attack_prompt(state: TurnState) -> PromptPacket:
    """Compatibility wrapper for callers that already know the phase."""

    return _build_phase_prompt(state, "attack")


def build_defense_prompt(state: TurnState) -> PromptPacket:
    """Compatibility wrapper for callers that already know the phase."""

    return _build_phase_prompt(state, "defense")


def build_synthesis_prompt(state: TurnState) -> PromptPacket:
    """Compatibility wrapper for callers that already know the phase."""

    return _build_phase_prompt(state, "synthesis")

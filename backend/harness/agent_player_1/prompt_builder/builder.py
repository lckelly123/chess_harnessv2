"""Load ordered prompt sections and render their dynamic context."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined

from ..state import TurnState
from .context import (
    build_attack_board_state_context,
    build_attack_see_eval_context,
    build_defense_board_state_context,
    build_defense_see_eval_context,
    build_forced_tool_retry_context,
    build_synthesis_board_state_context,
    build_synthesis_see_eval_context,
    build_tool_history_context,
)

INPUT_ROOT = Path(__file__).with_name("input_sections")


@dataclass(frozen=True, slots=True)
class PromptPacket:
    instructions: str
    dynamic_input: str


def _compact_markdown(value: str) -> str:
    value = re.sub(r"\n{3,}", "\n\n", value)
    return re.sub(r"(?m)(^- [^\n]+)\n\n(?=- )", r"\1\n", value).strip()


def _load_manifest(phase: str) -> dict[str, Any]:
    path = INPUT_ROOT / phase / "manifest.yaml"
    manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("phase") != phase:
        raise ValueError(f"Invalid prompt manifest for {phase}.")
    for role in ("system", "user"):
        names = manifest.get(role)
        if not isinstance(names, list) or not all(
            isinstance(name, str) for name in names
        ):
            raise ValueError(f"Manifest {role} sections must be a list of files.")
    return manifest


def _render_sections(
    phase: str,
    role: str,
    names: list[str],
    context: dict[str, Any],
) -> str:
    role_root = (INPUT_ROOT / phase / role).resolve()
    environment = Environment(
        autoescape=False,
        undefined=StrictUndefined,
        trim_blocks=False,
        lstrip_blocks=True,
        keep_trailing_newline=False,
    )
    rendered = []
    for name in names:
        path = (role_root / name).resolve()
        if not path.is_relative_to(role_root):
            raise ValueError(f"Prompt section escapes its {role} directory: {name}")
        template = environment.from_string(path.read_text(encoding="utf-8"))
        rendered.append(_compact_markdown(template.render(**context)))
    return "\n\n".join(section for section in rendered if section)


def _build_prompt(
    phase: str,
    context: dict[str, Any],
) -> PromptPacket:
    manifest = _load_manifest(phase)
    return PromptPacket(
        instructions=_render_sections(phase, "system", manifest["system"], context),
        dynamic_input=_render_sections(phase, "user", manifest["user"], context),
    )


def build_attack_prompt(state: TurnState) -> PromptPacket:
    """Render the currently migrated attack prompt sections."""

    context = asdict(build_attack_board_state_context(state))
    context["see_eval"] = asdict(build_attack_see_eval_context(state))
    context["tool_history"] = asdict(build_tool_history_context(state))
    context["forced_tool_retry"] = asdict(build_forced_tool_retry_context(state))
    return _build_prompt("attack", context)


def build_defense_prompt(state: TurnState) -> PromptPacket:
    """Render the currently migrated defense prompt sections."""

    context = asdict(build_defense_board_state_context(state))
    context["see_eval"] = asdict(build_defense_see_eval_context(state))
    context["tool_history"] = asdict(build_tool_history_context(state))
    return _build_prompt("defense", context)


def build_synthesis_prompt(state: TurnState) -> PromptPacket:
    """Render the currently migrated synthesis prompt sections."""

    context = asdict(build_synthesis_board_state_context(state))
    context["see_eval"] = asdict(build_synthesis_see_eval_context(state))
    context["tool_history"] = asdict(build_tool_history_context(state))
    return _build_prompt("synthesis", context)

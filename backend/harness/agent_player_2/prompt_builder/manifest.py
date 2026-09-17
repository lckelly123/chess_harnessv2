"""Typed loading and validation for prompt manifests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from .context import PROVIDER_PARAMETER_NAMES

Role = Literal["system", "user"]
CONDITION_VALUES = {
    "scratch.status": frozenset({"active", "unused"}),
    "retry.active": frozenset({True, False}),
}


@dataclass(frozen=True, slots=True)
class ConditionSpec:
    field: str
    equals: str | bool


@dataclass(frozen=True, slots=True)
class SectionSpec:
    id: str
    template: str
    provider: str | None
    condition: ConditionSpec | None
    parameters: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class MessageSpec:
    role: Role
    sections: tuple[SectionSpec, ...]


@dataclass(frozen=True, slots=True)
class PromptManifest:
    version: int
    phase: str
    messages: tuple[MessageSpec, ...]


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping.")
    return value


def _exact_keys(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"{label} contains unknown fields: {sorted(unknown)}")


def _condition(value: object, label: str) -> ConditionSpec | None:
    if value is None:
        return None
    data = _mapping(value, label)
    _exact_keys(data, {"field", "equals"}, label)
    field = data.get("field")
    equals = data.get("equals")
    if not isinstance(field, str) or not isinstance(equals, (str, bool)):
        raise ValueError(f"{label} requires string field and string/bool equals.")
    if field not in CONDITION_VALUES or equals not in CONDITION_VALUES[field]:
        raise ValueError(f"{label} contains an unsupported condition.")
    return ConditionSpec(field=field, equals=equals)


def _validate_provider_parameters(
    provider: str,
    parameters: Mapping[str, Any],
    label: str,
) -> None:
    if set(parameters) != set(PROVIDER_PARAMETER_NAMES[provider]):
        raise ValueError(f"{label}.with does not match provider {provider}.")
    if provider == "board_state":
        source = parameters["source"]
        include_moves = parameters["include_scratch_moves"]
        if source not in ("canonical", "scratch") or not isinstance(
            include_moves, bool
        ):
            raise ValueError(f"{label}.with has invalid board_state values.")
        if include_moves != (source == "scratch"):
            raise ValueError(f"{label}.with has inconsistent board source values.")
    if provider == "see_eval":
        source = parameters["source"]
        actor = parameters["actor"]
        if (
            source not in ("canonical", "scratch")
            or actor not in ("agent", "opponent_after_pass", "side_to_move")
            or parameters["score_perspective"] != "agent"
        ):
            raise ValueError(f"{label}.with has invalid see_eval values.")
        if actor == "opponent_after_pass" and source != "canonical":
            raise ValueError(f"{label}.with cannot pass on a scratchboard scan.")


def _section(value: object, role: Role, label: str) -> SectionSpec:
    data = _mapping(value, label)
    _exact_keys(data, {"id", "template", "provider", "when", "with"}, label)
    section_id = data.get("id")
    template = data.get("template")
    provider = data.get("provider")
    if not isinstance(section_id, str) or not section_id:
        raise ValueError(f"{label}.id must be a non-empty string.")
    if not isinstance(template, str) or not template.endswith(".md"):
        raise ValueError(f"{label}.template must name a Markdown file.")
    if not template.startswith(f"{role}/"):
        raise ValueError(f"{label}.template must be inside the {role} directory.")
    if provider is not None and not isinstance(provider, str):
        raise ValueError(f"{label}.provider must be a string.")
    if role == "system" and (provider is not None or data.get("when") is not None):
        raise ValueError("System sections must be unconditional static templates.")

    parameters = data.get("with", {})
    if not isinstance(parameters, Mapping):
        raise ValueError(f"{label}.with must be a mapping.")
    if role == "user" and provider not in PROVIDER_PARAMETER_NAMES:
        raise ValueError(f"{label}.provider must name a registered provider.")
    if provider is not None:
        _validate_provider_parameters(provider, parameters, label)
    return SectionSpec(
        id=section_id,
        template=template,
        provider=provider,
        condition=_condition(data.get("when"), f"{label}.when"),
        parameters=dict(parameters),
    )


def load_manifest(path: Path, phase: str) -> PromptManifest:
    """Load one v2 manifest and reject ambiguous composition rules."""

    data = _mapping(yaml.safe_load(path.read_text(encoding="utf-8")), str(path))
    _exact_keys(data, {"version", "phase", "messages"}, str(path))
    if data.get("version") != 2 or data.get("phase") != phase:
        raise ValueError(f"Invalid prompt manifest for {phase}.")
    raw_messages = data.get("messages")
    if not isinstance(raw_messages, list):
        raise ValueError("Manifest messages must be a list.")

    messages = []
    section_ids: set[str] = set()
    for message_index, raw_message in enumerate(raw_messages):
        label = f"messages[{message_index}]"
        message = _mapping(raw_message, label)
        _exact_keys(message, {"role", "sections"}, label)
        role = message.get("role")
        if role not in ("system", "user"):
            raise ValueError(f"{label}.role must be system or user.")
        raw_sections = message.get("sections")
        if not isinstance(raw_sections, list):
            raise ValueError(f"{label}.sections must be a list.")
        sections = tuple(
            _section(section, role, f"{label}.sections[{index}]")
            for index, section in enumerate(raw_sections)
        )
        duplicate_ids = section_ids.intersection(section.id for section in sections)
        if duplicate_ids:
            raise ValueError(f"Duplicate prompt section ids: {sorted(duplicate_ids)}")
        section_ids.update(section.id for section in sections)
        messages.append(MessageSpec(role=role, sections=sections))

    if [message.role for message in messages] != ["system", "user"]:
        raise ValueError(
            "Manifest must declare one system message, then one user message."
        )
    phase_root = path.parent.resolve()
    for message in messages:
        for section in message.sections:
            template_path = (phase_root / section.template).resolve()
            if (
                not template_path.is_relative_to(phase_root)
                or not template_path.is_file()
            ):
                raise ValueError(
                    f"Prompt template does not exist inside its phase: {section.template}"
                )
    return PromptManifest(version=2, phase=phase, messages=tuple(messages))

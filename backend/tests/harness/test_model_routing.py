import asyncio

import pytest
from conftest import JUSTIFICATION, ScriptedModel, thoughtful_call

from app.matches.catalog import (
    AGENT_PLAYER_1_ID,
    AGENT_PLAYER_2_ID,
    BASELINE_ID,
    GPT_LUNA_MODEL,
    HarnessCatalog,
)
from app.models import ModelSelection
from harness.model import ModelResolutionError


@pytest.mark.parametrize(
    "harness_id", [BASELINE_ID, AGENT_PLAYER_1_ID, AGENT_PLAYER_2_ID]
)
def test_gpt_selection_bypasses_lmstudio_and_uses_medium(
    harness_id, monkeypatch, request_position
):
    monkeypatch.setenv("LMSTUDIO_REASONING_EFFORT", "high")
    monkeypatch.setenv("LMSTUDIO_RETRY_REASONING_EFFORT", "low")
    monkeypatch.delenv("OPENAI_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.delenv("OPENAI_RETRY_MAX_OUTPUT_TOKENS", raising=False)

    async def unexpected_discovery():
        pytest.fail("GPT selection must not access LM Studio")

    catalog = HarnessCatalog(
        ScriptedModel([]),
        model_resolver=unexpected_discovery,
        openai_model=ScriptedModel([]),
    )
    player, name = asyncio.run(
        catalog.create_player(
            harness_id, lambda: False, ModelSelection(model_id="gpt-luna")
        )
    )
    assert name == player.config.model == GPT_LUNA_MODEL
    assert player.config.provider == "openai"
    assert player.config.reasoning_effort == "medium"
    assert player.config.retry_reasoning_effort == "none"
    assert player.config.max_output_tokens == 8000
    assert player.config.retry_max_output_tokens == 2000
    config = player.run_config(request_position)
    assert "openai" in config["tags"]
    assert "lmstudio" not in config["tags"]
    assert config["metadata"]["provider"] == "openai"


def test_selection_is_held_per_run_without_changing_another_client(request_position):
    def responses():
        return [
            thoughtful_call("scratch_play_move", move="e4"),
            thoughtful_call("scratch_play_move", move="e5"),
            thoughtful_call(
                "submit_move",
                move="e4",
                tested_branch="B1",
                decision_summary=JUSTIFICATION,
            ),
        ]

    local = ScriptedModel(responses())
    cloud = ScriptedModel(responses())
    discoveries = []

    async def resolve_local():
        discoveries.append(True)
        return "test-qwen"

    catalog = HarnessCatalog(local, resolve_local, openai_model=cloud)

    async def run():
        qwen, _ = await catalog.create_player(
            AGENT_PLAYER_2_ID, lambda: False, ModelSelection(model_id="qwen")
        )
        gpt, _ = await catalog.create_player(
            AGENT_PLAYER_2_ID, lambda: False, ModelSelection(model_id="gpt-luna")
        )
        return await asyncio.gather(
            qwen.choose_move(request_position), gpt.choose_move(request_position)
        )

    decisions = asyncio.run(run())
    assert [decision.move.san for decision in decisions] == ["e4", "e4"]
    assert len(discoveries) == 1
    assert len(local.calls) == len(cloud.calls) == 3
    assert {call["model"] for call in local.calls} == {"test-qwen"}
    assert {call["model"] for call in cloud.calls} == {GPT_LUNA_MODEL}
    for local_call, cloud_call in zip(local.calls, cloud.calls, strict=True):
        assert local_call["instructions"] == cloud_call["instructions"]
        assert local_call["dynamic_input"] == cloud_call["dynamic_input"]


@pytest.mark.parametrize("model_id", [None, "qwen", "gpt-luna"])
def test_match_resolves_one_configuration_for_both_players(model_id, monkeypatch):
    monkeypatch.setenv("LMSTUDIO_REASONING_EFFORT", "low")
    discoveries = []

    async def resolve_local():
        discoveries.append(True)
        return "test-qwen"

    catalog = HarnessCatalog(
        ScriptedModel([]), resolve_local, openai_model=ScriptedModel([])
    )
    white, black, name = asyncio.run(
        catalog.create_players(
            BASELINE_ID,
            AGENT_PLAYER_2_ID,
            lambda: False,
            ModelSelection(model_id=model_id) if model_id else None,
        )
    )
    assert white.config.model == black.config.model == name
    assert white.config.reasoning_effort == black.config.reasoning_effort
    if model_id == "gpt-luna":
        assert discoveries == []
        assert name == GPT_LUNA_MODEL
    else:
        assert len(discoveries) == 1
        assert name == "test-qwen"
        assert white.config.max_output_tokens == 4000
        assert black.config.max_output_tokens == 2000
        assert black.config.retry_max_output_tokens == 600
    assert black.config.reasoning_effort == ("low" if model_id is None else "medium")


def test_gpt_output_limits_can_be_configured(monkeypatch):
    monkeypatch.setenv("OPENAI_MAX_OUTPUT_TOKENS", "2000")
    monkeypatch.setenv("OPENAI_RETRY_MAX_OUTPUT_TOKENS", "600")
    catalog = HarnessCatalog(ScriptedModel([]), openai_model=ScriptedModel([]))
    player, _ = asyncio.run(
        catalog.create_player(
            AGENT_PLAYER_2_ID, lambda: False, ModelSelection(model_id="gpt-luna")
        )
    )
    assert player.config.max_output_tokens == 2000
    assert player.config.retry_max_output_tokens == 600


@pytest.mark.parametrize("value", ["0", "-1", "bad", "128001"])
def test_invalid_gpt_output_limit_fails_before_run(monkeypatch, value):
    monkeypatch.setenv("OPENAI_MAX_OUTPUT_TOKENS", value)
    catalog = HarnessCatalog(ScriptedModel([]), openai_model=ScriptedModel([]))
    with pytest.raises(ModelResolutionError, match="OPENAI_MAX_OUTPUT_TOKENS"):
        asyncio.run(
            catalog.create_player(
                AGENT_PLAYER_2_ID, lambda: False, ModelSelection(model_id="gpt-luna")
            )
        )

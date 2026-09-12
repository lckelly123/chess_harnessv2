import asyncio

from conftest import ScriptedModel, finish

from app.matches.catalog import AGENT_PLAYER_2_ID, HarnessCatalog
from harness.agent_player_2 import AgentConfig, AgentPlayer2


def test_agent_player_2_is_an_independent_registered_copy(request_position) -> None:
    model = ScriptedModel(finish())

    async def resolve_model() -> str:
        return "test-model"

    catalog = HarnessCatalog(model, model_resolver=resolve_model)
    player, model_name = asyncio.run(
        catalog.create_player(AGENT_PLAYER_2_ID, lambda: False)
    )
    result = asyncio.run(player.choose_move(request_position))

    assert isinstance(player, AgentPlayer2)
    assert isinstance(player.config, AgentConfig)
    assert player.config.prompt_version == AGENT_PLAYER_2_ID
    assert player.run_config(request_position)["run_name"] == "agent_player_2_turn"
    assert model_name == "test-model"
    assert result.move.san == "e4"

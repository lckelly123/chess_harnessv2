import asyncio
from types import SimpleNamespace

from conftest import JUSTIFICATION, ScriptedModel, call, finish

from chess_core import STARTING_FEN
from harness import studio
from harness.agent_player_1 import AgentConfig
from harness.agent_player_1 import build_graph as build_agent_player_1_graph
from harness.baseline import BaselineConfig
from harness.baseline import build_graph as build_baseline_graph


def public_input(request):
    return request.as_graph_input()


def test_agent_player_1_studio_graph_accepts_public_turn_input(request_position):
    graph = build_agent_player_1_graph(
        ScriptedModel(finish()),
        AgentConfig(model="test-model"),
        accept_turn_input=True,
    )

    async def run():
        updates = []
        async for update in graph.astream(
            public_input(request_position), stream_mode="updates"
        ):
            updates.append(update)
        return updates

    updates = asyncio.run(run())
    assert [name for update in updates for name in update] == [
        "prepare_turn",
        "defense",
        "attack",
        "synthesis",
    ]
    assert updates[-1]["synthesis"]["decision"]["move"] == "e4"


def test_baseline_studio_graph_accepts_public_turn_input(request_position):
    graph = build_baseline_graph(
        ScriptedModel(
            [
                call(
                    "submit_move",
                    move="e4",
                    justification=JUSTIFICATION,
                )
            ]
        ),
        BaselineConfig(model="test-model"),
        accept_turn_input=True,
    )

    state = asyncio.run(graph.ainvoke(public_input(request_position)))

    assert state["canonical_fen"] == STARTING_FEN
    assert state["decision"]["move"] == "e4"
    assert set(graph.get_graph().nodes) == {
        "__start__",
        "prepare_turn",
        "decide",
        "validate_submission",
        "__end__",
    }


def test_studio_introspection_builds_both_graphs_without_lmstudio(monkeypatch):
    async def unexpected_resolution(**kwargs):
        del kwargs
        raise AssertionError("Introspection must not contact LM Studio.")

    monkeypatch.setattr(studio, "resolve_lmstudio_model", unexpected_resolution)
    runtime = SimpleNamespace(execution_runtime=None)

    async def inspect_graphs():
        async with studio.make_agent_player_1_graph(runtime) as phased:
            phased_nodes = set(phased.get_graph().nodes)
        async with studio.make_baseline_graph(runtime) as baseline:
            baseline_nodes = set(baseline.get_graph().nodes)
        return phased_nodes, baseline_nodes

    phased_nodes, baseline_nodes = asyncio.run(inspect_graphs())
    assert {"prepare_turn", "defense", "attack", "synthesis"} <= phased_nodes
    assert {"prepare_turn", "decide", "validate_submission"} <= baseline_nodes


def test_studio_execution_factory_owns_model_client(monkeypatch):
    class ClosingModel(ScriptedModel):
        closed = False

        async def aclose(self):
            self.closed = True

    model = ClosingModel([])

    async def studio_model():
        return model, "test-model"

    monkeypatch.setattr(studio, "_studio_model", studio_model)
    runtime = SimpleNamespace(execution_runtime=object())

    async def build():
        async with studio.make_baseline_graph(runtime) as graph:
            assert "prepare_turn" in graph.get_graph().nodes
            assert not model.closed

    asyncio.run(build())
    assert model.closed

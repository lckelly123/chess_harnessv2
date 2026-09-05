import asyncio
from dataclasses import replace

import pytest
from conftest import ATTACK, DEFENSE, JUSTIFICATION, ScriptedModel, call, finish

from chess_core import STARTING_FEN
from harness.agent_player_1 import AgentConfig, AgentPlayer1
from harness.agent_player_1.state import initial_state
from harness.contracts import HarnessError, TurnCancelled


def run_state(model, request, **settings):
    agent = AgentPlayer1(model, AgentConfig(model="test-model", **settings))
    return asyncio.run(
        agent.graph.ainvoke(initial_state(request), config=agent.run_config(request))
    )


def test_phase_order_and_context_isolation(request_position):
    model = ScriptedModel(
        [
            call("scratch_play_move", move="e4", justification=JUSTIFICATION),
            call("submit_defense_report", report=DEFENSE),
            call("scratch_play_move", move="d4", justification=JUSTIFICATION),
            call("submit_attack_report", report=ATTACK),
            call("scratch_play_move", move="Nf3", justification=JUSTIFICATION),
            call("submit_move", move="e4", justification=JUSTIFICATION),
        ]
    )
    state = run_state(model, request_position)
    assert state["canonical_fen"] == STARTING_FEN
    assert state["decision"]["move"] == "e4"  # Real board, not scratch (black to move).
    assert "Status: active" in model.calls[1]["dynamic_input"]
    for index in (0, 2, 4):
        assert "Status: unused" in model.calls[index]["dynamic_input"]
        assert "No tool calls yet." in model.calls[index]["dynamic_input"]
    assert DEFENSE not in model.calls[2]["dynamic_input"]
    assert DEFENSE in model.calls[4]["dynamic_input"]
    assert ATTACK in model.calls[4]["dynamic_input"]


def test_reasoning_only_forces_same_phase_with_previous_output(request_position):
    model = ScriptedModel(
        [{"output_text": "Investigate the central pawn advance."}, *finish()]
    )
    run_state(model, request_position)
    assert not model.calls[0]["forced_retry"]
    assert model.calls[1]["forced_retry"]
    assert model.calls[1]["reasoning_effort"] == "none"
    assert model.calls[1]["max_output_tokens"] == 600
    assert "Investigate the central pawn advance." in model.calls[1]["dynamic_input"]
    assert not model.calls[2]["forced_retry"]


def test_exposed_reasoning_and_truncation_force_retry(request_position):
    response = {
        "status": "incomplete",
        "output": [
            {"type": "reasoning", "summary": [{"text": "Check the e4 target."}]}
        ],
    }
    model = ScriptedModel([response, *finish()])
    state = run_state(model, request_position)
    assert "Check the e4 target." in model.calls[1]["dynamic_input"]
    assert state["events"][0]["reasoning"] == "Check the e4 target."


def test_forced_retry_is_bounded(request_position):
    model = ScriptedModel([{"output_text": "Still analyzing."}] * 10)
    with pytest.raises(HarnessError, match="forced-tool retries"):
        run_state(model, request_position)
    assert len(model.calls) == 4  # Original + three forced attempts.


def test_rejected_scratch_move_keeps_position_and_history(request_position):
    model = ScriptedModel(
        [call("scratch_play_move", move="e5", justification=JUSTIFICATION), *finish()]
    )
    state = run_state(model, request_position)
    assert "Status: unused" in model.calls[1]["dynamic_input"]
    assert "rejected" in model.calls[1]["dynamic_input"]
    assert "not legal" in model.calls[1]["dynamic_input"]
    assert state["canonical_fen"] == STARTING_FEN


def test_third_illegal_tool_fails_without_a_move(request_position):
    model = ScriptedModel(
        [call("scratch_play_move", move="e5", justification=JUSTIFICATION)] * 3
    )
    with pytest.raises(HarnessError, match="rejected-tool limit"):
        run_state(model, request_position)
    assert len(model.calls) == 3


def test_bad_report_does_not_advance(request_position):
    model = ScriptedModel([call("submit_defense_report", report="bad"), *finish()])
    run_state(model, request_position)
    assert "Phase 1" in model.calls[1]["dynamic_input"]
    assert "Protocol Correction" in model.calls[1]["dynamic_input"]


def test_invalid_final_move_retries_synthesis(request_position):
    model = ScriptedModel(
        [
            *finish()[:2],
            call("submit_move", move="e5", justification=JUSTIFICATION),
            finish()[2],
        ]
    )
    state = run_state(model, request_position)
    assert state["decision"]["move"] == "e4"
    assert "not legal" in model.calls[-1]["dynamic_input"]
    assert "Phase 3" in model.calls[-1]["dynamic_input"]


@pytest.mark.parametrize(
    "settings, match",
    [
        ({"max_model_calls": 1}, "model-call limit"),
        ({"max_tool_calls": 1}, "tool-call limit"),
    ],
)
def test_limits(settings, match, request_position):
    model = ScriptedModel([call("scratch_reset", justification=JUSTIFICATION)] * 4)
    with pytest.raises(HarnessError, match=match):
        run_state(model, request_position, **settings)


def test_history_window_does_not_truncate_trace_events(request_position):
    model = ScriptedModel(
        [call("scratch_reset", justification=JUSTIFICATION)] * 4 + finish()
    )
    state = run_state(model, request_position, history_event_limit=2)
    assert model.calls[4]["dynamic_input"].count("`scratch_reset`") == 2
    assert sum(event.get("tool") == "scratch_reset" for event in state["events"]) == 4


def test_cancellation_before_model_call(request_position):
    model = ScriptedModel(finish())
    agent = AgentPlayer1(
        model, AgentConfig(model="test"), cancellation_check=lambda: True
    )
    with pytest.raises(TurnCancelled):
        asyncio.run(agent.choose_move(request_position))
    assert model.calls == []


def test_cancellation_after_response_prevents_tool(request_position):
    model = ScriptedModel(finish())
    agent = AgentPlayer1(
        model, AgentConfig(model="test"), cancellation_check=lambda: bool(model.calls)
    )
    with pytest.raises(TurnCancelled):
        asyncio.run(agent.choose_move(request_position))
    assert len(model.calls) == 1


def test_provider_errors_do_not_retry_silently(request_position):
    model = ScriptedModel([ConnectionError("LM Studio is unavailable")])
    with pytest.raises(ConnectionError):
        run_state(model, request_position)
    assert len(model.calls) == 1


def test_reusing_compiled_graph_does_not_reuse_turn_state(request_position):
    model = ScriptedModel(finish() + finish())
    agent = AgentPlayer1(model, AgentConfig(model="test"))

    async def twice():
        await agent.choose_move(request_position)
        return await agent.choose_move(replace(request_position, game_id="second"))

    decision = asyncio.run(twice())
    assert decision.move.san == "e4"
    assert "Status: unused" in model.calls[3]["dynamic_input"]
    assert "No tool calls yet." in model.calls[3]["dynamic_input"]


def test_streamed_node_order(request_position):
    model = ScriptedModel(
        [call("scratch_reset", justification=JUSTIFICATION), *finish()]
    )
    agent = AgentPlayer1(model, AgentConfig(model="test"))

    async def collect():
        return [
            name
            async for update in agent.graph.astream(
                initial_state(request_position),
                config=agent.run_config(request_position),
                stream_mode="updates",
            )
            for name in update
        ]

    assert asyncio.run(collect()) == [
        "defense",
        "defense_tools",
        "defense",
        "attack",
        "synthesis",
    ]

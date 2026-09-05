import asyncio
from copy import deepcopy
from dataclasses import replace

import pytest
from conftest import JUSTIFICATION, ScriptedModel, call

from chess_core import STARTING_FEN, apply_move
from harness.baseline import BaselineAgent, BaselineConfig
from harness.baseline.nodes import BaselineNodes
from harness.baseline.state import initial_state
from harness.contracts import HarnessError, TurnCancelled


def submit(move="e4"):
    return call("submit_move", move=move, justification=JUSTIFICATION)


def run_state(model, request, **settings):
    agent = BaselineAgent(model, BaselineConfig(model="test-model", **settings))
    return asyncio.run(
        agent.graph.ainvoke(initial_state(request), config=agent.run_config(request))
    )


def test_direct_move_without_reports_or_board_mutation(request_position):
    model = ScriptedModel([submit()])
    agent = BaselineAgent(model, BaselineConfig(model="test-model"))
    decision = asyncio.run(agent.choose_move(request_position))
    assert decision.move.san == "e4"
    assert decision.move.uci == "e2e4"
    assert decision.justification == JUSTIFICATION
    assert decision.defense_report is None
    assert decision.attack_report is None
    assert request_position.fen == STARTING_FEN
    assert len(model.calls) == 1
    assert model.calls[0]["max_output_tokens"] == 4000
    assert not model.calls[0]["forced_retry"]
    assert set(agent.graph.get_graph().nodes) == {
        "__start__",
        "decide",
        "validate_submission",
        "__end__",
    }


def test_reasoning_only_uses_same_transport_retry(request_position):
    model = ScriptedModel(
        [{"output_text": "Review the central pawn advance."}, submit()]
    )
    state = run_state(model, request_position)
    assert state["canonical_fen"] == STARTING_FEN
    assert state["model_calls"] == 2
    assert state["protocol_errors"] == 0
    assert state["decision"]["move"] == "e4"
    retry = model.calls[1]
    assert retry["forced_retry"]
    assert retry["reasoning_effort"] == "none"
    assert retry["max_output_tokens"] == 600
    assert "Review the central pawn advance." in retry["dynamic_input"]
    assert "Do not continue analysis." in retry["dynamic_input"]
    assert retry["instructions"] == model.calls[0]["instructions"]
    assert [event["type"] for event in state["events"]] == [
        "model_output",
        "forced_tool_retry",
        "model_output",
        "tool_call",
    ]


@pytest.mark.parametrize("reasoning_tokens", [0, 4000])
def test_exposed_reasoning_and_budget_exhaustion(request_position, reasoning_tokens):
    response = {
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
        "output": [
            {"type": "reasoning", "summary": [{"text": "Prefer central development."}]}
        ],
        "usage": {"output_tokens_details": {"reasoning_tokens": reasoning_tokens}},
    }
    model = ScriptedModel([response, {}, submit()])
    state = run_state(model, request_position)
    assert "4000-token" in model.calls[1]["dynamic_input"]
    assert "Reasoning Budget Exhausted" in model.calls[1]["dynamic_input"]
    # Empty forced output must not discard the previous exposed reasoning.
    assert "Prefer central development." in model.calls[2]["dynamic_input"]
    assert state["events"][0]["reasoning"] == "Prefer central development."


def test_forced_retry_limit_is_original_plus_three_attempts(request_position):
    model = ScriptedModel([{"output_text": "Still analyzing."}] * 10)
    with pytest.raises(HarnessError, match="forced-tool retries"):
        run_state(model, request_position)
    assert len(model.calls) == 4


@pytest.mark.parametrize("move", ["Nf5", "e2e4", "--", "0000", "Z0", "@@@@"])
def test_rejected_submission_keeps_fen_and_returns_feedback(request_position, move):
    model = ScriptedModel([submit(move), submit()])
    state = run_state(model, request_position)
    assert state["canonical_fen"] == STARTING_FEN
    assert state["rejected_calls"] == 1
    assert state["history"][0]["ok"] is False
    assert "not legal on the current canonical board" in model.calls[1]["dynamic_input"]
    assert "Status: unused" in model.calls[1]["dynamic_input"]
    assert not model.calls[1]["forced_retry"]  # Chess rejection, not missing protocol.


def test_rejected_forced_submission_preserves_previous_output(request_position):
    model = ScriptedModel(
        [{"output_text": "Keep the king safe."}, submit("e5"), submit()]
    )
    run_state(model, request_position)
    assert model.calls[2]["forced_retry"]
    assert "Keep the king safe." in model.calls[2]["dynamic_input"]
    assert "Rejected." in model.calls[2]["dynamic_input"]


def test_third_rejected_move_fails_turn(request_position):
    model = ScriptedModel([submit("e5")] * 4)
    with pytest.raises(HarnessError, match="rejected-tool limit"):
        run_state(model, request_position)
    assert len(model.calls) == 3


@pytest.mark.parametrize(
    "response",
    [
        call("scratch_play_move", move="e4", justification=JUSTIFICATION),
        call(
            "inspect_square",
            board="canonical",
            square="e4",
            justification=JUSTIFICATION,
        ),
        call("submit_defense_report", report="Severity: None. No immediate threat."),
        call("submit_move", move="e4"),
        call("submit_move", move="e4", justification="check"),
        call("submit_move", move="e4", justification=JUSTIFICATION, fen=STARTING_FEN),
        {"output_text": "<agent_tool_call>{bad}</agent_tool_call>"},
        {"output_text": submit()["output_text"] + submit()["output_text"]},
        {"output_text": submit()["output_text"] + "extra"},
        {"output_text": "</agent_tool_call><agent_tool_call>{}"},
        {},
    ],
)
def test_protocol_errors_retry_without_executing_tools(request_position, response):
    model = ScriptedModel([response, submit()])
    state = run_state(model, request_position)
    assert state["protocol_errors"] == 1
    assert model.calls[1]["forced_retry"]
    assert "## Protocol Correction" in model.calls[1]["dynamic_input"]
    assert [
        event["tool"] for event in state["events"] if event["type"] == "tool_call"
    ] == ["submit_move"]


@pytest.mark.parametrize(
    "settings,match,responses,expected_calls",
    [
        ({"max_protocol_retries": 0}, "protocol retry limit", [{}], 1),
        (
            {"max_forced_retries": 0},
            "forced-tool retries",
            [{"output_text": "Thinking."}],
            1,
        ),
        ({"max_model_calls": 1}, "model-call limit", [submit("e5"), submit()], 1),
    ],
)
def test_independent_limits(
    request_position, settings, match, responses, expected_calls
):
    model = ScriptedModel(responses)
    with pytest.raises(HarnessError, match=match):
        run_state(model, request_position, **settings)
    assert len(model.calls) == expected_calls


@pytest.mark.parametrize("limit", [0, 1])
def test_history_window_does_not_truncate_trace(request_position, limit):
    model = ScriptedModel([submit("e5"), submit("Nf5"), submit()])
    state = run_state(model, request_position, history_event_limit=limit)
    assert len(state["history"]) == limit
    assert (
        len([event for event in state["events"] if event["type"] == "tool_call"]) == 3
    )
    assert model.calls[2]["dynamic_input"].count("### 1. `submit_move`") == limit


@pytest.mark.parametrize("after_response", [False, True])
def test_cancellation_never_submits(request_position, after_response):
    model = ScriptedModel([submit()])
    agent = BaselineAgent(
        model,
        BaselineConfig(model="test"),
        cancellation_check=lambda: bool(model.calls) if after_response else True,
    )
    with pytest.raises(TurnCancelled):
        asyncio.run(agent.choose_move(request_position))
    assert len(model.calls) == int(after_response)


def test_cancellation_between_graph_nodes(request_position):
    model = ScriptedModel([submit()])
    cancelled = False
    nodes = BaselineNodes(model, BaselineConfig(model="test"), lambda: cancelled)
    pending = asyncio.run(nodes.decide(initial_state(request_position)))
    cancelled = True
    with pytest.raises(TurnCancelled):
        nodes.validate_submission(pending)
    assert pending["decision"] is None


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_failed_provider_status_does_not_accept_tool(request_position, status):
    model = ScriptedModel([{**submit(), "status": status}])
    with pytest.raises(HarnessError, match="response status"):
        run_state(model, request_position)
    assert len(model.calls) == 1


def test_provider_exception_not_silently_retried(request_position):
    model = ScriptedModel([ConnectionError("offline")])
    with pytest.raises(ConnectionError):
        run_state(model, request_position)
    assert len(model.calls) == 1


def test_fresh_state_between_invocations(request_position):
    model = ScriptedModel([submit("Nf5"), submit(), submit()])
    agent = BaselineAgent(model, BaselineConfig(model="test"))

    async def twice():
        await agent.choose_move(request_position)
        await agent.choose_move(replace(request_position, game_id="second"))

    asyncio.run(twice())
    assert "No tool calls yet." in model.calls[2]["dynamic_input"]
    assert "Nf5" not in model.calls[2]["dynamic_input"]
    assert "Game ID: `second`" in model.calls[2]["dynamic_input"]


def test_same_graph_supports_independent_concurrent_turns(request_position):
    class PositionModel:
        async def complete(self, **kwargs):
            await asyncio.sleep(0)
            move = "e5" if "Agent side: black" in kwargs["dynamic_input"] else "e4"
            return submit(move)

    black = replace(
        request_position,
        game_id="other-game",
        side="black",
        fen=apply_move(STARTING_FEN, "e4").fen_after,
        pgn="1. e4 *",
        ply=1,
    )
    agent = BaselineAgent(PositionModel(), BaselineConfig(model="test"))

    async def together():
        return await asyncio.gather(
            agent.choose_move(request_position), agent.choose_move(black)
        )

    white_move, black_move = asyncio.run(together())
    assert white_move.move.san == "e4"
    assert black_move.move.san == "e5"
    assert black.fen == apply_move(STARTING_FEN, "e4").fen_after


def test_nodes_do_not_mutate_input_state(request_position):
    model = ScriptedModel([submit()])
    nodes = BaselineNodes(model, BaselineConfig(model="test"))
    state = initial_state(request_position)
    original = deepcopy(state)
    pending = asyncio.run(nodes.decide(state))
    before_validation = deepcopy(pending)
    result = nodes.validate_submission(pending)
    assert state == original
    assert pending == before_validation
    assert result["decision"]["move"] == "e4"


def test_streamed_node_order_exposes_both_retry_kinds(request_position):
    model = ScriptedModel([{"output_text": "Thinking."}, submit("e5"), submit()])
    agent = BaselineAgent(model, BaselineConfig(model="test"))

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
        "decide",
        "decide",
        "validate_submission",
        "decide",
        "validate_submission",
    ]

import asyncio
from copy import deepcopy
from unittest.mock import patch

import pytest
from conftest import (
    JUSTIFICATION,
    ScriptedModel,
    call,
    thoughtful_batch,
    thoughtful_call,
)

from app.matches.catalog import AGENT_PLAYER_2_ID, HarnessCatalog
from harness.agent_player_2 import AgentConfig, AgentPlayer2
from harness.agent_player_2.nodes import SynthesisNodes
from harness.agent_player_2.prompt_builder import build_prompt
from harness.agent_player_2.state import initial_state
from harness.agent_player_2.tools import (
    ToolRejected,
    execute_tool,
    validate_tool_batch,
)
from harness.contracts import HarnessError, TurnCancelled, TurnRequest
from harness.protocol import ToolProtocolError


def verified_e4_responses():
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


def test_agent_player_2_is_a_registered_single_phase_harness(request_position) -> None:
    model = ScriptedModel(verified_e4_responses())

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
    assert result.defense_report is None
    assert result.attack_report is None
    assert len(model.calls) == 3
    assert "# Synthesis" in model.calls[0]["instructions"]
    assert "<agent_tool_calls>" in model.calls[0]["instructions"]
    assert "Phase 1" not in model.calls[0]["instructions"]
    assert "Phase 2" not in model.calls[0]["instructions"]


def test_running_thoughts_annotations_and_tested_lines_flow(request_position) -> None:
    initial_notes = (
        "e4 is the leading candidate, but Black's reply is unresolved. "
        "Play e4 on scratch to expose the reply position."
    )
    reply_notes = "Branch B1 contains e4. Record its purpose and test Black's e5 reply."
    final_notes = (
        "Branch B1 now contains a tested opponent reply and is ready to submit."
    )
    model = ScriptedModel(
        [
            thoughtful_call(
                "scratch_play_move",
                running_thoughts=initial_notes,
                move="e4",
            ),
            thoughtful_batch(
                {
                    "tool": "annotate_branch",
                    "arguments": {
                        "branch_id": "B1",
                        "annotation": "e4 claims central space; Black's reply is being tested.",
                    },
                },
                {"tool": "scratch_play_move", "arguments": {"move": "e5"}},
                running_thoughts=reply_notes,
            ),
            thoughtful_batch(
                {
                    "tool": "annotate_branch",
                    "arguments": {
                        "branch_id": "B1.1",
                        "annotation": "Black answers with e5 without changing material.",
                    },
                },
                {
                    "tool": "submit_move",
                    "arguments": {
                        "move": "e4",
                        "tested_branch": "B1",
                        "decision_summary": JUSTIFICATION,
                    },
                },
                running_thoughts=final_notes,
            ),
        ]
    )
    agent = AgentPlayer2(model, AgentConfig(model="test-model"))

    result = asyncio.run(agent.choose_move(request_position))

    first_follow_up = model.calls[1]["dynamic_input"]
    final_input = model.calls[2]["dynamic_input"]
    tested_lines = final_input.split("# Tested Lines", 1)[1]

    assert result.justification == JUSTIFICATION
    assert "No working notes yet." in model.calls[0]["dynamic_input"]
    assert initial_notes in first_follow_up
    assert "## Latest Tool Batch" in first_follow_up
    assert "Created branch B1 by playing e4" in first_follow_up
    assert "## Branch B1" in first_follow_up
    assert "Ply 1 | Agent (White) | e4" in first_follow_up
    assert "Annotation: None yet" in first_follow_up
    assert "Verification: 1/2 halfmoves tested" in first_follow_up

    assert reply_notes in final_input
    assert "Annotation: e4 claims central space" in tested_lines
    assert "Verification: Done" in tested_lines
    assert "### Branch B1.1" in tested_lines
    assert "Ply 2 | Opponent (Black) | e5" in tested_lines
    assert "Annotation: None yet" in tested_lines
    assert tested_lines.count("Verification:") == 1
    assert "Position:" not in tested_lines
    assert "# Tool History" not in final_input
    assert "`annotate_branch`: Accepted" in final_input
    assert "`scratch_play_move`: Accepted" in final_input


def test_inspect_square_prompt_names_attackers_and_defenders_without_status() -> None:
    model = ScriptedModel(
        [
            thoughtful_call(
                "inspect_square",
                board="canonical",
                square="e3",
            ),
            thoughtful_call("scratch_play_move", move="Qd6"),
            thoughtful_call("scratch_play_move", move="O-O"),
            thoughtful_call(
                "submit_move",
                move="Qd6",
                tested_branch="B1",
                decision_summary=JUSTIFICATION,
            ),
        ]
    )
    agent = AgentPlayer2(model, AgentConfig(model="test-model"))
    request = TurnRequest(
        game_id="inspect-square",
        fen="2r1kb1r/p1p1pppp/2p5/8/3q4/2N1B3/PPP2PPP/R3K2R b KQk - 1 12",
        pgn="*",
        side="black",
    )

    result = asyncio.run(agent.choose_move(request))
    latest_inspection_input = model.calls[1]["dynamic_input"]
    later_input = model.calls[2]["dynamic_input"]
    summary = (
        "Inspected canonical e3; occupant=white bishop; "
        "attackers=black queen d4; defenders=white pawn f2."
    )

    assert result.move.san == "Qd6"
    assert latest_inspection_input.count(summary) == 1
    assert "`inspect_square`: Accepted" in latest_inspection_input
    assert "# Tool History" not in latest_inspection_input
    assert "Created branch B1 by playing Qd6" in later_input
    assert summary not in later_input
    assert "\nStatus:" not in latest_inspection_input
    assert "\nStatus:" not in later_input


def test_missing_running_thoughts_forces_retry_without_executing_tool(
    request_position,
) -> None:
    model = ScriptedModel(
        [
            call("scratch_play_move", move="e4"),
            *verified_e4_responses(),
        ]
    )
    agent = AgentPlayer2(model, AgentConfig(model="test-model"))

    result = asyncio.run(agent.choose_move(request_position))

    assert result.move.san == "e4"
    assert model.calls[1]["forced_retry"]
    assert model.calls[1]["dynamic_input"] == model.calls[0]["dynamic_input"]
    assert model.calls[1]["instructions"] == model.calls[0]["instructions"]
    assert model.calls[1]["reasoning_effort"] is None
    assert model.calls[1]["max_output_tokens"] == 2000
    assert "No tested lines yet." in model.calls[1]["dynamic_input"]


def test_rejected_batch_does_not_execute_annotation_before_retry(
    request_position,
) -> None:
    rolled_back_annotation = "e4 is already fully verified and ready to submit."
    model = ScriptedModel(
        [
            thoughtful_call("scratch_play_move", move="e4"),
            thoughtful_batch(
                {
                    "tool": "annotate_branch",
                    "arguments": {
                        "branch_id": "B1",
                        "annotation": rolled_back_annotation,
                    },
                },
                {
                    "tool": "submit_move",
                    "arguments": {
                        "move": "e4",
                        "tested_branch": "B9",
                        "decision_summary": JUSTIFICATION,
                    },
                },
            ),
            thoughtful_batch(
                {
                    "tool": "annotate_branch",
                    "arguments": {
                        "branch_id": "B1",
                        "annotation": "e4 remains a candidate while e5 is tested.",
                    },
                },
                {"tool": "scratch_play_move", "arguments": {"move": "e5"}},
            ),
            thoughtful_call(
                "submit_move",
                move="e4",
                tested_branch="B1",
                decision_summary=JUSTIFICATION,
            ),
        ]
    )
    agent = AgentPlayer2(model, AgentConfig(model="test-model"))

    with patch(
        "harness.agent_player_2.nodes.execute_tool", wraps=execute_tool
    ) as executed:
        result = asyncio.run(agent.choose_move(request_position))
    assert len(executed.call_args_list) == 4
    assert all(
        call.kwargs["arguments"].get("annotation") != rolled_back_annotation
        for call in executed.call_args_list
    )
    retry_input = model.calls[2]["dynamic_input"]
    tested_lines = retry_input.split("# Tested Lines", 1)[1]

    assert result.move.san == "e4"
    assert rolled_back_annotation not in tested_lines
    assert "Annotation: None yet" in tested_lines
    assert "Verification: 1/2 halfmoves tested" in tested_lines
    assert retry_input == model.calls[1]["dynamic_input"]
    assert "Tested branch `B9` does not exist" not in retry_input


@pytest.mark.parametrize(
    "invalid_tool",
    ["submit_move", "scratch_play_move", "inspect_square", "annotate_branch"],
)
def test_entire_state_survives_a_rejected_batch(request_position, invalid_tool):
    state = initial_state(request_position)
    state.update(
        execute_tool(
            phase="synthesis",
            name="scratch_play_move",
            arguments={"move": "e4"},
            canonical_fen=state["canonical_fen"],
            side=state["side"],
            scratch_moves=[],
            tested_lines=[],
            active_branch_id=None,
        )
    )
    state["running_thoughts"] = "Accepted notes: need to check Black's reply."
    state["latest_tool_results"] = [
        {"tool": "scratch_play_move", "ok": True, "result_summary": "Played e4."}
    ]
    state["history"] = [{"type": "tool_call", "tool": "scratch_play_move"}]
    args = {
        "submit_move": {
            "move": "e4",
            "tested_branch": "B1",
            "decision_summary": JUSTIFICATION,
        },
        "scratch_play_move": {"move": "e4"},  # Black to move now.
        "inspect_square": {"board": "scratch", "square": "z9"},
        "annotate_branch": {"branch_id": "B9", "annotation": "Missing branch."},
    }[invalid_tool]
    response = thoughtful_batch(
        {
            "tool": "annotate_branch",
            "arguments": {"branch_id": "B1", "annotation": "Must not be committed."},
        },
        {"tool": invalid_tool, "arguments": args},
        running_thoughts="Rejected notes must not replace the accepted notes.",
    )
    model = ScriptedModel([response])
    nodes = SynthesisNodes(model, AgentConfig(model="offline"))
    before = deepcopy(state)
    with patch(
        "harness.agent_player_2.nodes.execute_tool", wraps=execute_tool
    ) as executed:
        after = asyncio.run(nodes.synthesis(state))
        if after["pending_tools"]:
            after = nodes.synthesis_tools(after)
        executed.assert_not_called()
    for key in (
        "canonical_fen",
        "scratch_moves",
        "tested_lines",
        "active_branch_id",
        "running_thoughts",
        "latest_tool_results",
        "history",
        "decision",
        "tool_calls",
    ):
        assert after[key] == before[key], key
    assert state == before
    assert after["forced_retry"]
    assert after["pending_tools"] == []
    assert build_prompt(after) == build_prompt(before)


@pytest.mark.parametrize(
    "bad_response",
    [
        {"status": "completed", "output_text": "I need to think more."},
        thoughtful_call("annotate_branch", branch_id="B1", annotation="x" * 601),
        thoughtful_call("scratch_play_move", move="e5"),
        {
            **thoughtful_call("scratch_play_move", move="e4"),
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
        },
    ],
)
def test_ten_additional_attempts_reuse_identical_input_and_settings(
    request_position, bad_response
):
    model = ScriptedModel([deepcopy(bad_response) for _ in range(11)])
    agent = AgentPlayer2(
        model,
        AgentConfig(model="offline", reasoning_effort="high", max_output_tokens=3500),
    )
    with patch(
        "harness.agent_player_2.nodes.execute_tool", wraps=execute_tool
    ) as executed:
        with pytest.raises(HarnessError, match="exhausted 10 same-input retries"):
            asyncio.run(agent.choose_move(request_position))
        executed.assert_not_called()
    assert len(model.calls) == 11
    first = {k: v for k, v in model.calls[0].items() if k != "forced_retry"}
    assert all(
        {k: v for k, v in c.items() if k != "forced_retry"} == first
        for c in model.calls
    )
    assert not model.calls[0]["forced_retry"]
    assert all(c["forced_retry"] for c in model.calls[1:])
    assert first["max_output_tokens"] == 3500
    assert first["reasoning_effort"] == "high"


def test_retry_count_resets_after_an_accepted_batch(request_position):
    model = ScriptedModel(
        [
            *[{} for _ in range(10)],
            thoughtful_call("scratch_play_move", move="e4"),
            *[thoughtful_call("scratch_play_move", move="e4") for _ in range(10)],
            thoughtful_call("scratch_play_move", move="e5"),
            thoughtful_call(
                "submit_move",
                move="e4",
                tested_branch="B1",
                decision_summary=JUSTIFICATION,
            ),
        ]
    )
    agent = AgentPlayer2(model, AgentConfig(model="offline"))
    result = asyncio.run(agent.choose_move(request_position))
    assert result.move.san == "e4"
    assert len(model.calls) == 23
    assert not model.calls[11]["forced_retry"]
    assert not model.calls[22]["forced_retry"]
    assert model.calls[0]["dynamic_input"] != model.calls[11]["dynamic_input"]


def test_retry_uses_captured_input_without_rebuilding_it(request_position):
    model = ScriptedModel([{}, *verified_e4_responses()])
    original_prompt = build_prompt(initial_state(request_position))
    with patch(
        "harness.agent_player_2.nodes.build_prompt", return_value=original_prompt
    ) as builder:
        result = asyncio.run(
            AgentPlayer2(model, AgentConfig(model="offline")).choose_move(
                request_position
            )
        )
    assert result.move.san == "e4"
    assert builder.call_count == 3  # Once per accepted pass, never again for its retry.


def test_provider_failure_is_not_resampled(request_position):
    model = ScriptedModel([HarnessError("Unsloth timed out")])
    with pytest.raises(HarnessError, match="Unsloth timed out"):
        asyncio.run(
            AgentPlayer2(model, AgentConfig(model="offline")).choose_move(
                request_position
            )
        )
    assert len(model.calls) == 1


def test_cancellation_and_model_budget_stop_retrying(request_position):
    model = ScriptedModel([{}, {}])
    with pytest.raises(HarnessError, match="model-call limit"):
        asyncio.run(
            AgentPlayer2(
                model, AgentConfig(model="offline", max_model_calls=2)
            ).choose_move(request_position)
        )
    assert len(model.calls) == 2
    model = ScriptedModel([{}])
    with pytest.raises(TurnCancelled):
        asyncio.run(
            AgentPlayer2(model, AgentConfig(model="offline"), lambda: True).choose_move(
                request_position
            )
        )
    assert model.calls == []


def test_scratch_navigation_preserves_and_reuses_tested_branches(
    request_position,
) -> None:
    state = initial_state(request_position)
    scratch_moves = state["scratch_moves"]
    tested_lines = state["tested_lines"]
    active_branch_id = state["active_branch_id"]

    def apply(name, **arguments):
        nonlocal scratch_moves, tested_lines, active_branch_id
        result = execute_tool(
            phase="synthesis",
            name=name,
            arguments=arguments,
            canonical_fen=state["canonical_fen"],
            side=state["side"],
            scratch_moves=scratch_moves,
            tested_lines=tested_lines,
            active_branch_id=active_branch_id,
        )
        scratch_moves = result["scratch_moves"]
        tested_lines = result["tested_lines"]
        active_branch_id = result["active_branch_id"]
        return result

    assert apply("scratch_play_move", move="e4")["result"]["branch_id"] == "B1"
    assert apply("scratch_play_move", move="e5")["result"]["branch_id"] == "B1.1"
    apply("scratch_undo")
    assert apply("scratch_play_move", move="c5")["result"]["branch_id"] == "B1.2"
    apply("scratch_reset")
    replay = apply("scratch_play_move", move="e4")

    assert replay["result"]["branch_id"] == "B1"
    assert replay["result"]["reused"] is True
    assert active_branch_id == "B1"
    assert scratch_moves == ["e4"]
    assert [node["branch_id"] for node in tested_lines] == ["B1", "B1.1", "B1.2"]


def test_submit_move_rejects_an_incomplete_base_branch(request_position) -> None:
    state = initial_state(request_position)
    candidate = execute_tool(
        phase="synthesis",
        name="scratch_play_move",
        arguments={"move": "e4"},
        canonical_fen=state["canonical_fen"],
        side=state["side"],
        scratch_moves=[],
        tested_lines=[],
        active_branch_id=None,
    )

    with pytest.raises(ToolRejected, match="B1.*incomplete"):
        execute_tool(
            phase="synthesis",
            name="submit_move",
            arguments={
                "move": "e4",
                "tested_branch": "B1",
                "decision_summary": JUSTIFICATION,
            },
            canonical_fen=state["canonical_fen"],
            side=state["side"],
            scratch_moves=candidate["scratch_moves"],
            tested_lines=candidate["tested_lines"],
            active_branch_id=candidate["active_branch_id"],
        )


def test_scratch_branch_cannot_exceed_four_halfmoves(request_position) -> None:
    state = initial_state(request_position)
    scratch_moves = []
    tested_lines = []
    active_branch_id = None

    for move in ("e4", "e5", "Nf3", "Nc6"):
        result = execute_tool(
            phase="synthesis",
            name="scratch_play_move",
            arguments={"move": move},
            canonical_fen=state["canonical_fen"],
            side=state["side"],
            scratch_moves=scratch_moves,
            tested_lines=tested_lines,
            active_branch_id=active_branch_id,
        )
        scratch_moves = result["scratch_moves"]
        tested_lines = result["tested_lines"]
        active_branch_id = result["active_branch_id"]

    with pytest.raises(ToolRejected, match="limited to 4 halfmoves"):
        execute_tool(
            phase="synthesis",
            name="scratch_play_move",
            arguments={"move": "Bb5"},
            canonical_fen=state["canonical_fen"],
            side=state["side"],
            scratch_moves=scratch_moves,
            tested_lines=tested_lines,
            active_branch_id=active_branch_id,
        )


def test_tested_line_material_change_is_cumulative_from_agent_perspective() -> None:
    request = TurnRequest(
        game_id="material-change",
        fen="2r1kb1r/p1p1pppp/2p5/8/3q4/2N1B3/PPP2PPP/R3K2R b KQk - 1 12",
        pgn="*",
        side="black",
    )
    state = initial_state(request)
    first = execute_tool(
        phase="synthesis",
        name="scratch_play_move",
        arguments={"move": "Qxe3+"},
        canonical_fen=state["canonical_fen"],
        side=state["side"],
        scratch_moves=[],
        tested_lines=[],
        active_branch_id=None,
    )
    reply = execute_tool(
        phase="synthesis",
        name="scratch_play_move",
        arguments={"move": "fxe3"},
        canonical_fen=state["canonical_fen"],
        side=state["side"],
        scratch_moves=first["scratch_moves"],
        tested_lines=first["tested_lines"],
        active_branch_id=first["active_branch_id"],
    )

    assert first["tested_lines"][0]["material_change_cp"] == 330
    assert reply["tested_lines"][1]["material_change_cp"] == -570


@pytest.mark.parametrize(
    ("calls", "message"),
    [
        (
            [
                {"tool": "scratch_undo", "arguments": {}},
                {"tool": "scratch_reset", "arguments": {}},
            ],
            "at most one board-mutating call",
        ),
        (
            [
                {
                    "tool": "inspect_square",
                    "arguments": {"board": "canonical", "square": "e4"},
                },
                {"tool": "scratch_play_move", "arguments": {"move": "e4"}},
            ],
            "cannot share a batch",
        ),
        (
            [
                {
                    "tool": "annotate_branch",
                    "arguments": {"branch_id": "B1", "annotation": "First"},
                },
                {
                    "tool": "annotate_branch",
                    "arguments": {"branch_id": "B1", "annotation": "Second"},
                },
            ],
            "cannot annotate the same branch",
        ),
    ],
)
def test_ambiguous_parallel_tool_batches_are_rejected(calls, message) -> None:
    with pytest.raises(ToolProtocolError, match=message):
        validate_tool_batch(calls)

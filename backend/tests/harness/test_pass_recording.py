import asyncio
import json
from uuid import uuid4

import pytest
from conftest import JUSTIFICATION, ScriptedModel, call, finish, thoughtful_call

from harness.agent_player3 import AgentConfig as Config3
from harness.agent_player3 import AgentPlayer3
from harness.agent_player_1 import AgentConfig as Config1
from harness.agent_player_1 import AgentPlayer1
from harness.agent_player_2 import AgentConfig as Config2
from harness.agent_player_2 import AgentPlayer2
from harness.baseline import BaselineAgent, BaselineConfig
from harness.contracts import HarnessError
from harness.recording import current_recorder
from positional_testing.recording import PassRecorder


def native(identifier, *actions, notes="Inspect central space and the opponent reply."):
    return {
        "status": "completed",
        "output": [
            {
                "type": "reasoning",
                "encrypted_content": "must-never-be-stored",
                "summary": [],
            },
            {
                "type": "function_call",
                "name": "agent_step",
                "call_id": identifier,
                "arguments": json.dumps(
                    {"running_thoughts": notes, "tool_calls": actions}
                ),
            },
        ],
    }


def action(tool, **arguments):
    return {"tool": tool, "arguments": arguments}


async def record(agent, request, store):
    run_id = str(uuid4())
    recorder = PassRecorder(store, run_id)
    token = current_recorder.set(recorder)
    try:
        await agent.choose_move(request)
    finally:
        current_recorder.reset(token)
    return [row for (rid, _), row in store.passes.items() if rid == run_id]


@pytest.mark.parametrize("harness", ["baseline", "agent1", "agent2", "agent3"])
def test_each_model_invocation_is_one_complete_pass(
    harness, request_position, run_store
):
    if harness == "baseline":
        responses = [call("submit_move", move="e4", justification=JUSTIFICATION)]
        agent = BaselineAgent(ScriptedModel(responses), BaselineConfig(model="offline"))
    elif harness == "agent1":
        responses = finish()
        agent = AgentPlayer1(ScriptedModel(responses), Config1(model="offline"))
    elif harness == "agent2":
        responses = [
            thoughtful_call("scratch_play_move", move="e4"),
            thoughtful_call("scratch_play_move", move="e5"),
            thoughtful_call(
                "submit_move",
                move="e4",
                tested_branch="B1",
                decision_summary=JUSTIFICATION,
            ),
        ]
        agent = AgentPlayer2(ScriptedModel(responses), Config2(model="offline"))
    else:
        responses = [
            native("one", action("scratch_play_move", move="e4")),
            native(
                "two",
                action(
                    "annotate_branch", branch_id="B1", annotation="Reply unresolved."
                ),
                action("scratch_play_move", move="e5"),
            ),
            native(
                "three",
                action(
                    "annotate_branch",
                    branch_id="B1.1",
                    annotation="Material unchanged.",
                ),
                action(
                    "submit_move",
                    move="e4",
                    tested_branch="B1",
                    decision_summary=JUSTIFICATION,
                ),
            ),
        ]
        agent = AgentPlayer3(ScriptedModel(responses), Config3(model="offline"))
    rows = asyncio.run(record(agent, request_position, run_store))
    assert len(rows) == len(responses)
    assert [r["pass_number"] for r in rows] == list(range(1, len(rows) + 1))
    assert all(r["status"] == "completed" and r["finished_at"] for r in rows)
    assert all(
        c["executed"] and c["result"] is not None for r in rows for c in r["tool_calls"]
    )
    assert rows[-1]["tool_calls"][-1]["tool_name"] == "submit_move"
    assert "must-never-be-stored" not in str(rows)
    if harness in {"agent2", "agent3"}:
        assert all(r["working_notes"] for r in rows)
    if harness == "agent3":
        assert [len(r["tool_calls"]) for r in rows] == [1, 2, 2]
        assert rows[1]["tool_calls"][1]["board_context"]["scratch_moves"] == ["e4"]


def test_retries_and_provider_failure_keep_their_own_passes(
    request_position, run_store
):
    agent = BaselineAgent(
        ScriptedModel(
            [
                {"output_text": "I need to inspect the position before submitting."},
                HarnessError("Offline provider failure"),
            ]
        ),
        BaselineConfig(model="offline"),
    )
    with pytest.raises(HarnessError, match="Offline provider failure"):
        asyncio.run(record(agent, request_position, run_store))
    rows = list(run_store.passes.values())
    assert len(rows) == 2
    assert rows[0]["working_notes"].startswith("I need to inspect")
    assert rows[0]["tool_calls"] == []
    assert all(r["status"] == "failed" and r["error"] for r in rows)
    assert current_recorder.get() is None


def test_terminal_rejection_retains_calls_and_rollback(request_position, run_store):
    responses = [
        native("one", action("scratch_play_move", move="e4")),
        native(
            "bad",
            action(
                "annotate_branch",
                branch_id="B1",
                annotation="Pending opponent response.",
            ),
            action("scratch_play_move", move="e4"),
        ),
    ]
    agent = AgentPlayer3(
        ScriptedModel(responses), Config3(model="offline", max_failed_tool_calls=1)
    )
    with pytest.raises(HarnessError, match="rejected-tool limit"):
        asyncio.run(record(agent, request_position, run_store))
    rows = list(run_store.passes.values())
    assert rows[0]["status"] == "completed"
    assert rows[1]["status"] == "failed"
    assert rows[1]["tool_calls"][0]["rolled_back"] is True
    assert rows[1]["tool_calls"][0]["result"] is None
    assert rows[1]["tool_calls"][1]["error"]


def test_simultaneous_turns_do_not_mix_passes(request_position, run_store):
    async def turns():
        return await asyncio.gather(
            *[
                record(
                    BaselineAgent(
                        ScriptedModel(
                            [
                                call(
                                    "submit_move",
                                    move=move,
                                    justification=JUSTIFICATION,
                                )
                            ]
                        ),
                        BaselineConfig(model=move),
                    ),
                    request_position,
                    run_store,
                )
                for move in ("e4", "d4")
            ]
        )

    left, right = asyncio.run(turns())
    assert left[0]["run_id"] != right[0]["run_id"]
    assert left[0]["tool_calls"][0]["arguments"]["move"] == "e4"
    assert right[0]["tool_calls"][0]["arguments"]["move"] == "d4"


def test_cancelled_call_preserves_started_pass(request_position, run_store):
    async def check():
        entered = asyncio.Event()

        class WaitingModel:
            async def complete(self, **kwargs):
                entered.set()
                await asyncio.Event().wait()

        agent = BaselineAgent(WaitingModel(), BaselineConfig(model="offline"))
        task = asyncio.create_task(record(agent, request_position, run_store))
        await entered.wait()
        assert list(run_store.passes.values())[0]["status"] == "running"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        row = list(run_store.passes.values())[0]
        assert row["status"] == "failed"
        assert row["finished_at"]

    asyncio.run(check())

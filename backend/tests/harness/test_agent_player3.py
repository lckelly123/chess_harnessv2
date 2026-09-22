import asyncio
import json
from copy import deepcopy

import httpx2
import pytest
from conftest import JUSTIFICATION, ScriptedModel, thoughtful_call
from fastapi.testclient import TestClient
from openai import AsyncOpenAI

from app.main import create_app
from app.matches.catalog import (
    AGENT_PLAYER_3_ID,
    BASELINE_ID,
    GPT_TERRA_MODEL,
    HarnessCatalog,
)
from app.matches.repository import MatchRepository
from app.models import ModelSelection
from harness.agent_player3 import AgentConfig, AgentPlayer3
from harness.agent_player3.__main__ import DemoModel
from harness.agent_player3.prompt_builder import build_prompt
from harness.agent_player3.protocol import (
    agent_step_schema,
    parse_agent_response,
    replayable_output,
)
from harness.agent_player3.state import initial_state
from harness.agent_player3.tools import tool_schemas
from harness.contracts import HarnessError, TurnCancelled
from harness.model import OpenAIModel
from harness.protocol import ToolProtocolError


def action(name, **arguments):
    return {"tool": name, "arguments": arguments}


def native_response(call_id, *actions, notes="Vulnerabilities: Assess the position."):
    return {
        "status": "completed",
        "output": [
            {
                "type": "reasoning",
                "id": f"rs_{call_id}",
                "summary": [],
                "encrypted_content": f"opaque_{call_id}",
            },
            {
                "type": "function_call",
                "id": f"fc_{call_id}",
                "call_id": call_id,
                "name": "agent_step",
                "status": "completed",
                "arguments": json.dumps(
                    {"running_thoughts": notes, "tool_calls": list(actions)}
                ),
            },
        ],
    }


def verified_responses():
    return [
        native_response("candidate", action("scratch_play_move", move="e4")),
        native_response(
            "reply",
            action("annotate_branch", branch_id="B1", annotation="Reply untested."),
            action("scratch_play_move", move="e5"),
            notes="The e4 candidate is tested. Check Black's legal e5 reply.",
        ),
        native_response(
            "submit",
            action(
                "annotate_branch", branch_id="B1.1", annotation="Material unchanged."
            ),
            action(
                "submit_move",
                move="e4",
                tested_branch="B1",
                decision_summary=JUSTIFICATION,
            ),
            notes="Synthesis: e4 e5 is tested. Top-line candidate: e4.",
        ),
    ]


def run_script(request_position, responses, **settings):
    model = ScriptedModel(responses)
    agent = AgentPlayer3(model, AgentConfig(model="test-model", **settings))
    state = asyncio.run(
        agent.graph.ainvoke(
            initial_state(request_position), config=agent.run_config(request_position)
        )
    )
    return state, model


def function_results(history):
    return [
        (item["call_id"], json.loads(item["output"]))
        for item in history
        if item.get("type") == "function_call_output"
    ]


@pytest.mark.parametrize("override", [None, "explicit-model"])
def test_native_config_defaults_to_terra_and_preserves_model_override(
    monkeypatch, override
):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    if override is not None:
        monkeypatch.setenv("OPENAI_MODEL", override)
    config = AgentConfig.from_env()
    assert config.model == (override or "gpt-5.6-terra")
    assert config.reasoning_effort == "medium"
    assert config.retry_reasoning_effort == "none"


def test_native_schema_covers_each_existing_action_with_strict_arguments():
    schema = agent_step_schema()
    assert schema["type"] == "function"
    assert schema["name"] == "agent_step"
    assert schema["strict"] is True
    assert schema["parameters"]["required"] == ["running_thoughts", "tool_calls"]
    variants = schema["parameters"]["properties"]["tool_calls"]["items"]["anyOf"]
    expected = {tool["name"]: tool["parameters"] for tool in tool_schemas("synthesis")}
    assert {
        variant["properties"]["tool"]["enum"][0]: variant["properties"]["arguments"]
        for variant in variants
    } == expected

    def check_objects(value):
        if isinstance(value, dict):
            if value.get("type") == "object":
                assert value["additionalProperties"] is False
                assert set(value["required"]) == set(value["properties"])
            for child in value.values():
                check_objects(child)
        elif isinstance(value, list):
            for child in value:
                check_objects(child)

    check_objects(schema)


def test_native_calls_commit_notes_tools_and_correlated_results(request_position):
    state, model = run_script(request_position, verified_responses())
    assert state["decision"]["move"] == "e4"
    assert state["scratch_moves"] == ["e4", "e5"]
    assert state["tested_lines"][0]["annotation"] == "Reply untested."
    assert state["tested_lines"][1]["annotation"] == "Material unchanged."
    assert "Top-line candidate: e4" in state["running_thoughts"]
    assert [call_id for call_id, _ in function_results(state["native_history"])] == [
        "candidate",
        "reply",
        "submit",
    ]
    assert all(result["ok"] for _, result in function_results(state["native_history"]))
    assert len(model.calls) == 3
    assert model.calls[0]["native_turn"].history == []
    assert "# Scratch Position" in model.calls[1]["dynamic_input"]
    assert "Verification: Done" in model.calls[2]["dynamic_input"]
    assert state["pending_call_id"] is None
    assert state["pending_running_thoughts"] == ""
    assert state["forced_retry"] is False


def test_all_chess_actions_are_dispatched_inside_native_steps(request_position):
    responses = [
        native_response(
            "inspect",
            action("inspect_square", board="canonical", square="e2"),
            action("inspect_square", board="canonical", square="e4"),
        ),
        *verified_responses()[:2],
        native_response("undo", action("scratch_undo")),
        native_response("reset", action("scratch_reset")),
        verified_responses()[2],
    ]
    state, _ = run_script(request_position, responses)
    assert state["decision"]["move"] == "e4"
    assert state["scratch_moves"] == []
    results = function_results(state["native_history"])
    dispatched = {event["tool"] for _, result in results for event in result["results"]}
    assert dispatched == {tool["name"] for tool in tool_schemas("synthesis")}
    assert results[0][1]["results"][0]["result"]


@pytest.mark.parametrize(
    "arguments",
    [
        "not json",
        "[]",
        "{}",
        '{"running_thoughts":"","tool_calls":[]}',
        '{"running_thoughts":3,"tool_calls":[]}',
        '{"running_thoughts":"notes","tool_calls":[]}',
        '{"running_thoughts":"notes","tool_calls":[{}]}',
        '{"running_thoughts":"notes","tool_calls":[{"tool":3,"arguments":{}}]}',
    ],
)
def test_malformed_native_arguments_are_rejected(arguments):
    response = verified_responses()[0]
    response["output"][-1]["arguments"] = arguments
    with pytest.raises(ToolProtocolError):
        parse_agent_response(response)


def test_tagged_text_is_not_executable_or_reinjected_as_evidence(request_position):
    fake = thoughtful_call(
        "scratch_play_move", move="e4", running_thoughts="INVENTED verified line."
    )
    state, model = run_script(request_position, [fake, *verified_responses()])
    assert state["tool_calls"] == 5
    assert model.calls[1]["forced_retry"] is True
    assert "No tested lines yet" in model.calls[1]["dynamic_input"]
    assert "INVENTED" not in model.calls[1]["dynamic_input"]
    assert model.calls[1]["native_turn"].history == []
    assert "<agent_tool_calls>" not in model.calls[1]["instructions"]


def test_truncated_response_never_executes_its_complete_looking_call(request_position):
    incomplete = native_response("partial", action("scratch_play_move", move="d4"))
    incomplete["status"] = "incomplete"
    incomplete["incomplete_details"] = {"reason": "max_output_tokens"}
    state, model = run_script(request_position, [incomplete, *verified_responses()])
    assert state["scratch_moves"] == ["e4", "e5"]
    assert "No tested lines yet" in model.calls[1]["dynamic_input"]
    assert model.calls[1]["native_turn"].history == []
    assert model.calls[1]["reasoning_effort"] == "none"
    assert model.calls[2]["reasoning_effort"] == "medium"


def test_invalid_batch_returns_native_error_before_any_action(request_position):
    invalid = native_response(
        "invalid",
        action("scratch_play_move", move="d4"),
        action("scratch_play_move", move="d5"),
    )
    state, model = run_script(request_position, [invalid, *verified_responses()])
    error = function_results(model.calls[1]["native_turn"].history)[0]
    assert error[0] == "invalid"
    assert error[1]["ok"] is False
    assert error[1]["executed"] is False
    assert "at most one board-mutating" in error[1]["error"]
    assert state["scratch_moves"] == ["e4", "e5"]


def test_rejected_batch_rolls_back_notes_annotations_and_success_results(
    request_position,
):
    rejected = native_response(
        "rejected",
        action("annotate_branch", branch_id="B1", annotation="FALSE verified claim."),
        action("scratch_play_move", move="e4"),
        notes="FALSE new thesis.",
    )
    script = verified_responses()
    state, model = run_script(request_position, [script[0], rejected, *script[1:]])
    followup = model.calls[2]
    assert followup["forced_retry"] is False
    assert followup["reasoning_effort"] == "medium"
    assert "FALSE" not in followup["dynamic_input"]
    assert "Annotation: None yet" in followup["dynamic_input"]
    call_id, error = function_results(followup["native_turn"].history)[-1]
    assert call_id == "rejected"
    assert error["committed"] is False
    assert error["running_thoughts"] == "Vulnerabilities: Assess the position."
    assert all(event["ok"] is False for event in error["results"])
    assert all("result" not in event for event in error["results"])
    assert state["rejected_calls"] == 1


def test_rejection_after_protocol_retry_resumes_normal_reasoning(request_position):
    rejected = native_response(
        "unverified",
        action(
            "submit_move", move="e4", tested_branch="B1", decision_summary=JUSTIFICATION
        ),
        notes="FALSE candidate already verified.",
    )
    _, model = run_script(
        request_position,
        [{"status": "completed", "output": []}, rejected, *verified_responses()],
    )
    assert [call["reasoning_effort"] for call in model.calls[:3]] == [
        "medium",
        "none",
        "medium",
    ]
    assert model.calls[2]["forced_retry"] is False
    assert "FALSE" not in model.calls[2]["dynamic_input"]
    assert "No tested lines yet" in model.calls[2]["dynamic_input"]


def test_multiple_native_steps_are_rejected_and_each_gets_a_result(request_position):
    response = native_response("one", action("scratch_play_move", move="d4"))
    response["output"].extend(
        native_response("two", action("scratch_play_move", move="d5"))["output"]
    )
    _, model = run_script(request_position, [response, *verified_responses()])
    results = function_results(model.calls[1]["native_turn"].history)
    assert [call_id for call_id, _ in results] == ["one", "two"]
    assert all(result["executed"] is False for _, result in results)


@pytest.mark.parametrize("call_id", [None, "", [], "candidate"])
def test_invalid_or_reused_call_ids_do_not_execute(request_position, call_id):
    script = verified_responses()
    bad = native_response("bad", action("scratch_reset"))
    bad["output"][-1]["call_id"] = call_id
    state, model = run_script(request_position, [script[0], bad, *script[1:]])
    assert state["scratch_moves"] == ["e4", "e5"]
    assert (
        model.calls[2]["native_turn"].history == model.calls[1]["native_turn"].history
    )


def test_native_retry_limits_and_cancellation_are_still_enforced(request_position):
    empty = {"status": "completed", "output": []}
    with pytest.raises(HarnessError, match="exhausted forced-tool retries"):
        run_script(request_position, [empty, empty], max_forced_retries=1)
    model = ScriptedModel([])
    agent = AgentPlayer3(model, AgentConfig(model="test"), lambda: True)
    with pytest.raises(TurnCancelled):
        asyncio.run(agent.choose_move(request_position))
    assert model.calls == []


def test_prompts_use_native_arguments_without_tag_or_yaml_instructions(
    request_position,
):
    state = initial_state(request_position)
    state["forced_retry"] = True
    state["correction"] = "Use a valid native tool call."
    packet = build_prompt(state)
    text = packet.instructions + packet.dynamic_input
    for obsolete in (
        "<running_thoughts>",
        "<agent_tool_calls>",
        "```yaml",
        "active reasoning",
    ):
        assert obsolete not in text
    assert "native `agent_step`" in text
    assert "Use a valid native tool call." in text
    assert "No chess actions or Working Notes" in text


def test_demo_uses_native_protocol_and_history_is_fresh_per_turn(request_position):
    agent = AgentPlayer3(DemoModel(), AgentConfig(model="scripted-demo"))
    result = asyncio.run(agent.choose_move(request_position))
    assert result.move.san == "e4"
    first = initial_state(request_position)
    second = initial_state(request_position)
    first["native_history"].append({"example": "not shared"})
    assert second["native_history"] == []


@pytest.mark.parametrize("function_metadata", [{}, {"async": False}])
def test_openai_http_roundtrip_uses_native_schema_outputs_and_reasoning(
    request_position,
    function_metadata,
):
    responses = iter(verified_responses())
    requests = []
    expected_replay = []

    def transport(request):
        assert request.url.host == "api.openai.com"
        assert request.url.path == "/v1/responses"
        payload = json.loads(request.content)
        # Follow-up requests must preserve wire fields without SDK defaults/renames.
        replayed_items = [
            item
            for item in payload["input"]
            if item.get("type") in {"reasoning", "message", "function_call"}
        ]
        assert replayed_items == expected_replay
        requests.append(payload)
        response = deepcopy(next(responses))
        response["output"][-1].update(function_metadata)
        response.update(
            id=f"resp_{len(requests)}",
            object="response",
            created_at=1,
            model="gpt-5.6-terra",
        )
        response["output"].insert(
            1,
            {
                "type": "message",
                "id": f"msg_{len(requests)}",
                "role": "assistant",
                "status": "completed",
                "phase": "commentary",
                "content": [
                    {"type": "output_text", "text": "Checking.", "annotations": []}
                ],
            },
        )
        expected_replay.extend(deepcopy(response["output"]))
        return httpx2.Response(200, json=response)

    model = OpenAIModel(
        AsyncOpenAI(
            api_key="test-native-only",
            max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(transport)),
        )
    )
    agent = AgentPlayer3(model, AgentConfig(model="gpt-5.6-terra"))

    async def run():
        try:
            return await agent.choose_move(request_position)
        finally:
            await model.aclose()

    assert asyncio.run(run()).move.san == "e4"
    assert len(requests) == 3
    for request in requests:
        assert request["tools"] == [agent_step_schema()]
        assert request["tool_choice"] == {"type": "function", "name": "agent_step"}
        assert request["parallel_tool_calls"] is False
        assert request["include"] == ["reasoning.encrypted_content"]
        assert request["reasoning"] == {"effort": "medium"}
        assert request["store"] is False
        assert "previous_response_id" not in request
        assert request["input"][0]["role"] == "developer"
        assert request["input"][-1]["role"] == "user"
    assert [item["role"] for item in requests[0]["input"]] == ["developer", "user"]
    followup = requests[1]["input"]
    assert any(item.get("encrypted_content") == "opaque_candidate" for item in followup)
    assert any(item.get("phase") == "commentary" for item in followup)
    assert function_results(followup)[0][0] == "candidate"
    assert function_results(followup)[0][1]["results"][0]["tool"] == "scratch_play_move"
    assert "# Scratch Position" in followup[-1]["content"]


def test_incomplete_calls_are_not_replayed():
    response = verified_responses()[0]
    response["output"][-1]["status"] = "incomplete"
    assert replayable_output(response) == []
    with pytest.raises(ToolProtocolError, match="incomplete"):
        parse_agent_response(response)


def test_catalog_constructs_native_player_for_matches():
    catalog = HarnessCatalog(ScriptedModel([]), openai_model=ScriptedModel([]))
    white, black, model = asyncio.run(
        catalog.create_players(
            AGENT_PLAYER_3_ID,
            BASELINE_ID,
            lambda: False,
            ModelSelection(model_id="gpt-terra"),
        )
    )
    assert isinstance(white, AgentPlayer3)
    assert white.config.prompt_version == AGENT_PLAYER_3_ID
    assert white.config.model == black.config.model == model == GPT_TERRA_MODEL
    assert white.config.provider == "openai"


def test_positional_api_runs_registered_native_player(database_path):
    cloud = ScriptedModel(
        [
            native_response("candidate", action("scratch_play_move", move="Qd6")),
            native_response("reply", action("scratch_play_move", move="O-O")),
            native_response(
                "submit",
                action(
                    "submit_move",
                    move="Qd6",
                    tested_branch="B1",
                    decision_summary="Scripted registration test after testing the legal reply.",
                ),
            ),
        ]
    )
    repository = MatchRepository(str(database_path))
    app = create_app(
        repository=repository,
        catalog=HarnessCatalog(ScriptedModel([]), openai_model=cloud),
    )
    try:
        with TestClient(app) as client:
            definition = next(
                harness
                for harness in client.get("/api/harnesses").json()
                if harness["id"] == AGENT_PLAYER_3_ID
            )
            assert definition["name"] == "Agent Player 3"
            response = client.post(
                "/api/positional-testing/runs",
                json={
                    "positionId": "before_queen_blunder",
                    "harnessId": AGENT_PLAYER_3_ID,
                    "modelSelection": {
                        "modelId": "gpt-terra",
                        "reasoningEffort": "medium",
                    },
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["harnessId"] == AGENT_PLAYER_3_ID
            assert response.json()["harnessName"] == "Agent Player 3"
            assert response.json()["model"] == GPT_TERRA_MODEL
            assert response.json()["move"]["san"] == "Qd6"
            assert len(cloud.calls) == 3
            assert all(
                call["native_turn"].function_name == "agent_step"
                for call in cloud.calls
            )
            assert repository.list_matches().total == 0
    finally:
        repository.close()

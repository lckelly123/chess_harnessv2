import asyncio
import json
from unittest.mock import Mock

import httpx2
import pytest
from conftest import JUSTIFICATION, call, finish
from langchain_core.tracers.langchain import LangChainTracer, wait_for_all_tracers
from langsmith import Client, tracing_context
from openai import AsyncOpenAI

from harness.agent_player_1 import AgentConfig, AgentPlayer1
from harness.agent_player_1.state import initial_state
from harness.baseline import BaselineAgent, BaselineConfig
from harness.baseline.state import initial_state as baseline_initial_state
from harness.model import LMStudioModel


def mock_provider(responses):
    script = iter(responses)
    calls = []

    def transport(request):
        calls.append(json.loads(request.content))
        item = next(script)
        return httpx2.Response(
            200,
            json={
                "id": f"resp_{len(calls)}",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": "test-local-model",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "id": f"msg_{len(calls)}",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": item["output_text"],
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "total_tokens": 120,
                },
            },
        )

    client = AsyncOpenAI(
        base_url="http://lmstudio.invalid/v1",
        api_key="test-local-secret",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(transport)),
    )
    return LMStudioModel(client), calls


def test_local_request_contract_and_forced_retry(request_position):
    model, calls = mock_provider(
        [{"output_text": "Review the current position."}, *finish()]
    )
    agent = AgentPlayer1(model, AgentConfig(model="test-local-model"))

    async def run():
        try:
            return await agent.choose_move(request_position)
        finally:
            await model.aclose()

    decision = asyncio.run(run())
    assert decision.move.san == "e4"
    for payload in calls:
        assert payload["store"] is False
        assert "tools" not in payload  # Text tools are embedded in instructions.
        assert "previous_response_id" not in payload
        assert "conversation" not in payload
        assert [item["role"] for item in payload["input"]] == ["developer", "user"]
        assert "<agent_tool_call>" in payload["input"][0]["content"]
        assert "test-local-secret" not in json.dumps(payload)
    assert calls[0]["reasoning"] == {"effort": "medium"}
    assert calls[1]["reasoning"] == {"effort": "none"}
    assert calls[0]["max_output_tokens"] == 2000
    assert calls[1]["max_output_tokens"] == 600


def test_langsmith_records_nested_graph_model_and_tool_runs(request_position):
    model, requests = mock_provider(
        [
            {"output_text": "Review the current position."},
            call("scratch_reset", justification=JUSTIFICATION),
            *finish(),
        ]
    )
    # Capture SDK emissions in memory; no LangSmith account or network needed.
    trace_client = Mock(spec=Client)
    tracer = LangChainTracer(client=trace_client, project_name="offline-test")
    agent = AgentPlayer1(model, AgentConfig(model="test-local-model"))

    async def run():
        try:
            config = {**agent.run_config(request_position), "callbacks": [tracer]}
            return await agent.graph.ainvoke(
                initial_state(request_position), config=config
            )
        finally:
            await model.aclose()

    with tracing_context(enabled=True, client=trace_client):
        state = asyncio.run(run())
    wait_for_all_tracers()
    starts = [item.kwargs for item in trace_client.create_run.call_args_list]
    roots = [run for run in starts if run.get("name") == "agent_player_1_turn"]
    assert roots
    assert roots[0]["extra"]["metadata"]["game_id"] == "test-game"
    llms = [run for run in starts if run.get("run_type") == "llm"]
    assert len(llms) == len(requests) == 5
    assert all(run.get("parent_run_id") for run in llms)
    assert any(run.get("name") == "LM Studio forced tool retry" for run in llms)
    tools = [run for run in starts if run.get("run_type") == "tool"]
    assert {run["name"] for run in tools} == {
        "scratch_reset",
        "submit_defense_report",
        "submit_attack_report",
        "submit_move",
    }
    assert all(run.get("parent_run_id") for run in tools)
    assert state["decision"]["move"] == "e4"
    assert "test-local-secret" not in str(trace_client.mock_calls)


def test_configuration_requires_an_explicit_local_model(monkeypatch):
    monkeypatch.delenv("LMSTUDIO_MODEL", raising=False)
    with pytest.raises(ValueError, match="LMSTUDIO_MODEL"):
        AgentConfig.from_env()


def test_baseline_local_transport_and_nested_langsmith_trace(request_position):
    model, requests = mock_provider(
        [
            {"output_text": "Review the central pawn advance."},
            call("submit_move", move="e5", justification=JUSTIFICATION),
            call("submit_move", move="e4", justification=JUSTIFICATION),
        ]
    )
    trace_client = Mock(spec=Client)
    tracer = LangChainTracer(client=trace_client, project_name="offline-test")
    agent = BaselineAgent(model, BaselineConfig(model="test-local-model"))

    async def run():
        try:
            config = {**agent.run_config(request_position), "callbacks": [tracer]}
            return await agent.graph.ainvoke(
                baseline_initial_state(request_position), config=config
            )
        finally:
            await model.aclose()

    with tracing_context(enabled=True, client=trace_client):
        state = asyncio.run(run())
    wait_for_all_tracers()
    starts = [item.kwargs for item in trace_client.create_run.call_args_list]
    root = next(run for run in starts if run.get("name") == "baseline_turn")
    metadata = root["extra"]["metadata"]
    assert metadata["game_id"] == metadata["thread_id"] == "test-game"
    assert metadata["harness"] == "baseline"
    assert metadata["harness_version"] == "baseline-direct-submit-langgraph-v1"
    assert metadata["side"] == "white"
    assert metadata["ply"] == 0
    assert metadata["model"] == "test-local-model"
    llms = [run for run in starts if run.get("run_type") == "llm"]
    tools = [run for run in starts if run.get("run_type") == "tool"]
    assert len(llms) == len(requests) == 3
    assert [run["name"] for run in tools] == ["submit_move", "submit_move"]
    assert sum(run["name"] == "LM Studio forced tool retry" for run in llms) == 2
    by_id = {str(run["id"]): run for run in starts}
    for run in llms + tools:
        parent = by_id[str(run["parent_run_id"])]
        assert parent["name"] == (
            "decide" if run["run_type"] == "llm" else "validate_submission"
        )
        assert str(parent["parent_run_id"]) == str(root["id"])
        assert run["extra"]["metadata"]["thread_id"] == "test-game"
        assert run["extra"]["metadata"]["harness"] == "baseline"
    assert state["decision"]["move"] == "e4"
    assert state["rejected_calls"] == 1
    assert requests[0]["max_output_tokens"] == 4000
    assert requests[0]["reasoning"] == {"effort": "medium"}
    for payload in requests[1:]:
        assert payload["max_output_tokens"] == 600
        assert payload["reasoning"] == {"effort": "none"}
    for payload in requests:
        assert payload["store"] is False
        assert "tools" not in payload
        assert "previous_response_id" not in payload
        assert "conversation" not in payload
        assert [message["role"] for message in payload["input"]] == [
            "developer",
            "user",
        ]
        assert "<agent_tool_call>" in payload["input"][0]["content"]
    assert "test-local-secret" not in str(trace_client.mock_calls)


def test_both_agents_trace_into_one_project_without_context_leakage(request_position):
    model, _ = mock_provider(
        [*finish(), call("submit_move", move="e4", justification=JUSTIFICATION)]
    )
    trace_client = Mock(spec=Client)
    tracer = LangChainTracer(client=trace_client, project_name="shared-offline-project")
    phased = AgentPlayer1(model, AgentConfig(model="test-local-model"))
    baseline = BaselineAgent(model, BaselineConfig(model="test-local-model"))

    async def run():
        try:
            await phased.graph.ainvoke(
                initial_state(request_position),
                config={**phased.run_config(request_position), "callbacks": [tracer]},
            )
            await baseline.graph.ainvoke(
                baseline_initial_state(request_position),
                config={**baseline.run_config(request_position), "callbacks": [tracer]},
            )
        finally:
            await model.aclose()

    with tracing_context(enabled=True, client=trace_client):
        asyncio.run(run())
    wait_for_all_tracers()
    starts = [item.kwargs for item in trace_client.create_run.call_args_list]
    roots = [
        run
        for run in starts
        if run.get("name") in {"agent_player_1_turn", "baseline_turn"}
    ]
    assert len(roots) == 2
    assert {run["session_name"] for run in roots} == {"shared-offline-project"}
    assert {run["extra"]["metadata"]["harness"] for run in roots} == {
        "agent_player_1",
        "baseline",
    }
    assert all(run["extra"]["metadata"]["thread_id"] == "test-game" for run in starts)
    assert not any(run.get("parent_run_id") for run in roots)

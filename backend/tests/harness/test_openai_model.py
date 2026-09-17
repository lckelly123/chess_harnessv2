import asyncio
import json
from unittest.mock import Mock

import httpx2
import pytest
from conftest import JUSTIFICATION, ScriptedModel, thoughtful_batch, thoughtful_call
from fastapi.testclient import TestClient
from langchain_core.tracers.langchain import LangChainTracer, wait_for_all_tracers
from langsmith import Client, tracing_context
from openai import AsyncOpenAI

from app import main as main_module
from app.main import create_app
from app.matches.catalog import (
    AGENT_PLAYER_2_ID,
    BASELINE_ID,
    GPT_LUNA_MODEL,
    HarnessCatalog,
)
from app.matches.repository import MatchRepository
from app.models import ModelSelection
from harness.agent_player_2.state import initial_state
from harness.contracts import HarnessError
from harness.model import LMStudioModel, ModelResolutionError, OpenAIModel


def mock_openai(responses):
    script = iter(responses)
    requests = []

    def transport(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert request.url.host == "api.openai.com"
        assert request.url.path == "/v1/responses"
        assert request.headers["authorization"] == "Bearer test-openai-secret"
        item = next(script)
        if isinstance(item, httpx2.Response):
            return item
        exhausted = item.get("status") == "incomplete"
        text = item.get("output_text")
        output = [{"type": "reasoning", "id": "rs_test", "summary": []}]
        if text:
            output.append(
                {
                    "type": "message",
                    "role": "assistant",
                    "id": f"msg_{len(requests)}",
                    "status": "completed",
                    "content": [
                        {"type": "output_text", "text": text, "annotations": []}
                    ],
                }
            )
        return httpx2.Response(
            200,
            json={
                "id": f"resp_{len(requests)}",
                "object": "response",
                "created_at": 1,
                "status": "incomplete" if exhausted else "completed",
                "incomplete_details": {"reason": "max_output_tokens"}
                if exhausted
                else None,
                "model": GPT_LUNA_MODEL,
                "output": output,
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 8000 if exhausted else 100,
                    "total_tokens": 8100 if exhausted else 200,
                    "output_tokens_details": {
                        "reasoning_tokens": 8000 if exhausted else 0
                    },
                },
            },
        )

    client = AsyncOpenAI(
        base_url="https://api.openai.com/v1",
        api_key="test-openai-secret",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(transport)),
    )
    return OpenAIModel(client), requests


def test_gpt_runs_existing_graph_with_notes_batches_and_hidden_reasoning_retry(
    request_position,
):
    model, requests = mock_openai(
        [
            {"status": "incomplete"},
            thoughtful_call(
                "scratch_play_move",
                move="e4",
                running_thoughts="Test e4 before judging it.",
            ),
            thoughtful_batch(
                {
                    "tool": "annotate_branch",
                    "arguments": {
                        "branch_id": "B1",
                        "annotation": "e4 is tested; the reply is pending.",
                    },
                },
                {"tool": "scratch_play_move", "arguments": {"move": "e5"}},
                running_thoughts="Test the listed e5 reply.",
            ),
            thoughtful_batch(
                {
                    "tool": "annotate_branch",
                    "arguments": {
                        "branch_id": "B1.1",
                        "annotation": "e4 e5 leaves material unchanged.",
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
                running_thoughts="The tested e4 e5 line is the leading candidate.",
            ),
        ]
    )
    trace_client = Mock(spec=Client)
    tracer = LangChainTracer(client=trace_client, project_name="offline-openai-test")
    catalog = HarnessCatalog(ScriptedModel([]), openai_model=model)

    async def run():
        try:
            player, name = await catalog.create_player(
                AGENT_PLAYER_2_ID, lambda: False, ModelSelection(model_id="gpt-luna")
            )
            assert name == GPT_LUNA_MODEL
            return await player.graph.ainvoke(
                initial_state(request_position),
                config={**player.run_config(request_position), "callbacks": [tracer]},
            )
        finally:
            await model.aclose()

    with tracing_context(enabled=True, client=trace_client):
        state = asyncio.run(run())
    wait_for_all_tracers()
    assert state["decision"]["move"] == "e4"
    assert (
        state["running_thoughts"] == "The tested e4 e5 line is the leading candidate."
    )
    assert state["forced_retry"] is False
    assert len(requests) == 4
    assert [call["reasoning"]["effort"] for call in requests] == [
        "medium",
        "none",
        "medium",
        "medium",
    ]
    assert [call["max_output_tokens"] for call in requests] == [8000, 2000, 8000, 8000]
    assert (
        "No visible previous output was captured" in requests[1]["input"][1]["content"]
    )
    assert "Test e4 before judging it." in requests[2]["input"][1]["content"]
    assert "e4 is tested; the reply is pending." in requests[3]["input"][1]["content"]
    for payload in requests:
        assert payload["model"] == GPT_LUNA_MODEL
        assert payload["store"] is False
        assert "tools" not in payload
        assert "previous_response_id" not in payload
        assert [message["role"] for message in payload["input"]] == [
            "developer",
            "user",
        ]
        assert "<running_thoughts>" in payload["input"][0]["content"]
        assert "<agent_tool_calls>" in payload["input"][0]["content"]

    starts = [item.kwargs for item in trace_client.create_run.call_args_list]
    root = next(run for run in starts if run["name"] == "agent_player_2_turn")
    assert root["extra"]["metadata"]["provider"] == "openai"
    llms = [run for run in starts if run.get("run_type") == "llm"]
    assert len(llms) == 4
    assert all(run["extra"]["metadata"]["ls_provider"] == "openai" for run in llms)
    assert all(
        run["extra"]["metadata"]["ls_model_name"] == GPT_LUNA_MODEL for run in llms
    )
    assert sum(run["name"] == "OpenAI forced tool retry" for run in llms) == 1
    assert "test-openai-secret" not in str(trace_client.mock_calls)


def test_gpt_positional_api_uses_real_graph_and_reports_resolved_model(database_path):
    model, requests = mock_openai(
        [
            thoughtful_call("scratch_play_move", move="Qxe3+"),
            thoughtful_call("scratch_play_move", move="fxe3"),
            thoughtful_call(
                "submit_move",
                move="Qxe3+",
                tested_branch="B1",
                decision_summary="Scripted transport test, not a move recommendation.",
            ),
        ]
    )
    repository = MatchRepository(str(database_path))
    app = create_app(
        repository=repository,
        catalog=HarnessCatalog(ScriptedModel([]), openai_model=model),
    )
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/positional-testing/runs",
                json={
                    "positionId": "before_queen_blunder",
                    "harnessId": AGENT_PLAYER_2_ID,
                    "modelSelection": {
                        "modelId": "gpt-luna",
                        "reasoningEffort": "medium",
                    },
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["model"] == GPT_LUNA_MODEL
            assert response.json()["move"]["san"] == "Qxe3+"
            assert len(requests) == 3
            assert repository.list_matches().total == 0
    finally:
        asyncio.run(model.aclose())
        repository.close()


@pytest.mark.parametrize(
    "status, message",
    [
        (401, "authentication failed"),
        (403, "denied access"),
        (429, "quota exceeded"),
        (404, "HTTP 404"),
        (500, "HTTP 500"),
    ],
)
def test_provider_failures_return_safe_actionable_api_errors(
    database_path, status, message
):
    model, requests = mock_openai(
        [
            httpx2.Response(
                status,
                json={
                    "error": {"message": "test-openai-secret", "type": "provider_error"}
                },
            )
        ]
    )
    repository = MatchRepository(str(database_path))
    app = create_app(
        repository=repository,
        catalog=HarnessCatalog(ScriptedModel([]), openai_model=model),
    )
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/positional-testing/runs",
                json={
                    "positionId": "before_queen_blunder",
                    "harnessId": BASELINE_ID,
                    "modelSelection": {"modelId": "gpt-luna"},
                },
            )
            assert response.status_code == 502
            assert "OpenAI" in response.json()["detail"]
            assert message in response.json()["detail"]
            assert "test-openai-secret" not in response.text
            assert len(requests) == 1
    finally:
        asyncio.run(model.aclose())
        repository.close()


def test_missing_key_does_not_use_lmstudio_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LMSTUDIO_API_KEY", "not-an-openai-key")
    with pytest.raises(ModelResolutionError, match="OPENAI_API_KEY"):
        OpenAIModel()


def test_openai_credentials_cannot_be_routed_to_local_endpoint(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://local.invalid/v1")
    monkeypatch.setenv("LMSTUDIO_BASE_URL", "http://local.invalid/v1")
    model = OpenAIModel()
    try:
        assert str(model.client.base_url) == "https://api.openai.com/v1/"
        assert model.client.api_key == "test-openai-secret"
        assert model.client.max_retries == 0
    finally:
        asyncio.run(model.aclose())


def test_connection_failure_is_a_harness_error():
    def transport(request):
        raise httpx2.ConnectError("test-openai-secret", request=request)

    client = AsyncOpenAI(
        api_key="test-openai-secret",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(transport)),
    )
    model = OpenAIModel(client)

    async def run():
        try:
            await model.complete(
                model=GPT_LUNA_MODEL,
                instructions="test",
                dynamic_input="test",
                reasoning_effort="medium",
                max_output_tokens=2000,
                forced_retry=False,
            )
        finally:
            await model.aclose()

    with pytest.raises(HarnessError, match="OpenAI could not be reached") as error:
        asyncio.run(run())
    assert "test-openai-secret" not in str(error.value)


@pytest.mark.parametrize("has_key", [False, True])
def test_app_initializes_and_closes_only_configured_clients(
    database_path, monkeypatch, has_key
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-secret" if has_key else "")
    local = Mock(spec=LMStudioModel)
    cloud = Mock(spec=OpenAIModel)
    local_factory = Mock(return_value=local)
    cloud_factory = Mock(return_value=cloud)
    monkeypatch.setattr(main_module, "LMStudioModel", local_factory)
    monkeypatch.setattr(main_module, "OpenAIModel", cloud_factory)
    repository = MatchRepository(str(database_path))
    app = create_app(repository=repository)
    try:
        with TestClient(app) as client:
            assert client.get("/api/health").status_code == 200
            if has_key:
                player, name = asyncio.run(
                    app.state.match_manager.catalog.create_player(
                        AGENT_PLAYER_2_ID,
                        lambda: False,
                        ModelSelection(model_id="gpt-luna"),
                    )
                )
                assert name == GPT_LUNA_MODEL
                assert player.config.provider == "openai"
            local.aclose.assert_not_awaited()
            cloud.aclose.assert_not_awaited()
        local_factory.assert_called_once_with()
        local.aclose.assert_awaited_once()
        if has_key:
            cloud_factory.assert_called_once_with()
            cloud.aclose.assert_awaited_once()
        else:
            cloud_factory.assert_not_called()
            cloud.aclose.assert_not_awaited()
    finally:
        repository.close()

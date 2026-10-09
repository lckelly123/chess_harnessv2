import asyncio
import io
import json
import urllib.error
from unittest.mock import Mock

import httpx2
import pytest
from fastapi.testclient import TestClient
from openai import AsyncOpenAI

import app.routes as routes
import harness.model as models
from app.main import create_app
from app.matches.catalog import AGENT_PLAYER_2_ID, HarnessCatalog
from app.models import ModelSelection
from harness.agent_player_2.nodes import SynthesisNodes
from harness.agent_player_2.state import initial_state
from harness.contracts import HarnessError
from harness.model import ModelResolutionError, UnslothModel
from positional_testing.models import CreatePositionQueueRequest
from positional_testing.queue import PositionQueueManager

CHECKPOINT = "Qwen_Qwen3-14B__project-test_train_set_1_1791485578"


def test_discovery_lists_loaded_language_models_only_and_authenticates(monkeypatch):
    def open_request(request, timeout):
        assert request.full_url == "http://localhost:8888/v1/models"
        assert request.get_header("Authorization") == "Bearer test-unsloth-secret"
        return io.StringIO(
            json.dumps(
                {
                    "data": [
                        {"id": CHECKPOINT, "loaded": True},
                        {"id": "downloaded-base", "loaded": False},
                        {"id": "unknown-state"},
                        {"id": "audio", "loaded": True, "task": "text-to-speech"},
                        {"id": CHECKPOINT, "loaded": True},
                    ]
                }
            )
        )

    monkeypatch.setattr(models.urllib.request, "urlopen", open_request)
    assert asyncio.run(
        models.loaded_unsloth_models(
            base_url="http://localhost:8888/v1/", api_key="test-unsloth-secret"
        )
    ) == (CHECKPOINT,)


@pytest.mark.parametrize("inventory", [[], [CHECKPOINT, "second-adapter"]])
def test_discovery_does_not_guess_or_fall_back(monkeypatch, inventory):
    async def discovered():
        return tuple(inventory)

    monkeypatch.delenv("UNSLOTH_MODEL", raising=False)
    monkeypatch.setattr(models, "loaded_unsloth_models", discovered)
    with pytest.raises(ModelResolutionError):
        asyncio.run(models.resolve_unsloth_model())


def test_explicit_checkpoint_does_not_follow_newly_loaded_model(monkeypatch):
    async def unexpected():
        raise AssertionError("Pinned checkpoints must not rediscover")

    monkeypatch.setattr(models, "loaded_unsloth_models", unexpected)
    assert asyncio.run(models.resolve_unsloth_model(CHECKPOINT)) == CHECKPOINT


def test_discovery_auth_failure_does_not_expose_server_body(monkeypatch):
    def fail(*args, **kwargs):
        raise urllib.error.HTTPError(
            "http://localhost/v1/models", 401, "test-unsloth-secret", {}, None
        )

    monkeypatch.setattr(models.urllib.request, "urlopen", fail)
    with pytest.raises(
        ModelResolutionError, match="Unsloth authentication failed"
    ) as error:
        models._fetch_unsloth_models("http://localhost/v1", "test-unsloth-secret")
    assert "test-unsloth-secret" not in str(error.value)


def test_loaded_models_route_and_failure_are_backend_only(monkeypatch):
    async def discovered():
        return (CHECKPOINT,)

    monkeypatch.setattr(routes, "loaded_unsloth_models", discovered)
    client = TestClient(create_app())  # No lifespan/DB work needed for discovery.
    result = client.get("/api/models?server=unsloth")
    assert result.status_code == 200
    assert result.json() == {"server": "unsloth", "models": [CHECKPOINT]}
    assert "sk-unsloth" not in result.text
    assert client.get("/api/models?server=unknown").status_code == 422

    async def unavailable():
        raise ModelResolutionError("Unsloth is unavailable.")

    monkeypatch.setattr(routes, "loaded_unsloth_models", unavailable)
    assert client.get("/api/models?server=unsloth").status_code == 503


def test_agent_2_uses_unsloth_wire_request_and_parses_reasoning_and_tools(
    request_position,
):
    requests = []
    output = (
        "<running_thoughts>Vulnerabilities: Pending.\n\nOpportunities: Pending."
        "\n\nSynthesis: Inspect first.</running_thoughts>\n<agent_tool_calls>"
        '[{"tool":"inspect_square","arguments":{"board":"canonical","square":"e1"}}]'
        "</agent_tool_calls>"
    )

    def transport(request):
        assert request.url.host == "unsloth.invalid"
        assert request.url.path == "/v1/responses"
        assert request.headers["authorization"] == "Bearer test-unsloth-secret"
        requests.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "resp_test",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": CHECKPOINT,
                "output": [
                    {
                        "type": "reasoning",
                        "id": "rs_1",
                        "summary": [],
                        "content": [
                            {
                                "type": "reasoning_text",
                                "text": "Inspect queen safety first.",
                            }
                        ],
                    },
                    {
                        "type": "message",
                        "id": "msg_1",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": output, "annotations": []}
                        ],
                    },
                ],
            },
        )

    client = UnslothModel(
        AsyncOpenAI(
            base_url="http://unsloth.invalid/v1",
            api_key="test-unsloth-secret",
            max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(transport)),
        )
    )

    async def run():
        async def unexpected():
            raise AssertionError("LM Studio should not be consulted")

        catalog = HarnessCatalog(
            Mock(), model_resolver=unexpected, unsloth_model=client
        )
        try:
            player, name = await catalog.create_player(
                AGENT_PLAYER_2_ID,
                lambda: False,
                ModelSelection(model_id="unsloth", model_name=CHECKPOINT),
            )
            assert name == CHECKPOINT
            assert player.config.provider == "unsloth"
            state = initial_state(request_position)
            result = await SynthesisNodes(client, player.config).synthesis(state)
            assert result["forced_retry"] is False
            assert result["pending_tools"][0]["tool"] == "inspect_square"
            event = next(e for e in result["events"] if e["type"] == "model_output")
            assert event["reasoning"] == "Inspect queen safety first."
            assert requests[0]["model"] == CHECKPOINT
            assert requests[0]["input"][0]["role"] == "developer"
            assert "test-unsloth-secret" not in json.dumps(requests)
        finally:
            await client.aclose()

    asyncio.run(run())


def test_queue_pins_checkpoint_at_creation():
    calls = []

    async def discovered():
        calls.append("discovery")
        return CHECKPOINT

    catalog = HarnessCatalog(Mock(), unsloth_model=Mock(), unsloth_resolver=discovered)
    repository = Mock()
    repository.enqueue.side_effect = lambda **kwargs: kwargs
    queue = PositionQueueManager(Mock(), catalog, repository=repository)

    async def run():
        row = await queue.enqueue(
            CreatePositionQueueRequest(
                dataset_version="v1",
                split="train",
                harness_id=AGENT_PLAYER_2_ID,
                model_selection=ModelSelection(model_id="unsloth"),
            )
        )
        selection = row["model_selection"]
        assert selection.model_name == CHECKPOINT
        for _ in range(2):
            player, name = await catalog.create_player(
                AGENT_PLAYER_2_ID, lambda: False, selection
            )
            assert name == CHECKPOINT and player.config.provider == "unsloth"
        assert calls == ["discovery"]

    asyncio.run(run())


def test_slow_unsloth_generation_has_a_clear_timeout_error():
    def transport(request):
        raise httpx2.ReadTimeout("Local generation timed out", request=request)

    client = UnslothModel(
        AsyncOpenAI(
            base_url="http://unsloth.invalid/v1",
            api_key="test-secret",
            max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(transport)),
        )
    )

    async def run():
        try:
            with pytest.raises(HarnessError, match="Unsloth timed out waiting for"):
                await client.complete(
                    model=CHECKPOINT,
                    instructions="test",
                    dynamic_input="test",
                    reasoning_effort="medium",
                    max_output_tokens=2000,
                    forced_retry=False,
                )
        finally:
            await client.aclose()

    asyncio.run(run())

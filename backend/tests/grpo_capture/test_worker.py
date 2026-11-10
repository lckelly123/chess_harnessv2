import math
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from grpo_capture.worker import (
    CaptureWorker,
    CompleteBody,
    PrepareBody,
    SamplingSettings,
    SessionBody,
    UnslothEngine,
    create_app,
    resolve_adapter,
    response_payload,
    sampling_scores,
    text_messages,
    validate_capture,
)

TOKEN = "capture-worker-unit-test-token-1234567890"


@pytest.fixture
def adapter_root(tmp_path):
    adapter = tmp_path / "qwen-v2.3"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text("{}")
    (adapter / "adapter_model.safetensors").write_bytes(b"test")
    return tmp_path


@pytest.mark.parametrize(
    "name", ["../qwen-v2.3", "..", "C:\\elsewhere", "/tmp/a", "a/b"]
)
def test_adapter_cannot_escape_output_root(adapter_root, name):
    with pytest.raises(ValueError):
        resolve_adapter(adapter_root, name)


def test_adapter_resolution_requires_both_files(adapter_root):
    assert resolve_adapter(adapter_root, "qwen-v2.3") == adapter_root / "qwen-v2.3"
    (adapter_root / "qwen-v2.3" / "adapter_model.safetensors").unlink()
    with pytest.raises(ValueError, match="safetensors"):
        resolve_adapter(adapter_root, "qwen-v2.3")


def test_text_request_preserves_content_and_normalizes_developer_role():
    result = text_messages(
        {
            "input": [
                {"role": "developer", "content": "  rules\n"},
                {"role": "user", "content": [{"type": "input_text", "text": "board"}]},
            ]
        }
    )
    assert result == [
        {"role": "system", "content": "  rules\n"},
        {"role": "user", "content": "board"},
    ]
    with pytest.raises(ValueError, match="text-tool"):
        text_messages({"tools": [{"name": "agent_step"}], "input": result})
    with pytest.raises(ValueError, match="text input"):
        text_messages(
            {"input": [{"role": "user", "content": [{"type": "input_image"}]}]}
        )


class FakeEngine:
    def __init__(self, adapter, settings, cancelled):
        self.metadata = {
            "adapter_sha256": "abc",
            "sampling": settings.sampling.model_dump(),
        }
        self.closed = False
        self.entered = threading.Event()

    def generate(self, body, cancelled):
        self.entered.set()
        while body.request.get("wait") and not cancelled.wait(0.01):
            pass
        capture = {
            "request_id": body.request_id,
            "completion_token_ids": [3],
            "old_logprobs": [-0.25],
            "sampling_logprobs": [-0.1],
            "finish_reason": "cancelled" if cancelled.is_set() else "stop",
        }
        return {"response": {"output": []}, "capture": capture}

    def close(self):
        self.closed = True


def test_worker_auth_session_isolation_and_result_recovery(adapter_root):
    worker = CaptureWorker(adapter_root, FakeEngine)
    with TestClient(create_app(worker, TOKEN)) as client:
        assert client.get("/health").json()["service"] == "chess-grpo-capture"
        assert (
            client.post("/prepare", json={"model_name": "qwen-v2.3"}).status_code == 401
        )
        client.headers["Authorization"] = f"Bearer {TOKEN}"
        prepared = client.post(
            "/prepare", json={"model_name": "qwen-v2.3", "session_id": "session-a"}
        )
        assert prepared.status_code == 200
        assert (
            client.post("/prepare", json={"model_name": "qwen-v2.3"}).status_code == 409
        )
        wrong = {"session_id": "wrong", "request": {}, "seed": 1}
        assert client.post("/complete", json=wrong).status_code == 409
        result = client.post(
            "/complete",
            json={
                "session_id": "session-a",
                "request_id": "call-1",
                "request": {},
                "seed": 2,
            },
        )
        assert result.status_code == 200
        recovered = client.get("/result/session-a?request_id=call-1").json()
        assert recovered["last_result"] == result.json()
        assert (
            client.get("/result/session-a?request_id=other").json()["last_result"]
            is None
        )
        engine = worker.engine
        assert (
            client.post("/release", json={"session_id": "session-a"}).status_code == 200
        )
        assert engine.closed
        assert client.get("/health").json()["model_name"] is None


def test_cancel_keeps_partial_capture_and_release_waits_for_generation(adapter_root):
    worker = CaptureWorker(adapter_root, FakeEngine)
    worker.prepare(PrepareBody(model_name="qwen-v2.3", session_id="session"))
    engine = worker.engine
    results = []
    thread = threading.Thread(
        target=lambda: results.append(
            worker.complete(
                CompleteBody(session_id="session", request={"wait": True}, seed=3)
            )
        )
    )
    thread.start()
    assert engine.entered.wait(2)
    worker.cancel(SessionBody(session_id="session"))
    thread.join(2)
    assert not thread.is_alive()
    assert results[0]["capture"]["completion_token_ids"] == [3]
    assert results[0]["capture"]["finish_reason"] == "cancelled"
    worker.release(SessionBody(session_id="session"))
    assert engine.closed


def test_failed_prepare_does_not_leave_a_claimed_session(adapter_root):
    def fail(*args):
        raise ValueError("No GPU")

    worker = CaptureWorker(adapter_root, fail)
    with pytest.raises(ValueError, match="No GPU"):
        worker.prepare(PrepareBody(model_name="qwen-v2.3"))
    assert worker.health()["session_id"] is None
    assert not worker.health()["busy"]


def test_invalid_probability_alignment_is_rejected():
    with pytest.raises(ValueError, match="alignment"):
        validate_capture(
            {
                "completion_token_ids": [1],
                "old_logprobs": [],
                "sampling_logprobs": [0.0],
            }
        )
    with pytest.raises(ValueError, match="log probability"):
        validate_capture(
            {
                "completion_token_ids": [1],
                "old_logprobs": [float("nan")],
                "sampling_logprobs": [0.0],
            }
        )


def test_raw_response_preserved_separately_from_harness_thinking_parse():
    capture = {
        "finish_reason": "length",
        "error": None,
        "prompt_token_ids": [1, 2],
        "completion_token_ids": [3, 4],
    }
    response = response_payload(
        "qwen",
        capture,
        "<think>reason</think>\n\n<agent_tool_calls>[]</agent_tool_calls>",
    )
    assert response["status"] == "incomplete"
    assert response["output"][0]["content"][0]["text"] == "reason"
    assert (
        response["output"][1]["content"][0]["text"]
        == "<agent_tool_calls>[]</agent_tool_calls>"
    )


def cpu_engine(logits_steps, *, max_length=10, top_k=1):
    torch = pytest.importorskip("torch")

    class Model:
        generation_config = SimpleNamespace(eos_token_id=3)

        def __init__(self):
            self.calls = []

        def get_input_embeddings(self):
            return SimpleNamespace(weight=torch.zeros(1))

        def __call__(self, **kwargs):
            self.calls.append(kwargs)
            index = len(self.calls) - 1
            if isinstance(logits_steps[index], Exception):
                raise logits_steps[index]
            return SimpleNamespace(
                logits=torch.tensor([[logits_steps[index]]], dtype=torch.float32),
                past_key_values=(index,),
            )

    class Tokenizer:
        eos_token_id = 3

        def apply_chat_template(self, *args, **kwargs):
            self.template_options = kwargs
            return "exact rendered prompt"

        def encode(self, text, **kwargs):
            return [0, 1]

        def decode(self, ids, **kwargs):
            return " ".join(map(str, ids))

    engine = object.__new__(UnslothEngine)
    engine.torch = torch
    engine.settings = PrepareBody(
        model_name="qwen-v2.3",
        max_seq_length=max(128, max_length),
        sampling=SamplingSettings(top_k=top_k, top_p=1, temperature=1),
    )
    engine.model = Model()
    engine.tokenizer = Tokenizer()
    return engine


def generation_body(**kwargs):
    return CompleteBody(
        session_id="session",
        request={
            "model": "qwen-v2.3",
            "input": [{"role": "user", "content": "input"}],
            "max_output_tokens": 4,
        },
        seed=3,
        **kwargs,
    )


def test_each_selected_id_uses_same_steps_raw_logits_and_sampler_probabilities():
    engine = cpu_engine([[0, 1, 4, 2], [0, 0, 0, 7]])
    result = engine.generate(generation_body(), threading.Event())
    capture = result["capture"]
    assert capture["prompt_token_ids"] == [0, 1]
    assert capture["completion_token_ids"] == [2, 3]  # Includes sampled EOS.
    expected = [
        4 - math.log(sum(math.exp(x) for x in [0, 1, 4, 2])),
        7 - math.log(3 + math.exp(7)),
    ]
    assert capture["old_logprobs"] == pytest.approx(expected, abs=1e-6)
    assert capture["sampling_logprobs"] == pytest.approx([0, 0])
    assert engine.model.calls[0]["input_ids"].tolist() == [[0, 1]]
    assert engine.model.calls[1]["input_ids"].tolist() == [[2]]
    assert engine.model.calls[0]["position_ids"].tolist() == [[0, 1]]
    assert engine.model.calls[1]["position_ids"].tolist() == [[2]]
    assert engine.model.calls[1]["past_key_values"] == (0,)
    assert capture["finish_reason"] == "stop"


def test_default_capture_preserves_model_template_thinking_default():
    engine = cpu_engine([[0, 0, 0, 7]])
    engine.generate(generation_body(), threading.Event())
    assert "enable_thinking" not in engine.tokenizer.template_options
    assert "reasoning_effort" not in engine.tokenizer.template_options
    assert engine.tokenizer.template_options["add_generation_prompt"] is True


@pytest.mark.parametrize("enabled", [True, False])
def test_explicit_thinking_override_is_honored(enabled):
    engine = cpu_engine([[0, 0, 0, 7]])
    engine.settings.sampling.enable_thinking = enabled
    engine.generate(generation_body(), threading.Event())
    assert engine.tokenizer.template_options["enable_thinking"] is enabled


def test_sampler_matches_transformers_with_studio_min_p():
    torch = pytest.importorskip("torch")
    processors = pytest.importorskip("transformers.generation.logits_process")
    # The tail survives top-p but is removed by min-p; include a repeated token.
    logits = torch.tensor([0.0, 1.0, 7.0, 2.0, -4.0, -5.0])
    settings = SamplingSettings(
        temperature=0.6, top_k=5, top_p=1.0, min_p=0.01, repetition_penalty=1.2
    )
    ids = torch.tensor([[0, 2]])
    expected = logits[None].clone()
    for processor in (
        processors.RepetitionPenaltyLogitsProcessor(1.2),
        processors.TemperatureLogitsWarper(0.6),
        processors.TopKLogitsWarper(5),
        processors.TopPLogitsWarper(1.0),
        processors.MinPLogitsWarper(0.01),
    ):
        expected = processor(ids, expected)
    actual = sampling_scores(torch, logits, [0, 2], settings)
    torch.testing.assert_close(actual, expected[0])
    assert torch.isneginf(actual[1])


def test_generation_error_preserves_exact_partial_token_arrays():
    engine = cpu_engine([[0, 1, 4, 2], RuntimeError("fake OOM")])
    capture = engine.generate(generation_body(), threading.Event())["capture"]
    assert capture["finish_reason"] == "error"
    assert capture["error"] == "fake OOM"
    assert capture["completion_token_ids"] == [2]
    assert len(capture["old_logprobs"]) == len(capture["sampling_logprobs"]) == 1


def test_timeout_and_cancellation_return_empty_aligned_capture_before_forward():
    engine = cpu_engine([])
    cancelled = threading.Event()
    cancelled.set()
    capture = engine.generate(generation_body(), cancelled)["capture"]
    assert capture["finish_reason"] == "cancelled"
    assert capture["completion_token_ids"] == []
    assert engine.model.calls == []
    capture["effective_max_output_tokens"] = 1
    engine._decode(capture, threading.Event(), time.monotonic() - 1)
    assert capture["finish_reason"] == "timeout"
    assert engine.model.calls == []


def test_context_overflow_is_recorded_without_silently_truncating_prompt():
    engine = cpu_engine([])
    engine.tokenizer.encode = lambda *args, **kwargs: list(range(128))
    capture = engine.generate(generation_body(), threading.Event())["capture"]
    assert capture["finish_reason"] == "error"
    assert len(capture["prompt_token_ids"]) == 128
    assert capture["completion_token_ids"] == []
    assert capture["prompt_executed"] is False


def test_sampling_filters_do_not_mutate_raw_logits():
    torch = pytest.importorskip("torch")
    raw = torch.tensor([0.0, 1.0, 4.0, 2.0])
    original = raw.clone()
    scores = sampling_scores(
        torch,
        raw,
        [2],
        SamplingSettings(temperature=1, top_k=0, top_p=0.7, repetition_penalty=2),
    )
    assert torch.equal(raw, original)
    assert scores[2].item() == 2.0
    assert torch.isneginf(scores[0])
    assert torch.isfinite(scores[3])

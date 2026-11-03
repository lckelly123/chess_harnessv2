"""Exercise durable GRPO records without a GPU, model server or public database."""

import json
from copy import deepcopy

import pytest

from grpo import storage
from grpo.recording import GrpoRecorder
from grpo.storage import CollectionStore, validate_capture


@pytest.fixture
def collection(tmp_path):
    store = CollectionStore(tmp_path / "collections")
    store.create(
        "trial",
        "position-123",
        "agent-player-2-langgraph-v1",
        "adapter-v2.3",
        seed=42,
        position={"fen": "fixture", "pgn": "fixture"},
        harness={"version": "fixture"},
    )
    store.update("trial", status="running", trajectory=1, trajectory_status="running")
    return store


def capture(**overrides):
    return {
        "input": "  Exact input\n雪\t",
        "prompt_token_ids": [11, 12, 13],
        "generated_response": "  Generated response\n",
        "completion_token_ids": [20, 21, 151645],
        "old_logprobs": [-0.1, -3.2, -0.01],
        "sampling_logprobs": [-0.02, -2.1, 0.0],
        "finish_reason": "eos",
        "status": "completed",
        **overrides,
    }


def response(text):
    return {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": text}],
            }
        ]
    }


def read_records(store, trajectory=1):
    path = store.path("trial") / f"trajectory_{trajectory:02d}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def read_manifest(store):
    return json.loads(
        (store.path("trial") / "manifest.json").read_text(encoding="utf-8")
    )


def durable_record(call_index=1):
    return {
        **capture(),
        "call_index": call_index,
        "harness_rejected": True,
        "tool_requests": [
            {"tool_name": "inspect_square", "executed": False},
            {"tool_name": "inspect_square", "executed": False},
            {"tool_name": "scratch_play_move", "executed": False},
        ],
    }


def test_exact_token_and_probability_values_are_accepted():
    original = capture()
    snapshot = deepcopy(original)
    validate_capture(original)
    assert original == snapshot


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("prompt_token_ids", [1, True]),
        ("prompt_token_ids", [1, -3]),
        ("completion_token_ids", [1, 2.0, 3]),
        ("completion_token_ids", "1,2,3"),
        ("old_logprobs", [-0.1, -0.2]),
        ("sampling_logprobs", [-0.1, -0.2, -0.3, -0.4]),
        ("old_logprobs", [-0.1, float("nan"), -0.3]),
        ("old_logprobs", [-0.1, float("-inf"), -0.3]),
        ("sampling_logprobs", [-0.1, float("inf"), -0.3]),
        ("sampling_logprobs", [-0.1, True, -0.3]),
        ("old_logprobs", [-0.1, 0.25, -0.3]),
        ("input", None),
        ("generated_response", None),
        ("finish_reason", None),
    ],
)
def test_invalid_capture_cannot_be_marked_trainable(field, value):
    with pytest.raises(ValueError):
        validate_capture(capture(**{field: value}))


@pytest.mark.parametrize(
    "name",
    [
        "../outside",
        "..",
        "/absolute",
        "C:\\outside",
        "a/b",
        "a\\b",
        "trial.",
        "CON",
        "nul.json",
        "LPT1",
        "COM9.txt",
        "",
        "a" * 81,
    ],
)
def test_output_names_cannot_escape_root_or_use_windows_devices(tmp_path, name):
    store = CollectionStore(tmp_path / "collections")
    with pytest.raises(ValueError):
        store.create(name, "p", "h", "m", seed=1, position={}, harness={})
    assert not store.root.exists()


def test_existing_collection_is_never_overwritten(collection):
    collection.append_call("trial", 1, durable_record())
    directory = collection.path("trial")
    before = {path.name: path.read_bytes() for path in directory.iterdir()}
    with pytest.raises(FileExistsError):
        collection.create(
            "trial", "other", "other", "other", seed=99, position={}, harness={}
        )
    assert {path.name: path.read_bytes() for path in directory.iterdir()} == before
    assert set(read_manifest(collection)) == {
        "position_id",
        "qlora_adapter_version",
        "trajectories",
    }
    assert len(list(directory.glob("trajectory_*.jsonl"))) == 10
    assert "advantage" not in (directory / "manifest.json").read_text()


def test_live_recorder_flushes_calls_and_counts_requests_once(collection, run_store):
    recorder = GrpoRecorder(run_store, "run-1", collection, "trial", 1)
    calls = [
        {"tool": "inspect_square", "arguments": {"square": "e4"}},
        {"tool": "inspect_square", "arguments": {"square": "d4"}},
        {"tool": "scratch_play_move", "arguments": {"move": "invalid"}},
    ]
    text = "<agent_tool_calls>" + json.dumps(calls) + "</agent_tool_calls>"
    recorder.begin({"phase": "synthesis"})
    recorder.capture_input({"input": [{"role": "user", "content": "request"}]})
    original = capture(generated_response=text)
    recorder.capture_tokens(original)
    original["completion_token_ids"].clear()
    recorder.response(response(text))
    recorder.state({}, {"pending_tools": calls, "events": []})
    assert read_records(collection) == []

    rejected = {
        "events": [{"type": "response_retry", "reason": "Illegal move"}],
        "pending_tools": [],
    }
    recorder.state({}, rejected)
    recorder.state({}, rejected)  # Nested observed nodes can see the same outcome.
    recorder.flush()
    records = read_records(collection)
    assert len(records) == 1
    assert records[0]["completion_token_ids"] == [20, 21, 151645]
    assert records[0]["generated_response"] == text
    assert records[0]["input"] == "  Exact input\n雪\t"
    assert records[0]["harness_rejected"] is True
    assert all(not tool["executed"] for tool in records[0]["tool_requests"])
    summary = read_manifest(collection)["trajectories"][0]
    assert summary["status"] == "running"  # Written before trajectory completion.
    assert summary["rejected_model_calls"] == 1
    assert summary["tool_counts"]["inspect_square"] == 2
    assert summary["tool_counts"]["scratch_play_move"] == 1
    assert summary["cp_loss"] is None

    recorder.begin({"phase": "synthesis"})
    recorder.capture_input({"input": [{"role": "user", "content": "next"}]})
    recorder.capture_tokens(capture())
    recorder.response(response("Reasoning without a tool request."))
    recorder.state({}, {"events": [], "pending_tools": []})
    recorder.flush()
    assert [row["call_index"] for row in read_records(collection)] == [1, 2]
    assert collection.get("trial")["currentCall"] == 2
    assert read_manifest(collection)["trajectories"][0]["rejected_model_calls"] == 1


def test_timeout_keeps_partial_tokens_without_counting_harness_rejection(
    collection, run_store
):
    recorder = GrpoRecorder(run_store, "run-timeout", collection, "trial", 1)
    recorder.begin({"phase": "synthesis"})
    recorder.capture_input({"input": [{"role": "user", "content": "request"}]})
    recorder.capture_tokens(capture(finish_reason="timeout", status="failed"))
    recorder.fail(TimeoutError("Generation timed out"))
    recorder.flush()
    records = read_records(collection)
    assert len(records) == 1
    assert records[0]["finish_reason"] == "timeout"
    assert records[0]["completion_token_ids"] == [20, 21, 151645]
    assert records[0]["capture_valid"] is True
    assert records[0]["harness_status"] == "failed"
    assert records[0]["harness_rejected"] is False


def test_missing_capture_is_explicitly_untrainable(collection, run_store):
    recorder = GrpoRecorder(run_store, "run-disconnected", collection, "trial", 1)
    recorder.begin({"phase": "synthesis"})
    request = {"input": [{"role": "user", "content": "captured request"}]}
    recorder.capture_input(request)
    recorder.fail(ConnectionError("Worker disconnected"))
    (record,) = read_records(collection)
    assert record["request"] == request
    assert record["capture_valid"] is False
    assert record["finish_reason"] == "capture_error"
    assert record["completion_token_ids"] == record["old_logprobs"] == []
    assert record["harness_error"] == "Worker disconnected"


def test_summary_write_failure_does_not_duplicate_durable_call(collection, monkeypatch):
    original_atomic_json = storage.atomic_json
    failed = False

    def fail_summary_once(path, value):
        nonlocal failed
        if path.name == "manifest.json" and not failed:
            failed = True
            raise OSError("simulated summary write interruption")
        return original_atomic_json(path, value)

    monkeypatch.setattr(storage, "atomic_json", fail_summary_once)
    with pytest.raises(OSError, match="summary write interruption"):
        collection.append_call("trial", 1, durable_record())
    assert len(read_records(collection)) == 1
    # Retrying a flush after the JSONL fsync must repair summaries, not append twice.
    collection.append_call("trial", 1, durable_record())
    assert len(read_records(collection)) == 1
    summary = read_manifest(collection)["trajectories"][0]
    assert summary["rejected_model_calls"] == 1
    assert summary["tool_counts"]["inspect_square"] == 2


def test_restart_reconciles_durable_calls_and_preserves_completed_grades(collection):
    collection.append_call("trial", 1, durable_record())
    collection.update("trial", trajectory=1, trajectory_status="completed", cp_loss=0)
    collection.update(
        "trial", trajectory=2, trajectory_status="running", currentTrajectory=2
    )
    # Simulate a crash after the call was fsynced but before its summary was saved.
    path = collection.path("trial") / "trajectory_02.jsonl"
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(durable_record()) + "\n")
    before = path.read_bytes()
    reopened = CollectionStore(collection.root)
    reopened.recover()
    state = reopened.get("trial")
    assert state["status"] == "interrupted"
    assert state["stopping"] is False
    assert state["trajectories"][0]["status"] == "completed"
    assert state["trajectories"][0]["cpLoss"] == 0
    assert state["trajectories"][1]["status"] == "interrupted"
    assert state["trajectories"][1]["rejectedModelCalls"] == 1
    assert state["trajectories"][1]["toolCounts"]["inspect_square"] == 2
    assert state["trajectories"][2]["status"] == "pending"
    assert path.read_bytes() == before
    assert state["completedTrajectories"] == 2


def test_partial_last_line_is_preserved_without_counting_it(collection):
    collection.append_call("trial", 1, durable_record())
    path = collection.path("trial") / "trajectory_01.jsonl"
    with path.open("ab") as output:
        output.write(b'{"call_index": 2, "completion_token_ids": [')
    original = path.read_bytes()
    CollectionStore(collection.root).recover()
    state = collection.get("trial")
    assert state["status"] == "interrupted"
    assert state["trajectories"][0]["rejectedModelCalls"] == 1
    assert state["trajectories"][0]["toolCounts"]["inspect_square"] == 2
    assert path.read_bytes() == original


def test_corrupt_middle_record_cannot_leave_group_looking_active(collection):
    path = collection.path("trial") / "trajectory_01.jsonl"
    path.write_text(
        json.dumps(durable_record())
        + "\n{malformed record}\n"
        + json.dumps(durable_record(3))
        + "\n",
        encoding="utf-8",
    )
    original = path.read_bytes()
    CollectionStore(collection.root).recover()
    state = collection.get("trial")
    assert state["status"] == "interrupted"
    assert "corrupt" in state["error"].lower()
    assert path.read_bytes() == original

"""Exercise capture at the real SDK boundary without making paid model calls."""

import asyncio
import json
from uuid import uuid4

import httpx2
import pytest
from conftest import JUSTIFICATION, call
from openai import AsyncOpenAI

from harness.baseline import BaselineAgent, BaselineConfig
from harness.contracts import HarnessError
from harness.model import LMStudioModel, NativeToolTurn, OpenAIModel
from harness.recording import complete_pass, current_recorder
from positional_testing.exchange import output_blocks, present_exchange
from positional_testing.recording import PassRecorder


def envelope(output, status="completed"):
    return dict(
        id="resp_test",
        object="response",
        created_at=1,
        status=status,
        model="offline",
        output=output,
    )


def message(text):
    return dict(
        type="message",
        id="msg_test",
        status="completed",
        role="assistant",
        content=[dict(type="output_text", text=text, annotations=[])],
    )


def provider(transport, cls=LMStudioModel):
    return cls(
        AsyncOpenAI(
            base_url="http://provider.invalid/v1",
            api_key="secret-not-in-prompt",
            max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(transport)),
        )
    )


async def invoke(model, **overrides):
    return await complete_pass(
        model,
        {},
        **(
            dict(
                model="offline",
                instructions="  Developer\n\t雪  ",
                dynamic_input="User\r\n  input  ",
                reasoning_effort="medium",
                max_output_tokens=1000,
                forced_retry=False,
            )
            | overrides
        ),
    )


@pytest.mark.parametrize("cls", [LMStudioModel, OpenAIModel])
def test_snapshot_matches_wire_request_and_raw_returned_strings(cls, run_store):
    recorder = PassRecorder(run_store, str(uuid4()))
    arguments = ' \n{"running_thoughts": "unfinished 雪", "tool_calls": [ malformed\t '
    response = envelope(
        [
            dict(
                type="reasoning",
                id="rs_test",
                encrypted_content="opaque-state",
                summary=[dict(type="summary_text", text="  reasoning\nreasoning  ")],
            ),
            message(" \nraw <tag>& output\r\n  "),
            dict(
                type="function_call",
                id="fc_test",
                call_id="call_test",
                name="agent_step",
                arguments=arguments,
            ),
        ]
    )
    native = NativeToolTurn(
        tools=[dict(type="function", name="agent_step", parameters={"type": "object"})],
        function_name="agent_step",
        history=[
            dict(
                type="function_call",
                call_id="previous",
                name="inspect_square",
                arguments='{"square":"e4"}',
            ),
            dict(type="function_call_output", call_id="previous", output="  empty\n"),
        ],
    )

    def transport(request):
        saved = run_store.get_pass_exchange(recorder.run_id, 1)
        # The snapshot has committed before any provider work starts.
        assert saved["model_input"] == json.loads(request.content)
        assert saved["model_output"] is None
        assert "secret-not-in-prompt" not in json.dumps(saved)
        assert "langsmith_extra" not in saved["model_input"]
        return httpx2.Response(200, json=response)

    async def run():
        model = provider(transport, cls)
        token = current_recorder.set(recorder)
        try:
            result = await invoke(model, native_turn=native)
            result[
                "output"
            ].clear()  # Later parsing/mutation must not change the snapshot.
            native.history.clear()
        finally:
            current_recorder.reset(token)
            await model.aclose()

    asyncio.run(run())
    saved = run_store.get_pass_exchange(recorder.run_id, 1)
    assert saved["model_output"] == response
    assert len(saved["model_input"]["input"]) == 4
    assert saved["model_input"]["tools"][0]["name"] == "agent_step"
    assert present_exchange(saved).output == [
        "  reasoning\nreasoning  ",
        " \nraw <tag>& output\r\n  ",
        arguments,
    ]
    assert json.loads(present_exchange(saved).input) == saved["model_input"]
    assert "model_output" not in run_store.passes[(recorder.run_id, 1)]


@pytest.mark.parametrize("status", ["failed", "cancelled", "incomplete"])
def test_capture_precedes_status_validation(status, run_store):
    recorder = PassRecorder(run_store, str(uuid4()))
    response = envelope([message("  partial response\n")], status)

    async def run():
        model = provider(lambda _: httpx2.Response(200, json=response))
        token = current_recorder.set(recorder)
        try:
            if status == "incomplete":
                await invoke(model)
            else:
                with pytest.raises(HarnessError, match="response status"):
                    await invoke(model)
        finally:
            current_recorder.reset(token)
            await model.aclose()

    asyncio.run(run())
    assert run_store.get_pass_exchange(recorder.run_id, 1)["model_output"] == response


def test_rejected_output_and_forced_retry_have_distinct_snapshots(
    request_position, run_store
):
    recorder = PassRecorder(run_store, str(uuid4()))
    text = [
        " \nNo valid tool call.\t ",
        call("submit_move", move="e4", justification=JUSTIFICATION)["output_text"],
    ]
    requests = []

    def transport(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=envelope([message(text[len(requests) - 1])]))

    async def run():
        model = provider(transport)
        token = current_recorder.set(recorder)
        try:
            await BaselineAgent(model, BaselineConfig(model="offline")).choose_move(
                request_position
            )
        finally:
            current_recorder.reset(token)
            await model.aclose()

    asyncio.run(run())
    assert len(requests) == 2
    assert requests[0] != requests[1]
    for number in (1, 2):
        saved = run_store.get_pass_exchange(recorder.run_id, number)
        assert saved["model_input"] == requests[number - 1]
        assert present_exchange(saved).output == [text[number - 1]]
    assert run_store.passes[(recorder.run_id, 1)]["status"] == "failed"
    assert run_store.passes[(recorder.run_id, 2)]["status"] == "completed"


def test_connection_failure_retains_input_without_inventing_output(run_store):
    recorder = PassRecorder(run_store, str(uuid4()))

    def transport(request):
        raise httpx2.ConnectError("offline", request=request)

    async def run():
        model = provider(transport)
        token = current_recorder.set(recorder)
        try:
            with pytest.raises(HarnessError, match="could not be reached"):
                await invoke(model)
        finally:
            current_recorder.reset(token)
            await model.aclose()

    asyncio.run(run())
    saved = run_store.get_pass_exchange(recorder.run_id, 1)
    assert saved["model_input"]["input"][-1]["content"] == "User\r\n  input  "
    assert saved["model_output"] is None
    assert present_exchange(saved).output == []


def test_concurrent_runs_and_cancelled_call_keep_their_own_input(run_store):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()

        async def transport(request):
            content = json.loads(request.content)["input"][-1]["content"]
            if content == "cancel me":
                started.set()
                await release.wait()
            return httpx2.Response(200, json=envelope([message(content)]))

        model = provider(transport)

        async def attempt(run_id, content):
            recorder = PassRecorder(run_store, run_id)
            token = current_recorder.set(recorder)
            try:
                return await invoke(model, dynamic_input=content)
            finally:
                current_recorder.reset(token)

        try:
            cancelled = asyncio.create_task(attempt("cancelled", "cancel me"))
            await started.wait()
            await attempt("completed", "complete me")
            cancelled.cancel()
            with pytest.raises(asyncio.CancelledError):
                await cancelled
        finally:
            await model.aclose()

    asyncio.run(run())
    assert present_exchange(run_store.get_pass_exchange("completed", 1)).output == [
        "complete me"
    ]
    cancelled = run_store.get_pass_exchange("cancelled", 1)
    assert cancelled["model_input"]["input"][-1]["content"] == "cancel me"
    assert cancelled["model_output"] is None


def test_output_keeps_repeats_refusals_and_top_level_compatible_text():
    text = " \nunchanged\t "
    assert output_blocks({"output_text": text}) == [text]
    assert output_blocks(
        {"output": [message(text), message(text)], "output_text": text * 2}
    ) == [text, text]
    assert output_blocks(
        {
            "output": [
                {"type": "message", "content": [{"type": "refusal", "refusal": text}]}
            ]
        }
    ) == [text]
    assert (
        output_blocks({"output": [None, {"type": "message", "content": [None]}]}) == []
    )

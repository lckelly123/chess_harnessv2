import asyncio
import json
import os
import socket
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import chess
import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from app.main import create_app
from app.matches.catalog import AGENT_PLAYER_2_ID, HarnessCatalog
from app.matches.repository import MatchRepository
from codex_training.mcp_server import create_server
from harness.agent_player_2.prompt_builder.builder import build_prompt
from harness.agent_player_2.state import initial_state
from harness.contracts import TurnRequest
from positional_testing.exchange import present_exchange

REASONING = (
    "  The tool checks the square before a move is selected.\nCafé; literal \\n.\n"
)


def response(
    tool, *, notes="Inspect the position before choosing a move.", **arguments
):
    return (
        "\n<running_thoughts>" + notes + "</running_thoughts>\n"
        "<agent_tool_calls>"
        + json.dumps([{"tool": tool, "arguments": arguments}])
        + "</agent_tool_calls>\n"
    )


@pytest.fixture
def bridge_app(library_rows, run_store, monkeypatch):
    # SQL restart recovery is exercised separately against an isolated PG schema.
    monkeypatch.setattr(
        run_store, "recover_codex_training", lambda: None, raising=False
    )
    repository = MatchRepository(":memory:")
    app = create_app(repository=repository, catalog=HarnessCatalog(None))
    yield app
    repository.close()


@pytest.fixture
def api(bridge_app):
    with TestClient(bridge_app) as client:
        yield client


def start(api, position_id, **options):
    result = api.post(
        "/api/codex-training/runs",
        json={"position_id": position_id, "model_label": "fixture-teacher", **options},
    )
    assert result.status_code == 202, result.text
    return result.json()


def headers(run):
    return {"Authorization": f"Bearer {run['run_token']}"}


def submit(api, run, current, raw):
    result = api.post(
        f"/api/codex-training/runs/{run['run_id']}/response",
        headers=headers(run),
        json={
            "pass_id": current["pass"]["pass_id"],
            "response": raw,
            "reasoning_text": REASONING,
        },
    )
    assert result.status_code == 200, result.text
    return result.json()


def move_responses(row):
    board = chess.Board(row["fen"])
    board.push_san("e5")
    reply = board.san(next(iter(board.legal_moves)))
    return [
        response("scratch_play_move", move="e5"),
        response("scratch_play_move", move=reply),
        response(
            "submit_move",
            move="e5",
            tested_branch="B1",
            decision_summary=(
                "The e5 pawn move is legal and was tested with an opponent reply. "
                "This is a deterministic transport test, not a chess quality claim."
            ),
        ),
    ]


def test_real_harness_retry_tools_exact_capture_and_post_run_grading(
    api, library_rows, run_store
):
    row = library_rows[0]
    grading = []
    delegate = api.app.state.codex_training.evaluator

    class Evaluator:
        async def evaluate(self, **kwargs):
            grading.append(kwargs)
            assert next(iter(run_store.runs.values()))["final_move_uci"] == "e4e5"
            return await delegate.evaluate(**kwargs)

    api.app.state.codex_training.evaluator = Evaluator()
    run = start(api, row["id"])
    assert run["status"] == "waiting"
    assert len(run_store.runs) == 1
    current = api.get(
        f"/api/codex-training/runs/{run['run_id']}/pass", headers=headers(run)
    ).json()
    assert current == {k: v for k, v in run.items() if k != "run_token"}
    expected = build_prompt(
        initial_state(
            TurnRequest(
                game_id=run["run_id"],
                fen=row["fen"],
                pgn=row["pgn_prefix"],
                side="white",
                ply=row["source_ply"],
            )
        )
    )
    assert current["pass"]["model_input"]["input"] == [
        {"role": "developer", "content": expected.instructions},
        {"role": "user", "content": expected.dynamic_input},
    ]
    assert grading == []
    first = current
    malformed = "  This is deliberately not the harness format.\r\n"
    current = submit(api, run, current, malformed)
    assert current["pass"]["pass_number"] == 2
    assert current["last_accepted_pass_id"] == first["pass"]["pass_id"]
    assert current["pass"]["model_input"]["forced_retry"] is True
    assert run_store.passes[(run["run_id"], 1)]["status"] == "failed"
    repeated = submit(api, run, first, malformed)
    assert repeated["duplicate"] is True
    assert repeated["pass"] == current["pass"]
    changed = api.post(
        f"/api/codex-training/runs/{run['run_id']}/response",
        headers=headers(run),
        json={
            "pass_id": first["pass"]["pass_id"],
            "response": "changed",
            "reasoning_text": REASONING,
        },
    )
    assert changed.status_code == 409
    notes = "Vulnerabilities: inspect e4.\nOpportunities: pending. Synthesis: café \\n."
    outputs = [
        malformed,
        response("inspect_square", notes=notes, board="canonical", square="e4"),
        *move_responses(row),
    ]
    packets = [first["pass"]["model_input"]]
    for raw in outputs[1:]:
        assert grading == []
        packets.append(current["pass"]["model_input"])
        current = submit(api, run, current, raw)
    assert current["status"] == "completed", current
    assert current["pass"] is None
    assert current["move"] == "e4e5"
    assert "evaluation" not in current and "better_moves" not in current
    assert len(grading) == 1
    assert len(run_store.passes) == len(outputs)
    stored = run_store.get(run["run_id"])
    assert stored["harness"] == AGENT_PLAYER_2_ID
    assert stored["config"]["harness_name"] == "chess_harness"
    assert stored["config"]["provider"] == "codex_mcp"
    assert stored["model"] == "fixture-teacher"
    assert stored["classification"] == "good"
    for number, (packet, raw) in enumerate(zip(packets, outputs, strict=True), 1):
        saved = run_store.get_pass_exchange(run["run_id"], number)
        assert saved["model_input"] == packet
        assert saved["model_output"]["output"][0]["content"][0]["text"] == REASONING
        assert saved["model_output"]["output"][1]["content"][0]["text"] == raw
        assert present_exchange(saved).output == [REASONING, raw]
    assert notes in packets[2]["input"][1]["content"]
    assert "Created branch B1 by playing e5" in packets[3]["input"][1]["content"]
    assert all(
        call["executed"] and call["result"] is not None
        for saved in stored["passes"][1:]
        for call in saved["tool_calls"]
    )
    history = api.get(f"/api/positional-testing/runs/{run['run_id']}")
    assert history.status_code == 200, history.text
    assert len(history.json()["passes"]) == len(outputs)


def test_run_authentication_isolation_conflicts_and_stop(api, library_rows, run_store):
    one, two = [start(api, library_rows[0]["id"]) for _ in range(2)]
    path = f"/api/codex-training/runs/{one['run_id']}"
    assert api.get(path + "/pass").status_code == 401
    assert api.get(path + "/pass", headers=headers(two)).status_code == 403
    result = api.post(
        path + "/response",
        headers=headers(one),
        json={
            "pass_id": two["pass"]["pass_id"],
            "response": "wrong run",
            "reasoning_text": REASONING,
        },
    )
    assert result.status_code == 409
    assert len(run_store.passes) == 2
    for run in (one, two):
        stopped = api.post(
            f"/api/codex-training/runs/{run['run_id']}/stop", headers=headers(run)
        )
        assert stopped.json()["status"] == "cancelled"
        assert run_store.get(run["run_id"])["status"] == "failed"
        saved = run_store.get_pass_exchange(run["run_id"], 1)
        assert saved["model_input"] is not None
        assert saved["model_output"] is None
    result = api.post(
        path + "/response",
        headers=headers(one),
        json={
            "pass_id": one["pass"]["pass_id"],
            "response": "late",
            "reasoning_text": REASONING,
        },
    )
    assert result.status_code == 409


def test_timeout_and_shutdown_finish_waiting_database_passes(
    bridge_app, library_rows, run_store
):
    with TestClient(bridge_app) as api:
        run = start(api, library_rows[0]["id"], pass_timeout_seconds=1)
        # A read doesn't extend the submission deadline.
        task = bridge_app.state.codex_training.tasks[run["run_id"]]
        api.portal.call(lambda: asyncio.wait_for(asyncio.shield(task), 3))
        state = api.get(
            f"/api/codex-training/runs/{run['run_id']}/pass", headers=headers(run)
        ).json()
        assert state["status"] == "failed"
        assert "within 1 seconds" in state["error"]
        assert run_store.get(run["run_id"])["status"] == "failed"
        waiting = start(api, library_rows[0]["id"])
    assert run_store.get(waiting["run_id"])["status"] == "failed"
    assert run_store.passes[(waiting["run_id"], 1)]["status"] == "failed"


def test_bad_position_and_capacity_do_not_create_extra_records(
    api, library_rows, run_store
):
    result = api.post("/api/codex-training/runs", json={"position_id": str(uuid4())})
    assert result.status_code == 404
    assert run_store.runs == {}
    api.app.state.codex_training.max_active = 1
    start(api, library_rows[0]["id"])
    result = api.post(
        "/api/codex-training/runs", json={"position_id": library_rows[0]["id"]}
    )
    assert result.status_code == 409
    assert len(run_store.runs) == 1


def test_failed_grading_retains_submitted_move(api, library_rows, run_store):
    class FailedEvaluator:
        async def evaluate(self, **kwargs):
            raise RuntimeError("test engine unavailable")

    api.app.state.codex_training.evaluator = FailedEvaluator()
    run = start(api, library_rows[0]["id"])
    current = run
    for raw in move_responses(library_rows[0]):
        current = submit(api, run, current, raw)
    assert current["status"] == "failed"
    assert current["move"] == "e4e5"
    stored = run_store.get(run["run_id"])
    assert stored["final_move_uci"] == "e4e5"
    assert stored["failure_stage"] == "evaluation"


@contextmanager
def live_backend(app):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    worker = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True
    )
    worker.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            if not worker.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Test backend failed to start.")
            time.sleep(0.01)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        worker.join(10)
        listener.close()
        assert not worker.is_alive()


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_stdio_subprocess_completes_real_recorded_harness_run(
    bridge_app, library_rows, run_store, mode
):
    from mcp import Client, StdioServerParameters

    with live_backend(bridge_app) as url:
        with httpx.Client(base_url=url, trust_env=False) as api:
            run = start(api, library_rows[0]["id"])

        async def play():
            backend = Path(__file__).resolve().parents[2]
            parameters = StdioServerParameters(
                command=sys.executable,
                args=[
                    "-m",
                    "codex_training.mcp_server",
                    "--run-id",
                    run["run_id"],
                    "--backend-url",
                    url,
                ],
                cwd=str(backend),
                env={**os.environ, "CHESS_RUN_TOKEN": run["run_token"]},
            )
            async with Client(parameters, read_timeout_seconds=40, mode=mode) as client:
                tools = await client.list_tools()
                assert {t.name for t in tools.tools} == {
                    "get_current_pass",
                    "submit_response",
                }
                result = await client.call_tool("get_current_pass")
                assert not result.is_error
                current = result.structured_content
                assert current["run_id"] == run["run_id"]
                for raw in move_responses(library_rows[0]):
                    result = await client.call_tool(
                        "submit_response",
                        {
                            "pass_id": current["pass"]["pass_id"],
                            "response": raw,
                            "reasoning_text": REASONING,
                        },
                    )
                    assert not result.is_error, result
                    current = result.structured_content
                assert current["status"] == "completed", current

        asyncio.run(play())
    assert run_store.get(run["run_id"])["final_move_uci"] == "e4e5"
    assert len(run_store.passes) == 3


@pytest.mark.parametrize("failure", ["denied", "unreachable", "invalid-json"])
def test_mcp_backend_errors_are_tool_errors(failure):
    from mcp import Client

    async def check():
        def reject(request):
            if failure == "unreachable":
                raise httpx.ConnectError("offline", request=request)
            if failure == "invalid-json":
                return httpx.Response(200, text="not JSON")
            return httpx.Response(403, json={"detail": "Invalid run token."})

        async with httpx.AsyncClient(
            base_url="http://localhost", transport=httpx.MockTransport(reject)
        ) as backend:
            async with Client(create_server(backend, str(uuid4()))) as client:
                result = await client.call_tool("get_current_pass")
                assert result.is_error
                expected = {
                    "denied": "403",
                    "unreachable": "Retry the same submission",
                    "invalid-json": "invalid JSON reply",
                }
                assert expected[failure] in result.content[0].text

    asyncio.run(check())


def test_real_database_run_and_restart_recovery(postgres):
    from codex_training.service import CodexTrainingService
    from positional_testing.recording import PassRecorder
    from positional_testing.run_repository import RunRepository

    seed = Path(__file__).resolve().parents[2] / "positional_testing/datasets/seed/v1"
    postgres.import_collection(seed)
    position_id = json.loads((seed / "positions.jsonl").read_text().splitlines()[0])[
        "id"
    ]
    row = next(r for r in postgres.list_position_rows() if str(r["id"]) == position_id)
    row["id"] = position_id
    repository = RunRepository()
    graded = []

    class Evaluator:
        async def evaluate(self, **kwargs):
            graded.append(kwargs)
            return {"evaluation": {"status": "completed", "engine_name": "fixture"}}

    async def play():
        service = CodexTrainingService(repository, Evaluator())
        try:
            session = await service.start(
                row["id"], model_label="db-fixture", pass_timeout=10
            )
            submitted = []
            for raw in move_responses(row):
                packet = session.snapshot()["pass"]
                submitted.append((packet["model_input"], raw))
                session.submit(packet["pass_id"], raw, REASONING)
                current = await session.current(5)
            assert current["status"] == "completed", current
            return session.run_id, submitted
        finally:
            await service.close()

    run_id, submitted = asyncio.run(play())
    assert len(graded) == 1
    restarted = RunRepository()
    before = restarted.get(run_id)
    assert before["status"] == "completed"
    assert before["final_move_uci"] == "e4e5"
    assert len(before["passes"]) == 3
    for number, (packet, raw) in enumerate(submitted, 1):
        saved = restarted.get_pass_exchange(run_id, number)
        assert saved["model_input"] == packet
        assert present_exchange(saved).output == [REASONING, raw]

    interrupted, other = str(uuid4()), str(uuid4())
    for identifier, provider in ((interrupted, "codex_mcp"), (other, "lmstudio")):
        restarted.create(
            identifier, row["id"], "fixture", AGENT_PLAYER_2_ID, {"provider": provider}
        )
        recorder = PassRecorder(restarted, identifier)
        recorder.begin({"phase": "synthesis"})
        recorder.capture_input({"input": "captured before interruption"})
    # The move was already saved when grading was interrupted.
    restarted.save_move(interrupted, "e4e5")
    for _ in range(2):
        restarted.recover_codex_training()
    recovered = restarted.get(interrupted)
    assert recovered["status"] == "failed"
    assert recovered["failure_stage"] == "evaluation"
    assert recovered["final_move_uci"] == "e4e5"
    assert recovered["passes"][0]["status"] == "failed"
    assert restarted.get_pass_exchange(interrupted, 1)["model_input"] == {
        "input": "captured before interruption"
    }
    assert restarted.get(other)["status"] == "running"
    assert restarted.get(run_id) == before


def test_explanation_validation_duplicate_identity_and_pass_scoping(api, library_rows):
    run = start(api, library_rows[0]["id"])
    assigned = run["pass"]
    scoped = {"Authorization": "Bearer " + assigned["pass_token"]}
    path = f"/api/codex-training/runs/{run['run_id']}"
    packet = api.get(path + "/pass", headers=scoped).json()
    assert "pass_token" not in packet["pass"]
    assert "1,500 tokens" in packet["pass"]["model_input"]["teacher_instructions"]
    assert (
        packet["pass"]["model_input"]["teacher"]["reasoning_origin"]
        == "authored_explanation"
    )
    body = {
        "pass_id": assigned["pass_id"],
        "response": response("inspect_square", board="canonical", square="e4"),
    }
    for invalid in (None, "", "   ", "<think>Example</think>"):
        candidate = {**body, "reasoning_text": invalid} if invalid is not None else body
        assert (
            api.post(path + "/response", headers=scoped, json=candidate).status_code
            == 422
        )
    body["reasoning_text"] = REASONING
    accepted = api.post(path + "/response", headers=scoped, json=body)
    assert accepted.status_code == 200
    assert accepted.json()["pass"] is None
    assert api.get(path + "/pass", headers=scoped).json()["status"] == "pass_finished"
    next_pass = api.get(path + "/pass?wait_seconds=5", headers=headers(run)).json()[
        "pass"
    ]
    assert next_pass["pass_number"] == 2
    assert api.post(path + "/response", headers=scoped, json=body).json()["duplicate"]
    assert (
        api.post(
            path + "/response",
            headers=scoped,
            json={**body, "reasoning_text": "Changed explanation"},
        ).status_code
        == 409
    )
    assert (
        api.post(
            path + "/response",
            headers=scoped,
            json={**body, "pass_id": next_pass["pass_id"]},
        ).status_code
        == 403
    )
    assert api.post(path + "/stop", headers=scoped).status_code == 403


def register_worker(api, monkeypatch):
    monkeypatch.setenv("CODEX_WORKER_TOKEN", "test-worker-token")
    auth = {"Authorization": "Bearer test-worker-token"}
    identity = {
        "worker_id": str(uuid4()),
        "model": "fixture-teacher",
        "reasoning_effort": "medium",
        "cli_version": "fixture-cli",
    }
    assert (
        api.post(
            "/api/codex-training/worker/heartbeat", json=identity, headers=auth
        ).status_code
        == 200
    )
    return auth, identity


def test_lost_worker_finishes_waiting_database_pass(
    api, library_rows, run_store, monkeypatch
):
    register_worker(api, monkeypatch)
    job = api.post(
        "/api/codex-training/jobs", json={"position_id": library_rows[0]["id"]}
    ).json()
    api.app.state.codex_jobs.seen -= 60
    task = api.app.state.codex_training.tasks[job["run_id"]]
    api.portal.call(lambda: asyncio.wait_for(asyncio.shield(task), 7))
    stored = run_store.get(job["run_id"])
    assert stored["status"] == "failed"
    assert "disconnected" in stored["error"]
    assert stored["passes"][0]["status"] == "failed"


@pytest.mark.skipif(
    os.getenv("CODEX_LIVE_SMOKE") != "1",
    reason="Opt in to one real Codex pass with CODEX_LIVE_SMOKE=1",
)
def test_live_codex_exec_one_isolated_pass(
    bridge_app, library_rows, run_store, monkeypatch, tmp_path
):
    import tomllib

    from codex_training.worker import WindowsWorker, resolve_codex

    config = tomllib.loads((Path.home() / ".codex/config.toml").read_text("utf-8"))
    executable, version = resolve_codex()
    monkeypatch.setenv("CODEX_WORKER_TOKEN", "live-smoke-worker")
    with live_backend(bridge_app) as url:

        async def exercise():
            worker = WindowsWorker(
                backend_url=url,
                token="live-smoke-worker",
                executable=executable,
                model=config["model"],
                effort=config.get("model_reasoning_effort", "medium"),
                cli_version=version,
                runtime=tmp_path,
            )
            heartbeat = asyncio.create_task(worker.heartbeat())
            try:
                await worker.request("POST", "/worker/heartbeat", json=worker.identity)
                job = await worker.request(
                    "POST", "/jobs", json={"position_id": library_rows[0]["id"]}
                )
                claimed = (
                    await worker.request(
                        "POST", "/worker/claim", json={"worker_id": worker.worker_id}
                    )
                )["job"]
                current = await worker.request(
                    "GET", f"/runs/{job['run_id']}/pass", token=claimed["run_token"]
                )
                await asyncio.wait_for(worker.run_pass(claimed, current), 300)
                after = await worker.request(
                    "GET",
                    f"/runs/{job['run_id']}/pass",
                    token=claimed["run_token"],
                    params={"wait_seconds": 10},
                )
                assert (
                    after.get("pass", {}).get("pass_id") != current["pass"]["pass_id"]
                )
                saved = run_store.get_pass_exchange(job["run_id"], 1)
                assert saved["model_output"]["output"][0]["content"][0]["text"].strip()
                assert run_store.passes[(job["run_id"], 1)]["status"] == "completed"
            finally:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
                await worker.client.aclose()

        asyncio.run(exercise())


def test_worker_jobs_auth_claim_stop_and_saved_result(
    api, library_rows, run_store, monkeypatch
):
    base = "/api/codex-training"
    assert api.get(base + "/worker").json()["online"] is False
    assert (
        api.post(
            base + "/jobs", json={"position_id": library_rows[0]["id"]}
        ).status_code
        == 409
    )
    assert not run_store.runs
    auth, identity = register_worker(api, monkeypatch)
    assert (
        api.post(
            base + "/worker/claim", json={"worker_id": identity["worker_id"]}
        ).status_code
        == 403
    )
    assert api.get(base + "/worker").json()["model"] == "fixture-teacher"
    job = api.post(base + "/jobs", json={"position_id": library_rows[0]["id"]}).json()
    assert "run_token" not in job and "pass" not in job
    assert (
        api.post(
            base + "/jobs", json={"position_id": library_rows[1]["id"]}
        ).status_code
        == 409
    )
    claim_body = {"worker_id": identity["worker_id"]}
    claim = api.post(base + "/worker/claim", json=claim_body, headers=auth).json()[
        "job"
    ]
    assert (
        api.post(base + "/worker/claim", json=claim_body, headers=auth).json()["job"]
        is None
    )
    assert len(run_store.runs) == 1
    current = api.get(
        base + f"/runs/{job['run_id']}/pass", headers=headers(claim)
    ).json()
    for raw in move_responses(library_rows[0]):
        current = submit(api, claim, current, raw)
    done = api.get(base + f"/jobs/{job['run_id']}").json()
    assert done["status"] == "completed"
    assert done["result"]["move"]["uci"] == "e4e5"
    stored = run_store.get(job["run_id"])
    assert stored["config"]["context_mode"] == "fresh_per_pass"
    assert stored["config"]["teacher_model"] == "fixture-teacher"
    assert stored["config"]["teacher_prompt_sha256"]
    new = api.post(base + "/jobs", json={"position_id": library_rows[0]["id"]}).json()
    assert api.post(base + f"/jobs/{new['run_id']}/stop").status_code == 202
    task = api.app.state.codex_training.tasks[new["run_id"]]
    api.portal.call(lambda: asyncio.wait_for(asyncio.shield(task), 3))
    assert run_store.get(new["run_id"])["status"] == "failed"
    assert api.get(base + "/worker").json()["active_run_id"] is None


def test_windows_worker_fresh_processes_use_real_mcp_and_persist_explanations(
    bridge_app, library_rows, run_store, monkeypatch, tmp_path
):
    from codex_training.worker import WindowsWorker

    monkeypatch.setenv("CODEX_WORKER_TOKEN", "test-worker-token")
    responses = move_responses(library_rows[0])
    fake = tmp_path / "fixture_codex.py"
    fake.write_text(
        "import asyncio, json, os, sys\nfrom mcp import Client, StdioServerParameters\n"
        f"responses = {responses!r}\n"
        "prompt = sys.stdin.read()\nassert '1,500 tokens' in prompt\n"
        "async def main():\n"
        f"    params = StdioServerParameters(command=sys.executable, args=['-m', 'codex_training.mcp_server'], cwd={str(Path(__file__).resolve().parents[2])!r}, env=dict(os.environ))\n"
        "    async with Client(params) as client:\n"
        "        result = await client.call_tool('get_current_pass')\n"
        "        current = result.structured_content['pass']\n"
        "        assert 'pass_token' not in current\n"
        "        result = await client.call_tool('submit_response', {'pass_id': current['pass_id'], 'reasoning_text': 'This is a transport fixture explanation.', 'response': responses[current['pass_number']-1]})\n"
        "        assert not result.is_error, result\n"
        "        assert result.structured_content['pass'] is None\n"
        "        print(json.dumps({'type': 'turn.completed'}), flush=True)\n"
        "asyncio.run(main())\n",
        encoding="utf-8",
    )
    launches = []

    def command(executable, workspace, **kwargs):
        launches.append(str(workspace))
        return [sys.executable, str(fake)]

    monkeypatch.setattr("codex_training.worker.codex_command", command)
    with live_backend(bridge_app) as url:

        async def exercise():
            worker = WindowsWorker(
                backend_url=url,
                token="test-worker-token",
                executable="fixture",
                model="fixture-teacher",
                effort="medium",
                cli_version="fixture",
                runtime=tmp_path,
            )
            try:
                await worker.request("POST", "/worker/heartbeat", json=worker.identity)
                job = await worker.request(
                    "POST", "/jobs", json={"position_id": library_rows[0]["id"]}
                )
                claim = (
                    await worker.request(
                        "POST", "/worker/claim", json={"worker_id": worker.worker_id}
                    )
                )["job"]
                await worker.execute(claim)
                result = await worker.request("GET", f"/jobs/{job['run_id']}")
                assert result["status"] == "completed", result
                return job["run_id"]
            finally:
                await worker.client.aclose()

        run_id = asyncio.run(exercise())
    assert len(launches) == len(set(launches)) == 3
    for number in (1, 2, 3):
        saved = run_store.get_pass_exchange(run_id, number)
        assert (
            saved["model_output"]["output"][0]["content"][0]["text"]
            == "This is a transport fixture explanation."
        )
